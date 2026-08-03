"""Fourfold-bound, owner-controlled promotion authorization.

This module verifies the immutable candidate/evidence/nomination chain, checks
that deterministic evidence names the exact candidate Fourfold snapshot,
authenticates the owner capability, and consumes it exactly once. It returns a
canonical :class:`PromotionReceipt` but deliberately does not mutate a Git ref
or primary checkout. The later sealed-application boundary must re-check the
live target revision immediately before its repository effect.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Sequence

from daedalus.kernel.approvals import (
    ApprovalExpectation,
    ApprovalLedger,
    ConsumedOwnerApproval,
    verify_owner_approval,
)
from daedalus.kernel.contracts import OwnerApproval
from daedalus.schemas import (
    ContractProvenance,
    EvidencePacket,
    NominationReceipt,
    PromotionReceipt,
    _locator_sha256,
)
from daedalus.twin.contracts import FOURFOLD_PLANES, FourfoldSnapshot


class PromotionAuthorizationError(RuntimeError):
    """Base class for fail-closed promotion authorization rejection."""


class PromotionBindingMismatch(PromotionAuthorizationError):
    """The candidate, evidence, Twin, nomination, or locator identities differ."""


class PromotionEvidenceError(PromotionAuthorizationError):
    """The retained evidence is not sufficient for the requested authorization."""


@dataclass(frozen=True)
class PromotionAuthorization:
    """In-memory result joining the canonical receipt and consumed capability."""

    receipt: PromotionReceipt
    consumed_approval: ConsumedOwnerApproval
    candidate_snapshot_sha256: str
    required_complete_planes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "receipt": self.receipt.to_dict(),
            "consumed_approval": self.consumed_approval.to_dict(),
            "candidate_snapshot_sha256": self.candidate_snapshot_sha256,
            "required_complete_planes": list(self.required_complete_planes),
        }


def _authorization_time(value: datetime | None) -> datetime:
    instant = value or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("authorized_at must be timezone-aware")
    return instant.astimezone(timezone.utc)


def _required_planes(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError("required_complete_planes must be a sequence")
    selected = tuple(sorted(values))
    if not selected:
        raise ValueError("at least one complete Fourfold plane must be required")
    if len(set(selected)) != len(selected):
        raise ValueError("required_complete_planes must not contain duplicates")
    unknown = sorted(set(selected) - set(FOURFOLD_PLANES))
    if unknown:
        raise ValueError(f"unknown Fourfold plane(s): {unknown}")
    return selected


def _verify_candidate_chain(
    *,
    nomination: NominationReceipt,
    evidence: EvidencePacket,
    candidate_snapshot: FourfoldSnapshot,
    repository_id: str,
    required_complete_planes: tuple[str, ...],
) -> None:
    if nomination.nomination_status != "nominated":
        raise PromotionEvidenceError("only a nominated candidate may be authorized")
    if evidence.evaluation_status != "passed":
        raise PromotionEvidenceError("promotion requires a passed evidence packet")
    if nomination.source_revision != evidence.source_revision:
        raise PromotionBindingMismatch(
            "nomination and evidence bind different base revisions"
        )
    if nomination.evidence_packet_sha256 != evidence.digest:
        raise PromotionBindingMismatch(
            "nomination is bound to a different evidence packet"
        )
    if evidence.candidate_artifact_sha256 is None:
        raise PromotionEvidenceError(
            "passed promotion evidence must name a candidate source artifact"
        )
    if evidence.candidate_artifact_locator is None:
        raise PromotionEvidenceError(
            "passed promotion evidence must retain the candidate source locator"
        )
    if nomination.candidate_artifact_sha256 != evidence.candidate_artifact_sha256:
        raise PromotionBindingMismatch(
            "nomination and evidence bind different candidate artifacts"
        )
    if nomination.candidate_artifact_locator != evidence.candidate_artifact_locator:
        raise PromotionBindingMismatch(
            "nomination and evidence bind different candidate locators"
        )
    if nomination.policy_decision_sha256 != evidence.policy_decision_sha256:
        raise PromotionBindingMismatch(
            "nomination and evidence bind different policy decisions"
        )
    if nomination.evidence_locator not in {
        item.evidence_locator for item in evidence.items
    }:
        raise PromotionBindingMismatch(
            "nomination evidence locator is not retained by the evidence packet"
        )
    if candidate_snapshot.repository_id != repository_id:
        raise PromotionBindingMismatch(
            "candidate Fourfold snapshot belongs to a different repository"
        )
    if candidate_snapshot.source_revision != evidence.candidate_artifact_sha256:
        raise PromotionBindingMismatch(
            "candidate Fourfold source revision is not the candidate artifact digest"
        )
    if evidence.subject_sha256 != candidate_snapshot.digest:
        raise PromotionBindingMismatch(
            "evidence subject is not the candidate Fourfold snapshot"
        )
    matching_snapshot_evidence = [
        item
        for item in evidence.items
        if item.output_sha256 == candidate_snapshot.digest
        and item.verdict == "passed"
        and item.assurance in {"deterministic", "independent"}
    ]
    if not matching_snapshot_evidence:
        raise PromotionEvidenceError(
            "evidence packet lacks deterministic or independent candidate Twin evidence"
        )
    incomplete = {
        name: candidate_snapshot.plane_map[name].status
        for name in required_complete_planes
        if candidate_snapshot.plane_map[name].status != "complete"
    }
    if incomplete:
        raise PromotionEvidenceError(
            "required Fourfold planes are not complete: "
            + ", ".join(
                f"{name}={status}" for name, status in sorted(incomplete.items())
            )
        )


def authorize_fourfold_promotion(
    *,
    promotion_id: str,
    nomination: NominationReceipt,
    evidence: EvidencePacket,
    candidate_snapshot: FourfoldSnapshot,
    repository_id: str,
    owner_approval: OwnerApproval,
    owner_approval_locator: str,
    owner_keyring: Mapping[tuple[str, str], bytes | str],
    approval_ledger: ApprovalLedger,
    target_ref: str,
    current_target_revision: str,
    authorized_at: datetime | None = None,
    required_complete_planes: Sequence[str] = FOURFOLD_PLANES,
) -> PromotionAuthorization:
    """Authorize one exact Fourfold-bound candidate without applying it.

    All semantic and artifact checks occur before the one-use approval is
    consumed. The direct owner-approval locator must address the exact
    canonical approval payload. Successful return is authorization evidence,
    not a repository mutation; a later effect boundary must compare the live
    target revision again inside its mutation transaction.
    """

    instant = _authorization_time(authorized_at)
    required = _required_planes(required_complete_planes)
    _verify_candidate_chain(
        nomination=nomination,
        evidence=evidence,
        candidate_snapshot=candidate_snapshot,
        repository_id=repository_id,
        required_complete_planes=required,
    )

    try:
        approval_locator_sha256 = _locator_sha256(owner_approval_locator)
    except ValueError as exc:
        raise PromotionBindingMismatch("owner approval locator is invalid") from exc
    if approval_locator_sha256 != owner_approval.digest:
        raise PromotionBindingMismatch(
            "owner approval locator does not address the supplied approval"
        )

    verified = verify_owner_approval(
        owner_approval,
        keyring=owner_keyring,
        expectation=ApprovalExpectation(
            operation="promote-candidate",
            nomination_receipt_sha256=nomination.digest,
            candidate_artifact_sha256=nomination.candidate_artifact_sha256,
            evidence_packet_sha256=evidence.digest,
            base_revision=nomination.source_revision,
            target_ref=target_ref,
            current_target_revision=current_target_revision,
        ),
        now=instant,
    )
    consumed = approval_ledger.consume(
        verified,
        promotion_id=promotion_id,
        consumed_at=instant,
    )

    inputs = tuple(
        sorted(
            {
                nomination.digest,
                nomination.candidate_artifact_sha256,
                _locator_sha256(nomination.candidate_artifact_locator),
                evidence.digest,
                _locator_sha256(nomination.evidence_locator),
                owner_approval.digest,
                candidate_snapshot.digest,
                consumed.digest,
            }
        )
    )
    provenance = ContractProvenance(
        origin="kernel.promotion-authorizer",
        source_revision=nomination.source_revision,
        created_at=instant.isoformat(timespec="microseconds"),
        input_digests=inputs,
        trace_id=nomination.mission_id,
    )
    receipt = PromotionReceipt(
        promotion_id=promotion_id,
        nomination_receipt_sha256=nomination.digest,
        candidate_artifact_sha256=nomination.candidate_artifact_sha256,
        candidate_artifact_locator=nomination.candidate_artifact_locator,
        evidence_packet_sha256=evidence.digest,
        evidence_locator=nomination.evidence_locator,
        source_revision=nomination.source_revision,
        target_revision=current_target_revision,
        promotion_status="approved",
        owner_approval_ref=owner_approval_locator,
        approval_assurance="authenticated",
        reasons=(
            "authenticated owner approval consumed",
            "fourfold candidate evidence verified",
        ),
        provenance=provenance,
    )
    return PromotionAuthorization(
        receipt=receipt,
        consumed_approval=consumed,
        candidate_snapshot_sha256=candidate_snapshot.digest,
        required_complete_planes=required,
    )
