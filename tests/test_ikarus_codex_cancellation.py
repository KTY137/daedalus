"""Regression tests for the Codex CLI leg of canonical Ikarus Stop."""
from __future__ import annotations

import subprocess as stdlib_subprocess
import sys
import threading
import types
from unittest import mock

import pytest

from daedalus.orchestration.ikarus import shell as ikarus_os
from daedalus.orchestration import runtime_registry
from daedalus.orchestration.ikarus.cancellation import CancellationSignal
from daedalus.providers._openai_compat import ProviderCancelled


def test_precancelled_codex_refuses_before_resolution_admission_or_spawn() -> None:
    signal = CancellationSignal("codex-pre-cancel-0001")
    assert signal.cancel() is True
    with mock.patch.object(runtime_registry, "resolve_runtime_command") as which, \
         mock.patch.object(ikarus_os, "_provider_start") as provider_start, \
         mock.patch.object(ikarus_os.subprocess, "Popen") as popen:
        with pytest.raises(ProviderCancelled, match="before Ikarus spawned Codex CLI"):
            list(ikarus_os._codex_stream("hello", cancellation=signal))
    which.assert_not_called()
    provider_start.assert_not_called()
    popen.assert_not_called()


def test_codex_rejects_duck_typed_cancellation_before_resolution() -> None:
    class FakeSignal:
        request_id = "codex-fake-signal"
        def cancelled(self) -> bool:
            return False
    with mock.patch.object(runtime_registry, "resolve_runtime_command") as which, \
         mock.patch.object(ikarus_os, "_provider_start") as provider_start:
        with pytest.raises(TypeError, match="exact CancellationSignal"):
            list(ikarus_os._codex_stream("hello", cancellation=FakeSignal()))
    which.assert_not_called()
    provider_start.assert_not_called()


def _blocking_codex_proxy(monkeypatch, *, sleep_s: float = 60.0):
    spawned = threading.Event()
    holder: dict[str, object] = {}
    def spawn(_args, **kwargs):
        holder["argv"] = list(_args)
        child = stdlib_subprocess.Popen(
            [sys.executable, "-u", "-c", f"import time; time.sleep({sleep_s})"],
            **kwargs,
        )
        holder["process"] = child
        spawned.set()
        return child
    proxy = types.SimpleNamespace(
        Popen=spawn,
        DEVNULL=stdlib_subprocess.DEVNULL,
        TimeoutExpired=stdlib_subprocess.TimeoutExpired,
        SubprocessError=stdlib_subprocess.SubprocessError,
    )
    monkeypatch.setattr(ikarus_os, "subprocess", proxy)
    monkeypatch.setattr(runtime_registry, "resolve_runtime_command", lambda _name: "/safe/codex")
    monkeypatch.setattr(ikarus_os, "_provider_start", lambda *args, **kwargs: None)
    return spawned, holder


def test_cancellation_terminates_real_codex_child_while_wait_is_blocked(monkeypatch) -> None:
    signal = CancellationSignal("codex-live-cancel-0001")
    spawned, holder = _blocking_codex_proxy(monkeypatch)
    outcome: dict[str, BaseException] = {}
    def consume() -> None:
        try:
            list(ikarus_os._codex_stream("hello", timeout_s=30.0, cancellation=signal))
        except BaseException as exc:
            outcome["exception"] = exc
    worker = threading.Thread(target=consume, name="test-codex-stream-consumer")
    worker.start()
    assert spawned.wait(3.0), "Codex child was never spawned"
    assert signal.cancel() is True
    worker.join(5.0)
    child = holder["process"]
    assert isinstance(child, stdlib_subprocess.Popen)
    try:
        assert not worker.is_alive(), "cancellation did not unblock Codex"
        assert isinstance(outcome.get("exception"), ProviderCancelled)
        assert child.poll() is not None, "request returned while Codex child was live"
        argv = holder["argv"]
        assert "--sandbox" in argv and argv[argv.index("--sandbox") + 1] == "read-only"
        assert "--output-last-message" in argv
        assert "--skip-git-repo-check" in argv
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5.0)


def test_codex_timeout_kills_owned_child_instead_of_leaking(monkeypatch) -> None:
    spawned, holder = _blocking_codex_proxy(monkeypatch)
    result = list(ikarus_os._codex_stream("hello", timeout_s=0.08,
        cancellation=CancellationSignal("codex-timeout-test")))
    assert spawned.is_set()
    child = holder["process"]
    assert isinstance(child, stdlib_subprocess.Popen)
    try:
        assert result == []
        assert child.poll() is not None
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5.0)
