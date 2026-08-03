from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Mapping

import pytest

from daedalus.runtimes import (
    RuntimeBindingError,
    RuntimeCapabilities,
    RuntimeConformanceReceipt,
    RuntimeEvidenceError,
    RuntimeManifest,
    RuntimeProbeEvent,
    RuntimeProbeRequest,
    RuntimeProbeTimeout,
    run_runtime_conformance,
)
from daedalus.schemas import ContractProvenance, RUNTIME_CONFORMANCE_CHECKS


REVISION = "a" * 40
NOW = datetime(2026, 8, 3, 6, 0, tzinfo=timezone.utc)
WORKER = Path(__file__).with_name("runtime_fixture_worker.py").resolve()


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


class SubprocessFixtureSession:
    def __init__(self, process: subprocess.Popen[str]) -> None:
        self.process = process
        self._events: list[RuntimeProbeEvent] = []
        self._parse_errors: list[str] = []
        self._lock = threading.Lock()
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self) -> None:
        assert self.process.stdout is not None
        for line_number, raw in enumerate(self.process.stdout, start=1):
            try:
                payload = json.loads(raw)
                if not isinstance(payload, Mapping):
                    raise ValueError("event must be an object")
                event = RuntimeProbeEvent(
                    kind=payload["kind"],
                    sequence=payload["sequence"],
                    payload=payload.get("payload", {}),
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                with self._lock:
                    self._parse_errors.append(
                        f"line {line_number}: {type(exc).__name__}"
                    )
                continue
            with self._lock:
                self._events.append(event)

    @property
    def running(self) -> bool:
        return self.process.poll() is None

    @property
    def exit_code(self) -> int | None:
        return self.process.poll()

    @property
    def parse_errors(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._parse_errors)

    def events(self) -> tuple[RuntimeProbeEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def _join(self) -> None:
        self._reader.join(timeout=1.0)
        assert not self._reader.is_alive()

    def wait(self, timeout_s: float) -> int:
        try:
            result = self.process.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired as exc:
            self.process.kill()
            self.process.wait(timeout=2.0)
            self._join()
            raise RuntimeProbeTimeout("fixture exceeded timeout") from exc
        self._join()
        return result

    def cancel(self, grace_s: float = 1.0) -> int:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=grace_s)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2.0)
        self._join()
        assert self.process.returncode is not None
        return self.process.returncode


class PythonSubprocessFixtureAdapter:
    runtime_id = "python_fixture"

    def __init__(self, *, escape_workspace: bool = False) -> None:
        self.escape_workspace = escape_workspace
        self.sessions: list[SubprocessFixtureSession] = []

    def start(self, request: RuntimeProbeRequest) -> SubprocessFixtureSession:
        if request.runtime_id != self.runtime_id:
            raise RuntimeBindingError("request runtime does not match fixture")
        argv = [
            sys.executable,
            str(WORKER),
            "--mode",
            request.mode,
            "--workspace",
            str(request.workspace),
            "--outside-canary",
            str(request.outside_canary),
        ]
        if self.escape_workspace:
            argv.append("--escape")
        allowed = {
            "PATH",
            "PATHEXT",
            "SYSTEMROOT",
            "WINDIR",
            "TMP",
            "TEMP",
            "TMPDIR",
        }
        environment = {key: value for key, value in os.environ.items() if key in allowed}
        environment["PYTHONIOENCODING"] = "utf-8"
        environment["PYTHONUNBUFFERED"] = "1"
        process = subprocess.Popen(
            argv,
            cwd=request.workspace,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="strict",
            close_fds=True,
        )
        session = SubprocessFixtureSession(process)
        self.sessions.append(session)
        return session


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
    adapter: PythonSubprocessFixtureAdapter | None = None,
    receipt_id: str = "conformance-1",
    store: MemoryEvidenceStore | None = None,
):
    tmp_path.mkdir(parents=True, exist_ok=True)
    evidence = store or MemoryEvidenceStore()
    selected_adapter = adapter or PythonSubprocessFixtureAdapter()
    receipt = run_runtime_conformance(
        runtime_manifest or manifest(),
        selected_adapter,
        evidence_writer=evidence.put,
        receipt_id=receipt_id,
        expected_source_revision=REVISION,
        workspace_parent=tmp_path,
        clock=FixedClock(),
        normal_timeout_s=5.0,
        timeout_probe_s=0.1,
        cancellation_grace_s=1.0,
    )
    assert all(not session.running for session in selected_adapter.sessions)
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
    adapter = PythonSubprocessFixtureAdapter()
    with pytest.raises(RuntimeBindingError, match="stale"):
        run_runtime_conformance(
            manifest(),
            adapter,
            evidence_writer=MemoryEvidenceStore().put,
            receipt_id="conformance-stale",
            expected_source_revision="b" * 40,
            workspace_parent=tmp_path,
            clock=FixedClock(),
        )
    assert not adapter.sessions

    wrong = dataclasses.replace(manifest(), runtime_id="other-runtime")
    with pytest.raises(RuntimeBindingError, match="runtime_id"):
        run_runtime_conformance(
            wrong,
            adapter,
            evidence_writer=MemoryEvidenceStore().put,
            receipt_id="conformance-wrong-runtime",
            expected_source_revision=REVISION,
            workspace_parent=tmp_path,
            clock=FixedClock(),
        )
    assert not adapter.sessions


def test_observed_feature_without_manifest_capability_fails_closed(tmp_path: Path) -> None:
    caps = dataclasses.replace(manifest().capabilities, streaming=False)
    receipt, _ = run(tmp_path, runtime_manifest=manifest(capabilities=caps))

    assert receipt.status == "failed"
    checks = {check.name: check for check in receipt.checks}
    assert not checks["stream"].passed
    assert all(check.passed for name, check in checks.items() if name != "stream")


def test_workspace_escape_is_retained_as_failed_evidence(tmp_path: Path) -> None:
    receipt, evidence = run(
        tmp_path,
        adapter=PythonSubprocessFixtureAdapter(escape_workspace=True),
    )

    checks = {check.name: check for check in receipt.checks}
    assert receipt.status == "failed"
    assert not checks["workspace-isolation"].passed
    payload = evidence.objects[checks["workspace-isolation"].evidence_sha256]
    assert b'"outside_canary_unchanged":false' in payload


def test_evidence_writer_cannot_relabel_or_lose_evidence(tmp_path: Path) -> None:
    def wrong_address(_payload: bytes) -> str:
        return "artifact-locator:sha256:" + "f" * 64

    adapter = PythonSubprocessFixtureAdapter()
    with pytest.raises(RuntimeEvidenceError, match="wrong content address"):
        run_runtime_conformance(
            manifest(),
            adapter,
            evidence_writer=wrong_address,
            receipt_id="conformance-bad-store",
            expected_source_revision=REVISION,
            workspace_parent=tmp_path,
            clock=FixedClock(),
            normal_timeout_s=5.0,
        )
    assert all(not session.running for session in adapter.sessions)


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
