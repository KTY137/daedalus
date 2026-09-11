from __future__ import annotations

import threading
import json

import pytest

from daedalus.providers import _ollama_native as native
from daedalus.providers._openai_compat import ProviderCancelled, ProviderHTTPError


_FRAME = b'{"message":{"content":"hello"},"done":false}\n'
_DONE = b'{"message":{"content":""},"done":true}\n'


class _Response:
    def __init__(self, frames):
        self._frames = iter(frames)
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._frames)

    def close(self):
        self.closed = True


class _BlockingResponse:
    def __init__(self):
        self._first = True
        self.blocked = threading.Event()
        self.release = threading.Event()
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def __iter__(self):
        return self

    def __next__(self):
        if self._first:
            self._first = False
            return _FRAME
        self.blocked.set()
        self.release.wait(5)
        if self.closed:
            raise OSError("closed")
        return _DONE

    def close(self):
        self.closed = True
        self.release.set()


def _stream(**kwargs):
    return native.native_chat_stream(
        host="http://127.0.0.1:11434",
        model="qwen-test",
        messages=[{"role": "user", "content": "hi"}],
        **kwargs,
    )


def test_stream_without_probe_stays_on_caller_thread(monkeypatch):
    caller_tid = threading.get_ident()
    seen = {}
    response = _Response([_FRAME, _DONE])

    def fake_urlopen(_request, *, timeout):
        seen["thread"] = threading.get_ident()
        seen["timeout"] = timeout
        return response

    monkeypatch.setattr(native.urllib.request, "urlopen", fake_urlopen)

    assert list(_stream(timeout_s=41.25)) == ["hello"]
    assert seen == {"thread": caller_tid, "timeout": 41.25}
    assert response.closed is True


def test_already_cancelled_stream_never_opens_connection(monkeypatch):
    opened = 0

    def fake_urlopen(*_args, **_kwargs):
        nonlocal opened
        opened += 1
        raise AssertionError("cancelled stream must not connect")

    monkeypatch.setattr(native.urllib.request, "urlopen", fake_urlopen)
    stream = _stream(cancelled=lambda: True, poll_interval_s=0.01)

    with pytest.raises(ProviderCancelled, match="before native Ollama stream"):
        next(stream)
    assert opened == 0


def test_inflight_cancel_closes_response_and_never_replays(monkeypatch):
    response = _BlockingResponse()
    calls = 0
    cancelled = threading.Event()

    def fake_urlopen(_request, *, timeout):
        nonlocal calls
        calls += 1
        assert timeout == 90.0
        return response

    monkeypatch.setattr(native.urllib.request, "urlopen", fake_urlopen)
    stream = _stream(
        timeout_s=90.0,
        cancelled=cancelled.is_set,
        poll_interval_s=0.01,
    )

    assert next(stream) == "hello"
    assert response.blocked.wait(1), "worker never entered the in-flight read"
    cancelled.set()
    with pytest.raises(ProviderCancelled, match="while native Ollama stream"):
        next(stream)

    assert response.closed is True
    assert calls == 1


def test_cancellable_stream_preserves_caller_timeout(monkeypatch):
    seen = {}
    response = _Response([_DONE])

    def fake_urlopen(_request, *, timeout):
        seen["timeout"] = timeout
        return response

    monkeypatch.setattr(native.urllib.request, "urlopen", fake_urlopen)

    assert list(_stream(
        timeout_s=123.5,
        cancelled=lambda: False,
        poll_interval_s=0.01,
    )) == []
    assert seen["timeout"] == 123.5


def test_invalid_poll_interval_fails_before_connection(monkeypatch):
    opened = 0

    def fake_urlopen(*_args, **_kwargs):
        nonlocal opened
        opened += 1
        raise AssertionError("invalid cancellation policy must fail first")

    monkeypatch.setattr(native.urllib.request, "urlopen", fake_urlopen)
    stream = _stream(cancelled=lambda: False, poll_interval_s=0)

    with pytest.raises(ValueError, match="poll_interval_s must be > 0"):
        next(stream)
    assert opened == 0


@pytest.mark.parametrize("cancelled", [None, lambda: False])
def test_stream_preserves_uncapped_timeout_and_native_options(monkeypatch, cancelled):
    requests = []

    def connect(request, *, timeout):
        requests.append((request.full_url, json.loads(request.data), timeout))
        return _Response([_FRAME, _DONE])

    monkeypatch.setattr(native.urllib.request, "urlopen", connect)
    assert list(_stream(
        timeout_s=None, cancelled=cancelled, keep_alive="30m", num_ctx=8192,
        num_predict=128, think=False, force_json={"type": "object"},
    )) == ["hello"]
    assert len(requests) == 1
    url, body, timeout = requests[0]
    assert url == "http://127.0.0.1:11434/api/chat"
    assert timeout is None
    assert body["keep_alive"] == "30m"
    assert body["options"] == {"num_ctx": 8192, "num_predict": 128, "temperature": 0.0}
    assert body["think"] is False
    assert body["format"] == {"type": "object"}
    assert body["stream"] is True


@pytest.mark.parametrize("cancelled", [None, lambda: False])
@pytest.mark.parametrize("frame", [
    b"[]\n", b"null\n", b"not-json\n", b'{"error":"failed"}\n',
    b"", b'{"done":"false"}\n',
])
def test_invalid_native_frame_is_terminal_without_replay(monkeypatch, cancelled, frame):
    calls = []

    def connect(*args, **kwargs):
        calls.append(1)
        return _Response([_FRAME, frame])

    monkeypatch.setattr(native.urllib.request, "urlopen", connect)
    stream = _stream(cancelled=cancelled)
    assert next(stream) == "hello"
    with pytest.raises(ProviderHTTPError):
        next(stream)
    assert len(calls) == 1


@pytest.mark.parametrize("cancelled", [None, lambda: False])
def test_native_timeout_error_with_disabled_deadline_keeps_error_type(monkeypatch, cancelled):
    def fail(*args, **kwargs):
        assert kwargs["timeout"] is None
        raise TimeoutError("socket timed out")

    monkeypatch.setattr(native.urllib.request, "urlopen", fail)
    with pytest.raises(ProviderHTTPError, match="timed out"):
        list(_stream(timeout_s=None, cancelled=cancelled))
