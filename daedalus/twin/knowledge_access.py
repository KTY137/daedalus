"""Access-scoped output boundary for Fourfold knowledge correlation.

Correlation is intentionally broader than disclosure: Daedalus may correlate a
private Obsidian note or restricted Confluence page while a particular runtime
is only allowed to receive public/internal content.  This module is therefore
the canonical bridge from :mod:`knowledge_correlation` into an agent prompt.

The lower-level ``build_context_capsule`` function remains useful for pure
ranking experiments, but production callers must use
``build_access_scoped_context`` so source ACLs cannot disappear between
correlation and prompt construction.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Sequence

from ..spine.envelope import canonical_sha
from .contracts import FourfoldSnapshot
from .knowledge_correlation import (
    CorrelationPolicy,
    KnowledgeContextCapsule,
    KnowledgeCorrelationError,
    KnowledgeCorrelationResult,
    build_context_capsule,
)
from .knowledge_sources import ACCESS_CLASSES, KnowledgeCorpus


@dataclass(frozen=True)
class KnowledgeAccessPolicy:
    """Explicit disclosure scope for one context construction operation."""

    allowed_access_classes: tuple[str, ...] = ("public", "internal")
    include_external_background: bool = True
    max_context_bundles: int = 24

    SCHEMA: ClassVar[str] = "daedalus-knowledge-access-policy/1"

    def __post_init__(self) -> None:
        values = tuple(sorted(set(self.allowed_access_classes)))
        if not values:
            raise KnowledgeCorrelationError(
                "knowledge access policy must allow at least one access class"
            )
        unknown = sorted(set(values) - ACCESS_CLASSES)
        if unknown:
            raise KnowledgeCorrelationError(
                f"knowledge access policy contains unknown access classes: {unknown}"
            )
        if self.max_context_bundles < 1:
            raise KnowledgeCorrelationError("max_context_bundles must be positive")
        object.__setattr__(self, "allowed_access_classes", values)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "allowed_access_classes": list(self.allowed_access_classes),
            "include_external_background": self.include_external_background,
            "max_context_bundles": self.max_context_bundles,
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class AccessScopedKnowledgeContext:
    """Prompt-ready capsule plus the disclosure decision that produced it."""

    policy: KnowledgeAccessPolicy
    capsule: KnowledgeContextCapsule
    included_source_ids: tuple[str, ...]
    withheld_source_ids: tuple[str, ...]
    withheld_claim_sha256s: tuple[str, ...]

    SCHEMA: ClassVar[str] = "daedalus-access-scoped-knowledge-context/1"

    def __post_init__(self) -> None:
        if not isinstance(self.policy, KnowledgeAccessPolicy):
            raise KnowledgeCorrelationError("policy must be KnowledgeAccessPolicy")
        if not isinstance(self.capsule, KnowledgeContextCapsule):
            raise KnowledgeCorrelationError("capsule must be KnowledgeContextCapsule")
        included = tuple(sorted(set(self.included_source_ids)))
        withheld = tuple(sorted(set(self.withheld_source_ids)))
        if set(included).intersection(withheld):
            raise KnowledgeCorrelationError(
                "a source cannot be both included and withheld"
            )
        object.__setattr__(self, "included_source_ids", included)
        object.__setattr__(self, "withheld_source_ids", withheld)
        object.__setattr__(
            self,
            "withheld_claim_sha256s",
            tuple(sorted(set(self.withheld_claim_sha256s))),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "policy": self.policy.to_dict(),
            "capsule": self.capsule.to_dict(),
            "included_source_ids": list(self.included_source_ids),
            "withheld_source_ids": list(self.withheld_source_ids),
            "withheld_claim_sha256s": list(self.withheld_claim_sha256s),
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def build_access_scoped_context(
    result: KnowledgeCorrelationResult,
    *,
    snapshot: FourfoldSnapshot,
    corpus: KnowledgeCorpus,
    objective: str,
    anchor_node_ids: Sequence[str],
    access_policy: KnowledgeAccessPolicy = KnowledgeAccessPolicy(),
    correlation_policy: CorrelationPolicy = CorrelationPolicy(),
) -> AccessScopedKnowledgeContext:
    """Build an ACL-preserving context for one exact result/corpus pair.

    Access is enforced before the low-level capsule builder sees bundles.  A
    caller cannot substitute a corpus because its digest must equal the digest
    recorded by the correlation result.  Missing document identities fail
    closed instead of silently dropping ACL metadata.
    """

    if result.corpus_sha256 != corpus.digest:
        raise KnowledgeCorrelationError(
            "correlation result does not bind the supplied knowledge corpus"
        )
    document_map = corpus.document_map
    included_bundles = []
    included_source_ids: set[str] = set()
    withheld_source_ids: set[str] = set()
    withheld_claims: set[str] = set()

    for bundle in result.bundles:
        document = document_map.get(bundle.claim.document_id)
        if document is None:
            raise KnowledgeCorrelationError(
                "correlation bundle references a document outside the bound corpus"
            )
        source = document.source
        if source.access_class not in access_policy.allowed_access_classes:
            withheld_source_ids.add(source.source_id)
            withheld_claims.add(bundle.claim.digest)
            continue
        if (
            source.authority == "external_reference"
            and not access_policy.include_external_background
        ):
            withheld_source_ids.add(source.source_id)
            withheld_claims.add(bundle.claim.digest)
            continue
        included_source_ids.add(source.source_id)
        included_bundles.append(bundle)

    filtered = KnowledgeCorrelationResult(
        snapshot_sha256=result.snapshot_sha256,
        forest_sha256=result.forest_sha256,
        corpus_sha256=result.corpus_sha256,
        cards=result.cards,
        bundles=tuple(included_bundles),
    )
    effective_policy = CorrelationPolicy(
        min_proposal_score=correlation_policy.min_proposal_score,
        max_proposals_per_claim=correlation_policy.max_proposals_per_claim,
        max_context_bundles=min(
            correlation_policy.max_context_bundles,
            access_policy.max_context_bundles,
        ),
        external_background_in_context=access_policy.include_external_background,
    )
    base_capsule = build_context_capsule(
        filtered,
        snapshot=snapshot,
        objective=objective,
        anchor_node_ids=anchor_node_ids,
        policy=effective_policy,
    )
    capsule = KnowledgeContextCapsule(
        source_revision=base_capsule.source_revision,
        snapshot_sha256=base_capsule.snapshot_sha256,
        corpus_sha256=base_capsule.corpus_sha256,
        objective=base_capsule.objective,
        anchor_node_ids=base_capsule.anchor_node_ids,
        bundles=base_capsule.bundles,
        withheld_claim_sha256s=tuple(
            sorted(
                set(base_capsule.withheld_claim_sha256s).union(withheld_claims)
            )
        ),
    )
    actually_included_document_ids = {
        bundle.claim.document_id for bundle in capsule.bundles
    }
    actually_included_source_ids = {
        document_map[document_id].source.source_id
        for document_id in actually_included_document_ids
    }
    included_source_ids.intersection_update(actually_included_source_ids)

    return AccessScopedKnowledgeContext(
        policy=access_policy,
        capsule=capsule,
        included_source_ids=tuple(included_source_ids),
        withheld_source_ids=tuple(withheld_source_ids),
        withheld_claim_sha256s=tuple(
            sorted(set(capsule.withheld_claim_sha256s).union(withheld_claims))
        ),
    )


__all__ = [
    "AccessScopedKnowledgeContext",
    "KnowledgeAccessPolicy",
    "build_access_scoped_context",
]
