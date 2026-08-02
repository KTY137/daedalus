"""Evidence receipt joining ingestion, correlation, access and prompt output.

A receipt is a statement of identity, not an approval and not a correctness
claim. It exists so an agent attempt can later prove exactly which external
knowledge corpus, Fourfold revision, correlation policy, access policy and
prompt payload it consumed.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, ClassVar

from ..spine.envelope import canonical_sha
from .contracts import FourfoldSnapshot
from .knowledge_access import (
    AccessScopedKnowledgeContext,
    KnowledgeAccessPolicy,
)
from .knowledge_correlation import (
    CorrelationPolicy,
    KnowledgeCorrelationError,
    KnowledgeCorrelationResult,
)
from .knowledge_prompt import KnowledgePromptEnvelope
from .knowledge_sources import KnowledgeCorpus


_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _sha(value: str, name: str) -> str:
    if not isinstance(value, str) or not _SHA_RE.fullmatch(value):
        raise KnowledgeCorrelationError(f"{name} must be lowercase sha256")
    return value


def _text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise KnowledgeCorrelationError(f"{name} must be a non-empty string")
    return value.strip()


def correlation_policy_dict(policy: CorrelationPolicy) -> dict[str, Any]:
    if not isinstance(policy, CorrelationPolicy):
        raise KnowledgeCorrelationError("correlation policy has wrong type")
    return {
        "min_proposal_score": policy.min_proposal_score,
        "max_proposals_per_claim": policy.max_proposals_per_claim,
        "max_context_bundles": policy.max_context_bundles,
        "external_background_in_context": policy.external_background_in_context,
    }


@dataclass(frozen=True)
class KnowledgeAttemptContextReceipt:
    receipt_id: str
    created_at: str
    source_revision: str
    snapshot_sha256: str
    forest_sha256: str
    corpus_sha256: str
    correlation_policy_sha256: str
    correlation_result_sha256: str
    access_policy_sha256: str
    access_context_sha256: str
    prompt_envelope_sha256: str
    prompt_payload_sha256: str
    target_paths: tuple[str, ...]
    included_claims: int
    omitted_claims: int

    SCHEMA: ClassVar[str] = "daedalus-knowledge-attempt-context-receipt/1"

    def __post_init__(self) -> None:
        for name in ("receipt_id", "created_at", "source_revision"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        for name in (
            "snapshot_sha256",
            "forest_sha256",
            "corpus_sha256",
            "correlation_policy_sha256",
            "correlation_result_sha256",
            "access_policy_sha256",
            "access_context_sha256",
            "prompt_envelope_sha256",
            "prompt_payload_sha256",
        ):
            object.__setattr__(self, name, _sha(getattr(self, name), name))
        paths = tuple(sorted(set(self.target_paths)))
        if not paths:
            raise KnowledgeCorrelationError("receipt requires target paths")
        object.__setattr__(self, "target_paths", paths)
        for name in ("included_claims", "omitted_claims"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise KnowledgeCorrelationError(
                    f"{name} must be a non-negative integer"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "receipt_id": self.receipt_id,
            "created_at": self.created_at,
            "source_revision": self.source_revision,
            "snapshot_sha256": self.snapshot_sha256,
            "forest_sha256": self.forest_sha256,
            "corpus_sha256": self.corpus_sha256,
            "correlation_policy_sha256": self.correlation_policy_sha256,
            "correlation_result_sha256": self.correlation_result_sha256,
            "access_policy_sha256": self.access_policy_sha256,
            "access_context_sha256": self.access_context_sha256,
            "prompt_envelope_sha256": self.prompt_envelope_sha256,
            "prompt_payload_sha256": self.prompt_payload_sha256,
            "target_paths": list(self.target_paths),
            "included_claims": self.included_claims,
            "omitted_claims": self.omitted_claims,
            "authority_granted": False,
            "verification_claimed": False,
            "gate_closure_claimed": False,
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def build_knowledge_attempt_context_receipt(
    *,
    receipt_id: str,
    created_at: str,
    snapshot: FourfoldSnapshot,
    corpus: KnowledgeCorpus,
    correlation_policy: CorrelationPolicy,
    result: KnowledgeCorrelationResult,
    access_policy: KnowledgeAccessPolicy,
    context: AccessScopedKnowledgeContext,
    prompt: KnowledgePromptEnvelope,
) -> KnowledgeAttemptContextReceipt:
    """Join exact artifacts and fail closed on any substitution."""

    if result.snapshot_sha256 != snapshot.digest:
        raise KnowledgeCorrelationError("result/snapshot digest mismatch")
    if result.forest_sha256 != snapshot.source_forest_sha256:
        raise KnowledgeCorrelationError("result/snapshot forest digest mismatch")
    if result.corpus_sha256 != corpus.digest:
        raise KnowledgeCorrelationError("result/corpus digest mismatch")
    if context.policy.digest != access_policy.digest:
        raise KnowledgeCorrelationError("context/access policy digest mismatch")
    if context.capsule.snapshot_sha256 != snapshot.digest:
        raise KnowledgeCorrelationError("context/snapshot digest mismatch")
    if context.capsule.corpus_sha256 != corpus.digest:
        raise KnowledgeCorrelationError("context/corpus digest mismatch")
    if prompt.context_sha256 != context.digest:
        raise KnowledgeCorrelationError("prompt/context digest mismatch")
    if prompt.snapshot_sha256 != snapshot.digest:
        raise KnowledgeCorrelationError("prompt/snapshot digest mismatch")
    if prompt.corpus_sha256 != corpus.digest:
        raise KnowledgeCorrelationError("prompt/corpus digest mismatch")
    if prompt.source_revision != snapshot.source_revision:
        raise KnowledgeCorrelationError("prompt/source revision mismatch")

    return KnowledgeAttemptContextReceipt(
        receipt_id=receipt_id,
        created_at=created_at,
        source_revision=snapshot.source_revision,
        snapshot_sha256=snapshot.digest,
        forest_sha256=snapshot.source_forest_sha256,
        corpus_sha256=corpus.digest,
        correlation_policy_sha256=canonical_sha(
            correlation_policy_dict(correlation_policy)
        ),
        correlation_result_sha256=result.digest,
        access_policy_sha256=access_policy.digest,
        access_context_sha256=context.digest,
        prompt_envelope_sha256=prompt.digest,
        prompt_payload_sha256=prompt.payload_sha256,
        target_paths=prompt.target_paths,
        included_claims=prompt.included_claims,
        omitted_claims=len(prompt.omitted_claim_sha256s),
    )


__all__ = [
    "KnowledgeAttemptContextReceipt",
    "build_knowledge_attempt_context_receipt",
    "correlation_policy_dict",
]
