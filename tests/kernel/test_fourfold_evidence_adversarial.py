from __future__ import annotations

import dataclasses
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from daedalus.kernel.fourfold_evidence import (
    FourfoldEvidenceExpectation,
    FourfoldEvidenceMismatch,
    assemble_fourfold_evidence_packet,
    assemble_fourfold_nomination_receipt,
    verify_fourfold_evidence_packet,
    verify_fourfold_nomination_receipt,
)
from daedalus.kernel.source_trees import SourceTreeStore
from daedalus.schemas import ContractProvenance, EvidenceItem, EvidencePacket, ResourceUsage
from daedalus.storage import ArtifactStore
from daedalus.twin import FourfoldSnapshot, PlaneSnapshot, compile_reference_project


REVISION = "a" * 40
NOW = datetime(2026, 8, 3, 16, 15, tzinfo=timezone.utc)
FIXTURE = Path(__file__).resolve().parents[2] / "examples" / "fourfold_wiki_app"


def _sha(value: str | bytes) -> str:
    raw = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _base():
    compiled = compile_reference_project(
        FIXTURE,
        source_revision=REVISION,
        created_at=NOW.isoformat(),
        trace_id="g0-fourfold-adversarial",
    )
    snapshot = compiled.snapshot
    candidate_sha = compiled.source_bundle_sha256
    locator = f"artifact-locator:sha256:{candidate_sha}"
    expectation = FourfoldEvidenceExpectation(
        candidate_artifact_sha256=candidate_sha,
        candidate_artifact_locator=locator,
        snapshot_sha256=snapshot.digest,
        source_revision=REVISION,
    )
    packet = assemble_fourfold_evidence_packet(
        snapshot=snapshot,
        candidate_artifact_sha256=candidate_sha,
        candidate_artifact_locator=locator,
        packet_id="fourfold-adversarial-packet",
        mission_id="g0-fourfold-adversarial",
        attempt_id="g0-fourfold-adversarial-attempt",
        attempt_contract_sha256=_sha("attempt"),
        policy_decision_sha256=_sha("policy"),
        collected_at=NOW.isoformat(),
        usage=ResourceUsage(wall_time_ms=1),
        trace_id="g0-fourfold-adversarial",
    )
    nomination = assemble_fourfold_nomination_receipt(
        snapshot=snapshot,
        packet=packet,
        expectation=expectation,
        nomination_id="fourfold-adversarial-nomination",
        reasons=("exact semantic candidate retained",),
        created_at=NOW.isoformat(),
        trace_id="g0-fourfold-adversarial",
    )
    return compiled, candidate_sha, locator, expectation, packet, nomination


def _provenance_with(provenance: ContractProvenance, *digests: str) -> ContractProvenance:
    return ContractProvenance(
        origin=provenance.origin,
        source_revision=provenance.source_revision,
        created_at=provenance.created_at,
        input_digests=tuple(sorted(set(provenance.input_digests).union(digests))),
        trace_id=provenance.trace_id,
    )


def _partial_snapshot(snapshot: FourfoldSnapshot, candidate_sha: str) -> FourfoldSnapshot:
    planes = list(snapshot.planes)
    original = planes[0]
    planes[0] = PlaneSnapshot(
        plane=original.plane,
        source_revision=original.source_revision,
        status="partial",
        node_ids=original.node_ids,
        relation_sha256s=original.relation_sha256s,
        evidence_sha256s=original.evidence_sha256s,
        reason="fixture intentionally lacks complete Code-plane assurance",
    )
    provenance = ContractProvenance(
        origin="tests.partial-fourfold-snapshot",
        source_revision=snapshot.source_revision,
        created_at=NOW.isoformat(),
        input_digests=tuple(
            sorted(
                {
                    candidate_sha,
                    snapshot.source_forest_sha256,
                    *(plane.digest for plane in planes),
                    *(binding.digest for binding in snapshot.bindings),
                }
            )
        ),
        trace_id="g0-fourfold-adversarial",
    )
    return FourfoldSnapshot(
        repository_id=snapshot.repository_id,
        source_revision=snapshot.source_revision,
        source_forest_sha256=snapshot.source_forest_sha256,
        planes=tuple(planes),
        bindings=snapshot.bindings,
        provenance=provenance,
    )


def test_valid_but_foreign_subject_is_refused() -> None:
    compiled, _, _, expectation, packet, _ = _base()
    foreign_subject = _sha("foreign-subject")
    substituted = dataclasses.replace(
        packet,
        subject_sha256=foreign_subject,
        provenance=_provenance_with(packet.provenance, foreign_subject),
    )

    with pytest.raises(FourfoldEvidenceMismatch, match="subject"):
        verify_fourfold_evidence_packet(
            substituted,
            snapshot=compiled.snapshot,
            expectation=expectation,
        )


def test_constructor_bypass_object_is_rebuilt_and_refused() -> None:
    compiled, _, _, expectation, packet, _ = _base()
    forged = object.__new__(EvidencePacket)
    for field in dataclasses.fields(packet):
        object.__setattr__(forged, field.name, getattr(packet, field.name))
    object.__setattr__(forged, "subject_sha256", _sha("constructor-bypass"))

    with pytest.raises((FourfoldEvidenceMismatch, ValueError)):
        verify_fourfold_evidence_packet(
            forged,
            snapshot=compiled.snapshot,
            expectation=expectation,
        )


def test_partial_snapshot_cannot_enter_default_gate_evidence() -> None:
    compiled, candidate_sha, locator, _, _, _ = _base()
    partial = _partial_snapshot(compiled.snapshot, candidate_sha)

    with pytest.raises(FourfoldEvidenceMismatch, match="incomplete_planes"):
        assemble_fourfold_evidence_packet(
            snapshot=partial,
            candidate_artifact_sha256=candidate_sha,
            candidate_artifact_locator=locator,
            packet_id="partial-fourfold-packet",
            mission_id="g0-fourfold-adversarial",
            attempt_id="g0-fourfold-adversarial-attempt",
            attempt_contract_sha256=_sha("attempt"),
            policy_decision_sha256=_sha("policy"),
            collected_at=NOW.isoformat(),
        )


def test_structurally_valid_snapshot_without_candidate_provenance_is_refused() -> None:
    compiled, candidate_sha, locator, _, _, _ = _base()
    snapshot = compiled.snapshot
    unbound = FourfoldSnapshot(
        repository_id=snapshot.repository_id,
        source_revision=snapshot.source_revision,
        source_forest_sha256=snapshot.source_forest_sha256,
        planes=snapshot.planes,
        bindings=snapshot.bindings,
        provenance=ContractProvenance(
            origin="tests.unbound-fourfold-snapshot",
            source_revision=snapshot.source_revision,
            created_at=NOW.isoformat(),
            input_digests=tuple(
                sorted(
                    {
                        snapshot.source_forest_sha256,
                        *(plane.digest for plane in snapshot.planes),
                        *(binding.digest for binding in snapshot.bindings),
                    }
                )
            ),
            trace_id="g0-fourfold-unbound",
        ),
    )

    assert candidate_sha not in unbound.provenance.input_digests
    with pytest.raises(FourfoldEvidenceMismatch, match="provenance.*candidate"):
        assemble_fourfold_evidence_packet(
            snapshot=unbound,
            candidate_artifact_sha256=candidate_sha,
            candidate_artifact_locator=locator,
            packet_id="unbound-fourfold-packet",
            mission_id="g0-fourfold-adversarial",
            attempt_id="g0-fourfold-adversarial-attempt",
            attempt_contract_sha256=_sha("attempt"),
            policy_decision_sha256=_sha("policy"),
            collected_at=NOW.isoformat(),
        )


def test_nomination_with_foreign_evidence_digest_is_refused() -> None:
    compiled, _, _, expectation, packet, nomination = _base()
    foreign_packet = _sha("foreign-evidence-packet")
    substituted = dataclasses.replace(
        nomination,
        evidence_packet_sha256=foreign_packet,
        provenance=_provenance_with(nomination.provenance, foreign_packet),
    )

    with pytest.raises(FourfoldEvidenceMismatch, match="evidence_packet"):
        verify_fourfold_nomination_receipt(
            substituted,
            packet=packet,
            snapshot=compiled.snapshot,
            expectation=expectation,
        )


def test_same_candidate_from_stale_revision_is_refused() -> None:
    compiled, candidate_sha, locator, expectation, packet, _ = _base()
    stale_compiled = compile_reference_project(
        FIXTURE,
        source_revision="c" * 40,
        created_at=NOW.isoformat(),
        trace_id="g0-fourfold-adversarial-stale",
    )

    assert stale_compiled.source_bundle_sha256 == candidate_sha
    assert stale_compiled.snapshot.digest != compiled.snapshot.digest
    assert locator.endswith(candidate_sha)
    with pytest.raises(FourfoldEvidenceMismatch, match="source_revision|expected_snapshot"):
        verify_fourfold_evidence_packet(
            packet,
            snapshot=stale_compiled.snapshot,
            expectation=expectation,
        )


@pytest.mark.parametrize("status", ["failed", "inconclusive"])
@pytest.mark.parametrize("with_store", [False, True])
def test_negative_packets_remain_rejected_by_public_verifier_and_nomination(
    tmp_path: Path, status: str, with_store: bool,
) -> None:
    """Build canonical negatives independently of the new assembler mode."""
    source_store = SourceTreeStore(tmp_path / "source-cas")
    source = source_store.capture_tree(
        FIXTURE,
        tree_id="negative-nomination-source",
        source_revision=REVISION,
        origin="tests.negative-nomination",
        created_at=NOW.isoformat(),
    )
    compiled = compile_reference_project(
        FIXTURE,
        source_revision=REVISION,
        created_at=NOW.isoformat(),
        source_tree_sha256=source.ref.sha256,
    )
    store = ArtifactStore(tmp_path / "evidence-cas")
    expectation = FourfoldEvidenceExpectation(
        candidate_artifact_sha256=source.ref.sha256,
        candidate_artifact_locator=source.locator,
        snapshot_sha256=compiled.snapshot.digest,
        source_revision=REVISION,
    )
    positive = assemble_fourfold_evidence_packet(
        snapshot=compiled.snapshot,
        candidate_artifact_sha256=source.ref.sha256,
        candidate_artifact_locator=source.locator,
        packet_id="negative-nomination-packet",
        mission_id="negative-nomination-mission",
        attempt_id="negative-nomination-attempt",
        attempt_contract_sha256=_sha("negative-nomination-attempt"),
        policy_decision_sha256=_sha("negative-nomination-policy"),
        collected_at=NOW.isoformat(),
        store=store,
    )
    nomination_arguments = {
        "snapshot": compiled.snapshot,
        "expectation": expectation,
        "nomination_id": "negative-nomination-control",
        "reasons": ("positive structural control",),
        "created_at": NOW.isoformat(),
    }
    positive_nomination = assemble_fourfold_nomination_receipt(
        packet=positive, **nomination_arguments,
    )
    output = b"retained measured refusal\n"
    output_sha = _sha(output)
    output_provenance = ContractProvenance(
        origin="tests.negative-nomination-output",
        source_revision=REVISION,
        created_at=NOW.isoformat(),
        input_digests=(output_sha,),
    )
    stored = store.put_bytes(output, provenance=output_provenance.to_dict())
    assert store.get_bytes(store.verify(stored).artifact_sha256) == output
    item = EvidenceItem(
        evidence_id="negative-nomination-check",
        evaluator="tests.negative-nomination-check",
        verdict="failed" if status == "failed" else "error",
        assurance="deterministic" if status == "failed" else "unverified",
        output_sha256=output_sha,
        evidence_locator=stored.locator_uri,
        collected_at=NOW.isoformat(),
        provenance=_provenance_with(output_provenance, stored.locator_sha256),
    )
    negative = dataclasses.replace(
        positive,
        evaluation_status=status,
        items=(*positive.items, item),
        provenance=_provenance_with(positive.provenance, output_sha),
    )
    assert EvidencePacket.from_dict(negative.to_dict()) == negative
    # Rebind the receipt to the actual negative digest so an unrelated stale
    # evidence digest cannot be the reason nomination verification refuses.
    matching_nomination = dataclasses.replace(
        positive_nomination,
        evidence_packet_sha256=negative.digest,
        provenance=_provenance_with(positive_nomination.provenance, negative.digest),
    )
    with pytest.raises(FourfoldEvidenceMismatch, match="evaluation_status"):
        verify_fourfold_evidence_packet(
            negative,
            snapshot=compiled.snapshot,
            expectation=expectation,
            store=store if with_store else None,
        )
    with pytest.raises(FourfoldEvidenceMismatch, match="evaluation_status"):
        assemble_fourfold_nomination_receipt(packet=negative, **nomination_arguments)
    with pytest.raises(FourfoldEvidenceMismatch, match="evaluation_status"):
        verify_fourfold_nomination_receipt(
            matching_nomination,
            packet=negative,
            snapshot=compiled.snapshot,
            expectation=expectation,
        )
