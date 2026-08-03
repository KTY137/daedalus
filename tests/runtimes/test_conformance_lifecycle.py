from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from daedalus.runtimes import RuntimeProbeEvent, RuntimeProbeRequest
from tests.runtimes.test_conformance import run
from tests.runtimes.test_conformance_adversarial import (
    ScriptedAdapter,
    ScriptedSession,
    execute,
    valid_events,
)


def test_unknown_event_kind_fails_the_exact_normal_lifecycle(tmp_path: Path) -> None:
    base = valid_events()
    transcript = (
        base[0],
        RuntimeProbeEvent("debug.raw", 1, {"message": "not provider-neutral"}),
        *(
            RuntimeProbeEvent(event.kind, event.sequence + 1, dict(event.payload))
            for event in base[1:]
        ),
    )

    receipt, _ = execute(tmp_path, ScriptedAdapter(transcript))

    checks = {check.name: check for check in receipt.checks}
    assert receipt.status == "failed"
    assert not checks["start"].passed


@dataclass
class NormalLiveSession(ScriptedSession):
    def wait(self, timeout_s: float) -> int:
        # A broken adapter reports successful wait while leaving the runtime live.
        return 0


class NormalLiveAdapter(ScriptedAdapter):
    def start(self, request: RuntimeProbeRequest) -> ScriptedSession:
        if request.mode == "normal":
            (request.workspace / "fixture-output.txt").write_text(
                "fixture\n", encoding="utf-8"
            )
            session = NormalLiveSession(valid_events())
            self.sessions.append(session)
            return session
        return super().start(request)


def test_successful_wait_cannot_hide_a_live_normal_session(tmp_path: Path) -> None:
    adapter = NormalLiveAdapter(valid_events())

    receipt, _ = execute(tmp_path, adapter)

    checks = {check.name: check for check in receipt.checks}
    assert receipt.status == "failed"
    assert not checks["start"].passed
    assert all(not session.running for session in adapter.sessions)


@dataclass
class ParseObserverFailureSession(ScriptedSession):
    @property
    def parse_errors(self) -> tuple[str, ...]:
        # The transcript is valid, but the adapter's final observer boundary fails.
        # No already-captured normal data may survive as passing evidence.
        raise RuntimeError("observer failed")


class ParseObserverFailureAdapter(ScriptedAdapter):
    def start(self, request: RuntimeProbeRequest) -> ScriptedSession:
        if request.mode == "normal":
            (request.workspace / "fixture-output.txt").write_text(
                "fixture\n", encoding="utf-8"
            )
            session = ParseObserverFailureSession(valid_events())
            self.sessions.append(session)
            return session
        return super().start(request)


def test_late_parse_observer_failure_cannot_retain_a_passing_transcript(
    tmp_path: Path,
) -> None:
    receipt, evidence = execute(
        tmp_path,
        ParseObserverFailureAdapter(valid_events()),
    )

    checks = {check.name: check for check in receipt.checks}
    assert receipt.status == "failed"
    for name in (
        "start",
        "stream",
        "tool-events",
        "structured-output",
        "cost",
        "workspace-isolation",
    ):
        assert not checks[name].passed

    start_payload = json.loads(evidence.objects[checks["start"].evidence_sha256])
    assert start_payload["observations"]["observation_complete"] is False
    assert start_payload["observations"]["exception"] == "RuntimeError"
    assert start_payload["observations"]["event_shape"] == []


def test_frozen_structured_output_is_retained_as_plain_canonical_json(
    tmp_path: Path,
) -> None:
    receipt, evidence = run(tmp_path)
    check = {item.name: item for item in receipt.checks}["structured-output"]

    payload = json.loads(evidence.objects[check.evidence_sha256])

    assert payload["observations"]["value"] == {
        "ok": True,
        "value": "fixture",
    }
