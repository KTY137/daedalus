"""Regression tests for the Claude CLI leg of the canonical Ikarus Stop path.

The HTTP/request-id cancellation seam already reaches ``CancellationSignal``.
These tests pin the missing provider invariant: when the Claude stream is
blocked waiting for stdout, cancelling that exact signal must terminate the
exact child process rather than merely stop the browser from reading it.
"""
from __future__ import annotations

import subprocess as stdlib_subprocess
import sys
import threading
import types
from unittest import mock

import pytest

from daedalus import ikarus_os
from daedalus.ikarus_cancellation import CancellationSignal
from daedalus.providers._openai_compat import ProviderCancelled


def test_precancelled_claude_stream_refuses_before_provider_start_or_spawn() -> None:
    signal = CancellationSignal("claude-pre-cancel-0001")
    assert signal.cancel() is True

    with mock.patch.object(ikarus_os, "_claude_command_for_chat") as command, \
         mock.patch.object(ikarus_os, "_provider_start") as provider_start, \
         mock.patch.object(ikarus_os.subprocess, "Popen") as popen:
        with pytest.raises(ProviderCancelled, match="before Ikarus spawned Claude Code"):
            list(ikarus_os._claude_stream("hello", cancellation=signal))

    command.assert_not_called()
    provider_start.assert_not_called()
    popen.assert_not_called()


def test_claude_stream_rejects_duck_typed_cancellation_before_admission() -> None:
    class FakeSignal:
        request_id = "claude-fake-signal"

        def cancelled(self) -> bool:
            return False

    with mock.patch.object(ikarus_os, "_claude_command_for_chat") as command, \
         mock.patch.object(ikarus_os, "_provider_start") as provider_start:
        with pytest.raises(TypeError, match="exact CancellationSignal"):
            list(ikarus_os._claude_stream("hello", cancellation=FakeSignal()))

    command.assert_not_called()
    provider_start.assert_not_called()


def test_cancellation_terminates_real_claude_child_while_stdout_is_blocked(monkeypatch) -> None:
    """A real child proves Stop interrupts the blocking stdout iterator.

    ``ikarus_os.subprocess`` is rebound to a tiny proxy instead of monkeypatching
    the stdlib module itself.  That matters because ``terminate_owned_subprocess``
    deliberately requires an *exact* stdlib ``subprocess.Popen`` handle at its
    trust boundary; the spawned object below therefore remains real evidence.
    """
    signal = CancellationSignal("claude-live-cancel-0001")
    spawned = threading.Event()
    holder: dict[str, stdlib_subprocess.Popen[str]] = {}

    def spawn_blocking_child(_args, **kwargs):
        child = stdlib_subprocess.Popen(
            [
                sys.executable,
                "-u",
                "-c",
                "import sys,time; sys.stdin.read(); time.sleep(60)",
            ],
            **kwargs,
        )
        holder["process"] = child
        spawned.set()
        return child

    subprocess_proxy = types.SimpleNamespace(
        Popen=spawn_blocking_child,
        PIPE=stdlib_subprocess.PIPE,
        DEVNULL=stdlib_subprocess.DEVNULL,
        SubprocessError=stdlib_subprocess.SubprocessError,
    )
    monkeypatch.setattr(ikarus_os, "subprocess", subprocess_proxy)
    monkeypatch.setattr(ikarus_os, "_claude_command_for_chat", lambda: "/safe/claude")
    monkeypatch.setattr(ikarus_os, "_provider_start", lambda *args, **kwargs: None)

    outcome: dict[str, BaseException] = {}

    def consume() -> None:
        try:
            list(ikarus_os._claude_stream(
                "hello",
                timeout_s=30.0,
                cancellation=signal,
            ))
        except BaseException as exc:  # captured for assertion in the test thread
            outcome["exception"] = exc

    worker = threading.Thread(target=consume, name="test-claude-stream-consumer")
    worker.start()
    assert spawned.wait(3.0), "Claude child was never spawned"

    assert signal.cancel() is True
    worker.join(5.0)

    child = holder["process"]
    try:
        assert not worker.is_alive(), "cancellation did not unblock the Claude stream"
        assert isinstance(outcome.get("exception"), ProviderCancelled)
        assert child.poll() is not None, "request owner returned while its Claude child was still live"
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5.0)
