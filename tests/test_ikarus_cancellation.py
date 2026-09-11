"""Owned-child fault matrix. Durable identity/idempotency/restart/cancel races
are exercised in test_conversation_requests.py; the upstream transient registry
is superseded by that canonical manager, not installed as another authority.
"""
from __future__ import annotations

import subprocess
import sys
import threading

import pytest

from daedalus.orchestration.ikarus.cancellation import (
    CancellationSignal,
    terminate_owned_subprocess,
)




def test_signal_cancel_transition_has_exactly_one_winner_under_race() -> None:
    signal = CancellationSignal("turn-race-000001")
    start = threading.Barrier(9)
    results: list[bool] = []
    results_lock = threading.Lock()

    def cancel() -> None:
        start.wait()
        result = signal.cancel()
        with results_lock:
            results.append(result)

    threads = [threading.Thread(target=cancel) for _ in range(8)]
    for thread in threads:
        thread.start()
    start.wait()
    for thread in threads:
        thread.join(timeout=2)

    assert len(results) == 8
    assert results.count(True) == 1
    assert results.count(False) == 7
    assert signal.cancelled() is True




















def _sleeping_child() -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_owned_subprocess_is_not_touched_before_cancellation() -> None:
    signal = CancellationSignal("turn-proc-live-01")
    proc = _sleeping_child()
    try:
        receipt = terminate_owned_subprocess(signal, proc, grace_s=0.5)
        assert receipt.cancellation_requested is False
        assert receipt.was_running is True
        assert receipt.terminate_sent is False
        assert receipt.kill_sent is False
        assert receipt.process_exited is False
        assert proc.poll() is None
    finally:
        proc.kill()
        proc.wait(timeout=5)


def test_owned_subprocess_stop_produces_positive_exit_evidence() -> None:
    signal = CancellationSignal("turn-proc-stop-01")
    proc = _sleeping_child()
    signal.cancel()

    receipt = terminate_owned_subprocess(signal, proc, grace_s=1.0)

    assert receipt.request_id == signal.request_id
    assert receipt.cancellation_requested is True
    assert receipt.was_running is True
    assert receipt.terminate_sent is True
    assert receipt.process_exited is True
    assert receipt.returncode is not None
    assert proc.poll() is not None


def test_owned_subprocess_already_terminal_is_observed_not_reterminated() -> None:
    signal = CancellationSignal("turn-proc-done-01")
    proc = subprocess.Popen(
        [sys.executable, "-c", "pass"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    proc.wait(timeout=5)
    signal.cancel()

    receipt = terminate_owned_subprocess(signal, proc, grace_s=0.5)

    assert receipt.cancellation_requested is True
    assert receipt.was_running is False
    assert receipt.terminate_sent is False
    assert receipt.kill_sent is False
    assert receipt.process_exited is True
    assert receipt.returncode == proc.returncode


def test_owned_subprocess_boundary_rejects_substituted_handles_before_methods_run() -> None:
    signal = CancellationSignal("turn-proc-type-01")

    class SubstituteSignal(CancellationSignal):
        pass

    class FakeProcess:
        def __getattribute__(self, name: str):
            raise AssertionError(f"substituted process member accessed: {name}")

    with pytest.raises(TypeError, match="exact CancellationSignal"):
        terminate_owned_subprocess(SubstituteSignal(signal.request_id), FakeProcess())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="exact subprocess.Popen"):
        terminate_owned_subprocess(signal, FakeProcess())  # type: ignore[arg-type]


def test_owned_subprocess_negative_grace_fails_before_process_observation() -> None:
    signal = CancellationSignal("turn-proc-grace-01")
    proc = _sleeping_child()
    try:
        with pytest.raises(ValueError, match="grace_s must be >= 0"):
            terminate_owned_subprocess(signal, proc, grace_s=-0.1)
        assert proc.poll() is None
    finally:
        proc.kill()
        proc.wait(timeout=5)
