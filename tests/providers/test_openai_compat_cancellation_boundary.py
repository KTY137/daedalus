"""Focused cancellation contract for the shared blocking LLM transport.

This is the narrow Ikarus-facing slice of G1-KERNEL-02: cancellation must return
control from a blocked provider wait without inventing a timeout, replaying the
call, or double-booking an already explicit budget reservation.
"""

from __future__ import annotations

import threading
import time
import io
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


class _StaticStreamResponse:
    def __init__(self, *lines: bytes) -> None:
        self._lines = lines
        self.closed = threading.Event()

    def __enter__(self) -> "_StaticStreamResponse":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def __iter__(self):
        return iter(self._lines)

    def close(self) -> None:
        self.closed.set()


def _stream(**kwargs: Any):
    return compat.chat_stream(
        base_url="http://provider.invalid",
        model="m",
        system="system",
        user="user",
        timeout_s=17,
        **kwargs,
    )


def test_chat_stream_without_probe_stays_on_the_direct_caller_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caller_thread = threading.get_ident()
    opened_on: list[int] = []
    response = _StaticStreamResponse(
        b'data: {"choices":[{"delta":{"content":"hello"}}]}\n',
        b"data: [DONE]\n",
    )

    def fake_urlopen(request: Any, *, timeout: float | None = None) -> _StaticStreamResponse:
        assert request.full_url == "http://provider.invalid/chat/completions"
        assert timeout == 17
        opened_on.append(threading.get_ident())
        return response

    monkeypatch.setattr(compat.urllib.request, "urlopen", fake_urlopen)

    assert list(_stream()) == ["hello"]
    assert opened_on == [caller_thread]
    assert response.closed.is_set()


def test_pre_cancelled_chat_stream_never_opens_a_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_urlopen(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("pre-cancelled stream must not open a connection")

    monkeypatch.setattr(compat.urllib.request, "urlopen", forbidden_urlopen)

    with pytest.raises(compat.ProviderCancelled, match="before chat stream opened"):
        next(_stream(cancelled=lambda: True, poll_interval_s=0.01))


def test_chat_stream_cancellation_closes_response_before_blocked_worker_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocked = threading.Event()
    release = threading.Event()
    cancelled = threading.Event()

    class BlockingResponse:
        def __init__(self) -> None:
            self._first = True
            self.closed = threading.Event()

        def __enter__(self) -> "BlockingResponse":
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            self.close()

        def __iter__(self) -> "BlockingResponse":
            return self

        def __next__(self) -> bytes:
            if self._first:
                self._first = False
                return b'data: {"choices":[{"delta":{"content":"first"}}]}\n'
            blocked.set()
            release.wait(5.0)
            raise StopIteration

        def close(self) -> None:
            self.closed.set()

    response = BlockingResponse()
    monkeypatch.setattr(
        compat.urllib.request,
        "urlopen",
        lambda request, *, timeout=None: response,
    )

    stream = _stream(cancelled=cancelled.is_set, poll_interval_s=0.01)
    assert next(stream) == "first"
    assert blocked.wait(1.0)
    cancelled.set()
    began = time.monotonic()
    try:
        with pytest.raises(compat.ProviderCancelled, match="chat stream was in flight"):
            next(stream)
        assert time.monotonic() - began < 1.5
        assert response.closed.wait(0.2)
        # The fake worker is intentionally still blocked: returning control did
        # not depend on it completing, and no replay path was introduced.
        assert not release.is_set()
    finally:
        release.set()


def test_cancellable_chat_stream_preserves_transport_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def offline(*args: Any, **kwargs: Any) -> Any:
        raise compat.urllib.error.URLError("offline")

    monkeypatch.setattr(compat.urllib.request, "urlopen", offline)

    with pytest.raises(compat.ProviderHTTPError, match="cannot reach .*offline"):
        list(_stream(cancelled=lambda: False, poll_interval_s=0.01))


def test_cancellable_chat_stream_worker_inherits_explicit_budget_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from daedalus import budget

    adopted_on: list[int] = []
    caller_thread = threading.get_ident()
    response = _StaticStreamResponse(b"data: [DONE]\n")

    monkeypatch.setattr(budget, "_inside_explicit", lambda: True)
    monkeypatch.setattr(
        budget,
        "_enter_explicit",
        lambda: adopted_on.append(threading.get_ident()),
    )
    monkeypatch.setattr(
        compat.urllib.request,
        "urlopen",
        lambda request, *, timeout=None: response,
    )

    assert list(_stream(cancelled=lambda: False, poll_interval_s=0.01)) == []
    assert len(adopted_on) == 1
    assert adopted_on[0] != caller_thread


def test_response_close_cannot_block_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    blocked = threading.Event()
    release = threading.Event()
    closing = threading.Event()
    cancelled = threading.Event()

    class LockedResponse(_StaticStreamResponse):
        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"content":"first"}}]}\n'
            blocked.set()
            release.wait(5)

        def close(self) -> None:
            # urllib's response close may wait for a buffered read's lock.
            closing.set()
            release.wait(5)
            super().close()

    response = LockedResponse()
    monkeypatch.setattr(compat.urllib.request, "urlopen", lambda *a, **k: response)
    stream = _stream(cancelled=cancelled.is_set, poll_interval_s=0.01)
    assert next(stream) == "first"
    assert blocked.wait(1)
    cancelled.set()
    began = time.monotonic()
    try:
        with pytest.raises(compat.ProviderCancelled):
            next(stream)
        assert time.monotonic() - began < 1.5
        assert closing.wait(1)
        assert not response.closed.is_set()
    finally:
        release.set()


def test_late_connection_is_closed_without_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    opened = threading.Event()
    release = threading.Event()
    cancelled = threading.Event()
    response = _StaticStreamResponse(b"data: [DONE]\n")
    calls = []

    def connect(*args: Any, **kwargs: Any):
        calls.append(kwargs["timeout"])
        opened.set()
        release.wait(5)
        return response

    def cancel() -> None:
        assert opened.wait(1)
        cancelled.set()

    monkeypatch.setattr(compat.urllib.request, "urlopen", connect)
    threading.Thread(target=cancel, daemon=True).start()
    try:
        with pytest.raises(compat.ProviderCancelled):
            next(_stream(cancelled=cancelled.is_set, poll_interval_s=0.01))
        assert not response.closed.is_set()
    finally:
        release.set()
    assert response.closed.wait(1)
    assert calls == [17]


@pytest.mark.parametrize("interval", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_poll_interval_refuses_before_transport(monkeypatch, interval):
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid polling interval opened a connection")

    monkeypatch.setattr(compat.urllib.request, "urlopen", forbidden)
    with pytest.raises(ValueError, match="poll_interval_s"):
        next(_stream(cancelled=lambda: False, poll_interval_s=interval))


def test_slow_http_error_body_remains_cancellable(monkeypatch):
    reading_error = threading.Event()
    release = threading.Event()
    cancelled = threading.Event()
    opened = []

    class SlowError(compat.urllib.error.HTTPError):
        def read(self, *args):
            reading_error.set()
            release.wait(5)
            return b"provider failed"

    def fail(*args, **kwargs):
        opened.append(1)
        raise SlowError("http://provider.invalid", 503, "Unavailable", {}, None)

    def cancel():
        assert reading_error.wait(1)
        cancelled.set()

    monkeypatch.setattr(compat.urllib.request, "urlopen", fail)
    threading.Thread(target=cancel, daemon=True).start()
    began = time.monotonic()
    try:
        with pytest.raises(compat.ProviderCancelled):
            next(_stream(cancelled=cancelled.is_set, poll_interval_s=0.01))
        assert time.monotonic() - began < 1.5
        assert opened == [1]
    finally:
        release.set()


def test_late_http_error_is_closed_without_reading_or_replay(monkeypatch):
    opening = threading.Event()
    release = threading.Event()
    closed = threading.Event()
    cancelled = threading.Event()
    calls = []
    reads = []

    class ErrorBody(io.BytesIO):
        def read(self, *args):
            reads.append(args)
            raise AssertionError("cancelled late error must not read its body")

        def close(self):
            super().close()
            closed.set()

    error = compat.urllib.error.HTTPError(
        "http://provider.invalid", 503, "Unavailable", {}, ErrorBody(b"late error"),
    )

    def connect(*args, **kwargs):
        calls.append(1)
        opening.set()
        release.wait(5)
        raise error

    def cancel():
        assert opening.wait(1)
        cancelled.set()

    monkeypatch.setattr(compat.urllib.request, "urlopen", connect)
    threading.Thread(target=cancel, daemon=True).start()
    try:
        with pytest.raises(compat.ProviderCancelled):
            next(_stream(cancelled=cancelled.is_set, poll_interval_s=0.01))
        assert not closed.is_set()
    finally:
        release.set()
    assert closed.wait(1)
    assert calls == [1]
    assert reads == []


@pytest.mark.parametrize("read_fails", [False, True])
def test_http_error_body_is_bounded_and_always_closed(monkeypatch, read_fails):
    closed = threading.Event()
    reads = []

    class ErrorBody(io.BytesIO):
        def read(self, size=-1):
            reads.append(size)
            if read_fails:
                raise OSError("error body failed")
            return super().read(size)

        def close(self):
            super().close()
            closed.set()

    body = ErrorBody(b"x" * 2000)
    error = compat.urllib.error.HTTPError(
        "http://provider.invalid", 503, "Unavailable", {}, body,
    )

    def connect(*args, **kwargs):
        raise error

    monkeypatch.setattr(compat.urllib.request, "urlopen", connect)
    error_type = OSError if read_fails else compat.ProviderHTTPError
    with pytest.raises(error_type) as failure:
        list(_stream(cancelled=lambda: False, poll_interval_s=0.01))
    assert reads == [500]
    assert closed.wait(1)
    if not read_fails:
        assert str(failure.value).count("x") == 500
