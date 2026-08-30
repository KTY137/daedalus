# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from daedalus.gates.report import GateReport, assert_monotonic, build_gate0_report
from daedalus.spine.writer_inventory import scan_event_store_writers


REVISION = "a" * 40
NEXT_REVISION = "b" * 40


def test_gate_report_is_deterministic_and_fail_closed() -> None:
    root = Path(__file__).resolve().parents[2]
    first = build_gate0_report(root, source_revision=REVISION)
    second = build_gate0_report(root, source_revision=REVISION)
    assert first.to_dict() == second.to_dict()
    assert first.closed is False
    assert first.security_boundary_claimed is False
    assert first.owner_approval_enforced is True
    assert first.event_store_writer_inventory_sha256 is not None
    assert "python.offload" not in first.unguarded_entrypoints
    assert "python.offload" not in first.inventory_only_production_entrypoints
    assert "python.promote_candidates" not in first.unguarded_entrypoints


def test_gate_report_binds_exact_writer_inventory_digest() -> None:
    root = Path(__file__).resolve().parents[2]
    inventory = scan_event_store_writers(root, source_revision=REVISION)
    report = build_gate0_report(root, source_revision=REVISION)
    assert report.event_store_writer_inventory_sha256 == inventory.digest
    assert report.event_store_writer_failures == tuple(
        f"{site.path}:{site.line}:{site.column}:{site.kind}:{site.callee}"
        for site in inventory.blockers
    )


def test_round_trip_rejects_tampering() -> None:
    report = GateReport(
        gate=0,
        source_revision=NEXT_REVISION,
        registry_sha256="c" * 64,
        security_boundary_claimed=False,
        unguarded_entrypoints=("z", "z", "a"),
        event_store_writer_inventory_sha256="d" * 64,
    )
    payload = report.to_dict()
    restored = GateReport.from_dict(payload)
    assert restored.unguarded_entrypoints == ("a", "z")
    assert restored.event_store_writer_inventory_sha256 == "d" * 64
    payload["event_store_writer_failures"] = []
    payload["event_store_writer_inventory_sha256"] = "e" * 64
    with pytest.raises(ValueError, match="digest mismatch"):
        GateReport.from_dict(payload)


def test_monotonic_comparison_refuses_new_blockers() -> None:
    baseline = GateReport(
        gate=0,
        source_revision=REVISION,
        registry_sha256="1" * 64,
        security_boundary_claimed=False,
        unguarded_entrypoints=("old",),
        event_store_writer_inventory_sha256="3" * 64,
    )
    current = GateReport(
        gate=0,
        source_revision=NEXT_REVISION,
        registry_sha256="2" * 64,
        security_boundary_claimed=False,
        unguarded_entrypoints=("old", "new"),
        event_store_writer_inventory_sha256="4" * 64,
    )
    assert assert_monotonic(current, baseline) == (
        "unguarded_entrypoints:new",
    )


def test_monotonic_comparison_includes_new_writer_findings() -> None:
    baseline = GateReport(
        gate=0,
        source_revision=REVISION,
        registry_sha256="1" * 64,
        security_boundary_claimed=False,
        event_store_writer_inventory_sha256="3" * 64,
    )
    current = GateReport(
        gate=0,
        source_revision=NEXT_REVISION,
        registry_sha256="2" * 64,
        security_boundary_claimed=False,
        event_store_writer_inventory_sha256="4" * 64,
        event_store_writer_failures=(
            "daedalus/app.py:10:4:legacy_direct:daedalus.spine.SpineLedger",
        ),
    )
    assert assert_monotonic(current, baseline) == (
        "event_store_writer_failures:"
        "daedalus/app.py:10:4:legacy_direct:daedalus.spine.SpineLedger",
    )


def test_serialized_shape_matches_gate_contract_v2() -> None:
    report = GateReport(
        gate=0,
        source_revision=REVISION,
        registry_sha256="0" * 64,
        security_boundary_claimed=True,
        owner_approval_enforced=True,
        event_store_writer_inventory_sha256="1" * 64,
    )
    payload = report.to_dict()
    assert payload["schema"] == "daedalus-gate-report/2"
    assert payload["closed"] is True
    assert payload["event_store_writer_inventory_sha256"] == "1" * 64
    assert payload["event_store_writer_failures"] == []
    assert payload["blockers"] == []
    json.dumps(payload)


def test_legacy_v1_report_loads_but_cannot_claim_current_closure() -> None:
    body = {
        "schema": "daedalus-gate-report/1",
        "gate": 0,
        "source_revision": REVISION,
        "registry_sha256": "0" * 64,
        "closed": True,
        "security_boundary_claimed": True,
        "unregistered_effectful_entrypoints": [],
        "unguarded_entrypoints": [],
        "inventory_only_production_entrypoints": [],
        "missing_guard_contracts": [],
        "runtime_conformance_failures": [],
        "fault_injection_failures": [],
        "primary_checkout_mutations": [],
        "owner_approval_enforced": True,
        "diagnostics": [],
        "blockers": [],
    }
    body["report_sha256"] = hashlib.sha256(
        json.dumps(
            body,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()
    ).hexdigest()
    restored = GateReport.from_dict(body)
    assert restored.closed is False
    assert restored.event_store_writer_inventory_sha256 is None
    assert (
        "event_store_writer_inventory_sha256:missing" in restored.blockers
    )
    assert restored.to_dict()["schema"] == "daedalus-gate-report/2"


def test_gate_report_accepts_bound_fault_results() -> None:
    """Caller-supplied rows supplement the bound matrix verdict; they never replace it.

    ``fault_results`` used to be the only source of this field, so an empty map
    read as "no fault findings".  The whole-matrix binding now always runs, so a
    caller can add rows but cannot subtract the verdict's own.
    """

    root = Path(__file__).resolve().parents[2]
    report = build_gate0_report(
        root,
        source_revision=REVISION,
        fault_results={"approval-replay": True, "target-head-race": False},
        security_boundary_claimed=True,
    )
    assert report.security_boundary_claimed is True
    assert report.owner_approval_enforced is True
    assert "target-head-race" in report.fault_injection_failures
    assert "approval-replay" not in report.fault_injection_failures
    assert report.event_store_writer_inventory_sha256 is not None
    assert report.closed is False

    laundered = build_gate0_report(
        root,
        source_revision=REVISION,
        fault_results={},
        security_boundary_claimed=True,
    )
    assert laundered.fault_injection_failures != ()
    assert laundered.closed is False


def test_missing_writer_inventory_digest_is_always_a_blocker() -> None:
    report = GateReport(
        gate=0,
        source_revision=REVISION,
        registry_sha256="0" * 64,
        security_boundary_claimed=True,
        owner_approval_enforced=True,
    )
    assert report.closed is False
    assert report.blockers == (
        "event_store_writer_inventory_sha256:missing",
    )


def test_writer_inventory_digest_validation_is_fail_closed() -> None:
    with pytest.raises(ValueError, match="event_store_writer_inventory_sha256"):
        GateReport(
            gate=0,
            source_revision=REVISION,
            registry_sha256="0" * 64,
            security_boundary_claimed=False,
            event_store_writer_inventory_sha256="bad",
        )


def test_source_revision_must_be_exact_lowercase_commit() -> None:
    for revision in ("a", "A" * 40, "a" * 39, "g" * 40, "a" * 64):
        with pytest.raises(ValueError, match="source_revision"):
            GateReport(
                gate=0,
                source_revision=revision,
                registry_sha256="0" * 64,
                security_boundary_claimed=False,
            )
