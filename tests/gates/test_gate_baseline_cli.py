from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from daedalus.gates.baseline import GateBaseline, GateMonotonicityReceipt
from daedalus.gates.report import GateReport
from daedalus.spine.ledger import ROOT


SCRIPT = ROOT / "scripts" / "gate0_baseline.py"
BASE_REVISION = "a" * 40
BASE_TREE = "b" * 40
CURRENT_REVISION = "c" * 40
CURRENT_TREE = "d" * 40
REGISTRY = "e" * 64
WRITERS = "f" * 64


def _report(*, current: bool = False, new_blocker: bool = False) -> GateReport:
    failures = (
        "daedalus/app.py:1:0:legacy_direct:daedalus.spine.SpineLedger",
    ) if new_blocker else ()
    return GateReport(
        gate=0,
        source_revision=CURRENT_REVISION if current else BASE_REVISION,
        registry_sha256=REGISTRY,
        security_boundary_claimed=False,
        unguarded_entrypoints=("python.legacy",),
        event_store_writer_inventory_sha256=WRITERS,
        event_store_writer_failures=failures,
        owner_approval_enforced=True,
    )


def _write(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def test_cli_create_compare_and_verify_round_trip(tmp_path: Path) -> None:
    baseline_report_path = tmp_path / "baseline-report.json"
    current_report_path = tmp_path / "current-report.json"
    baseline_path = tmp_path / "baseline.json"
    receipt_path = tmp_path / "receipt.json"
    _write(baseline_report_path, _report().to_dict())
    _write(current_report_path, _report(current=True).to_dict())

    created = _run(
        "create",
        "--report",
        str(baseline_report_path),
        "--baseline-id",
        "gate0-baseline-1",
        "--source-tree-revision",
        BASE_TREE,
        "--created-at",
        "2026-08-04T00:00:00Z",
    )
    assert created.returncode == 0, created.stderr
    assert created.stderr == ""
    assert created.stdout.count("\n") == 1
    baseline = GateBaseline.from_dict(json.loads(created.stdout))
    baseline_path.write_text(created.stdout, encoding="utf-8")

    compared = _run(
        "compare",
        "--baseline",
        str(baseline_path),
        "--current-report",
        str(current_report_path),
        "--expected-baseline-sha256",
        baseline.digest,
        "--current-source-tree-revision",
        CURRENT_TREE,
        "--assessment-id",
        "gate0-assessment-1",
        "--assessed-at",
        "2026-08-04T00:05:00Z",
        "--require-monotonic",
    )
    assert compared.returncode == 0, compared.stderr
    assert compared.stderr == ""
    receipt = GateMonotonicityReceipt.from_dict(json.loads(compared.stdout))
    assert receipt.status == "passed"
    receipt_path.write_text(compared.stdout, encoding="utf-8")

    verified = _run(
        "verify",
        "--receipt",
        str(receipt_path),
        "--baseline",
        str(baseline_path),
        "--current-report",
        str(current_report_path),
        "--expected-baseline-sha256",
        baseline.digest,
        "--current-source-tree-revision",
        CURRENT_TREE,
        "--require-monotonic",
    )
    assert verified.returncode == 0, verified.stderr
    assert verified.stderr == ""
    assert json.loads(verified.stdout) == receipt.to_dict()


def test_compare_emits_failed_receipt_before_nonzero_monotonic_exit(
    tmp_path: Path,
) -> None:
    baseline_report_path = tmp_path / "baseline-report.json"
    current_report_path = tmp_path / "current-report.json"
    baseline_path = tmp_path / "baseline.json"
    _write(baseline_report_path, _report().to_dict())
    _write(current_report_path, _report(current=True, new_blocker=True).to_dict())

    created = _run(
        "create",
        "--report",
        str(baseline_report_path),
        "--baseline-id",
        "gate0-baseline-1",
        "--source-tree-revision",
        BASE_TREE,
        "--created-at",
        "2026-08-04T00:00:00Z",
    )
    baseline = GateBaseline.from_dict(json.loads(created.stdout))
    baseline_path.write_text(created.stdout, encoding="utf-8")

    compared = _run(
        "compare",
        "--baseline",
        str(baseline_path),
        "--current-report",
        str(current_report_path),
        "--expected-baseline-sha256",
        baseline.digest,
        "--current-source-tree-revision",
        CURRENT_TREE,
        "--assessment-id",
        "gate0-assessment-2",
        "--assessed-at",
        "2026-08-04T00:05:00Z",
        "--require-monotonic",
    )
    assert compared.returncode == 1
    assert compared.stderr == ""
    receipt = GateMonotonicityReceipt.from_dict(json.loads(compared.stdout))
    assert receipt.status == "failed"
    assert receipt.new_blockers


def test_cli_refuses_unpinned_or_malformed_baseline_without_partial_stdout(
    tmp_path: Path,
) -> None:
    baseline_report_path = tmp_path / "baseline-report.json"
    current_report_path = tmp_path / "current-report.json"
    baseline_path = tmp_path / "baseline.json"
    _write(baseline_report_path, _report().to_dict())
    _write(current_report_path, _report(current=True).to_dict())
    created = _run(
        "create",
        "--report",
        str(baseline_report_path),
        "--baseline-id",
        "gate0-baseline-1",
        "--source-tree-revision",
        BASE_TREE,
        "--created-at",
        "2026-08-04T00:00:00Z",
    )
    baseline_path.write_text(created.stdout, encoding="utf-8")

    refused = _run(
        "compare",
        "--baseline",
        str(baseline_path),
        "--current-report",
        str(current_report_path),
        "--expected-baseline-sha256",
        "0" * 64,
        "--current-source-tree-revision",
        CURRENT_TREE,
        "--assessment-id",
        "gate0-assessment-3",
        "--assessed-at",
        "2026-08-04T00:05:00Z",
    )
    assert refused.returncode == 2
    assert refused.stdout == ""
    assert "expected baseline digest mismatch" in refused.stderr

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    refused = _run(
        "compare",
        "--baseline",
        str(malformed),
        "--current-report",
        str(current_report_path),
        "--expected-baseline-sha256",
        "0" * 64,
        "--current-source-tree-revision",
        CURRENT_TREE,
        "--assessment-id",
        "gate0-assessment-4",
        "--assessed-at",
        "2026-08-04T00:05:00Z",
    )
    assert refused.returncode == 2
    assert refused.stdout == ""
    assert "malformed JSON" in refused.stderr
