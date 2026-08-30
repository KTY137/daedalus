from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from daedalus.chip_design.contracts import (
    ChipRunReceipt,
    build_chip_contracts,
    build_evidence_packet,
    default_dimensions,
)
from daedalus.spine.envelope import canonical_sha
from daedalus.storage import ArtifactStore


NOW = datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _contracts():
    return build_chip_contracts(
        mission_id="chip-mission-1234",
        attempt_id="chip-attempt-1234",
        phase="impl",
        manifest_sha256="a" * 64,
        trusted_tcl_sha256="b" * 64,
        runtime_manifest_sha256="c" * 64,
        policy_decision_sha256="d" * 64,
        policy_sha256="e" * 64,
        timeout_s=90,
        created_at=NOW,
    )


def _receipt(**changes):
    body = dict(
        run_id="chip-run-1234",
        mission_id="chip-mission-1234",
        attempt_id="chip-attempt-1234",
        phase="impl",
        source_revision="a" * 64,
        manifest_sha256="a" * 64,
        trusted_tcl_sha256="b" * 64,
        tool={"id": "vivado", "version": "2025.1.1"},
        execution={"status": "ok", "duration_s": 12.5, "returncode": 0},
        effect_start={"receipt_sha256": "f" * 64},
        effect_terminal={"receipt_sha256": "1" * 64, "outcome": "COMPLETED"},
        metrics={"timing": {"wns_ns": 0.162, "whs_ns": 0.021}},
        dimensions=default_dimensions("impl"),
        verdict="passed",
        limitations=("simulation not run",),
        created_at=NOW,
    )
    body.update(changes)
    return ChipRunReceipt(**body)


def test_contract_pair_binds_manifest_tcl_runtime_and_policy():
    mission, attempt = _contracts()
    assert mission.source_revision == "a" * 64
    assert attempt.base_revision == mission.source_revision
    assert attempt.policy_decision_sha256 == "d" * 64
    assert attempt.runtime_manifest_sha256 == "c" * 64
    assert attempt.writable_paths == (".",)
    assert attempt.budget.max_wall_time_s == 90


def test_successful_build_stays_inconclusive_when_signoff_dimensions_are_not_run(tmp_path):
    _mission, attempt = _contracts()
    receipt = _receipt()
    raw = receipt.to_json().encode("ascii")
    locator = ArtifactStore(tmp_path).put_bytes(
        raw,
        expected_sha256=canonical_sha(receipt.to_dict()),
        media_type="application/json",
        provenance={
            "origin": "test.chip",
            "source_revision": receipt.source_revision,
            "created_at": NOW,
            "input_digests": [],
            "trace_id": None,
        },
    )
    packet = build_evidence_packet(
        receipt=receipt,
        receipt_locator=locator,
        attempt=attempt,
        policy_decision_sha256="d" * 64,
    )
    assert packet.evaluation_status == "inconclusive"
    assert packet.items[0].verdict == "passed"
    assert packet.candidate_artifact_sha256 is None
    assert packet.items[0].details["security_boundary_claimed"] is False


def test_failed_build_retains_failure_without_claiming_verified_assurance(tmp_path):
    _mission, attempt = _contracts()
    receipt = _receipt(
        verdict="failed",
        execution={"status": "failed", "duration_s": 1.0, "returncode": 1},
    )
    locator = ArtifactStore(tmp_path).put_bytes(
        receipt.to_json().encode("ascii"),
        media_type="application/json",
        provenance={
            "origin": "test.chip",
            "source_revision": receipt.source_revision,
            "created_at": NOW,
            "input_digests": [],
            "trace_id": None,
        },
    )
    packet = build_evidence_packet(
        receipt=receipt,
        receipt_locator=locator,
        attempt=attempt,
        policy_decision_sha256="d" * 64,
    )
    assert packet.evaluation_status == "inconclusive"
    assert packet.items[0].verdict == "failed"
    assert packet.items[0].assurance == "unverified"


def test_receipt_cannot_claim_a_host_security_boundary():
    with pytest.raises(ValueError, match="not an operating-system sandbox"):
        _receipt(security_boundary_claimed=True)


def test_dimensions_keep_vitis_and_unrun_verification_explicit():
    dimensions = default_dimensions("impl")
    assert dimensions["implementation"] == "pending"
    assert dimensions["vitis_software"] == "not_run"
    assert dimensions["cdc_rdc"] == "not_run"
    assert dimensions["hardware_in_loop"] == "not_run"
