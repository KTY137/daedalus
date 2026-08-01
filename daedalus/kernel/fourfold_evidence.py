"""Bind a real Fourfold snapshot into the canonical Gate-0 evidence chain.

This module is deliberately narrow. It does not compile repositories, create a
second evidence schema, consume approvals, or promote candidates. It projects
one already compiled :class:`FourfoldSnapshot` into the existing
:class:`EvidencePacket` contract and verifies that the packet still names the
same candidate tree, source revision, Forest and snapshot.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from daedalus.schemas import (
    ContractProvenance,
    EvidenceItem,
    EvidencePacket,
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
    """The exact identities a promotion reviewer expects to inspect."""

    candidate_artifact_sha256: str
    candidate_artifact_locator: str
    snapshot_sha256: str
    source_revision: str

    def __post_init__(self) -> None:
        candidate_sha = _sha256(
            self.candidate_artifact_sha256, "candidate_artifact_sha256"
        )
        candidate_locator = _artifact_locator(
            self.candidate_artifact_locator, "candidate_artifact_locator"
        )
        snapshot_sha = _sha256(self.snapshot_sha256, "snapshot_sha256")
        source_revision = _revision(self.source_revision, "source_revision")
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
) -> EvidencePacket:
    """Create a minimal passed packet for one real Fourfold snapshot.

    The packet's subject and durable candidate locator identify the candidate
    source bundle. The deterministic evidence item carries the exact snapshot
    digest. Both identities, the source revision, and the source Forest digest
    are retained in canonical provenance and in structured evidence details.
    """

    if not isinstance(snapshot, FourfoldSnapshot):
        raise TypeError("snapshot must be a FourfoldSnapshot")
    expectation = FourfoldEvidenceExpectation(
        candidate_artifact_sha256=candidate_artifact_sha256,
        candidate_artifact_locator=candidate_artifact_locator,
        snapshot_sha256=snapshot.digest,
        source_revision=snapshot.source_revision,
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
            input_digests=(
                expectation.candidate_artifact_sha256,
                snapshot.source_forest_sha256,
                snapshot.digest,
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


def verify_fourfold_evidence_packet(
    packet: EvidencePacket,
    *,
    snapshot: FourfoldSnapshot,
    expectation: FourfoldEvidenceExpectation,
) -> None:
    """Fail closed unless packet, candidate and snapshot identities are exact."""

    if not isinstance(packet, EvidencePacket):
        raise TypeError("packet must be an EvidencePacket")
    if not isinstance(snapshot, FourfoldSnapshot):
        raise TypeError("snapshot must be a FourfoldSnapshot")

    mismatches: list[str] = []
    if packet.source_revision != snapshot.source_revision:
        mismatches.append("source_revision")
    if expectation.source_revision != snapshot.source_revision:
        mismatches.append("expected_source_revision")
    if expectation.snapshot_sha256 != snapshot.digest:
        mismatches.append("expected_snapshot")
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


__all__ = [
    "FOURFOLD_EVIDENCE_SCHEMA",
    "FOURFOLD_EVALUATOR",
    "FourfoldEvidenceExpectation",
    "FourfoldEvidenceMismatch",
    "assemble_fourfold_evidence_packet",
    "verify_fourfold_evidence_packet",
]
