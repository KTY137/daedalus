# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Both gate-report CLIs bind a conformance-receipt bundle only when told to.

Without ``--conformance-receipts`` the fail-closed unbound blocker is
unchanged; a directory that does not exist stays fail-closed with a named
bundle failure instead of silently binding nothing.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from daedalus.gates.__main__ import main as gates_main
from daedalus.gates.runtime_conformance_binding import UNBOUND_ROW
from daedalus.kernel.runtime_conformance import (
    RecordedObservation,
    assemble_recorded_conformance,
    persist_conformance_receipt,
)
from daedalus.schemas import (
    RUNTIME_CONFORMANCE_CHECKS,
    ContractProvenance,
    RuntimeCapabilities,
    RuntimeManifest,
)
from scripts.report_gate0_v3 import main as v3_main


ROOT = Path(__file__).resolve().parents[2]
REVISION = "1" * 40
NOW = datetime(2026, 8, 18, 0, 0, tzinfo=timezone.utc)
BOUND_INFO = "info:runtime_conformance.receipts:1"


def _manifest() -> RuntimeManifest:
    return RuntimeManifest(
        runtime_id="fixture-runtime",
        runtime_version="1.0",
        adapter_id="fixture-adapter",
        adapter_version="1.0",
        source_revision=REVISION,
        assurance="declared",
        capabilities=RuntimeCapabilities(
            streaming=True,
            tool_events=True,
            structured_output=True,
            timeout=True,
            cancellation=True,
            workspace_isolation=True,
            cost_reporting=True,
            workspace_write=True,
        ),
        declared_tools=("read-file",),
        egress_transports=("internal-proxy",),
        workspace_modes=("isolated-worktree", "read-only"),
        cost_model="fixture-units",
        provenance=ContractProvenance(
            origin="tests.runtime-manifest",
            source_revision=REVISION,
            created_at=NOW.isoformat(),
            input_digests=(),
        ),
    )


def _persisted_bundle(tmp_path: Path) -> Path:
    receipt = assemble_recorded_conformance(
        _manifest(),
        observations={
            name: RecordedObservation(
                passed=True,
                detail="recorded offline fixture",
                transcript={"check": name},
            )
            for name in RUNTIME_CONFORMANCE_CHECKS
        },
        artifact_root=tmp_path / "cas",
        receipt_id="runtime-fixture-001",
        started_at=NOW.isoformat(),
        finished_at=(NOW + timedelta(seconds=1)).isoformat(),
    )
    receipt_dir = tmp_path / "receipts"
    persist_conformance_receipt(receipt, receipt_dir)
    return receipt_dir


def _module_cli_payload(monkeypatch, capsys, extra: list[str]) -> dict:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gates",
            "report",
            "--gate",
            "0",
            "--repo-root",
            str(ROOT),
            "--source-revision",
            REVISION,
            *extra,
        ],
    )
    assert gates_main() == 0
    return json.loads(capsys.readouterr().out)


def test_module_cli_flag_binds_bundle(tmp_path, monkeypatch, capsys) -> None:
    receipt_dir = _persisted_bundle(tmp_path)
    payload = _module_cli_payload(
        monkeypatch, capsys, ["--conformance-receipts", str(receipt_dir)]
    )
    assert payload["runtime_conformance_failures"] == []
    assert BOUND_INFO in payload["diagnostics"]
    assert "blocker:runtime_conformance_receipts:unbound" not in payload["diagnostics"]


def test_module_cli_without_flag_keeps_unbound_blocker(monkeypatch, capsys) -> None:
    payload = _module_cli_payload(monkeypatch, capsys, [])
    assert UNBOUND_ROW in payload["runtime_conformance_failures"]
    assert "blocker:runtime_conformance_receipts:unbound" in payload["diagnostics"]


def test_module_cli_missing_directory_fails_closed_with_named_error(
    tmp_path, monkeypatch, capsys
) -> None:
    payload = _module_cli_payload(
        monkeypatch,
        capsys,
        ["--conformance-receipts", str(tmp_path / "does-not-exist")],
    )
    assert "receipt-bundle:absent" in payload["runtime_conformance_failures"]
    assert UNBOUND_ROW in payload["runtime_conformance_failures"]
    assert payload["closed"] is False


def test_v3_cli_flag_binds_bundle(tmp_path, capsys) -> None:
    receipt_dir = _persisted_bundle(tmp_path)
    result = v3_main(
        [
            str(ROOT),
            "--source-revision",
            REVISION,
            "--conformance-receipts",
            str(receipt_dir),
        ]
    )
    assert result == 1  # other Gate-0 blockers remain; conformance itself is bound
    payload = json.loads(capsys.readouterr().out)
    assert payload["runtime_conformance_failures"] == []
    assert BOUND_INFO in payload["diagnostics"]
    assert "blocker:runtime_conformance_receipts:unbound" not in payload["diagnostics"]


def test_v3_cli_without_flag_keeps_unbound_blocker(capsys) -> None:
    result = v3_main([str(ROOT), "--source-revision", REVISION])
    assert result == 1
    payload = json.loads(capsys.readouterr().out)
    assert UNBOUND_ROW in payload["runtime_conformance_failures"]


def test_v3_cli_missing_directory_fails_closed_with_named_error(
    tmp_path, capsys
) -> None:
    result = v3_main(
        [
            str(ROOT),
            "--source-revision",
            REVISION,
            "--conformance-receipts",
            str(tmp_path / "does-not-exist"),
        ]
    )
    assert result == 1
    payload = json.loads(capsys.readouterr().out)
    assert "receipt-bundle:absent" in payload["runtime_conformance_failures"]
    assert UNBOUND_ROW in payload["runtime_conformance_failures"]
    assert payload["closed"] is False
