"""Adversarial request-boundary tests for desktop HTTP mutations."""
from __future__ import annotations

from email.message import Message
from types import SimpleNamespace
from typing import Any

import pytest

from daedalus import desktop_runtime
from daedalus.interfaces.http import effects as http_effects
from daedalus.interfaces.http import web_api
from daedalus.spine import effect_boundary


BOUND_HOST = "127.0.0.1"
BOUND_PORT = 8765
BOUND_ORIGIN = f"http://{BOUND_HOST}:{BOUND_PORT}"
BASE_HANDLER = web_api.DaedalusHandler


class _Manager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def snapshot(self) -> dict[str, Any]:
        return {}

    def save_settings(self, body: Any) -> dict[str, Any]:
        self.calls.append(("save_settings", body))
        return {}

    def ensure_bridge(self) -> dict[str, Any]:
        self.calls.append(("ensure_bridge", None))
        return {"running": True}

    def ensure_ollama(self) -> dict[str, Any]:
        self.calls.append(("ensure_ollama", None))
        return {"reachable": True}

    def stop_ollama(self) -> None:
        self.calls.append(("stop_ollama", None))

    def ensure_ide(self) -> dict[str, Any]:
        self.calls.append(("ensure_ide", None))
        return {"reachable": True}

    def stop_ide(self, *, strict: bool) -> None:
        self.calls.append(("stop_ide", strict))

    def close(self, *, strict: bool, timeout: float) -> None:
        self.calls.append(("close", (strict, timeout)))


def _headers(
    *,
    origin: str = BOUND_ORIGIN,
    fetch_site: str = "same-origin",
    content_type: str = "application/json",
    content_length: str = "2",
    nonce: str | None = None,
) -> Message:
    headers = Message()
    headers["Origin"] = origin
    headers["Sec-Fetch-Site"] = fetch_site
    headers["Content-Type"] = content_type
    headers["Content-Length"] = content_length
    if nonce is not None:
        headers["X-Daedalus-Desktop-Nonce"] = nonce
    return headers


@pytest.fixture
def installed_handler(monkeypatch: pytest.MonkeyPatch):
    manager = _Manager()
    begin_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    body_reads: list[object] = []

    monkeypatch.setattr(web_api, "DaedalusHandler", BASE_HANDLER)
    monkeypatch.setattr(
        web_api,
        "_read_body",
        lambda handler: body_reads.append(handler) or {"accepted": True},
    )
    monkeypatch.setattr(
        effect_boundary,
        "begin_effect",
        lambda *args, **kwargs: begin_calls.append((args, kwargs)),
    )
    desktop_runtime.install_web_integration(web_api, manager)
    return web_api.DaedalusHandler, manager, begin_calls, body_reads


def _request(
    handler_type: type,
    method: str,
    path: str,
    headers: Message,
) -> Any:
    handler = object.__new__(handler_type)
    handler.path = path
    handler.headers = headers
    handler.server = SimpleNamespace(
        daedalus_auth_token="",
        daedalus_desktop_startup_nonce="n" * 64,
        server_address=(BOUND_HOST, BOUND_PORT),
    )
    handler.responses = []
    handler._send_json = lambda payload, status=200: handler.responses.append(
        (status, payload)
    )
    getattr(handler, f"do_{method}")()
    return handler


def test_exact_origin_helper_rejects_aliases_and_authority_smuggling() -> None:
    handler = SimpleNamespace(
        server=SimpleNamespace(server_address=(BOUND_HOST, BOUND_PORT))
    )
    assert http_effects.same_origin_request(handler, BOUND_ORIGIN)
    for origin in (
        "null",
        "https://127.0.0.1:8765",
        "http://localhost:8765",
        "http://127.0.0.1:8766",
        "http://user@127.0.0.1:8765",
        "http://127.0.0.1:8765/",
        "http://127.0.0.1:8765?x=1",
        "http://127.0.0.1:8765#fragment",
    ):
        assert not http_effects.same_origin_request(handler, origin), origin


@pytest.mark.parametrize(
    ("method", "path"),
    (
        ("PUT", "/api/desktop/settings"),
        ("POST", "/api/desktop/services/bridge/start"),
        ("POST", "/api/desktop/services/ollama/start"),
        ("POST", "/api/desktop/services/ollama/stop"),
        ("POST", "/api/desktop/services/ide/start"),
        ("POST", "/api/desktop/services/ide/stop"),
        ("POST", "/api/desktop/shutdown"),
    ),
)
def test_cross_origin_desktop_mutations_reach_neither_effect_nor_manager(
    installed_handler: tuple[type, _Manager, list[Any], list[Any]],
    method: str,
    path: str,
) -> None:
    handler_type, manager, begin_calls, body_reads = installed_handler
    headers = _headers(
        origin="https://evil.example",
        fetch_site="cross-site",
        nonce="n" * 64,
    )

    request = _request(handler_type, method, path, headers)

    assert request.responses[0][0] == 403
    assert request.responses[0][1]["error_code"] == "desktop_policy_denied"
    assert request.close_connection is True
    assert begin_calls == []
    assert manager.calls == []
    assert body_reads == []


def test_other_localhost_port_is_not_same_origin(
    installed_handler: tuple[type, _Manager, list[Any], list[Any]],
) -> None:
    handler_type, manager, begin_calls, body_reads = installed_handler
    request = _request(
        handler_type,
        "POST",
        "/api/desktop/services/bridge/start",
        _headers(
            origin=f"http://{BOUND_HOST}:{BOUND_PORT + 1}",
            fetch_site="same-site",
        ),
    )

    assert request.responses[0][0] == 403
    assert begin_calls == []
    assert manager.calls == []
    assert body_reads == []


@pytest.mark.parametrize(
    "variant",
    ("missing-origin", "duplicate-origin", "missing-fetch", "duplicate-fetch"),
)
def test_missing_or_ambiguous_browser_metadata_fails_closed(
    installed_handler: tuple[type, _Manager, list[Any], list[Any]],
    variant: str,
) -> None:
    handler_type, manager, begin_calls, body_reads = installed_handler
    headers = _headers()
    if variant == "missing-origin":
        del headers["Origin"]
    elif variant == "duplicate-origin":
        headers["Origin"] = BOUND_ORIGIN
    elif variant == "missing-fetch":
        del headers["Sec-Fetch-Site"]
    else:
        headers["Sec-Fetch-Site"] = "same-origin"

    request = _request(
        handler_type,
        "POST",
        "/api/desktop/services/bridge/start",
        headers,
    )

    assert request.responses[0][0] == 403
    assert begin_calls == []
    assert manager.calls == []
    assert body_reads == []


def test_bodyless_form_post_is_refused_before_effect_admission(
    installed_handler: tuple[type, _Manager, list[Any], list[Any]],
) -> None:
    handler_type, manager, begin_calls, body_reads = installed_handler
    request = _request(
        handler_type,
        "POST",
        "/api/desktop/services/bridge/start",
        _headers(
            content_type="application/x-www-form-urlencoded",
            content_length="0",
        ),
    )

    assert request.responses[0][0] == 403
    assert begin_calls == []
    assert manager.calls == []
    assert body_reads == []


@pytest.mark.parametrize(
    ("method", "path", "expected_call"),
    (
        ("PUT", "/api/desktop/settings", "save_settings"),
        ("POST", "/api/desktop/services/bridge/start", "ensure_bridge"),
    ),
)
def test_exact_same_origin_desktop_mutation_reaches_canonical_chain(
    installed_handler: tuple[type, _Manager, list[Any], list[Any]],
    method: str,
    path: str,
    expected_call: str,
) -> None:
    handler_type, manager, begin_calls, body_reads = installed_handler
    request = _request(handler_type, method, path, _headers())

    assert request.responses[0][0] == 200
    assert len(begin_calls) == 1
    assert manager.calls[0][0] == expected_call
    assert len(body_reads) == (1 if method == "PUT" else 0)


def test_shutdown_requires_both_same_origin_metadata_and_parent_nonce(
    installed_handler: tuple[type, _Manager, list[Any], list[Any]],
) -> None:
    handler_type, manager, begin_calls, _ = installed_handler
    wrong = _request(
        handler_type,
        "POST",
        "/api/desktop/shutdown",
        _headers(content_length="0", nonce="x" * 64),
    )
    assert wrong.responses[0][0] == 403
    assert manager.calls == []

    valid = _request(
        handler_type,
        "POST",
        "/api/desktop/shutdown",
        _headers(content_length="0", nonce="n" * 64),
    )
    assert valid.responses[0][0] == 200
    assert manager.calls == [("close", (True, 6.0))]
    assert len(begin_calls) == 2
