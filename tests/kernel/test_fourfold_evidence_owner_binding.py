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
from daedalus.kernel.fourfold_evidence import (
    FourfoldEvidenceExpectation,
    FourfoldEvidenceMismatch,
    assemble_fourfold_evidence_packet,
    assemble_fourfold_nomination_receipt,
    verify_fourfold_evidence_packet,
    verify_fourfold_nomination_receipt,
)
from daedalus.schemas import ContractProvenance, ResourceUsage
from daedalus.twin import compile_reference_project


REVISION = "a" * 40
TARGET_REVISION = "b" * 40
NOW = datetime(2026, 8, 3, 16, 0, tzinfo=timezone.utc)
OWNER_SECRET = b"test-only-owner-key-material-32-bytes-minimum"
FIXTURE = Path(__file__).resolve().parents[2] / "examples" / "fourfold_wiki_app"


def _sha(value: str | bytes) -> str:
    raw = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


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


def _artifacts(root: Path, revision: str = REVISION):
    compiled = _compile(root, revision)
    snapshot = compiled.snapshot
    candidate_sha = _tree_digest(root)
    candidate_locator = f"artifact-locator:sha256:{candidate_sha}"
    expectation = FourfoldEvidenceExpectation(
        candidate_artifact_sha256=candidate_sha,
        candidate_artifact_locator=candidate_locator,
        snapshot_sha256=snapshot.digest,
        source_revision=revision,
    )
    packet = assemble_fourfold_evidence_packet(
        snapshot=snapshot,
        candidate_artifact_sha256=candidate_sha,
        candidate_artifact_locator=candidate_locator,
        packet_id="fourfold-evidence-packet",
        mission_id="g0-fourfold-binding",
        attempt_id="g0-fourfold-binding-attempt",
        attempt_contract_sha256=_sha("fixture-attempt-contract"),
        policy_decision_sha256=_sha("fixture-policy-decision"),
        collected_at=NOW.isoformat(),
        usage=ResourceUsage(wall_time_ms=1),
        trace_id="g0-fourfold-evidence-binding",
    )
    nomination = assemble_fourfold_nomination_receipt(
        snapshot=snapshot,
        packet=packet,
        expectation=expectation,
        nomination_id="fourfold-nomination",
        reasons=("deterministic Fourfold snapshot and candidate tree are retained",),
        created_at=NOW.isoformat(),
        trace_id="g0-fourfold-evidence-binding",
    )
    return compiled, candidate_sha, expectation, packet, nomination


def _approval(candidate_sha, packet, nomination):
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


def _approval_expectation(candidate_sha, packet, nomination):
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
    compiled, candidate_sha, expectation, packet, nomination = _artifacts(FIXTURE)
    snapshot = compiled.snapshot

    assert all(plane.status == "complete" for plane in snapshot.planes)
    assert tuple(snapshot.plane_map) == ("code", "type", "data", "knowledge")
    assert len(snapshot.bindings) == 31
    assert packet.subject_sha256 == candidate_sha
    assert packet.items[0].output_sha256 == snapshot.digest
    assert nomination.evidence_packet_sha256 == packet.digest

    verify_fourfold_evidence_packet(
        packet,
        snapshot=snapshot,
        expectation=expectation,
    )
    verify_fourfold_nomination_receipt(
        nomination,
        packet=packet,
        snapshot=snapshot,
        expectation=expectation,
    )

    approval = _approval(candidate_sha, packet, nomination)
    verified = verify_owner_approval(
        approval,
        keyring={("fixture-owner", "fixture-owner-key"): OWNER_SECRET},
        expectation=_approval_expectation(candidate_sha, packet, nomination),
        now=NOW + timedelta(seconds=1),
    )

    assert verified.candidate_artifact_sha256 == candidate_sha
    assert verified.evidence_packet_sha256 == packet.digest
    assert verified.nomination_receipt_sha256 == nomination.digest


def test_source_mutation_invalidates_snapshot_evidence_and_old_approval(tmp_path: Path) -> None:
    root = tmp_path / "candidate"
    shutil.copytree(FIXTURE, root)
    before, candidate_before, _, packet_before, nomination_before = _artifacts(root)
    approval = _approval(candidate_before, packet_before, nomination_before)

    source = root / "src" / "knowledge_hub" / "search.py"
    source.write_text(
        source.read_text(encoding="utf-8") + "\n# evidence-bearing source mutation\n",
        encoding="utf-8",
    )
    after, candidate_after, expectation_after, packet_after, nomination_after = _artifacts(root)

    assert after.snapshot.digest != before.snapshot.digest
    assert candidate_after != candidate_before
    assert packet_after.digest != packet_before.digest
    assert nomination_after.digest != nomination_before.digest
    verify_fourfold_nomination_receipt(
        nomination_after,
        packet=packet_after,
        snapshot=after.snapshot,
        expectation=expectation_after,
    )

    with pytest.raises(ApprovalBindingMismatch, match="binding mismatch"):
        verify_owner_approval(
            approval,
            keyring={("fixture-owner", "fixture-owner-key"): OWNER_SECRET},
            expectation=_approval_expectation(
                candidate_after,
                packet_after,
                nomination_after,
            ),
            now=NOW + timedelta(seconds=1),
        )


def test_revision_substitution_cannot_reuse_snapshot_bound_approval() -> None:
    _, candidate_sha, _, packet, nomination = _artifacts(FIXTURE, REVISION)
    approval = _approval(candidate_sha, packet, nomination)
    _, other_candidate, _, other_packet, other_nomination = _artifacts(
        FIXTURE,
        "c" * 40,
    )

    assert other_packet.source_revision != packet.source_revision
    assert other_packet.digest != packet.digest
    with pytest.raises(ApprovalBindingMismatch, match="base_revision"):
        verify_owner_approval(
            approval,
            keyring={("fixture-owner", "fixture-owner-key"): OWNER_SECRET},
            expectation=_approval_expectation(
                other_candidate,
                other_packet,
                other_nomination,
            ),
            now=NOW + timedelta(seconds=1),
        )


def test_foreign_candidate_locator_is_refused_before_evidence_assembly() -> None:
    compiled = _compile(FIXTURE)
    candidate_sha = _tree_digest(FIXTURE)

    with pytest.raises(FourfoldEvidenceMismatch, match="does not resolve"):
        assemble_fourfold_evidence_packet(
            snapshot=compiled.snapshot,
            candidate_artifact_sha256=candidate_sha,
            candidate_artifact_locator=(
                "artifact-locator:sha256:" + _sha("foreign-candidate")
            ),
            packet_id="foreign-locator-packet",
            mission_id="g0-fourfold-binding",
            attempt_id="g0-fourfold-binding-attempt",
            attempt_contract_sha256=_sha("fixture-attempt-contract"),
            policy_decision_sha256=_sha("fixture-policy-decision"),
            collected_at=NOW.isoformat(),
        )


def test_foreign_nomination_cannot_be_paired_with_valid_packet(tmp_path: Path) -> None:
    base, _, expectation, packet, nomination = _artifacts(FIXTURE)
    root = tmp_path / "foreign"
    shutil.copytree(FIXTURE, root)
    source = root / "src" / "knowledge_hub" / "models.py"
    source.write_text(
        source.read_text(encoding="utf-8") + "\n# foreign candidate\n",
        encoding="utf-8",
    )
    _, _, _, _, foreign_nomination = _artifacts(root)

    verify_fourfold_nomination_receipt(
        nomination,
        packet=packet,
        snapshot=base.snapshot,
        expectation=expectation,
    )
    with pytest.raises(FourfoldEvidenceMismatch, match="nomination binding mismatch"):
        verify_fourfold_nomination_receipt(
            foreign_nomination,
            packet=packet,
            snapshot=base.snapshot,
            expectation=expectation,
        )


def test_fixture_approval_is_inert_and_never_consumed_or_promoted() -> None:
    _, candidate_sha, _, packet, nomination = _artifacts(FIXTURE)
    approval = _approval(candidate_sha, packet, nomination)

    assert approval.owner_id == "fixture-owner"
    assert approval.key_id == "fixture-owner-key"
    assert "consumed" not in approval.to_dict()
    assert "promotion" not in approval.to_dict()
