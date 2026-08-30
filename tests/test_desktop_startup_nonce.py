from __future__ import annotations

import json
from threading import Thread
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from daedalus import web_api


def _server(nonce: str):
    server = web_api.ThreadingHTTPServer(("127.0.0.1", 0), web_api.DaedalusHandler)
    server.daedalus_auth_token = ""
    server.daedalus_desktop_startup_nonce = nonce
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_desktop_readiness_is_absent_without_parent_nonce() -> None:
    server, thread = _server("")
    try:
        with pytest.raises(HTTPError) as caught:
            urlopen(
                f"http://127.0.0.1:{server.server_port}/api/desktop-ready",
                timeout=2,
            )
        assert caught.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_desktop_readiness_returns_exact_parent_nonce() -> None:
    nonce = "a" * 64
    server, thread = _server(nonce)
    try:
        with urlopen(
            f"http://127.0.0.1:{server.server_port}/api/desktop-ready",
            timeout=2,
        ) as response:
            payload = json.loads(response.read())
        assert payload == {
            "schema": "daedalus-desktop-startup/1",
            "ready": True,
            "nonce": nonce,
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_malformed_desktop_nonce_refuses_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(web_api.DESKTOP_STARTUP_NONCE_ENV, "not-a-valid-nonce")
    with pytest.raises(ValueError, match="64 lowercase hex"):
        web_api._desktop_startup_nonce()
