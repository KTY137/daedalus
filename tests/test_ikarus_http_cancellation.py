from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace
from unittest import mock

from daedalus import ikarus_cancellation, web_api


def _post_handler(body: dict, registry: ikarus_cancellation.CancellationRegistry):
    handler = SimpleNamespace(path="/api/ikarus/cancel", _send_json=mock.Mock())
    with mock.patch.object(web_api, "_read_body", return_value=body), \
         mock.patch.object(web_api.ikarus_cancellation, "default_registry", return_value=registry):
        web_api.DaedalusHandler._handle_post(handler)
    return handler._send_json


def test_cancel_endpoint_returns_positive_exact_owner_release_evidence() -> None:
    registry = ikarus_cancellation.CancellationRegistry()
    request_id = "request-http-stop-001"
    entered = threading.Event()

    def owner() -> None:
        with registry.claim(request_id) as signal:
            entered.set()
            while not signal.cancelled():
                time.sleep(0.002)

    thread = threading.Thread(target=owner, daemon=True)
    thread.start()
    assert entered.wait(1.0)

    send = _post_handler({"request_id": request_id}, registry)
    thread.join(timeout=1.0)
    assert not thread.is_alive()
    payload = send.call_args.args[0]
    assert payload["cancellation"] == {
        "request_id": request_id,
        "active": True,
        "newly_cancelled": True,
        "request_finished": True,
    }


def test_cancel_endpoint_rejects_malformed_identity_without_owner_lookup() -> None:
    registry = ikarus_cancellation.CancellationRegistry()
    send = _post_handler({"request_id": "bad"}, registry)
    assert send.call_args.kwargs["status"] == 400
    assert "request_id" in send.call_args.args[0]["error"]
    assert registry.active_count() == 0


class _BrokenWriter:
    def write(self, _data: bytes) -> int:
        raise BrokenPipeError("client gone")

    def flush(self) -> None:
        return None


def test_sse_disconnect_cancels_and_releases_exact_live_signal() -> None:
    registry = ikarus_cancellation.CancellationRegistry()
    request_id = "request-http-stream-001"
    captured: dict[str, object] = {}

    def fake_stream(*_args, cancellation=None, **_kwargs):
        captured["signal"] = cancellation
        yield "start", {"intent": "chat", "provider_used": "ollama_http"}
        yield "final", {"ok": True}

    handler = SimpleNamespace(
        close_connection=False,
        wfile=_BrokenWriter(),
        send_response=lambda *_a, **_k: None,
        send_header=lambda *_a, **_k: None,
        end_headers=lambda *_a, **_k: None,
        _send_json=mock.Mock(),
    )
    qs = {
        "project": ["fixture"],
        "message": ["hello"],
        "request_id": [request_id],
    }
    with mock.patch.object(web_api.ikarus_cancellation, "default_registry", return_value=registry), \
         mock.patch.object(web_api.ikarus_os, "ask_stream", side_effect=fake_stream), \
         mock.patch("daedalus.progress.open_unit", side_effect=RuntimeError("skip progress")):
        web_api.DaedalusHandler._handle_ikarus_stream(handler, qs)

    signal = captured["signal"]
    assert type(signal) is ikarus_cancellation.CancellationSignal
    assert signal.request_id == request_id
    assert signal.cancelled()
    assert signal.finished()
    assert registry.active_count() == 0


def test_sse_start_frame_exposes_the_exact_request_identity() -> None:
    registry = ikarus_cancellation.CancellationRegistry()
    request_id = "request-http-start-001"
    chunks: list[bytes] = []

    class Writer:
        def write(self, data: bytes) -> int:
            chunks.append(data)
            return len(data)
        def flush(self) -> None:
            return None

    def fake_stream(*_args, cancellation=None, **_kwargs):
        assert cancellation.request_id == request_id
        yield "start", {"intent": "chat", "provider_used": "ollama_http"}
        yield "final", {"ok": True, "intent": "chat", "assistant": "done",
                        "provider_used": "ollama_http"}

    handler = SimpleNamespace(
        close_connection=False,
        wfile=Writer(),
        send_response=lambda *_a, **_k: None,
        send_header=lambda *_a, **_k: None,
        end_headers=lambda *_a, **_k: None,
        _send_json=mock.Mock(),
    )
    qs = {"project": ["fixture"], "message": ["hello"], "request_id": [request_id]}
    with mock.patch.object(web_api.ikarus_cancellation, "default_registry", return_value=registry), \
         mock.patch.object(web_api.ikarus_os, "ask_stream", side_effect=fake_stream), \
         mock.patch("daedalus.progress.open_unit", side_effect=RuntimeError("skip progress")):
        web_api.DaedalusHandler._handle_ikarus_stream(handler, qs)

    body = b"".join(chunks).decode("utf-8")
    start_data = body.split("event: start\n", 1)[1].split("\n\n", 1)[0]
    payload = json.loads(start_data.removeprefix("data: "))
    assert payload["request_id"] == request_id
    assert registry.active_count() == 0
