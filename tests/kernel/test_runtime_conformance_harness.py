from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from daedalus.kernel.runtime_conformance import (
    RecordedObservation,
    RuntimeConformanceError,
    assemble_recorded_conformance,
    verify_current_conformance,
)
from daedalus.schemas import (
    RUNTIME_CONFORMANCE_CHECKS,
    ContractProvenance,
    RuntimeCapabilities,
    RuntimeManifest,
)

REVISION = "a" * 40
NOW = datetime(2026, 8, 2, 0, 0, tzinfo=timezone.utc)


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


def _observations(passed: bool = True):
    return {
        name: RecordedObservation(
            passed=passed,
            detail="recorded offline fixture",
            transcript={"check": name, "result": "ok" if passed else "failed"},
        )
        for name in RUNTIME_CONFORMANCE_CHECKS
    }


def test_recorded_fixture_is_exact_content_addressed_and_current(tmp_path: Path) -> None:
    manifest = _manifest()
    receipt = assemble_recorded_conformance(
        manifest,
        observations=_observations(),
        artifact_root=tmp_path / "cas",
        receipt_id="runtime-fixture-001",
        started_at=NOW.isoformat(),
        finished_at=(NOW + timedelta(seconds=1)).isoformat(),
    )
    assert receipt.status == "passed"
    assert len(list((tmp_path / "cas").glob("*.json"))) == len(RUNTIME_CONFORMANCE_CHECKS)
    verify_current_conformance(
        receipt,
        manifest,
        now=NOW + timedelta(days=1),
    )


def test_partial_failed_and_stale_runtime_evidence_refuses(tmp_path: Path) -> None:
    manifest = _manifest()
    partial = _observations()
    partial.pop("cost")
    with pytest.raises(RuntimeConformanceError, match="exactly cover"):
        assemble_recorded_conformance(
            manifest,
            observations=partial,
            artifact_root=tmp_path / "partial",
            receipt_id="partial",
            started_at=NOW.isoformat(),
            finished_at=NOW.isoformat(),
        )
    failed = assemble_recorded_conformance(
        manifest,
        observations=_observations(False),
        artifact_root=tmp_path / "failed",
        receipt_id="failed",
        started_at=NOW.isoformat(),
        finished_at=NOW.isoformat(),
    )
    with pytest.raises(RuntimeConformanceError, match="did not pass"):
        verify_current_conformance(failed, manifest, now=NOW)
    passed = assemble_recorded_conformance(
        manifest,
        observations=_observations(),
        artifact_root=tmp_path / "passed",
        receipt_id="passed",
        started_at=NOW.isoformat(),
        finished_at=NOW.isoformat(),
    )
    with pytest.raises(RuntimeConformanceError, match="stale"):
        verify_current_conformance(passed, manifest, now=NOW + timedelta(days=8))
