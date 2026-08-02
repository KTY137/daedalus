"""One pure entry point for building knowledge-assisted provider context.

This module composes the hardened primitives without performing network access,
model invocation, filesystem writes or promotion. It is the intended integration
surface for orchestration code once the Trust Runtime authorizes a model call.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Mapping, Sequence

from ..spine.envelope import canonical_sha
from ..structcore.forest import KnowledgeForest
from .contracts import FourfoldSnapshot
from .knowledge_access import (
    AccessScopedKnowledgeContext,
    KnowledgeAccessPolicy,
    build_access_scoped_context,
)
from .knowledge_anchor_selection import (
    KnowledgeAnchorSelection,
    select_knowledge_anchors_for_paths,
)
from .knowledge_correlation import (
    CorrelationPolicy,
    SoftSignalProvider,
)
from .knowledge_graph_projection import (
    ExternalKnowledgeGraphProjection,
    project_external_knowledge_graph,
)
from .knowledge_prompt import (
    KnowledgePromptEnvelope,
    build_knowledge_prompt_envelope,
)
from .knowledge_provider_receipt import (
    KnowledgeProviderContextReceipt,
    build_knowledge_provider_context_receipt,
)
from .knowledge_receipt import KnowledgeAttemptContextReceipt
from .knowledge_run import (
    KnowledgeCorrelationRun,
    build_attempt_receipt_from_correlation_run,
    run_knowledge_correlation,
)
from .knowledge_slice_bridge import (
    KnowledgeAugmentedSlices,
    merge_knowledge_slice_texts,
)
from .knowledge_sources import KnowledgeCorpus


@dataclass(frozen=True)
class KnowledgeAssistedContextBuild:
    correlation_run: KnowledgeCorrelationRun
    anchors: KnowledgeAnchorSelection
    access_context: AccessScopedKnowledgeContext
    prompt: KnowledgePromptEnvelope
    knowledge_receipt: KnowledgeAttemptContextReceipt
    augmented_slices: KnowledgeAugmentedSlices
    provider_receipt: KnowledgeProviderContextReceipt
    graph_projection: ExternalKnowledgeGraphProjection

    SCHEMA: ClassVar[str] = "daedalus-knowledge-assisted-context-build/1"

    def __post_init__(self) -> None:
        result = self.correlation_run.result
        if self.anchors.correlation_result_sha256 != result.digest:
            raise ValueError("anchor selection does not bind the correlation result")
        if self.access_context.capsule.snapshot_sha256 != result.snapshot_sha256:
            raise ValueError("access context does not bind the correlation snapshot")
        if self.prompt.context_sha256 != self.access_context.digest:
            raise ValueError("prompt does not bind the access context")
        if (
            self.knowledge_receipt.prompt_envelope_sha256
            != self.prompt.digest
        ):
            raise ValueError("knowledge receipt does not bind the prompt")
        if (
            self.augmented_slices.receipt.knowledge_prompt_sha256
            != self.prompt.digest
        ):
            raise ValueError("slice bridge does not bind the prompt")
        if (
            self.provider_receipt.provider_context_sha256
            != self.augmented_slices.digest
        ):
            raise ValueError("provider receipt does not bind the merged slices")
        if (
            self.graph_projection.correlation_result_sha256
            != result.digest
        ):
            raise ValueError("graph projection does not bind the correlation result")

    @property
    def slice_texts(self) -> Mapping[str, str]:
        return self.augmented_slices.mapping

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "correlation_run_sha256": self.correlation_run.digest,
            "anchor_selection_sha256": self.anchors.digest,
            "access_context_sha256": self.access_context.digest,
            "prompt_envelope_sha256": self.prompt.digest,
            "knowledge_receipt_sha256": self.knowledge_receipt.digest,
            "augmented_slices_sha256": self.augmented_slices.digest,
            "provider_receipt_sha256": self.provider_receipt.digest,
            "graph_projection_sha256": self.graph_projection.digest,
            "source_revision": self.correlation_run.receipt.source_revision,
            "target_paths": list(self.anchors.target_paths),
            "anchor_node_ids": list(self.anchors.anchor_node_ids),
            "provider_paths": list(self.provider_receipt.target_paths),
            "model_invocation_claimed": False,
            "effect_performed": False,
            "authority_granted": False,
            "gate_closure_claimed": False,
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def build_knowledge_assisted_context(
    *,
    receipt_id: str,
    created_at: str,
    objective: str,
    target_paths: Sequence[str],
    base_slice_texts: Mapping[str, str],
    snapshot: FourfoldSnapshot,
    forest: KnowledgeForest,
    corpus: KnowledgeCorpus,
    correlation_policy: CorrelationPolicy = CorrelationPolicy(),
    access_policy: KnowledgeAccessPolicy = KnowledgeAccessPolicy(),
    soft_signal_provider: SoftSignalProvider | None = None,
    soft_signal_manifest_sha256: str | None = None,
    max_prompt_chars: int = 24_000,
    max_claim_chars: int = 2_000,
    max_total_slice_chars: int = 200_000,
    max_per_path_slice_chars: int = 100_000,
) -> KnowledgeAssistedContextBuild:
    """Build the exact context artifacts consumed by a future model attempt."""

    run = run_knowledge_correlation(
        snapshot=snapshot,
        forest=forest,
        corpus=corpus,
        policy=correlation_policy,
        soft_signal_provider=soft_signal_provider,
        soft_signal_manifest_sha256=soft_signal_manifest_sha256,
    )
    anchors = select_knowledge_anchors_for_paths(
        run.result,
        target_paths,
        fail_on_unmatched=True,
    )
    context = build_access_scoped_context(
        run.result,
        snapshot=snapshot,
        corpus=corpus,
        objective=objective,
        anchor_node_ids=anchors.anchor_node_ids,
        access_policy=access_policy,
        correlation_policy=correlation_policy,
    )
    prompt = build_knowledge_prompt_envelope(
        context,
        result=run.result,
        corpus=corpus,
        max_payload_chars=max_prompt_chars,
        max_claim_chars=max_claim_chars,
    )
    knowledge_receipt = build_attempt_receipt_from_correlation_run(
        receipt_id=receipt_id,
        created_at=created_at,
        snapshot=snapshot,
        corpus=corpus,
        run=run,
        access_policy=access_policy,
        context=context,
        prompt=prompt,
    )
    augmented = merge_knowledge_slice_texts(
        base_slice_texts,
        prompt,
        max_total_chars=max_total_slice_chars,
        max_per_path_chars=max_per_path_slice_chars,
    )
    provider_receipt = build_knowledge_provider_context_receipt(
        knowledge_receipt,
        augmented,
    )
    graph = project_external_knowledge_graph(corpus, run.result)
    return KnowledgeAssistedContextBuild(
        correlation_run=run,
        anchors=anchors,
        access_context=context,
        prompt=prompt,
        knowledge_receipt=knowledge_receipt,
        augmented_slices=augmented,
        provider_receipt=provider_receipt,
        graph_projection=graph,
    )


__all__ = [
    "KnowledgeAssistedContextBuild",
    "build_knowledge_assisted_context",
]
