"""Focused cancellation contract for the shared blocking LLM transport.

This is the narrow Ikarus-facing slice of G1-KERNEL-02: cancellation must return
control from a blocked provider wait without inventing a timeout, replaying the
call, or double-booking an already explicit budget reservation.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from daedalus.providers import _openai_compat as compat


def test_pre_cancelled_call_never_starts_work() -> None:
    touched = threading.Event()

    with pytest.raises(compat.ProviderCancelled, match="before .* opened"):
        compat.run_cancellable(
            lambda: touched.set(),
            cancelled=lambda: True,
            poll_interval_s=0.01,
            name="test-provider",
        )

    assert not touched.is_set()


def test_inflight_cancellation_returns_before_blocked_work_finishes() -> None:
    started = threading.Event()
    release = threading.Event()
    cancelled = threading.Event()

    def work() -> str:
        started.set()
        release.wait(5.0)
        return "late"

    def flip() -> None:
        assert started.wait(1.0)
        cancelled.set()

    threading.Thread(target=flip, daemon=True).start()
    began = time.monotonic()
    try:
        with pytest.raises(compat.ProviderCancelled, match="in flight"):
            compat.run_cancellable(
                work,
                cancelled=cancelled.is_set,
                poll_interval_s=0.01,
                name="test-provider",
            )
        assert time.monotonic() - began < 1.5
    finally:
        release.set()


def test_completed_work_and_worker_errors_keep_their_original_semantics() -> None:
    assert compat.run_cancellable(
        lambda: "answer", cancelled=lambda: False, poll_interval_s=0.01
    ) == "answer"

    error = LookupError("provider result failed")

    def fail() -> Any:
        raise error

    with pytest.raises(LookupError) as caught:
        compat.run_cancellable(
            fail, cancelled=lambda: False, poll_interval_s=0.01
        )
    assert caught.value is error


def test_provider_cancellation_is_not_reported_as_provider_http_failure() -> None:
    assert not issubclass(compat.ProviderCancelled, compat.ProviderHTTPError)


def test_nonpositive_poll_interval_is_refused() -> None:
    for value in (0.0, -0.1):
        with pytest.raises(ValueError, match="poll_interval_s"):
            compat.run_cancellable(
                lambda: None,
                cancelled=lambda: False,
                poll_interval_s=value,
            )


def test_post_without_probe_keeps_the_direct_blocking_path(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = {"choices": [{"message": {"content": "ok"}}]}
    send_calls: list[float | None] = []

    def fake_send(request: Any, url: str, timeout_s: float | None) -> dict[str, Any]:
        assert request.full_url == "http://provider.invalid/chat/completions"
        assert url == request.full_url
        send_calls.append(timeout_s)
        return sent

    def forbidden_wrapper(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("no-probe path must not create a cancellation worker")

    monkeypatch.setattr(compat, "_send", fake_send)
    monkeypatch.setattr(compat, "run_cancellable", forbidden_wrapper)

    got = compat._post(
        "http://provider.invalid",
        {"model": "m", "messages": [], "stream": False},
        None,
        None,
    )

    assert got is sent
    assert send_calls == [None]


def test_chat_completion_without_probe_keeps_legacy_post_call_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str | None, float | None]] = []

    # Intentionally accepts only the historic four positional arguments. Any
    # accidental cancellation keyword on the opt-out path makes this fail.
    def legacy_post(
        base_url: str,
        body: dict[str, Any],
        api_key: str | None,
        timeout_s: float | None,
    ) -> dict[str, Any]:
        assert body["model"] == "m"
        calls.append((base_url, api_key, timeout_s))
        return {"choices": [{"message": {"content": "unchanged"}}]}

    monkeypatch.setattr(compat, "_post", legacy_post)

    assert compat.chat_completion(
        base_url="http://provider.invalid",
        model="m",
        system="system",
        user="user",
        api_key="key",
        timeout_s=None,
        force_json=False,
    ) == "unchanged"
    assert calls == [("http://provider.invalid", "key", None)]


def test_cancellable_worker_inherits_explicit_budget_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    from daedalus import budget

    adopted_on: list[int] = []
    caller_thread = threading.get_ident()

    monkeypatch.setattr(budget, "_inside_explicit", lambda: True)
    monkeypatch.setattr(
        budget,
        "_enter_explicit",
        lambda: adopted_on.append(threading.get_ident()),
    )

    assert compat.run_cancellable(
        lambda: "ok",
        cancelled=lambda: False,
        poll_interval_s=0.01,
    ) == "ok"
    assert len(adopted_on) == 1
    assert adopted_on[0] != caller_thread
