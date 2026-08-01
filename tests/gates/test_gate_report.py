from __future__ import annotations

import json
from pathlib import Path

import pytest

from daedalus.gates.report import GateReport, assert_monotonic, build_gate0_report


def test_gate_report_is_deterministic_and_fail_closed() -> None:
    root = Path(__file__).resolve().parents[2]
    first = build_gate0_report(root, source_revision="a" * 40)
    second = build_gate0_report(root, source_revision="a" * 40)
    assert first.to_dict() == second.to_dict()
    assert first.closed is False
    assert first.security_boundary_claimed is False
    assert first.owner_approval_enforced is False
    assert "python.offload" in first.unguarded_entrypoints
    assert "python.promote_candidates" in first.unguarded_entrypoints


def test_round_trip_rejects_tampering() -> None:
    report = GateReport(
        gate=0,
        source_revision="b" * 40,
        registry_sha256="c" * 64,
        security_boundary_claimed=False,
        unguarded_entrypoints=("z", "z", "a"),
    )
    payload = report.to_dict()
    restored = GateReport.from_dict(payload)
    assert restored.unguarded_entrypoints == ("a", "z")
    payload["unguarded_entrypoints"] = []
    with pytest.raises(ValueError, match="digest mismatch"):
        GateReport.from_dict(payload)


def test_monotonic_comparison_refuses_new_blockers() -> None:
    baseline = GateReport(
        gate=0,
        source_revision="a",
        registry_sha256="1" * 64,
        security_boundary_claimed=False,
        unguarded_entrypoints=("old",),
    )
    current = GateReport(
        gate=0,
        source_revision="b",
        registry_sha256="2" * 64,
        security_boundary_claimed=False,
        unguarded_entrypoints=("old", "new"),
    )
    assert assert_monotonic(current, baseline) == ("unguarded_entrypoints:new",)


def test_serialized_shape_matches_gate_contract() -> None:
    report = GateReport(
        gate=0,
        source_revision="a",
        registry_sha256="0" * 64,
        security_boundary_claimed=True,
        owner_approval_enforced=True,
    )
    payload = report.to_dict()
    assert payload["schema"] == "daedalus-gate-report/1"
    assert payload["closed"] is True
    assert payload["blockers"] == []
    json.dumps(payload)
