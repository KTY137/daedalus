from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest

from daedalus.runtimes import (
    RuntimeConformanceError,
    RuntimeProbeEvent,
    RuntimeProbeRequest,
    RuntimeProbeTimeout,
    run_runtime_conformance,
)
from tests.runtimes.test_conformance import (
    FixedClock,
    MemoryEvidenceStore,
    REVISION,
    manifest,
)


def valid_events() -> tuple[RuntimeProbeEvent, ...]:
    return (
        RuntimeProbeEvent("started", 0, {"pid": 1}),
        RuntimeProbeEvent("stream.delta", 1, {"text": "fixture"}),
        RuntimeProbeEvent(
            "tool.started", 2, {"tool": "fixture.write", "call_id": "call-1"}
        ),
        RuntimeProbeEvent(
            "tool.finished",
            3,
            {"tool": "fixture.write", "call_id": "call-1", "status": "ok"},
        ),
        RuntimeProbeEvent(
            "structured-output", 4, {"value": {"ok": True, "value": "fixture"}}
        ),
        RuntimeProbeEvent(
            "usage",
            5,
            {
                "input_tokens": 3,
                "output_tokens": 2,
                "cost_microusd": 0,
                "wall_time_ms": 1,
            },
        ),
        RuntimeProbeEvent("finished", 6, {"status": "passed"}),
    )


@dataclass
class ScriptedSession:
    transcript: tuple[RuntimeProbeEvent, ...]
    hang: bool = False
    leave_running_on_timeout: bool = False
    refuse_cancel: bool = False
    _running: bool = True

    @property
    def running(self) -> bool:
        return self._running

    @property
    def exit_code(self) -> int | None:
        return None if self._running else (130 if self.hang else 0)

    @property
    def parse_errors(self) -> tuple[str, ...]:
        return ()

    def events(self) -> tuple[RuntimeProbeEvent, ...]:
        return self.transcript

    def wait(self, timeout_s: float) -> int:
        if self.hang:
            if not self.leave_running_on_timeout:
                self._running = False
            raise RuntimeProbeTimeout("scripted timeout")
        self._running = False
        return 0

    def cancel(self, grace_s: float = 1.0) -> int:
        if not self.refuse_cancel:
            self._running = False
        return 130


class ScriptedAdapter:
    runtime_id = "python_fixture"

    def __init__(
        self,
        transcript: tuple[RuntimeProbeEvent, ...],
        *,
        leave_running_on_timeout: bool = False,
        refuse_cancel: bool = False,
        mutate_canary_on_cancel_phase: bool = False,
    ) -> None:
        self.transcript = transcript
        self.leave_running_on_timeout = leave_running_on_timeout
        self.refuse_cancel = refuse_cancel
        self.mutate_canary_on_cancel_phase = mutate_canary_on_cancel_phase
        self.sessions: list[ScriptedSession] = []
        self.hang_starts = 0

    def start(self, request: RuntimeProbeRequest) -> ScriptedSession:
        if request.mode == "normal":
            (request.workspace / "fixture-output.txt").write_text(
                "fixture\n", encoding="utf-8"
            )
            session = ScriptedSession(self.transcript)
        else:
            self.hang_starts += 1
            if self.mutate_canary_on_cancel_phase and self.hang_starts == 2:
                request.outside_canary.write_text("modified\n", encoding="utf-8")
            session = ScriptedSession(
                (RuntimeProbeEvent("started", 0, {"pid": 1}),),
                hang=True,
                leave_running_on_timeout=(
                    self.leave_running_on_timeout and self.hang_starts == 1
                ),
                refuse_cancel=self.refuse_cancel,
            )
        self.sessions.append(session)
        return session


def execute(tmp_path: Path, adapter: ScriptedAdapter):
    store = MemoryEvidenceStore()
    receipt = run_runtime_conformance(
        manifest(),
        adapter,
        evidence_writer=store.put,
        receipt_id="adversarial-receipt",
        expected_source_revision=REVISION,
        workspace_parent=tmp_path,
        clock=FixedClock(),
    )
    return receipt, store


def test_gapped_sequence_and_duplicate_lifecycle_fail_start(tmp_path: Path) -> None:
    events = list(valid_events())
    events[1] = RuntimeProbeEvent("stream.delta", 2, {"text": "fixture"})
    receipt, _ = execute(tmp_path, ScriptedAdapter(tuple(events)))
    assert receipt.status == "failed"
    assert not {check.name: check for check in receipt.checks}["start"].passed

    duplicate = (
        valid_events()[0],
        RuntimeProbeEvent("started", 1, {"pid": 2}),
        *(
            RuntimeProbeEvent(event.kind, event.sequence + 1, dict(event.payload))
            for event in valid_events()[1:]
        ),
    )
    receipt, _ = execute(tmp_path, ScriptedAdapter(tuple(duplicate)))
    assert receipt.status == "failed"
    assert not {check.name: check for check in receipt.checks}["start"].passed


def test_undeclared_tool_fails_even_when_call_ids_pair(tmp_path: Path) -> None:
    events = list(valid_events())
    events[2] = RuntimeProbeEvent(
        "tool.started", 2, {"tool": "undeclared.tool", "call_id": "call-1"}
    )
    events[3] = RuntimeProbeEvent(
        "tool.finished",
        3,
        {"tool": "undeclared.tool", "call_id": "call-1", "status": "ok"},
    )
    receipt, _ = execute(tmp_path, ScriptedAdapter(tuple(events)))
    checks = {check.name: check for check in receipt.checks}
    assert receipt.status == "failed"
    assert not checks["tool-events"].passed


def test_timeout_lie_is_failed_and_session_is_still_cleaned_up(tmp_path: Path) -> None:
    adapter = ScriptedAdapter(valid_events(), leave_running_on_timeout=True)
    receipt, _ = execute(tmp_path, adapter)
    checks = {check.name: check for check in receipt.checks}
    assert receipt.status == "failed"
    assert not checks["timeout"].passed
    assert all(not session.running for session in adapter.sessions)


def test_workspace_canary_is_checked_after_cancellation_phase(tmp_path: Path) -> None:
    adapter = ScriptedAdapter(
        valid_events(), mutate_canary_on_cancel_phase=True
    )
    receipt, evidence = execute(tmp_path, adapter)
    checks = {check.name: check for check in receipt.checks}
    assert receipt.status == "failed"
    assert not checks["workspace-isolation"].passed
    payload = evidence.objects[checks["workspace-isolation"].evidence_sha256]
    assert b'"outside_canary_unchanged":false' in payload


def test_invalid_inputs_refuse_before_any_adapter_start(tmp_path: Path) -> None:
    adapter = ScriptedAdapter(valid_events())
    with pytest.raises(ValueError, match="receipt_id"):
        run_runtime_conformance(
            manifest(),
            adapter,
            evidence_writer=MemoryEvidenceStore().put,
            receipt_id="invalid receipt id",
            expected_source_revision=REVISION,
            workspace_parent=tmp_path,
            clock=FixedClock(),
        )
    assert not adapter.sessions

    with pytest.raises(ValueError, match="timezone-aware"):
        run_runtime_conformance(
            manifest(),
            adapter,
            evidence_writer=MemoryEvidenceStore().put,
            receipt_id="valid-receipt",
            expected_source_revision=REVISION,
            workspace_parent=tmp_path,
            clock=lambda: datetime(2026, 8, 3),
        )
    assert not adapter.sessions

    with pytest.raises(ValueError, match="finite positive"):
        run_runtime_conformance(
            manifest(),
            adapter,
            evidence_writer=MemoryEvidenceStore().put,
            receipt_id="valid-receipt",
            expected_source_revision=REVISION,
            workspace_parent=tmp_path,
            clock=FixedClock(),
            timeout_probe_s=math.nan,
        )
    assert not adapter.sessions


def test_adapter_that_refuses_cancellation_causes_hard_cleanup_failure(tmp_path: Path) -> None:
    adapter = ScriptedAdapter(valid_events(), refuse_cancel=True)
    with pytest.raises(RuntimeConformanceError, match="remained live"):
        execute(tmp_path, adapter)
