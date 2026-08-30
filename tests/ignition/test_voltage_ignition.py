# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from daedalus.ignition import run_voltage_ignition
from daedalus.kernel.approvals import (
    ApprovalBindingMismatch,
    ApprovalExpectation,
    issue_owner_approval,
    verify_owner_approval,
)
from daedalus.schemas import ContractProvenance
from daedalus.spine.envelope import canonical_sha

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "ignition" / "voltage"
BASE = "1" * 40
CANDIDATE = "2" * 40
NOW = "2026-08-02T00:00:00Z"
SECRET = b"owner-secret-material-must-be-at-least-thirty-two-bytes"


def _run(tmp_path: Path, name: str = "candidate"):
    return run_voltage_ignition(
        FIXTURE,
        tmp_path / name,
        base_revision=BASE,
        candidate_revision=CANDIDATE,
        collected_at=NOW,
    )


def test_gate1_voltage_rename_builds_real_fourfold_delta_and_evidence(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result.primary_unchanged
    assert result.base_source_bundle_sha256 != result.candidate_source_bundle_sha256
    assert result.base_snapshot.digest != result.candidate_snapshot.digest
    assert len(result.base_snapshot.bindings) == 10
    assert len(result.candidate_snapshot.bindings) == 10
    assert result.graph_delta.added_nodes
    assert result.graph_delta.removed_nodes
    assert result.evidence_packet.evaluation_status == "passed"
    assert result.evidence_packet.candidate_artifact_sha256 == result.candidate_source_bundle_sha256
    assert {item.evaluator for item in result.evidence_packet.items} == {
        "fourfold.snapshot-binding",
        "ignition-behavior",
        "ignition-graph-delta",
    }
    candidate = tmp_path / "candidate"
    assert "bias_voltage" in (candidate / "src/ignition_app/models.py").read_text()
    assert "id,bias_voltage" in (candidate / "data/events.csv").read_text()
    assert '"bias_voltage"' in (candidate / "schemas/event.schema.json").read_text()
    assert "`voltage`" not in (candidate / "wiki/Event.md").read_text()


def test_gate1_replay_is_digest_identical(tmp_path: Path) -> None:
    first = _run(tmp_path, "candidate-a")
    second = _run(tmp_path, "candidate-b")
    assert first.candidate_source_bundle_sha256 == second.candidate_source_bundle_sha256
    assert first.candidate_snapshot.digest == second.candidate_snapshot.digest
    assert first.graph_delta.digest == second.graph_delta.digest
    assert first.evidence_packet.digest == second.evidence_packet.digest
    assert first.behavior_sha256 == second.behavior_sha256


def test_gate1_owner_approval_binds_exact_candidate_and_evidence(tmp_path: Path) -> None:
    result = _run(tmp_path)
    nomination = canonical_sha({"nomination": "gate1"})
    now = datetime.fromisoformat(NOW.replace("Z", "+00:00"))
    approval = issue_owner_approval(
        approval_id="gate1-approval",
        owner_id="KTY137",
        key_id="owner-key",
        operation="promote-candidate",
        nomination_receipt_sha256=nomination,
        candidate_artifact_sha256=result.candidate_source_bundle_sha256,
        evidence_packet_sha256=result.evidence_packet.digest,
        base_revision=BASE,
        target_ref="experimental",
        expected_target_revision="3" * 40,
        nonce="gate1-nonce",
        issued_at=now.isoformat(),
        expires_at=(now + timedelta(minutes=10)).isoformat(),
        provenance=ContractProvenance(
            origin="tests.gate1.approval",
            source_revision=BASE,
            created_at=now.isoformat(),
            input_digests=(
                nomination,
                result.candidate_source_bundle_sha256,
                result.evidence_packet.digest,
            ),
        ),
        secret=SECRET,
    )
    expectation = ApprovalExpectation(
        operation="promote-candidate",
        nomination_receipt_sha256=nomination,
        candidate_artifact_sha256=result.candidate_source_bundle_sha256,
        evidence_packet_sha256=result.evidence_packet.digest,
        base_revision=BASE,
        target_ref="experimental",
        current_target_revision="3" * 40,
    )
    verified = verify_owner_approval(
        approval,
        keyring={("KTY137", "owner-key"): SECRET},
        expectation=expectation,
        now=now + timedelta(seconds=1),
    )
    assert verified.candidate_artifact_sha256 == result.candidate_source_bundle_sha256
    assert verified.evidence_packet_sha256 == result.evidence_packet.digest

    with pytest.raises(ApprovalBindingMismatch, match="candidate_artifact_sha256"):
        verify_owner_approval(
            approval,
            keyring={("KTY137", "owner-key"): SECRET},
            expectation=ApprovalExpectation(
                **{
                    **expectation.__dict__,
                    "candidate_artifact_sha256": "f" * 64,
                }
            ),
            now=now + timedelta(seconds=1),
        )


def test_gate1_candidate_revision_is_part_of_snapshot_identity(tmp_path: Path) -> None:
    first = _run(tmp_path, "candidate-a")
    second = run_voltage_ignition(
        FIXTURE,
        tmp_path / "candidate-b",
        base_revision=BASE,
        candidate_revision="4" * 40,
        collected_at=NOW,
    )
    assert first.candidate_source_bundle_sha256 == second.candidate_source_bundle_sha256
    assert first.candidate_snapshot.digest != second.candidate_snapshot.digest
    assert first.evidence_packet.digest != second.evidence_packet.digest
