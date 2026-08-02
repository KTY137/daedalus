"""Atomic execution wrapper for policy-bound knowledge correlation.

A result digest alone proves which correlations exist, not which threshold,
limits or optional soft provider produced them. ``run_knowledge_correlation``
is the evidence-producing entry point: it executes the correlator and creates a
receipt over the exact input identities, policy and result in one call.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, ClassVar

from ..spine.envelope import canonical_sha
from ..structcore.forest import KnowledgeForest
from .contracts import FourfoldSnapshot
from .knowledge_access import AccessScopedKnowledgeContext, KnowledgeAccessPolicy
from .knowledge_correlation import (
    CorrelationPolicy,
    KnowledgeCorrelationError,
    KnowledgeCorrelationResult,
    SoftSignalProvider,
    correlate_knowledge,
)
from .knowledge_prompt import KnowledgePromptEnvelope
from .knowledge_receipt import (
    KnowledgeAttemptContextReceipt,
    build_knowledge_attempt_context_receipt,
    correlation_policy_dict,
)
from .knowledge_sources import KnowledgeCorpus


_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _sha(value: str, name: str) -> str:
    if not isinstance(value, str) or not _SHA_RE.fullmatch(value):
        raise KnowledgeCorrelationError(f"{name} must be lowercase sha256")
    return value


@dataclass(frozen=True)
class KnowledgeCorrelationRunReceipt:
    source_revision: str
    snapshot_sha256: str
    forest_sha256: str
    corpus_sha256: str
    correlation_policy_sha256: str
    result_sha256: str
    soft_signal_manifest_sha256: str | None

    SCHEMA: ClassVar[str] = "daedalus-knowledge-correlation-run-receipt/1"

    def __post_init__(self) -> None:
        if not isinstance(self.source_revision, str) or not self.source_revision.strip():
            raise KnowledgeCorrelationError("source_revision must not be empty")
        for name in (
            "snapshot_sha256",
            "forest_sha256",
            "corpus_sha256",
            "correlation_policy_sha256",
            "result_sha256",
        ):
            object.__setattr__(self, name, _sha(getattr(self, name), name))
        if self.soft_signal_manifest_sha256 is not None:
            object.__setattr__(
                self,
                "soft_signal_manifest_sha256",
                _sha(
                    self.soft_signal_manifest_sha256,
                    "soft_signal_manifest_sha256",
                ),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "source_revision": self.source_revision,
            "snapshot_sha256": self.snapshot_sha256,
            "forest_sha256": self.forest_sha256,
            "corpus_sha256": self.corpus_sha256,
            "correlation_policy_sha256": self.correlation_policy_sha256,
            "result_sha256": self.result_sha256,
            "soft_signal_manifest_sha256": self.soft_signal_manifest_sha256,
            "authority_granted": False,
            "verification_claimed": False,
            "gate_closure_claimed": False,
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class KnowledgeCorrelationRun:
    result: KnowledgeCorrelationResult
    receipt: KnowledgeCorrelationRunReceipt
    policy: CorrelationPolicy

    def __post_init__(self) -> None:
        if self.receipt.result_sha256 != self.result.digest:
            raise KnowledgeCorrelationError("run receipt/result digest mismatch")
        if self.receipt.correlation_policy_sha256 != canonical_sha(
            correlation_policy_dict(self.policy)
        ):
            raise KnowledgeCorrelationError("run receipt/policy digest mismatch")

    @property
    def digest(self) -> str:
        return canonical_sha(
            {
                "result_sha256": self.result.digest,
                "receipt_sha256": self.receipt.digest,
            }
        )


def run_knowledge_correlation(
    *,
    snapshot: FourfoldSnapshot,
    forest: KnowledgeForest,
    corpus: KnowledgeCorpus,
    policy: CorrelationPolicy = CorrelationPolicy(),
    soft_signal_provider: SoftSignalProvider | None = None,
    soft_signal_manifest_sha256: str | None = None,
) -> KnowledgeCorrelationRun:
    """Execute correlation and bind the exact execution configuration.

    A learned/remote soft provider without a manifest digest is refused because
    its scores would otherwise be impossible to reproduce or attribute.
    """

    if (soft_signal_provider is None) != (soft_signal_manifest_sha256 is None):
        raise KnowledgeCorrelationError(
            "soft signal provider and manifest digest must be supplied together"
        )
    if soft_signal_manifest_sha256 is not None:
        _sha(soft_signal_manifest_sha256, "soft_signal_manifest_sha256")
    result = correlate_knowledge(
        snapshot=snapshot,
        forest=forest,
        corpus=corpus,
        policy=policy,
        soft_signal_provider=soft_signal_provider,
    )
    receipt = KnowledgeCorrelationRunReceipt(
        source_revision=snapshot.source_revision,
        snapshot_sha256=snapshot.digest,
        forest_sha256=forest.content_sha256,
        corpus_sha256=corpus.digest,
        correlation_policy_sha256=canonical_sha(
            correlation_policy_dict(policy)
        ),
        result_sha256=result.digest,
        soft_signal_manifest_sha256=soft_signal_manifest_sha256,
    )
    if receipt.forest_sha256 != snapshot.source_forest_sha256:
        raise KnowledgeCorrelationError("run forest does not match snapshot")
    return KnowledgeCorrelationRun(result=result, receipt=receipt, policy=policy)


def build_attempt_receipt_from_correlation_run(
    *,
    receipt_id: str,
    created_at: str,
    snapshot: FourfoldSnapshot,
    corpus: KnowledgeCorpus,
    run: KnowledgeCorrelationRun,
    access_policy: KnowledgeAccessPolicy,
    context: AccessScopedKnowledgeContext,
    prompt: KnowledgePromptEnvelope,
) -> KnowledgeAttemptContextReceipt:
    """Build an attempt receipt only from a policy-bound correlation run."""

    if run.receipt.snapshot_sha256 != snapshot.digest:
        raise KnowledgeCorrelationError("correlation run/snapshot mismatch")
    if run.receipt.corpus_sha256 != corpus.digest:
        raise KnowledgeCorrelationError("correlation run/corpus mismatch")
    return build_knowledge_attempt_context_receipt(
        receipt_id=receipt_id,
        created_at=created_at,
        snapshot=snapshot,
        corpus=corpus,
        correlation_policy=run.policy,
        result=run.result,
        access_policy=access_policy,
        context=context,
        prompt=prompt,
    )


__all__ = [
    "KnowledgeCorrelationRun",
    "KnowledgeCorrelationRunReceipt",
    "build_attempt_receipt_from_correlation_run",
    "run_knowledge_correlation",
]
