"""HTTP acceptance boundary for the bounded Ariadne campaign workbench."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from email.message import Message
from http.server import ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator

import pytest

from daedalus.ariadne import AriadneConflictError, AriadneRequestError
from daedalus.interfaces.http import web_api
from daedalus.spine import effect_boundary


BOUND_HOST = "127.0.0.1"
BOUND_PORT = 8765
BOUND_ORIGIN = f"http://{BOUND_HOST}:{BOUND_PORT}"


@contextmanager
def _server(host: str = "127.0.0.1") -> Iterator[tuple[str, ThreadingHTTPServer]]:
    httpd = ThreadingHTTPServer((host, 0), web_api.DaedalusHandler)
    httpd.daedalus_authority_root = Path.cwd().resolve(strict=True)
    web_api._install_genesis_preview_secret(httpd)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        yield base, httpd
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=10)


def _request_body() -> dict[str, str]:
    return {
        "project": "registered-project",
        "source_revision": "a" * 40,
        "campaign_id": "workbench-repair-1",
        "target_path": "src/example.py",
        "before": "return False",
        "after": "return True",
    }


def _receipt() -> dict[str, Any]:
    return {
        "contract": "daedalus.campaign-receipt",
        "campaign_id": "workbench-repair-1",
        "source_revision": "a" * 40,
        "outcome": "nominated",
        "selected_variant_id": "repair",
        "candidate_tree_sha256": "b" * 64,
        "nomination_receipt_sha256": "c" * 64,
        "negative_outcomes": ["negative-control: failed exact_match"],
        "blockers": [],
        "trials": [
            {"variant_id": "baseline", "status": "failed"},
            {"variant_id": "negative-control", "status": "failed"},
            {"variant_id": "repair", "status": "passed"},
        ],
    }


def _post(
    base: str,
    body: object,
    *,
    raw: bytes | None = None,
    browser_headers: bool = True,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    request_headers = {"Content-Type": "application/json"}
    if browser_headers:
        request_headers.update(
            {"Origin": base, "Sec-Fetch-Site": "same-origin"}
        )
    request_headers.update(headers or {})
    request = urllib.request.Request(
        base + "/api/ariadne",
        data=raw if raw is not None else json.dumps(body).encode("utf-8"),
        method="POST",
        headers=request_headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _direct_post(
    raw: bytes,
    header_pairs: tuple[tuple[str, str], ...],
    *,
    server_host: str = BOUND_HOST,
    client_host: str = BOUND_HOST,
) -> Any:
    headers = Message()
    for name, value in header_pairs:
        headers[name] = value
    handler = object.__new__(web_api.DaedalusHandler)
    handler.path = "/api/ariadne"
    handler.headers = headers
    handler.rfile = BytesIO(raw)
    handler.server = SimpleNamespace(
        daedalus_auth_token="",
        server_address=(server_host, BOUND_PORT),
    )
    handler.client_address = (client_host, 43210)
    handler.close_connection = False
    handler.responses = []
    handler._authorized = lambda: True
    handler._send_json = lambda payload, status=200: handler.responses.append(
        (status, payload)
    )
    handler._handle_post = lambda: pytest.fail(
        "refused request reached the mutation dispatcher"
    )
    handler.do_POST()
    return handler


def test_post_ariadne_resolves_registered_project_and_preserves_idempotent_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    resolved = tmp_path.resolve()
    resolver_calls: list[object] = []
    run_calls: list[dict[str, Any]] = []
    begin_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    events: list[str] = []
    receipt = _receipt()

    def resolve(project: object) -> str:
        events.append("resolve")
        resolver_calls.append(project)
        return str(resolved)

    def run(**kwargs: Any) -> dict[str, Any]:
        events.append("run")
        run_calls.append(kwargs)
        return receipt

    def begin(*args: Any, **kwargs: Any) -> None:
        events.append("begin")
        begin_calls.append((args, kwargs))

    monkeypatch.setattr(web_api, "resolve_registered_project_root", resolve)
    monkeypatch.setattr(web_api, "_run_ariadne_campaign", run)
    monkeypatch.setattr(
        effect_boundary,
        "begin_effect",
        begin,
    )

    with _server() as (base, _):
        first_status, first = _post(base, _request_body())
        second_status, second = _post(base, _request_body())

    assert (first_status, second_status) == (200, 200)
    assert first["ok"] is True
    assert first["project"] == "registered-project"
    assert first["ariadne"] == receipt == second["ariadne"]
    assert resolver_calls == ["registered-project", "registered-project"]
    expected_run = {
        "repo_root": str(resolved),
        "source_revision": "a" * 40,
        "campaign_id": "workbench-repair-1",
        "target_path": "src/example.py",
        "before": "return False",
        "after": "return True",
    }
    assert run_calls == [expected_run, expected_run]
    assert [call[0][0] for call in begin_calls] == [
        "web.mutations",
        "web.mutations",
    ]
    assert events == ["begin", "resolve", "run", "begin", "resolve", "run"]


@pytest.mark.parametrize(
    ("failure", "expected_status", "fragment"),
    (
        (
            AriadneRequestError("target_path is unavailable or unsafe: missing"),
            400,
            "missing",
        ),
        (
            AriadneRequestError("target_path is unavailable or unsafe: symlink"),
            400,
            "symlink",
        ),
        (
            AriadneConflictError("campaign_id was reused with changed repair inputs"),
            409,
            "changed repair inputs",
        ),
        (
            AriadneConflictError("source_revision conflict: stale HEAD"),
            409,
            "stale HEAD",
        ),
    ),
    ids=("missing-target", "symlink-target", "reuse-conflict", "stale-head"),
)
def test_post_ariadne_maps_expected_repository_failures_to_stable_4xx(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure: Exception,
    expected_status: int,
    fragment: str,
) -> None:
    monkeypatch.setattr(
        web_api,
        "resolve_registered_project_root",
        lambda _project: str(tmp_path),
    )

    def refuse(**_kwargs: Any) -> dict[str, Any]:
        raise failure

    monkeypatch.setattr(web_api, "_run_ariadne_campaign", refuse)

    with _server() as (base, _):
        status, payload = _post(base, _request_body())

    assert status == expected_status
    assert payload == {"ok": False, "error": str(failure)}
    assert fragment in payload["error"]


@pytest.mark.parametrize(
    ("body", "fragment"),
    (
        (["not", "an", "object"], "object"),
        (
            {
                key: value
                for key, value in _request_body().items()
                if key != "after"
            },
            "missing Ariadne fields: after",
        ),
        ({**_request_body(), "project": 7}, "project must be a string"),
        ({**_request_body(), "repo_root": "C:/attacker"}, "repo_root"),
        ({**_request_body(), "model": "unsealed"}, "model"),
        ({**_request_body(), "evaluator": "candidate-owned"}, "evaluator"),
        ({**_request_body(), "command": "git push"}, "command"),
        ({**_request_body(), "timeout_s": 999999}, "timeout_s"),
        ({**_request_body(), "promotion": True}, "promotion"),
    ),
)
def test_post_ariadne_rejects_malformed_or_authority_widening_fields_before_effect(
    monkeypatch: pytest.MonkeyPatch,
    body: object,
    fragment: str,
) -> None:
    begin_calls: list[object] = []
    monkeypatch.setattr(
        effect_boundary,
        "begin_effect",
        lambda *args, **kwargs: begin_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        web_api,
        "resolve_registered_project_root",
        lambda *args: pytest.fail("invalid input reached project resolution"),
    )
    monkeypatch.setattr(
        web_api,
        "_run_ariadne_campaign",
        lambda **kwargs: pytest.fail("invalid input reached Ariadne"),
    )

    with _server() as (base, _):
        status, payload = _post(base, body)

    assert status == 400
    assert payload["ok"] is False
    assert fragment in payload["error"]
    assert begin_calls == []


@pytest.mark.parametrize(
    ("raw", "browser_headers", "headers", "expected_status", "fragment"),
    (
        (
            None,
            False,
            {"Sec-Fetch-Site": "same-origin"},
            403,
            "Origin",
        ),
        (
            None,
            False,
            {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
            403,
            "Origin",
        ),
        (
            None,
            False,
            {"Origin": "BOUND_ORIGIN"},
            403,
            "Sec-Fetch-Site",
        ),
        (None, True, {"Sec-Fetch-Site": "same-site"}, 403, "same-origin"),
        (None, True, {"Content-Type": "text/plain"}, 415, "application/json"),
        (b"{not-json", True, {}, 400, "invalid JSON"),
        (
            b"{}",
            True,
            {
                "Content-Length": str(
                    web_api.http_effects.ARIADNE_MAX_BODY_BYTES + 1
                )
            },
            413,
            "exceeds",
        ),
    ),
    ids=(
        "missing-origin",
        "cross-origin",
        "missing-fetch-metadata",
        "same-site-fetch",
        "wrong-content-type",
        "invalid-json",
        "oversized-body",
    ),
)
def test_post_ariadne_rejects_csrf_and_unsafe_body_before_effect(
    monkeypatch: pytest.MonkeyPatch,
    raw: bytes | None,
    browser_headers: bool,
    headers: dict[str, str],
    expected_status: int,
    fragment: str,
) -> None:
    begin_calls: list[object] = []
    monkeypatch.setattr(
        effect_boundary,
        "begin_effect",
        lambda *args, **kwargs: begin_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        web_api,
        "_run_ariadne_campaign",
        lambda **kwargs: pytest.fail("refused request reached Ariadne"),
    )

    request_raw = (
        json.dumps(_request_body()).encode("utf-8") if raw is None else raw
    )
    request_headers = {
        "Content-Type": "application/json",
        "Content-Length": str(len(request_raw)),
    }
    if browser_headers:
        request_headers.update(
            {"Origin": BOUND_ORIGIN, "Sec-Fetch-Site": "same-origin"}
        )
    request_headers.update(
        {
            key: (BOUND_ORIGIN if value == "BOUND_ORIGIN" else value)
            for key, value in headers.items()
        }
    )
    request = _direct_post(request_raw, tuple(request_headers.items()))
    status, payload = request.responses[0]

    assert status == expected_status
    assert payload["ok"] is False
    assert fragment in payload["error"]
    assert begin_calls == []


def test_post_ariadne_rejects_duplicate_origin_before_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    begin_calls: list[object] = []
    monkeypatch.setattr(
        effect_boundary,
        "begin_effect",
        lambda *args, **kwargs: begin_calls.append((args, kwargs)),
    )
    body = json.dumps(_request_body()).encode("utf-8")
    request = _direct_post(
        body,
        (
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body))),
            ("Origin", BOUND_ORIGIN),
            ("Origin", BOUND_ORIGIN),
            ("Sec-Fetch-Site", "same-origin"),
        ),
    )
    status, payload = request.responses[0]

    assert status == 403
    assert "Origin" in payload["error"]
    assert begin_calls == []


def test_post_ariadne_refuses_non_loopback_server_before_body_and_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    begin_calls: list[object] = []
    monkeypatch.setattr(
        effect_boundary,
        "begin_effect",
        lambda *args, **kwargs: begin_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        web_api,
        "_run_ariadne_campaign",
        lambda **kwargs: pytest.fail("remote request reached Ariadne"),
    )

    body = json.dumps(_request_body()).encode("utf-8")
    request = _direct_post(
        body,
        (
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body))),
            ("Origin", BOUND_ORIGIN),
            ("Sec-Fetch-Site", "same-origin"),
        ),
        server_host="0.0.0.0",
    )
    status, payload = request.responses[0]

    assert status == 403
    assert "loopback-only" in payload["error"]
    assert begin_calls == []
    assert request.rfile.tell() == 0


@pytest.mark.parametrize(
    "transport_headers",
    (
        (("Content-Length", "2"), ("Content-Length", "2")),
        (("Content-Length", "2"), ("Transfer-Encoding", "chunked")),
    ),
    ids=("duplicate-content-length", "transfer-encoding"),
)
def test_post_ariadne_rejects_ambiguous_transport_before_effect(
    monkeypatch: pytest.MonkeyPatch,
    transport_headers: tuple[tuple[str, str], ...],
) -> None:
    begin_calls: list[object] = []
    monkeypatch.setattr(
        effect_boundary,
        "begin_effect",
        lambda *args, **kwargs: begin_calls.append((args, kwargs)),
    )

    request = _direct_post(
        b"{}",
        (
            ("Content-Type", "application/json"),
            ("Origin", BOUND_ORIGIN),
            ("Sec-Fetch-Site", "same-origin"),
            *transport_headers,
        ),
    )
    status, payload = request.responses[0]

    assert status == 400
    assert "Content-Length" in payload["error"]
    assert begin_calls == []


def test_post_ariadne_rejects_duplicate_json_field_before_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    begin_calls: list[object] = []
    monkeypatch.setattr(
        effect_boundary,
        "begin_effect",
        lambda *args, **kwargs: begin_calls.append((args, kwargs)),
    )
    raw = json.dumps(_request_body()).replace(
        '"project": "registered-project"',
        '"project": "registered-project", "project": "other"',
        1,
    ).encode("utf-8")

    with _server() as (base, _):
        status, payload = _post(base, None, raw=raw)

    assert status == 400
    assert "duplicate JSON field" in payload["error"]
    assert begin_calls == []
