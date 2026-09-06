from __future__ import annotations

import subprocess
import sys
import threading

import pytest

from daedalus.ikarus_cancellation import (
    CancellationRegistrationError,
    CancellationRegistry,
    CancellationSignal,
    terminate_owned_subprocess,
)


def test_registry_cancel_is_idempotent_and_reports_active_owner() -> None:
    registry = CancellationRegistry()
    signal = registry.open("turn-12345678")

    first = registry.cancel("turn-12345678")
    second = registry.cancel("turn-12345678")

    assert signal.cancelled() is True
    assert first.to_dict() == {
        "request_id": "turn-12345678",
        "active": True,
        "newly_cancelled": True,
    }
    assert second.active is True
    assert second.newly_cancelled is False


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


def test_unknown_id_is_not_misreported_as_cancelled_work() -> None:
    registry = CancellationRegistry()
    receipt = registry.cancel("turn-unknown-1")
    assert receipt.active is False
    assert receipt.newly_cancelled is False


def test_duplicate_live_request_id_refuses_instead_of_aliasing_signals() -> None:
    registry = CancellationRegistry()
    first = registry.open("turn-duplicate-1")
    with pytest.raises(CancellationRegistrationError, match="already belongs"):
        registry.open("turn-duplicate-1")
    assert registry.active_count() == 1
    assert first.cancelled() is False


def test_release_is_identity_safe_across_request_id_reuse() -> None:
    registry = CancellationRegistry()
    old = registry.open("turn-reused-0001")
    assert registry.release(old) is True
    assert old.finished() is True

    current = registry.open("turn-reused-0001")
    assert registry.release(old) is False
    assert current.finished() is False
    assert registry.active_count() == 1
    assert registry.cancel("turn-reused-0001").active is True
    assert current.cancelled() is True


def test_request_id_boundary_and_exact_release_type_are_fail_closed() -> None:
    registry = CancellationRegistry()
    for bad in ("", "short", " contains-space", "x" * 129, "/pathlike"):
        with pytest.raises(CancellationRegistrationError):
            registry.open(bad)

    class Substitute(CancellationSignal):
        pass

    with pytest.raises(TypeError, match="exact CancellationSignal"):
        registry.release(Substitute("turn-substitute-1"))


def test_claim_releases_and_marks_finished_even_when_owner_raises() -> None:
    registry = CancellationRegistry()
    signal: CancellationSignal | None = None

    with pytest.raises(RuntimeError, match="owner failed"):
        with registry.claim("turn-claimed-0001") as claimed:
            signal = claimed
            assert registry.active_count() == 1
            assert claimed.finished() is False
            raise RuntimeError("owner failed")

    assert signal is not None
    assert signal.finished() is True
    assert registry.active_count() == 0


def test_cancel_and_wait_never_rounds_timeout_up_to_finished() -> None:
    registry = CancellationRegistry()
    signal = registry.open("turn-waiting-0001")

    receipt = registry.cancel_and_wait("turn-waiting-0001", timeout_s=0)

    assert receipt.to_dict() == {
        "request_id": "turn-waiting-0001",
        "active": True,
        "newly_cancelled": True,
        "request_finished": False,
    }
    assert signal.cancelled() is True
    assert signal.finished() is False


def test_cancel_and_wait_observes_exact_owner_release() -> None:
    registry = CancellationRegistry()
    signal = registry.open("turn-terminal-0001")
    may_release = threading.Event()
    released = threading.Event()

    def owner() -> None:
        assert may_release.wait(1.0)
        assert registry.release(signal) is True
        released.set()

    thread = threading.Thread(target=owner)
    thread.start()
    may_release.set()

    receipt = registry.cancel_and_wait("turn-terminal-0001", timeout_s=1.0)
    thread.join(timeout=1.0)

    assert released.is_set()
    assert receipt.active is True
    assert receipt.newly_cancelled is True
    assert receipt.request_finished is True
    assert signal.finished() is True
    assert registry.active_count() == 0


def test_cancel_and_wait_unknown_id_is_not_false_terminal_evidence() -> None:
    registry = CancellationRegistry()
    receipt = registry.cancel_and_wait("turn-never-seen-1", timeout_s=0)
    assert receipt.to_dict() == {
        "request_id": "turn-never-seen-1",
        "active": False,
        "newly_cancelled": False,
        "request_finished": False,
    }


def test_cancel_wait_timeout_boundary_fails_closed() -> None:
    registry = CancellationRegistry()
    registry.open("turn-timeout-0001")
    with pytest.raises(ValueError, match="timeout_s must be >= 0"):
        registry.cancel_and_wait("turn-timeout-0001", timeout_s=-0.1)


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
