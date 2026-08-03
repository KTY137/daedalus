from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

import pytest

from daedalus.runtimes import (
    PythonFixtureRuntimeAdapter,
    RuntimeBindingError,
    RuntimeCapabilities,
    RuntimeConformanceReceipt,
    RuntimeEvidenceError,
    RuntimeManifest,
    run_runtime_conformance,
)
from daedalus.schemas import ContractProvenance, RUNTIME_CONFORMANCE_CHECKS


REVISION = "a" * 40
NOW = datetime(2026, 8, 3, 6, 0, tzinfo=timezone.utc)


class MemoryEvidenceStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, payload: bytes) -> str:
        digest = sha256(payload).hexdigest()
        self.objects[digest] = bytes(payload)
        return "artifact-locator:sha256:" + digest


class FixedClock:
    def __init__(self, start: datetime = NOW) -> None:
        self.current = start

    def __call__(self) -> datetime:
        value = self.current
        self.current += timedelta(seconds=1)
        return value


def manifest(*, capabilities: RuntimeCapabilities | None = None) -> RuntimeManifest:
    caps = capabilities or RuntimeCapabilities(
        streaming=True,
        tool_events=True,
        structured_output=True,
        timeout=True,
        cancellation=True,
        workspace_isolation=True,
        cost_reporting=True,
        workspace_write=True,
    )
    return RuntimeManifest(
        runtime_id="python_fixture",
        runtime_version="3",
        adapter_id="python-subprocess-fixture",
        adapter_version="1",
        source_revision=REVISION,
        assurance="declared",
        capabilities=caps,
        declared_tools=("fixture.write",),
        egress_transports=(),
        workspace_modes=("isolated-worktree", "read-only"),
        cost_model="deterministic-zero-cost-fixture",
        provenance=ContractProvenance(
            origin="tests.runtime-manifest",
            source_revision=REVISION,
            created_at=NOW.isoformat(),
            trace_id="runtime-conformance",
        ),
    )


def run(
    tmp_path: Path,
    *,
    runtime_manifest: RuntimeManifest | None = None,
    adapter: PythonFixtureRuntimeAdapter | None = None,
    receipt_id: str = "conformance-1",
    store: MemoryEvidenceStore | None = None,
):
    evidence = store or MemoryEvidenceStore()
    receipt = run_runtime_conformance(
        runtime_manifest or manifest(),
        adapter or PythonFixtureRuntimeAdapter(),
        evidence_writer=evidence.put,
        receipt_id=receipt_id,
        expected_source_revision=REVISION,
        workspace_parent=tmp_path,
        clock=FixedClock(),
        normal_timeout_s=5.0,
        timeout_probe_s=0.1,
        cancellation_grace_s=1.0,
    )
    return receipt, evidence


def test_real_subprocess_fixture_passes_exact_vendor_neutral_matrix(tmp_path: Path) -> None:
    receipt, evidence = run(tmp_path)

    assert receipt.status == "passed"
    assert {check.name for check in receipt.checks} == RUNTIME_CONFORMANCE_CHECKS
    assert all(check.passed for check in receipt.checks)
    assert receipt.usage.input_tokens == 3
    assert receipt.usage.output_tokens == 2
    assert receipt.usage.cost_microusd == 0
    assert len(evidence.objects) == len(RUNTIME_CONFORMANCE_CHECKS)
    assert all(check.evidence_sha256 in evidence.objects for check in receipt.checks)
    assert RuntimeConformanceReceipt.from_dict(receipt.to_dict()) == receipt


def test_evidence_is_deterministic_across_fresh_subprocess_runs(tmp_path: Path) -> None:
    first, first_store = run(tmp_path / "first", receipt_id="conformance-1")
    second, second_store = run(tmp_path / "second", receipt_id="conformance-2")

    assert tuple(check.evidence_sha256 for check in first.checks) == tuple(
        check.evidence_sha256 for check in second.checks
    )
    assert first_store.objects == second_store.objects


def test_stale_revision_and_wrong_runtime_refuse_before_execution(tmp_path: Path) -> None:
    with pytest.raises(RuntimeBindingError, match="stale"):
        run_runtime_conformance(
            manifest(),
            PythonFixtureRuntimeAdapter(),
            evidence_writer=MemoryEvidenceStore().put,
            receipt_id="conformance-stale",
            expected_source_revision="b" * 40,
            workspace_parent=tmp_path,
            clock=FixedClock(),
        )

    wrong = dataclasses.replace(manifest(), runtime_id="other-runtime")
    with pytest.raises(RuntimeBindingError, match="runtime_id"):
        run_runtime_conformance(
            wrong,
            PythonFixtureRuntimeAdapter(),
            evidence_writer=MemoryEvidenceStore().put,
            receipt_id="conformance-wrong-runtime",
            expected_source_revision=REVISION,
            workspace_parent=tmp_path,
            clock=FixedClock(),
        )


def test_observed_feature_without_manifest_capability_fails_closed(tmp_path: Path) -> None:
    caps = dataclasses.replace(manifest().capabilities, streaming=False)
    receipt, _ = run(tmp_path, runtime_manifest=manifest(capabilities=caps))

    assert receipt.status == "failed"
    checks = {check.name: check for check in receipt.checks}
    assert not checks["stream"].passed
    assert all(
        check.passed for name, check in checks.items() if name != "stream"
    )


def test_workspace_escape_is_retained_as_failed_evidence(tmp_path: Path) -> None:
    receipt, evidence = run(
        tmp_path,
        adapter=PythonFixtureRuntimeAdapter(escape_workspace=True),
    )

    checks = {check.name: check for check in receipt.checks}
    assert receipt.status == "failed"
    assert not checks["workspace-isolation"].passed
    payload = evidence.objects[checks["workspace-isolation"].evidence_sha256]
    assert b'"outside_canary_unchanged":false' in payload


def test_evidence_writer_cannot_relabel_or_lose_evidence(tmp_path: Path) -> None:
    def wrong_address(_payload: bytes) -> str:
        return "artifact-locator:sha256:" + "f" * 64

    with pytest.raises(RuntimeEvidenceError, match="wrong content address"):
        run_runtime_conformance(
            manifest(),
            PythonFixtureRuntimeAdapter(),
            evidence_writer=wrong_address,
            receipt_id="conformance-bad-store",
            expected_source_revision=REVISION,
            workspace_parent=tmp_path,
            clock=FixedClock(),
            normal_timeout_s=5.0,
        )


def test_manifest_capabilities_and_workspace_mode_remain_consistent() -> None:
    with pytest.raises(ValueError, match="workspace_isolation"):
        dataclasses.replace(
            manifest(),
            capabilities=dataclasses.replace(
                manifest().capabilities, workspace_isolation=False
            ),
        )
    with pytest.raises(ValueError, match="declared tools"):
        dataclasses.replace(
            manifest(),
            capabilities=dataclasses.replace(
                manifest().capabilities, tool_events=False
            ),
        )
