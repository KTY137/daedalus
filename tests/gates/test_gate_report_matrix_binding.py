"""The Gate-0 report speaks the bound matrix verdict, and never a silent pass."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from daedalus.gates.report import build_gate0_report
from daedalus.gates.report_v3 import build_gate0_report_v3
from daedalus.spine.envelope import canonical_json


ROOT = Path(__file__).resolve().parents[2]
LANDED_DIR = ROOT / "runs" / "gate0-matrix-2026-08-17"
LANDED_REVISION = "c93191fef4a89de316529d22d54713acebeae097"
SCOPING_DOC = "docs/GATE0_LINUX_FAULT_SCOPING_DECISION.md"
REVISION = "a" * 40

BLOCKED_ROWS = (
    "fault.blocked:runtime.egress.unauthorized-endpoint",
    "fault.blocked:runtime.process.oom",
    "fault.blocked:runtime.sandbox.daemon-unavailable",
    "fault.blocked:runtime.secrets.undeclared-access",
)
MISSING_ROWS = (
    "fault.missing:runtime.live-envelope.binary-drift",
    "fault.missing:runtime.live-envelope.expiry",
)


def test_the_report_binds_the_landed_verdict_at_this_repository() -> None:
    report = build_gate0_report(ROOT, source_revision=REVISION)
    assert set(MISSING_ROWS).issubset(report.fault_injection_failures)
    assert not set(BLOCKED_ROWS) & set(report.fault_injection_failures)
    assert (
        f"whole-matrix:observed-at-other-revision:{LANDED_REVISION}"
        in report.fault_injection_failures
    )
    for row in BLOCKED_ROWS:
        assert f"declared:fault_matrix.scoped:{row}@{SCOPING_DOC}" in report.diagnostics
    assert "info:fault_matrix.key_class:linux-host=development" in report.diagnostics
    assert "fault-matrix:not-yet-bound" not in report.fault_injection_failures
    assert report.closed is False


def test_every_bound_fault_row_reaches_the_blocker_list() -> None:
    report = build_gate0_report(ROOT, source_revision=REVISION)
    for row in report.fault_injection_failures:
        assert f"fault_injection_failures:{row}" in report.blockers


def test_a_repository_without_evidence_still_blocks(tmp_path: Path) -> None:
    report = build_gate0_report(
        ROOT, source_revision=REVISION, fault_matrix_evidence_dir=tmp_path / "nowhere"
    )
    assert "whole-matrix:unbound:no-verdict-artifact" in report.fault_injection_failures
    assert (
        "fault_injection_failures:whole-matrix:unbound:no-verdict-artifact"
        in report.blockers
    )


def test_a_tampered_verdict_makes_the_report_refuse_the_bundle(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    for name in ("whole-matrix-verdict.json", "receipt.json"):
        shutil.copyfile(LANDED_DIR / name, evidence / name)
    verdict = evidence / "whole-matrix-verdict.json"
    payload = json.loads(verdict.read_text(encoding="utf-8"))
    payload["closed"] = True
    verdict.write_text(canonical_json(payload) + "\n", encoding="utf-8")
    report = build_gate0_report(
        ROOT, source_revision=REVISION, fault_matrix_evidence_dir=evidence
    )
    assert "whole-matrix:unbound:verdict-invalid" in report.fault_injection_failures
    assert not set(MISSING_ROWS) & set(report.fault_injection_failures)


def test_claiming_the_boundary_over_dev_keys_adds_its_own_blocker() -> None:
    report = build_gate0_report(
        ROOT,
        source_revision=LANDED_REVISION,
        security_boundary_claimed=True,
    )
    assert (
        "whole-matrix:security-boundary-unproven:key-material-development"
        in report.fault_injection_failures
    )
    assert report.closed is False


def test_legacy_fault_results_supplement_the_binding_and_cannot_replace_it() -> None:
    report = build_gate0_report(
        ROOT,
        source_revision=REVISION,
        fault_results={"approval-replay": True, "target-head-race": False},
    )
    assert "target-head-race" in report.fault_injection_failures
    assert set(MISSING_ROWS).issubset(report.fault_injection_failures)


def test_an_empty_fault_results_map_cannot_launder_the_matrix_away() -> None:
    report = build_gate0_report(ROOT, source_revision=REVISION, fault_results={})
    assert set(MISSING_ROWS).issubset(report.fault_injection_failures)


def test_the_conformance_blocker_names_the_missing_producer_link() -> None:
    report = build_gate0_report(ROOT, source_revision=REVISION)
    assert report.runtime_conformance_failures == (
        "runtime-conformance-receipts:unbound:no-persisted-receipt-bundle",
    )
    assert "runtime-conformance-receipts:not-yet-bound" not in (
        report.runtime_conformance_failures
    )
    assert any(
        row.startswith("info:runtime_conformance.canonical_producer:")
        for row in report.diagnostics
    )


def test_report_v3_carries_the_same_bound_rows() -> None:
    report = build_gate0_report_v3(ROOT, source_revision=REVISION)
    assert set(MISSING_ROWS).issubset(report.fault_injection_failures)
    assert not set(BLOCKED_ROWS) & set(report.fault_injection_failures)
    assert report.runtime_conformance_failures == (
        "runtime-conformance-receipts:unbound:no-persisted-receipt-bundle",
    )
    restored = type(report).from_dict(report.to_dict())
    assert restored.to_dict() == report.to_dict()


def test_the_report_stays_deterministic_with_the_binding_wired() -> None:
    first = build_gate0_report(ROOT, source_revision=REVISION)
    second = build_gate0_report(ROOT, source_revision=REVISION)
    assert first.to_dict() == second.to_dict()
