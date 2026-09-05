"""Focused contracts for the HTTP response disconnect boundary."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from email.message import Message
from http.server import ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

from daedalus.interfaces.http import web_api
from daedalus.spine import effect_boundary


DISCONNECT_ERRORS = (
    BrokenPipeError,
    ConnectionResetError,
    ConnectionAbortedError,
)


class _Wire:
    def __init__(self, failure: type[OSError] | None = None) -> None:
        self.failure = failure
        self.writes = 0

    def write(self, _data: bytes) -> None:
        self.writes += 1
        if self.failure is not None:
            raise self.failure("client closed")


class _Handler(web_api.DaedalusHandler):
    """Handler-shaped fake with no socket, server, or live network."""

    def __init__(
        self,
        failure: type[OSError] | None = None,
        *,
        failure_phase: str = "body",
    ) -> None:
        self.close_connection = False
        self._header_failure = failure if failure_phase == "headers" else None
        self.wfile = _Wire(failure if failure_phase == "body" else None)
        self.responses: list[int] = []
        self.headers_sent: list[tuple[str, str]] = []

    def _authorized(self) -> bool:
        return True

    def _bind_decision(self) -> object:
        return object()

    def send_response(self, code: int, message: str | None = None) -> None:
        del message
        self.responses.append(code)

    def send_header(self, keyword: str, value: str) -> None:
        self.headers_sent.append((keyword, value))

    def end_headers(self) -> None:
        if self._header_failure is not None:
            raise self._header_failure("client closed")


class _UnreadableBody:
    def read(self, _length: int) -> bytes:
        raise AssertionError("unbounded or chunked refusal body must not be read")


@pytest.mark.parametrize("failure_phase", ("headers", "body"))
@pytest.mark.parametrize("disconnect", DISCONNECT_ERRORS)
def test_unauthorized_response_disconnect_is_terminal(
    disconnect: type[OSError],
    failure_phase: str,
) -> None:
    handler = _Handler(disconnect, failure_phase=failure_phase)
    handler._authorized = lambda: False

    handler.do_GET()

    assert handler.responses == [401]
    assert handler.wfile.writes == (1 if failure_phase == "body" else 0)
    assert handler.close_connection is True


def test_unauthorized_refusal_drains_one_bounded_declared_body() -> None:
    handler = _Handler()
    handler.headers = Message()
    handler.headers["Content-Length"] = "2"
    handler.rfile = BytesIO(b"{}")

    handler._deny()

    assert handler.rfile.tell() == 2
    assert handler.responses == [401]
    assert ("Connection", "close") not in handler.headers_sent


@pytest.mark.parametrize(
    "headers",
    (
        (("Transfer-Encoding", "chunked"),),
        (("Content-Length", str(web_api._AUTH_REFUSAL_MAX_DRAIN_BYTES + 1)),),
    ),
)
def test_unauthorized_refusal_never_drains_chunked_or_oversized_body(
    headers: tuple[tuple[str, str], ...],
) -> None:
    handler = _Handler()
    handler.headers = Message()
    for name, value in headers:
        handler.headers[name] = value
    handler.rfile = _UnreadableBody()

    handler._deny()

    assert handler.responses == [401]
    assert handler.close_connection is True
    assert ("Connection", "close") in handler.headers_sent


def test_repeated_unauthorized_posts_return_401_instead_of_windows_reset() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), web_api.DaedalusHandler)
    server.daedalus_auth_token = "z" * web_api.MIN_AUTH_TOKEN_CHARS
    thread = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": 0.01},
        daemon=True,
    )
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        for _ in range(32):
            request = urllib.request.Request(
                base + "/api/queue",
                data=b"{}",
                method="POST",
            )
            with pytest.raises(urllib.error.HTTPError) as refused:
                urllib.request.urlopen(request, timeout=10)
            assert refused.value.code == 401
            assert json.loads(refused.value.read())["ok"] is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


@pytest.mark.parametrize("failure_phase", ("headers", "body"))
@pytest.mark.parametrize("dist_available", (False, True))
@pytest.mark.parametrize("disconnect", DISCONNECT_ERRORS)
def test_static_response_disconnect_does_not_fall_back_to_json_500(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    disconnect: type[OSError],
    dist_available: bool,
    failure_phase: str,
) -> None:
    monkeypatch.setattr(web_api, "WEB_DIST", tmp_path)
    if dist_available:
        (tmp_path / "index.html").write_text("ready", encoding="utf-8")
    handler = _Handler(disconnect, failure_phase=failure_phase)
    handler._handle_get = lambda: handler._send_static("/")

    handler.do_GET()

    assert handler.responses == [200]
    assert handler.wfile.writes == (1 if failure_phase == "body" else 0)
    assert handler.close_connection is True


def test_static_file_read_failure_remains_a_json_500(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "index.html"
    target.write_text("ready", encoding="utf-8")
    monkeypatch.setattr(web_api, "WEB_DIST", tmp_path)

    def fail_read(_path: Path) -> bytes:
        raise ConnectionAbortedError("backend file read failed")

    monkeypatch.setattr(Path, "read_bytes", fail_read)
    handler = _Handler()
    handler._handle_get = lambda: handler._send_static("/")

    handler.do_GET()

    assert handler.responses == [500]
    assert ("Content-Type", "application/json; charset=utf-8") in handler.headers_sent
    assert handler.wfile.writes == 1
    assert handler.close_connection is False


@pytest.mark.parametrize("disconnect", DISCONNECT_ERRORS)
def test_preflight_header_disconnect_is_terminal(
    disconnect: type[OSError],
) -> None:
    handler = _Handler(disconnect, failure_phase="headers")

    handler.do_OPTIONS()

    assert handler.responses == [204]
    assert handler.wfile.writes == 0
    assert handler.close_connection is True


def _raise(exc_type: type[BaseException]) -> Callable[[], None]:
    def fail() -> None:
        raise exc_type("client closed")

    return fail


@pytest.mark.parametrize("disconnect", DISCONNECT_ERRORS)
def test_json_write_disconnect_is_terminal_without_second_response(
    disconnect: type[OSError],
) -> None:
    handler = _Handler(disconnect)
    handler._handle_get = lambda: handler._send_json({"ok": True})

    handler.do_GET()

    assert handler.wfile.writes == 1
    assert handler.responses == [200]
    assert handler.close_connection is True


@pytest.mark.parametrize("request_method", ("do_GET", "do_PUT", "do_POST"))
@pytest.mark.parametrize("disconnect", DISCONNECT_ERRORS)
def test_route_io_failure_is_not_misclassified_without_write_provenance(
    monkeypatch: pytest.MonkeyPatch,
    request_method: str,
    disconnect: type[OSError],
) -> None:
    monkeypatch.setattr(effect_boundary, "begin_effect", lambda *args: None)
    handler = _Handler()
    delegate = {
        "do_GET": "_handle_get",
        "do_PUT": "_handle_put",
        "do_POST": "_handle_post",
    }[request_method]
    setattr(handler, delegate, _raise(disconnect))
    sent: list[tuple[Any, int]] = []
    handler._send_json = lambda payload, status=200: sent.append((payload, status))

    getattr(handler, request_method)()

    assert sent == [({"ok": False, "error": "client closed"}, 500)]
    assert handler.close_connection is False


@pytest.mark.parametrize("failure", (RuntimeError, OSError))
def test_real_handler_failure_keeps_existing_json_500(
    failure: type[Exception],
) -> None:
    handler = _Handler()
    handler._handle_get = _raise(failure)
    sent: list[tuple[Any, int]] = []
    handler._send_json = lambda payload, status=200: sent.append((payload, status))

    handler.do_GET()

    assert sent == [({"ok": False, "error": "client closed"}, 500)]
    assert handler.close_connection is False
