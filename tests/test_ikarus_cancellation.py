from __future__ import annotations

import threading

import pytest

from daedalus.ikarus_cancellation import (
    CancellationRegistrationError,
    CancellationRegistry,
    CancellationSignal,
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

    current = registry.open("turn-reused-0001")
    assert registry.release(old) is False
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
