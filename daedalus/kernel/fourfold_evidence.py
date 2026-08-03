"""Bind a real Fourfold snapshot into the canonical Gate-0 evidence chain.

This module is deliberately narrow. It does not compile repositories, create a
second evidence schema, authenticate artifact storage, consume approvals, or
promote candidates. It projects one already compiled :class:`FourfoldSnapshot`
into the existing :class:`EvidencePacket` and :class:`NominationReceipt`
contracts and verifies that every record still names the same candidate tree,
source revision, Forest and snapshot.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Sequence

from daedalus.schemas import (
    ContractProvenance,
    EvidenceItem,
    EvidencePacket,
    NominationReceipt,
    ResourceUsage,
    _artifact_locator,
    _locator_sha256,
    _revision,
    _sha256,
)
from daedalus.twin.contracts import FourfoldSnapshot

FOURFOLD_EVIDENCE_SCHEMA: Final[str] = "daedalus-fourfold-evidence/1"
FOURFOLD_EVALUATOR: Final[str] = "fourfold.snapshot-binding"


class FourfoldEvidenceMismatch(ValueError):
    """Raised when evidence no longer names the exact compiled candidate."""


@dataclass(frozen=True)
class FourfoldEvidenceExpectation:
    """The exact identities and coverage a promotion reviewer expects.

    The candidate digest and locator are caller-owned inputs. They must be
    resolved from the candidate source-tree/CAS authority rather than copied
    out of the EvidencePacket under review.
    """

    candidate_artifact_sha256: str
    candidate_artifact_locator: str
    snapshot_sha256: str
    source_revision: str
    require_complete: bool = True

    def __post_init__(self) -> None:
        candidate_sha = _sha256(
            self.candidate_artifact_sha256, "candidate_artifact_sha256"
        )
        candidate_locator = _artifact_locator(
            self.candidate_artifact_locator, "candidate_artifact_locator"
        )
        snapshot_sha = _sha256(self.snapshot_sha256, "snapshot_sha256")
        source_revision = _revision(self.source_revision, "source_revision")
        if not isinstance(self.require_complete, bool):
            raise ValueError("require_complete must be boolean")
        object.__setattr__(self, "candidate_artifact_sha256", candidate_sha)
        object.__setattr__(self, "candidate_artifact_locator", candidate_locator)
        object.__setattr__(self, "snapshot_sha256", snapshot_sha)
        object.__setattr__(self, "source_revision", source_revision)
        if _locator_sha256(candidate_locator) != candidate_sha:
            raise FourfoldEvidenceMismatch(
                "candidate artifact locator does not resolve to candidate digest"
            )


def _snapshot_locator(snapshot: FourfoldSnapshot) -> str:
    return f"artifact-locator:sha256:{snapshot.digest}"


def _canonical_snapshot(snapshot: FourfoldSnapshot) -> FourfoldSnapshot:
    if not isinstance(snapshot, FourfoldSnapshot):
        raise TypeError("snapshot must be a FourfoldSnapshot")
    rebuilt = FourfoldSnapshot.from_dict(snapshot.to_dict())
    if rebuilt != snapshot:
        raise FourfoldEvidenceMismatch("FourfoldSnapshot is not canonical")
    return rebuilt


def _canonical_packet(packet: EvidencePacket) -> EvidencePacket:
    if not isinstance(packet, EvidencePacket):
        raise TypeError("packet must be an EvidencePacket")
    rebuilt = EvidencePacket.from_dict(packet.to_dict())
    if rebuilt != packet:
        raise FourfoldEvidenceMismatch("EvidencePacket is not canonical")
    return rebuilt


def _canonical_nomination(nomination: NominationReceipt) -> NominationReceipt:
    if not isinstance(nomination, NominationReceipt):
        raise TypeError("nomination must be a NominationReceipt")
    rebuilt = NominationReceipt.from_dict(nomination.to_dict())
    if rebuilt != nomination:
        raise FourfoldEvidenceMismatch("NominationReceipt is not canonical")
    return rebuilt


def assemble_fourfold_evidence_packet(
    *,
    snapshot: FourfoldSnapshot,
    candidate_artifact_sha256: str,
    candidate_artifact_locator: str,
    packet_id: str,
    mission_id: str,
    attempt_id: str,
    attempt_contract_sha256: str,
    policy_decision_sha256: str,
    collected_at: str,
    usage: ResourceUsage | None = None,
    trace_id: str | None = None,
    extra_items: tuple[EvidenceItem, ...] = (),
    require_complete: bool = True,
) -> EvidencePacket:
    """Create a passed packet for one exact candidate and Fourfold snapshot."""

    snapshot = _canonical_snapshot(snapshot)
    expectation = FourfoldEvidenceExpectation(
        candidate_artifact_sha256=candidate_artifact_sha256,
        candidate_artifact_locator=candidate_artifact_locator,
        snapshot_sha256=snapshot.digest,
        source_revision=snapshot.source_revision,
        require_complete=require_complete,
    )
    attempt_sha = _sha256(attempt_contract_sha256, "attempt_contract_sha256")
    policy_sha = _sha256(policy_decision_sha256, "policy_decision_sha256")
    snapshot_locator = _snapshot_locator(snapshot)
    details = {
        "schema": FOURFOLD_EVIDENCE_SCHEMA,
        "repository_id": snapshot.repository_id,
        "source_revision": snapshot.source_revision,
        "candidate_artifact_sha256": expectation.candidate_artifact_sha256,
        "source_forest_sha256": snapshot.source_forest_sha256,
        "fourfold_snapshot_sha256": snapshot.digest,
        "plane_statuses": {
            plane.plane: plane.status for plane in snapshot.planes
        },
    }
    item = EvidenceItem(
        evidence_id=f"{attempt_id}:fourfold",
        evaluator=FOURFOLD_EVALUATOR,
        assurance="deterministic",
        verdict="passed",
        output_sha256=snapshot.digest,
        evidence_locator=snapshot_locator,
        collected_at=collected_at,
        provenance=ContractProvenance(
            origin="daedalus.kernel.fourfold-evidence",
            source_revision=snapshot.source_revision,
            created_at=collected_at,
            input_digests=tuple(
                sorted(
                    {
                        expectation.candidate_artifact_sha256,
                        snapshot.source_forest_sha256,
                        snapshot.digest,
                    }
                )
            ),
            trace_id=trace_id,
        ),
        details=details,
    )
    packet = EvidencePacket(
        packet_id=packet_id,
        mission_id=mission_id,
        attempt_id=attempt_id,
        source_revision=snapshot.source_revision,
        attempt_contract_sha256=attempt_sha,
        subject_sha256=expectation.candidate_artifact_sha256,
        evaluation_status="passed",
        items=(item, *tuple(extra_items)),
        policy_decision_sha256=policy_sha,
        usage=usage or ResourceUsage(),
        provenance=ContractProvenance(
            origin="daedalus.kernel.fourfold-evidence-packet",
            source_revision=snapshot.source_revision,
            created_at=collected_at,
            input_digests=tuple(
                sorted(
                    {
                        attempt_sha,
                        policy_sha,
                        expectation.candidate_artifact_sha256,
                        snapshot.digest,
                        *(extra.output_sha256 for extra in extra_items),
                        _locator_sha256(expectation.candidate_artifact_locator),
                    }
                )
            ),
            trace_id=trace_id,
        ),
        candidate_artifact_sha256=expectation.candidate_artifact_sha256,
        candidate_artifact_locator=expectation.candidate_artifact_locator,
    )
    verify_fourfold_evidence_packet(
        packet,
        snapshot=snapshot,
        expectation=expectation,
    )
    return packet


def assemble_fourfold_nomination_receipt(
    *,
    snapshot: FourfoldSnapshot,
    packet: EvidencePacket,
    expectation: FourfoldEvidenceExpectation,
    nomination_id: str,
    reasons: Sequence[str],
    created_at: str,
    trace_id: str | None = None,
) -> NominationReceipt:
    """Nominate the exact packet without creating owner or promotion authority."""

    snapshot = _canonical_snapshot(snapshot)
    packet = _canonical_packet(packet)
    verify_fourfold_evidence_packet(
        packet,
        snapshot=snapshot,
        expectation=expectation,
    )
    snapshot_locator = _snapshot_locator(snapshot)
    nomination = NominationReceipt(
        nomination_id=nomination_id,
        mission_id=packet.mission_id,
        attempt_id=packet.attempt_id,
        source_revision=snapshot.source_revision,
        candidate_artifact_sha256=expectation.candidate_artifact_sha256,
        candidate_artifact_locator=expectation.candidate_artifact_locator,
        evidence_packet_sha256=packet.digest,
        evidence_locator=snapshot_locator,
        policy_decision_sha256=packet.policy_decision_sha256,
        nomination_status="nominated",
        reasons=tuple(reasons),
        provenance=ContractProvenance(
            origin="daedalus.kernel.fourfold-nomination",
            source_revision=snapshot.source_revision,
            created_at=created_at,
            input_digests=tuple(
                sorted(
                    {
                        expectation.candidate_artifact_sha256,
                        _locator_sha256(expectation.candidate_artifact_locator),
                        packet.digest,
                        _locator_sha256(snapshot_locator),
                        packet.policy_decision_sha256,
                    }
                )
            ),
            trace_id=trace_id,
        ),
    )
    verify_fourfold_nomination_receipt(
        nomination,
        packet=packet,
        snapshot=snapshot,
        expectation=expectation,
    )
    return nomination


def verify_fourfold_evidence_packet(
    packet: EvidencePacket,
    *,
    snapshot: FourfoldSnapshot,
    expectation: FourfoldEvidenceExpectation,
) -> None:
    """Fail closed unless packet, candidate and snapshot identities are exact."""

    packet = _canonical_packet(packet)
    snapshot = _canonical_snapshot(snapshot)

    mismatches: list[str] = []
    if packet.source_revision != snapshot.source_revision:
        mismatches.append("source_revision")
    if expectation.source_revision != snapshot.source_revision:
        mismatches.append("expected_source_revision")
    if expectation.snapshot_sha256 != snapshot.digest:
        mismatches.append("expected_snapshot")
    if expectation.require_complete:
        incomplete = [
            plane.plane for plane in snapshot.planes if plane.status != "complete"
        ]
        if incomplete:
            mismatches.append("incomplete_planes:" + "+".join(sorted(incomplete)))
    if packet.subject_sha256 != expectation.candidate_artifact_sha256:
        mismatches.append("subject")
    if packet.candidate_artifact_sha256 != expectation.candidate_artifact_sha256:
        mismatches.append("candidate_digest")
    if packet.candidate_artifact_locator != expectation.candidate_artifact_locator:
        mismatches.append("candidate_locator")
    if packet.evaluation_status != "passed":
        mismatches.append("evaluation_status")

    items = [item for item in packet.items if item.evaluator == FOURFOLD_EVALUATOR]
    if len(items) != 1:
        mismatches.append("fourfold_evidence_count")
    else:
        item = items[0]
        expected_details = {
            "schema": FOURFOLD_EVIDENCE_SCHEMA,
            "repository_id": snapshot.repository_id,
            "source_revision": snapshot.source_revision,
            "candidate_artifact_sha256": expectation.candidate_artifact_sha256,
            "source_forest_sha256": snapshot.source_forest_sha256,
            "fourfold_snapshot_sha256": snapshot.digest,
            "plane_statuses": {
                plane.plane: plane.status for plane in snapshot.planes
            },
        }
        if item.assurance != "deterministic" or item.verdict != "passed":
            mismatches.append("fourfold_verdict")
        if item.output_sha256 != snapshot.digest:
            mismatches.append("snapshot_digest")
        if item.evidence_locator != _snapshot_locator(snapshot):
            mismatches.append("snapshot_locator")
        if dict(item.details) != expected_details:
            mismatches.append("fourfold_details")
        if item.provenance.source_revision != snapshot.source_revision:
            mismatches.append("fourfold_item_revision")
        item_inputs = set(item.provenance.input_digests)
        if expectation.candidate_artifact_sha256 not in item_inputs:
            mismatches.append("fourfold_item_candidate_provenance")
        if snapshot.source_forest_sha256 not in item_inputs:
            mismatches.append("fourfold_item_forest_provenance")
        if snapshot.digest not in item_inputs:
            mismatches.append("fourfold_item_snapshot_provenance")

    packet_inputs = set(packet.provenance.input_digests)
    if packet.provenance.source_revision != snapshot.source_revision:
        mismatches.append("packet_revision")
    if expectation.candidate_artifact_sha256 not in packet_inputs:
        mismatches.append("packet_candidate_provenance")
    if snapshot.digest not in packet_inputs:
        mismatches.append("packet_snapshot_provenance")
    if packet.attempt_contract_sha256 not in packet_inputs:
        mismatches.append("packet_attempt_provenance")
    if packet.policy_decision_sha256 not in packet_inputs:
        mismatches.append("packet_policy_provenance")

    if mismatches:
        raise FourfoldEvidenceMismatch(
            "Fourfold evidence binding mismatch: " + ", ".join(sorted(set(mismatches)))
        )


def verify_fourfold_nomination_receipt(
    nomination: NominationReceipt,
    *,
    packet: EvidencePacket,
    snapshot: FourfoldSnapshot,
    expectation: FourfoldEvidenceExpectation,
) -> None:
    """Verify that nomination retains the exact verified semantic evidence."""

    nomination = _canonical_nomination(nomination)
    packet = _canonical_packet(packet)
    snapshot = _canonical_snapshot(snapshot)
    verify_fourfold_evidence_packet(
        packet,
        snapshot=snapshot,
        expectation=expectation,
    )

    mismatches: list[str] = []
    if nomination.nomination_status != "nominated":
        mismatches.append("nomination_status")
    if nomination.source_revision != snapshot.source_revision:
        mismatches.append("source_revision")
    if nomination.mission_id != packet.mission_id:
        mismatches.append("mission_id")
    if nomination.attempt_id != packet.attempt_id:
        mismatches.append("attempt_id")
    if nomination.candidate_artifact_sha256 != expectation.candidate_artifact_sha256:
        mismatches.append("candidate_digest")
    if nomination.candidate_artifact_locator != expectation.candidate_artifact_locator:
        mismatches.append("candidate_locator")
    if nomination.evidence_packet_sha256 != packet.digest:
        mismatches.append("evidence_packet")
    if nomination.evidence_locator != _snapshot_locator(snapshot):
        mismatches.append("snapshot_locator")
    if nomination.policy_decision_sha256 != packet.policy_decision_sha256:
        mismatches.append("policy_decision")
    if mismatches:
        raise FourfoldEvidenceMismatch(
            "Fourfold nomination binding mismatch: "
            + ", ".join(sorted(set(mismatches)))
        )


__all__ = [
    "FOURFOLD_EVIDENCE_SCHEMA",
    "FOURFOLD_EVALUATOR",
    "FourfoldEvidenceExpectation",
    "FourfoldEvidenceMismatch",
    "assemble_fourfold_evidence_packet",
    "assemble_fourfold_nomination_receipt",
    "verify_fourfold_evidence_packet",
    "verify_fourfold_nomination_receipt",
]
