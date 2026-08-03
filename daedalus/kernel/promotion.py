"""Fourfold-bound, one-use authorization for the sealed promotion boundary.

This packet deliberately stops before applying candidate bytes.  It joins the
existing canonical contracts without creating a second promotion mechanism:

* a passed :class:`~daedalus.schemas.EvidencePacket` must identify the exact
  candidate source-tree artifact;
* one deterministic/independent evidence item must retain the exact candidate
  :class:`~daedalus.twin.contracts.FourfoldSnapshot` digest;
* the nomination, evidence packet, candidate snapshot, owner approval, base
  revision and live target HEAD must agree exactly;
* the authenticated owner approval is consumed once in the existing SQLite
  replay ledger;
* the resulting capability must be rechecked against the live target HEAD by
  the later integration-worktree adapter immediately before mutation.

No function in this module writes a repository, creates a worktree, applies a
patch, merges a branch, or manufactures an owner decision.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from daedalus.kernel.approvals import (
    ApprovalExpectation,
    ApprovalLedger,
    ConsumedOwnerApproval,
    VerifiedOwnerApproval,
    verify_owner_approval,
)
from daedalus.kernel.contracts import OwnerApproval
from daedalus.schemas import (
    ContractProvenance,
    EvidencePacket,
    NominationReceipt,
    PromotionReceipt,
    _artifact_locator,
    _identifier,
    _revision,
)
from daedalus.spine.envelope import canonical_sha
from daedalus.twin.contracts import FourfoldSnapshot

FOURFOLD_PROMOTION_EVALUATOR = "fourfold.snapshot"


class PromotionBoundaryError(RuntimeError):
    """Base class for fail-closed sealed-promotion refusals."""


class PromotionBindingMismatch(PromotionBoundaryError):
    pass


class PromotionEvidenceError(PromotionBoundaryError):
    pass


class PromotionTargetMoved(PromotionBoundaryError):
    pass


class PromotionCapabilityError(PromotionBoundaryError):
    pass


@dataclass(frozen=True)
class PreparedPromotion:
    """Immutable binding result before the one-use approval is consumed."""

    promotion_id: str
    target_ref: str
    expected_target_revision: str
    base_revision: str
    candidate_artifact_sha256: str
    candidate_artifact_locator: str
    candidate_snapshot_sha256: str
    candidate_snapshot_revision: str
    repository_id: str
    evidence_packet_sha256: str
    evidence_locator: str
    nomination_receipt_sha256: str
    owner_approval_sha256: str
    verified_approval: VerifiedOwnerApproval

    def to_dict(self) -> dict[str, Any]:
        return {
            "promotion_id": self.promotion_id,
            "target_ref": self.target_ref,
            "expected_target_revision": self.expected_target_revision,
            "base_revision": self.base_revision,
            "candidate_artifact_sha256": self.candidate_artifact_sha256,
            "candidate_artifact_locator": self.candidate_artifact_locator,
            "candidate_snapshot_sha256": self.candidate_snapshot_sha256,
            "candidate_snapshot_revision": self.candidate_snapshot_revision,
            "repository_id": self.repository_id,
            "evidence_packet_sha256": self.evidence_packet_sha256,
            "evidence_locator": self.evidence_locator,
            "nomination_receipt_sha256": self.nomination_receipt_sha256,
            "owner_approval_sha256": self.owner_approval_sha256,
            "verified_approval": self.verified_approval.to_dict(),
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class AuthorizedPromotion:
    """Consumed one-use capability accepted by the later mutation adapter."""

    prepared: PreparedPromotion
    consumed_approval: ConsumedOwnerApproval

    def __post_init__(self) -> None:
        if self.consumed_approval.promotion_id != self.prepared.promotion_id:
            raise PromotionCapabilityError(
                "consumed approval belongs to a different promotion_id"
            )
        if self.consumed_approval.verified != self.prepared.verified_approval:
            raise PromotionCapabilityError(
                "consumed approval does not match the prepared owner capability"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "prepared": self.prepared.to_dict(),
            "consumed_approval": self.consumed_approval.to_dict(),
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def _fourfold_items(evidence: EvidencePacket) -> tuple[Any, ...]:
    return tuple(
        item for item in evidence.items
        if item.evaluator == FOURFOLD_PROMOTION_EVALUATOR
    )


def _require_fourfold_evidence(
    evidence: EvidencePacket,
    snapshot: FourfoldSnapshot,
    candidate_artifact_sha256: str,
) -> None:
    if evidence.evaluation_status != "passed":
        raise PromotionEvidenceError("promotion requires a passed evidence packet")
    if evidence.candidate_artifact_sha256 != candidate_artifact_sha256:
        raise PromotionBindingMismatch(
            "evidence packet is bound to a different candidate artifact"
        )
    if evidence.subject_sha256 != candidate_artifact_sha256:
        raise PromotionBindingMismatch(
            "evidence subject must be the exact candidate artifact"
        )
    expected_locator = f"artifact-locator:sha256:{candidate_artifact_sha256}"
    if evidence.candidate_artifact_locator != expected_locator:
        raise PromotionBindingMismatch(
            "evidence packet does not retain the exact candidate locator"
        )
    if snapshot.source_revision != candidate_artifact_sha256:
        raise PromotionBindingMismatch(
            "candidate FourfoldSnapshot source_revision must equal the candidate "
            "source-tree digest"
        )
    if any(plane.status != "complete" for plane in snapshot.planes):
        raise PromotionEvidenceError(
            "sealed promotion requires complete code, type, data and knowledge planes"
        )

    items = _fourfold_items(evidence)
    if len(items) != 1:
        raise PromotionEvidenceError(
            "evidence packet must contain exactly one fourfold.snapshot item"
        )
    item = items[0]
    if item.assurance not in {"deterministic", "independent"}:
        raise PromotionEvidenceError(
            "Fourfold promotion evidence must be deterministic or independent"
        )
    if item.verdict != "passed":
        raise PromotionEvidenceError("Fourfold promotion evidence did not pass")
    if item.output_sha256 != snapshot.digest:
        raise PromotionBindingMismatch(
            "Fourfold evidence output does not match the candidate snapshot"
        )

    expected_details = {
        "candidate_artifact_sha256": candidate_artifact_sha256,
        "snapshot_source_revision": snapshot.source_revision,
        "repository_id": snapshot.repository_id,
        "snapshot_contract_type": snapshot.CONTRACT_TYPE,
    }
    mismatches = [
        name for name, expected in expected_details.items()
        if item.details.get(name) != expected
    ]
    if mismatches:
        raise PromotionBindingMismatch(
            "Fourfold evidence detail mismatch: " + ", ".join(sorted(mismatches))
        )
    if snapshot.digest not in evidence.provenance.input_digests:
        raise PromotionBindingMismatch(
            "evidence provenance does not bind the candidate snapshot digest"
        )


def _require_nomination_bindings(
    nomination: NominationReceipt,
    evidence: EvidencePacket,
) -> None:
    if nomination.nomination_status != "nominated":
        raise PromotionEvidenceError("only a nominated candidate may be promoted")
    comparisons = {
        "source_revision": (nomination.source_revision, evidence.source_revision),
        "candidate_artifact_sha256": (
            nomination.candidate_artifact_sha256,
            evidence.candidate_artifact_sha256,
        ),
        "candidate_artifact_locator": (
            nomination.candidate_artifact_locator,
            evidence.candidate_artifact_locator,
        ),
        "evidence_packet_sha256": (
            nomination.evidence_packet_sha256,
            evidence.digest,
        ),
        "policy_decision_sha256": (
            nomination.policy_decision_sha256,
            evidence.policy_decision_sha256,
        ),
    }
    mismatches = [
        name for name, (actual, expected) in comparisons.items()
        if actual != expected
    ]
    if mismatches:
        raise PromotionBindingMismatch(
            "nomination binding mismatch: " + ", ".join(sorted(mismatches))
        )
    expected_evidence_locator = f"artifact-locator:sha256:{evidence.digest}"
    if nomination.evidence_locator != expected_evidence_locator:
        raise PromotionBindingMismatch(
            "nomination does not retain the exact evidence packet locator"
        )


def prepare_promotion(
    *,
    promotion_id: str,
    approval: OwnerApproval,
    nomination: NominationReceipt,
    evidence: EvidencePacket,
    candidate_snapshot: FourfoldSnapshot,
    target_ref: str,
    current_target_revision: str,
    keyring: Mapping[tuple[str, str], bytes | str],
    now: datetime | None = None,
) -> PreparedPromotion:
    """Verify every immutable binding without consuming the owner capability."""

    promotion_id = _identifier(promotion_id, "promotion_id")
    target_ref = _identifier(target_ref, "target_ref")
    current_target_revision = _revision(
        current_target_revision, "current_target_revision"
    )
    candidate_sha = evidence.candidate_artifact_sha256
    candidate_locator = evidence.candidate_artifact_locator
    if candidate_sha is None or candidate_locator is None:
        raise PromotionEvidenceError(
            "promotion evidence must retain a durable candidate source tree"
        )

    _require_fourfold_evidence(evidence, candidate_snapshot, candidate_sha)
    _require_nomination_bindings(nomination, evidence)

    verified = verify_owner_approval(
        approval,
        keyring=keyring,
        expectation=ApprovalExpectation(
            operation="promote-candidate",
            nomination_receipt_sha256=nomination.digest,
            candidate_artifact_sha256=candidate_sha,
            evidence_packet_sha256=evidence.digest,
            base_revision=evidence.source_revision,
            target_ref=target_ref,
            current_target_revision=current_target_revision,
        ),
        now=now,
    )
    return PreparedPromotion(
        promotion_id=promotion_id,
        target_ref=target_ref,
        expected_target_revision=current_target_revision,
        base_revision=evidence.source_revision,
        candidate_artifact_sha256=candidate_sha,
        candidate_artifact_locator=candidate_locator,
        candidate_snapshot_sha256=candidate_snapshot.digest,
        candidate_snapshot_revision=candidate_snapshot.source_revision,
        repository_id=candidate_snapshot.repository_id,
        evidence_packet_sha256=evidence.digest,
        evidence_locator=nomination.evidence_locator,
        nomination_receipt_sha256=nomination.digest,
        owner_approval_sha256=approval.digest,
        verified_approval=verified,
    )


def consume_prepared_promotion(
    prepared: PreparedPromotion,
    *,
    ledger: ApprovalLedger,
    current_target_revision: str,
    consumed_at: datetime | None = None,
) -> AuthorizedPromotion:
    """Recheck the live target and atomically consume the owner approval once."""

    current = _revision(current_target_revision, "current_target_revision")
    if current != prepared.expected_target_revision:
        raise PromotionTargetMoved(
            "target HEAD moved after owner approval; refusing capability consumption"
        )
    if prepared.verified_approval.expected_target_revision != current:
        raise PromotionCapabilityError(
            "prepared approval retained a contradictory target revision"
        )
    consumed = ledger.consume(
        prepared.verified_approval,
        promotion_id=prepared.promotion_id,
        consumed_at=consumed_at,
    )
    return AuthorizedPromotion(
        prepared=prepared,
        consumed_approval=consumed,
    )


def assert_authorized_promotion_start(
    authorization: AuthorizedPromotion,
    *,
    current_target_revision: str,
) -> None:
    """Fail closed immediately before the later adapter mutates integration state."""

    current = _revision(current_target_revision, "current_target_revision")
    expected = authorization.prepared.expected_target_revision
    if current != expected:
        raise PromotionTargetMoved(
            "target HEAD moved after approval consumption; a new owner approval is required"
        )
    if authorization.consumed_approval.verified.expected_target_revision != expected:
        raise PromotionCapabilityError(
            "consumed owner capability contradicts the prepared target revision"
        )


def build_approved_promotion_receipt(
    authorization: AuthorizedPromotion,
    *,
    target_revision: str,
    owner_approval_ref: str,
    reasons: Sequence[str],
    provenance: ContractProvenance,
) -> PromotionReceipt:
    """Build the canonical receipt after an integration adapter reports success.

    ``owner_approval_ref`` must locate the serialized ``AuthorizedPromotion``
    itself, not merely the raw signature.  That artifact therefore retains the
    one-use ledger consumption together with every Fourfold/candidate binding.
    """

    expected_ref = f"artifact-locator:sha256:{authorization.digest}"
    owner_approval_ref = _artifact_locator(
        owner_approval_ref, "owner_approval_ref"
    )
    if owner_approval_ref != expected_ref:
        raise PromotionCapabilityError(
            "promotion receipt must reference the exact consumed authorization"
        )
    required = {
        authorization.digest,
        authorization.prepared.candidate_snapshot_sha256,
    }
    missing = sorted(required - set(provenance.input_digests))
    if missing:
        raise PromotionBindingMismatch(
            "promotion receipt provenance misses authorization inputs: "
            + ", ".join(missing)
        )
    return PromotionReceipt(
        promotion_id=authorization.prepared.promotion_id,
        nomination_receipt_sha256=(
            authorization.prepared.nomination_receipt_sha256
        ),
        candidate_artifact_sha256=(
            authorization.prepared.candidate_artifact_sha256
        ),
        candidate_artifact_locator=(
            authorization.prepared.candidate_artifact_locator
        ),
        evidence_packet_sha256=(
            authorization.prepared.evidence_packet_sha256
        ),
        evidence_locator=authorization.prepared.evidence_locator,
        source_revision=authorization.prepared.base_revision,
        target_revision=target_revision,
        promotion_status="approved",
        owner_approval_ref=owner_approval_ref,
        approval_assurance="authenticated",
        reasons=tuple(reasons),
        provenance=provenance,
    )
