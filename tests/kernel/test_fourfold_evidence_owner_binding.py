from __future__ import annotations

import hashlib
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from daedalus.kernel.approvals import (
    ApprovalBindingMismatch,
    ApprovalExpectation,
    issue_owner_approval,
    verify_owner_approval,
)
from daedalus.schemas import (
    ContractProvenance,
    EvidenceItem,
    EvidencePacket,
    NominationReceipt,
    ResourceUsage,
)
from daedalus.twin import compile_reference_project


REVISION = "a" * 40
TARGET_REVISION = "b" * 40
NOW = datetime(2026, 8, 3, 16, 0, tzinfo=timezone.utc)
OWNER_SECRET = b"test-only-owner-key-material-32-bytes-minimum"
FIXTURE = Path(__file__).resolve().parents[2] / "examples" / "fourfold_wiki_app"


def _sha(value: str | bytes) -> str:
    raw = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _locator(label: str) -> str:
    return f"artifact-locator:sha256:{_sha(label)}"


def _locator_digest(locator: str) -> str:
    return locator.rsplit(":", 1)[1]


def _tree_digest(root: Path) -> str:
    """Deterministic candidate-tree identity independent of filesystem metadata."""

    digest = hashlib.sha256()
    files = sorted(path for path in root.rglob("*") if path.is_file())
    for path in files:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _compile(root: Path, revision: str = REVISION):
    return compile_reference_project(
        root,
        source_revision=revision,
        created_at=NOW.isoformat(),
        trace_id="g0-fourfold-evidence-binding",
    )


def _evidence(root: Path, revision: str = REVISION):
    compiled = _compile(root, revision)
    snapshot = compiled.snapshot
    candidate_sha = _tree_digest(root)
    attempt_sha = _sha("fixture-attempt-contract")
    policy_sha = _sha("fixture-policy-decision")
    snapshot_locator = _locator("fourfold-snapshot-evidence")
    candidate_locator = _locator("candidate-source-tree")

    item = EvidenceItem(
        evidence_id="fourfold-snapshot",
        evaluator="fourfold-reference-compiler",
        assurance="deterministic",
        verdict="passed",
        output_sha256=snapshot.digest,
        evidence_locator=snapshot_locator,
        collected_at=NOW.isoformat(),
        provenance=ContractProvenance(
            origin="tests.fourfold-evidence-item",
            source_revision=revision,
            created_at=NOW.isoformat(),
            input_digests=(snapshot.digest, _locator_digest(snapshot_locator)),
            trace_id="g0-fourfold-evidence-binding",
        ),
        details={
            "planes": [plane.plane for plane in snapshot.planes],
            "bindings": len(snapshot.bindings),
            "all_planes_complete": all(
                plane.status == "complete" for plane in snapshot.planes
            ),
        },
    )
    packet_inputs = {
        attempt_sha,
        snapshot.digest,
        policy_sha,
        candidate_sha,
        _locator_digest(candidate_locator),
    }
    packet = EvidencePacket(
        packet_id="fourfold-evidence-packet",
        mission_id="g0-fourfold-binding",
        attempt_id="g0-fourfold-binding-attempt",
        source_revision=revision,
        attempt_contract_sha256=attempt_sha,
        subject_sha256=snapshot.digest,
        evaluation_status="passed",
        items=(item,),
        policy_decision_sha256=policy_sha,
        usage=ResourceUsage(wall_time_ms=1),
        candidate_artifact_sha256=candidate_sha,
        candidate_artifact_locator=candidate_locator,
        provenance=ContractProvenance(
            origin="tests.fourfold-evidence-packet",
            source_revision=revision,
            created_at=NOW.isoformat(),
            input_digests=tuple(packet_inputs),
            trace_id="g0-fourfold-evidence-binding",
        ),
    )
    nomination_inputs = (
        candidate_sha,
        _locator_digest(candidate_locator),
        packet.digest,
        _locator_digest(snapshot_locator),
        policy_sha,
    )
    nomination = NominationReceipt(
        nomination_id="fourfold-nomination",
        mission_id=packet.mission_id,
        attempt_id=packet.attempt_id,
        source_revision=revision,
        candidate_artifact_sha256=candidate_sha,
        candidate_artifact_locator=candidate_locator,
        evidence_packet_sha256=packet.digest,
        evidence_locator=snapshot_locator,
        policy_decision_sha256=policy_sha,
        nomination_status="nominated",
        reasons=("deterministic Fourfold snapshot and candidate tree are retained",),
        provenance=ContractProvenance(
            origin="tests.fourfold-nomination",
            source_revision=revision,
            created_at=NOW.isoformat(),
            input_digests=nomination_inputs,
            trace_id="g0-fourfold-evidence-binding",
        ),
    )
    return compiled, candidate_sha, packet, nomination


def _approval(candidate_sha: str, packet: EvidencePacket, nomination: NominationReceipt):
    return issue_owner_approval(
        approval_id="test-fourfold-approval",
        owner_id="fixture-owner",
        key_id="fixture-owner-key",
        operation="promote-candidate",
        nomination_receipt_sha256=nomination.digest,
        candidate_artifact_sha256=candidate_sha,
        evidence_packet_sha256=packet.digest,
        base_revision=packet.source_revision,
        target_ref="experimental",
        expected_target_revision=TARGET_REVISION,
        nonce="test-fourfold-approval-nonce",
        issued_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(minutes=10)).isoformat(),
        provenance=ContractProvenance(
            origin="tests.fourfold-owner-approval",
            source_revision=packet.source_revision,
            created_at=NOW.isoformat(),
            input_digests=(nomination.digest, candidate_sha, packet.digest),
            trace_id="g0-fourfold-evidence-binding",
        ),
        secret=OWNER_SECRET,
    )


def _expectation(candidate_sha: str, packet: EvidencePacket, nomination: NominationReceipt):
    return ApprovalExpectation(
        operation="promote-candidate",
        nomination_receipt_sha256=nomination.digest,
        candidate_artifact_sha256=candidate_sha,
        evidence_packet_sha256=packet.digest,
        base_revision=packet.source_revision,
        target_ref="experimental",
        current_target_revision=TARGET_REVISION,
    )


def test_real_fourfold_snapshot_binds_evidence_nomination_and_owner_approval() -> None:
    compiled, candidate_sha, packet, nomination = _evidence(FIXTURE)
    snapshot = compiled.snapshot

    assert all(plane.status == "complete" for plane in snapshot.planes)
    assert tuple(snapshot.plane_map) == ("code", "type", "data", "knowledge")
    assert len(snapshot.bindings) == 31
    assert packet.subject_sha256 == snapshot.digest
    assert packet.candidate_artifact_sha256 == candidate_sha
    assert nomination.evidence_packet_sha256 == packet.digest

    approval = _approval(candidate_sha, packet, nomination)
    verified = verify_owner_approval(
        approval,
        keyring={("fixture-owner", "fixture-owner-key"): OWNER_SECRET},
        expectation=_expectation(candidate_sha, packet, nomination),
        now=NOW + timedelta(seconds=1),
    )

    assert verified.candidate_artifact_sha256 == candidate_sha
    assert verified.evidence_packet_sha256 == packet.digest
    assert verified.nomination_receipt_sha256 == nomination.digest


def test_source_mutation_invalidates_snapshot_evidence_and_old_approval(tmp_path: Path) -> None:
    root = tmp_path / "candidate"
    shutil.copytree(FIXTURE, root)
    before, candidate_before, packet_before, nomination_before = _evidence(root)
    approval = _approval(candidate_before, packet_before, nomination_before)

    source = root / "src" / "knowledge_hub" / "search.py"
    source.write_text(
        source.read_text(encoding="utf-8") + "\n# evidence-bearing source mutation\n",
        encoding="utf-8",
    )
    after, candidate_after, packet_after, nomination_after = _evidence(root)

    assert after.snapshot.digest != before.snapshot.digest
    assert candidate_after != candidate_before
    assert packet_after.digest != packet_before.digest
    assert nomination_after.digest != nomination_before.digest

    with pytest.raises(ApprovalBindingMismatch, match="binding mismatch"):
        verify_owner_approval(
            approval,
            keyring={("fixture-owner", "fixture-owner-key"): OWNER_SECRET},
            expectation=_expectation(candidate_after, packet_after, nomination_after),
            now=NOW + timedelta(seconds=1),
        )


def test_revision_substitution_cannot_reuse_snapshot_bound_approval() -> None:
    _, candidate_sha, packet, nomination = _evidence(FIXTURE, REVISION)
    approval = _approval(candidate_sha, packet, nomination)
    _, other_candidate, other_packet, other_nomination = _evidence(
        FIXTURE,
        "c" * 40,
    )

    assert other_packet.source_revision != packet.source_revision
    assert other_packet.digest != packet.digest
    with pytest.raises(ApprovalBindingMismatch, match="base_revision"):
        verify_owner_approval(
            approval,
            keyring={("fixture-owner", "fixture-owner-key"): OWNER_SECRET},
            expectation=_expectation(other_candidate, other_packet, other_nomination),
            now=NOW + timedelta(seconds=1),
        )


def test_test_fixture_approval_is_inert_and_never_consumed_or_promoted() -> None:
    _, candidate_sha, packet, nomination = _evidence(FIXTURE)
    approval = _approval(candidate_sha, packet, nomination)

    assert approval.owner_id == "fixture-owner"
    assert approval.key_id == "fixture-owner-key"
    assert "consumed" not in approval.to_dict()
    assert "promotion" not in approval.to_dict()
