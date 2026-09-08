from __future__ import annotations

import json
import io
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from contextlib import contextmanager
from email.message import Message
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Iterator

import pytest

from daedalus.interfaces.http import web_api
from daedalus.interfaces.cli import entry
from daedalus.orchestration.genesis import (
    GenesisConflictError,
    GenesisPreviewError,
)
from daedalus.spine import effect_boundary


_SOURCE_RUN = "genesis-1234567890abcdef12345678"
_SOURCE_DIGEST = "a" * 64
_SOURCE_PATH = f"/api/genesis/{_SOURCE_RUN}/source.zip"
_SOURCE_QUERY = f"?candidate_sha256={_SOURCE_DIGEST}"


def _source_response(
    httpd: ThreadingHTTPServer,
    *,
    path: str = _SOURCE_PATH + _SOURCE_QUERY,
    headers: list[tuple[str, str]] | None = None,
) -> tuple[int, Message, bytes]:
    connection = HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=30)
    try:
        connection.putrequest("GET", path, skip_host=True)
        for key, value in headers if headers is not None else [
            ("Host", f"127.0.0.1:{httpd.server_address[1]}"),
            ("Sec-Fetch-Site", "same-origin"),
        ]:
            connection.putheader(key, value)
        connection.endheaders()
        response = connection.getresponse()
        return response.status, response.headers, response.read()
    finally:
        connection.close()


def test_genesis_source_download_binds_archive_to_server_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from daedalus.orchestration import genesis

    calls = []

    def archive(run_id: str, candidate_sha256: str, *, repo_root: Path) -> bytes:
        calls.append((run_id, candidate_sha256, repo_root))
        return b"archive-bytes"

    monkeypatch.setattr(genesis, "read_genesis_source_archive", archive)
    with _server(authority_root=tmp_path) as (_, httpd):
        status, headers, body = _source_response(httpd)
    assert status == 200
    assert body == b"archive-bytes"
    assert calls == [(_SOURCE_RUN, _SOURCE_DIGEST, tmp_path.resolve())]
    assert headers["Content-Type"] == "application/zip"
    assert headers["Content-Length"] == str(len(body))
    assert headers["Content-Disposition"] == f'attachment; filename="{_SOURCE_RUN}-source.zip"'
    assert headers["X-Daedalus-Candidate-Sha256"] == _SOURCE_DIGEST
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Cross-Origin-Resource-Policy"] == "same-origin"
    assert headers["Cache-Control"] == "private, no-store"
    assert headers["Content-Security-Policy"] == "default-src 'none'; sandbox"
    assert headers["Access-Control-Allow-Origin"] is None


@pytest.mark.parametrize("case", [
    "foreign-host", "duplicate-host", "cross-site", "same-site", "none",
    "missing-fetch", "duplicate-fetch", "foreign-origin", "null-origin",
    "duplicate-origin", "remote-bind",
])
def test_genesis_source_download_refuses_foreign_or_ambiguous_browser_context(
    case: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        web_api.DaedalusHandler, "_read_genesis_source_archive",
        lambda *args: pytest.fail("refused request read source CAS"),
    )
    with _server("0.0.0.0" if case == "remote-bind" else "127.0.0.1") as (base, httpd):
        host = f"127.0.0.1:{httpd.server_address[1]}"
        headers = [("Host", host), ("Sec-Fetch-Site", "same-origin")]
        if case == "foreign-host":
            headers[0] = ("Host", "attacker.example")
        elif case == "duplicate-host":
            headers.append(("Host", host))
        elif case in {"cross-site", "same-site", "none"}:
            headers[1] = ("Sec-Fetch-Site", case)
        elif case == "missing-fetch":
            headers.pop()
        elif case == "duplicate-fetch":
            headers.append(("Sec-Fetch-Site", "same-origin"))
        elif case == "foreign-origin":
            headers.append(("Origin", "https://attacker.example"))
        elif case == "null-origin":
            headers.append(("Origin", "null"))
        elif case == "duplicate-origin":
            headers.extend([("Origin", base), ("Origin", base)])
        status, response_headers, body = _source_response(httpd, headers=headers)
    assert status == 403
    assert json.loads(body)["ok"] is False
    assert response_headers["Access-Control-Allow-Origin"] is None


@pytest.mark.parametrize("query", [
    "", "?candidate_sha256=", "?candidate_sha256=bad",
    "?candidate_sha256=" + "A" * 64,
    _SOURCE_QUERY + "&candidate_sha256=" + _SOURCE_DIGEST,
    _SOURCE_QUERY + "&candidate_sha256=",
    _SOURCE_QUERY + "&unknown=", _SOURCE_QUERY + "&unknown=value",
    _SOURCE_QUERY + "#fragment", _SOURCE_QUERY + "&",
    "?candidate_sha256=%61" + "a" * 63,
])
def test_genesis_source_download_requires_one_canonical_candidate_query(
    query: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        web_api.DaedalusHandler, "_read_genesis_source_archive",
        lambda *args: pytest.fail("invalid query read source CAS"),
    )
    with _server() as (_, httpd):
        status, _, body = _source_response(httpd, path=_SOURCE_PATH + query)
    assert status == 400
    assert "candidate_sha256" in json.loads(body)["error"]


@pytest.mark.parametrize("run_id", ["invalid", "genesis-" + "A" * 24, "%67" + _SOURCE_RUN[1:]])
def test_genesis_source_download_rejects_noncanonical_run_ids(
    run_id: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        web_api.DaedalusHandler, "_read_genesis_source_archive",
        lambda *args: pytest.fail("invalid run read source CAS"),
    )
    with _server() as (_, httpd):
        status, _, _ = _source_response(
            httpd, path=f"/api/genesis/{run_id}/source.zip{_SOURCE_QUERY}",
        )
    assert status == 404


def test_genesis_source_download_exposes_verification_failure_without_partial_zip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject(*args: object) -> bytes:
        raise GenesisPreviewError("candidate evidence is unavailable")

    monkeypatch.setattr(web_api.DaedalusHandler, "_read_genesis_source_archive", reject)
    with _server() as (_, httpd):
        status, headers, body = _source_response(httpd)
    assert status == 404
    assert headers["Content-Disposition"] is None
    assert json.loads(body)["error"] == "candidate evidence is unavailable"


def test_genesis_source_download_real_candidate_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from daedalus.orchestration.genesis import run_genesis
    from hashlib import sha256

    monkeypatch.setenv("DAEDALUS_KILLSWITCH", str(tmp_path / "control" / "killswitch"))
    authority = tmp_path / "authority"
    authority.mkdir()
    result = run_genesis(
        "Build a local kanban board with search",
        request_key="genesis:http-source-download",
        repo_root=authority,
    )
    assert result["status"] == "preview-ready", result.get("blockers")
    digest = result["candidate"]["sha256"]
    with _server(authority_root=authority) as (_, httpd):
        status, headers, body = _source_response(
            httpd,
            path=f'/api/genesis/{result["run_id"]}/source.zip?candidate_sha256={digest}',
        )
    assert status == 200
    assert headers["X-Daedalus-Candidate-Sha256"] == digest
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        manifest = archive.read("source-tree.json")
        assert sha256(manifest).hexdigest() == digest
        for entry in json.loads(manifest)["entries"]:
            source = archive.read("source/" + entry["path"])
            assert len(source) == entry["size"]
            assert sha256(source).hexdigest() == entry["blob_sha256"]
        assert json.loads(archive.read("genesis-run.json")) == result


@contextmanager
def _server(
    host: str = "127.0.0.1",
    *,
    authority_root: Path | None = None,
) -> Iterator[tuple[str, ThreadingHTTPServer]]:
    httpd = ThreadingHTTPServer((host, 0), web_api.DaedalusHandler)
    httpd.daedalus_authority_root = (authority_root or Path.cwd()).resolve(
        strict=True
    )
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


def _preview_request(
    base: str,
    path: str,
    *,
    fetch_site: str = "same-origin",
    headers: dict[str, str] | None = None,
) -> urllib.request.Request:
    request_headers = {"Sec-Fetch-Site": fetch_site}
    request_headers.update(headers or {})
    return urllib.request.Request(base + path, headers=request_headers)


def _post_response(
    base: str,
    body: object,
    *,
    raw: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict, Message]:
    request_headers = {"Content-Type": "application/json"}
    request_headers.update(headers or {})
    request = urllib.request.Request(
        base + "/api/genesis",
        data=raw if raw is not None else json.dumps(body).encode("utf-8"),
        method="POST",
        headers=request_headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read()), response.headers
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read()), exc.headers


def _post(
    base: str,
    body: object,
    *,
    raw: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict]:
    status, payload, _ = _post_response(base, body, raw=raw, headers=headers)
    return status, payload


def _green_result() -> dict:
    return {
        "run_id": "genesis-1234567890abcdef12345678",
        "request_key": "browser-retry-1",
        "status": "preview-ready",
        "target": "web",
        "defaults": {"base_repository": None},
        "blockers": [],
        "mission": {"mission_id": "mission-1234567890abcdef12345678"},
        "candidate": {"sha256": "a" * 64},
        "evidence": {"sha256": "b" * 64},
        "roundtrip": {"sha256": "c" * 64},
        "preview": {
            "kind": "read-only-cas-preview",
            "path": "/api/genesis/genesis-1234567890abcdef12345678/preview/",
        },
        "artifacts": {},
        "publication": {
            "status": "not-requested",
            "owner_approval_required": True,
            "automatic_promotion": False,
        },
    }


def test_post_genesis_forwards_strict_request_and_mints_server_loopback_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, dict]] = []

    def run(prompt: object, **kwargs: object) -> dict:
        calls.append((prompt, kwargs))
        return _green_result()

    monkeypatch.setattr(web_api, "run_genesis", run)
    with _server() as (base, httpd):
        status, payload = _post(
            base,
            {
                "prompt": "Build a local maintenance planner",
                "target": "web",
                "stack": "python-stdlib-pwa",
                "request_key": "browser-retry-1",
            },
        )

    assert status == 200
    assert payload["ok"] is True
    assert calls == [
        (
            "Build a local maintenance planner",
            {
                "target": "web",
                "stack": "python-stdlib-pwa",
                "request_key": "browser-retry-1",
                "repo_root": httpd.daedalus_authority_root,
            },
        )
    ]
    assert payload["genesis"]["preview"]["url"] == (
        f"http://127.0.0.1:{httpd.server_address[1]}"
        "/api/genesis/genesis-1234567890abcdef12345678/preview/"
    )
    assert payload["genesis"]["publication"]["automatic_promotion"] is False


def test_post_genesis_uses_the_exact_bound_numeric_loopback_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(web_api, "run_genesis", lambda *args, **kwargs: _green_result())
    body = json.dumps(
        {"prompt": "Build a local task board", "request_key": "loopback-two"}
    ).encode("utf-8")
    with _server("127.0.0.2") as (_, httpd):
        connection = HTTPConnection("127.0.0.2", httpd.server_address[1], timeout=30)
        try:
            connection.request(
                "POST",
                "/api/genesis",
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body)),
                },
            )
            response = connection.getresponse()
            payload = json.loads(response.read())
        finally:
            connection.close()

    assert response.status == 200
    assert payload["genesis"]["preview"]["url"] == (
        f"http://127.0.0.2:{httpd.server_address[1]}"
        "/api/genesis/genesis-1234567890abcdef12345678/preview/"
    )


@pytest.mark.parametrize(
    "body, fragment",
    [
        (["not", "an", "object"], "object"),
        ({"request_key": "key"}, "prompt"),
        ({"prompt": "idea"}, "request_key"),
        ({"prompt": 7, "request_key": "key"}, "prompt"),
        ({"prompt": "idea", "request_key": "key", "target": 7}, "target"),
        ({"prompt": "idea", "request_key": "key", "publish": True}, "publish"),
    ],
)
def test_post_genesis_rejects_malformed_or_expansive_input(
    monkeypatch: pytest.MonkeyPatch, body: object, fragment: str
) -> None:
    monkeypatch.setattr(
        web_api,
        "run_genesis",
        lambda *args, **kwargs: pytest.fail("invalid input reached Genesis"),
    )
    with _server() as (base, _):
        status, payload = _post(base, body)
    assert status == 400
    assert payload["ok"] is False
    assert fragment in payload["error"]


def test_post_genesis_maps_invalid_json_and_idempotency_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _server() as (base, _):
        status, payload = _post(base, None, raw=b"{not-json")
    assert status == 400
    assert "invalid JSON" in payload["error"]

    def conflict(*args: object, **kwargs: object) -> dict:
        raise GenesisConflictError("request key already belongs to another intent")

    monkeypatch.setattr(web_api, "run_genesis", conflict)
    with _server() as (base, _):
        status, payload = _post(
            base, {"prompt": "idea", "request_key": "reused"}
        )
    assert status == 409
    assert payload["ok"] is False
    assert "another intent" in payload["error"]


@pytest.mark.parametrize(
    ("headers", "raw", "expected_status", "fragment"),
    (
        ({"Content-Type": "text/plain"}, b"{}", 415, "application/json"),
        (
            {"Content-Length": str(web_api.http_effects.GENESIS_MAX_BODY_BYTES + 1)},
            b"{}",
            413,
            "exceeds",
        ),
        ({"Content-Length": "-1"}, b"{}", 400, "decimal integer"),
    ),
)
def test_post_genesis_rejects_unsafe_body_metadata_before_the_effect(
    monkeypatch: pytest.MonkeyPatch,
    headers: dict[str, str],
    raw: bytes,
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
        "run_genesis",
        lambda *args, **kwargs: pytest.fail("unsafe body reached Genesis"),
    )
    with _server() as (base, _):
        status, payload = _post(base, None, raw=raw, headers=headers)

    assert status == expected_status
    assert payload["ok"] is False
    assert fragment in payload["error"]
    assert begin_calls == []


def test_post_genesis_rejects_cross_origin_and_never_grants_cors_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        web_api,
        "run_genesis",
        lambda *args, **kwargs: pytest.fail("cross-origin request reached Genesis"),
    )
    with _server() as (base, _):
        status, payload, response_headers = _post_response(
            base,
            {"prompt": "Build a local task list", "request_key": "evil-origin"},
            headers={"Origin": "https://evil.example"},
        )
        preflight = urllib.request.Request(
            base + "/api/genesis",
            method="OPTIONS",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
        with urllib.request.urlopen(preflight, timeout=30) as response:
            assert response.status == 204
            assert response.headers.get("Access-Control-Allow-Origin") is None

    assert status == 403
    assert payload["ok"] is False
    assert "cross-origin" in payload["error"]
    assert response_headers.get("Access-Control-Allow-Origin") is None


def test_post_genesis_accepts_an_exact_same_origin_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def run(*args: object, **kwargs: object) -> dict:
        nonlocal calls
        calls += 1
        return _green_result()

    monkeypatch.setattr(web_api, "run_genesis", run)
    with _server() as (base, _):
        status, payload = _post(
            base,
            {"prompt": "Build a local task list", "request_key": "same-origin"},
            headers={"Origin": base},
        )

    assert status == 200
    assert payload["ok"] is True
    assert calls == 1


def test_post_genesis_refuses_a_non_loopback_server_bind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        web_api,
        "run_genesis",
        lambda *args, **kwargs: pytest.fail("remote request reached Genesis"),
    )
    with _server("0.0.0.0") as (base, _):
        status, payload = _post(
            base, {"prompt": "idea", "request_key": "remote"}
        )
    assert status == 403
    assert payload["ok"] is False
    assert "loopback-only" in payload["error"]


def test_get_genesis_preview_returns_raw_cas_bytes_and_browser_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, Path]] = []

    def preview(
        run_id: str, relative_path: str, *, repo_root: Path
    ) -> tuple[bytes, str]:
        calls.append((run_id, relative_path, repo_root))
        return b"console.log('green')", "application/javascript; charset=utf-8"

    monkeypatch.setattr(web_api, "read_genesis_preview", preview)
    path = "/api/genesis/genesis-1234567890abcdef12345678/preview/app.js"
    with _server() as (base, httpd):
        poisoned_host = urllib.request.Request(
            base + path,
            headers={
                "Host": "attacker.invalid",
                "Sec-Fetch-Site": "same-origin",
            },
        )
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(poisoned_host, timeout=30)
        assert refused.value.code == 403
        assert refused.value.headers["X-Content-Type-Options"] == "nosniff"
        assert "numeric bound Host" in json.loads(refused.value.read())["error"]
        assert calls == []

        with urllib.request.urlopen(
            _preview_request(base, path), timeout=30
        ) as response:
            assert response.status == 200
            assert response.read() == b"console.log('green')"
            assert response.headers["Content-Type"] == (
                "application/javascript; charset=utf-8"
            )
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert response.headers["Referrer-Policy"] == "no-referrer"
            csp = response.headers["Content-Security-Policy"]
            preview_origin = f"http://127.0.0.1:{httpd.server_address[1]}"
            final_path = urllib.parse.urlsplit(response.geturl()).path
            assert re.fullmatch(
                r"/api/genesis/genesis-[0-9a-f]{24}/preview/"
                r"~cap-[0-9a-f]{64}/app\.js",
                final_path,
            )
            preview_scope = f"{preview_origin}{final_path.rsplit('/', 1)[0]}/"
            assert "default-src 'none'" in csp
            assert f"script-src {preview_scope};" in csp
            assert f"style-src {preview_scope};" in csp
            assert f"img-src {preview_scope} data:" in csp
            assert "genesis-ffffffffffffffffffffffff" not in csp
            assert "script-src 'self'" not in csp
            assert "style-src 'self'" not in csp
            assert "connect-src 'none'" in csp
            assert "worker-src 'none'" in csp
            assert "object-src 'none'" in csp
            assert "form-action 'none'" in csp
            assert "frame-ancestors 'self'" in csp
            assert "frame-ancestors http:" not in csp
            assert "sandbox allow-scripts allow-forms" in csp
    assert calls == [
        (
            "genesis-1234567890abcdef12345678",
            "app.js",
            httpd.daedalus_authority_root,
        )
    ]


def test_preview_cross_site_cannot_mint_capability_or_reach_cas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        web_api,
        "read_genesis_preview",
        lambda *args, **kwargs: pytest.fail("cross-site request reached preview CAS"),
    )
    run = "genesis-1234567890abcdef12345678"
    path = f"/api/genesis/{run}/preview/app.js"
    with _server() as (base, _):
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(
                _preview_request(base, path, fetch_site="cross-site"),
                timeout=30,
            )
        assert refused.value.code == 403
        assert refused.value.headers["X-Content-Type-Options"] == "nosniff"
        assert "cross-origin" in json.loads(refused.value.read())["error"]


def test_preview_same_site_other_port_cannot_mint_capability_or_reach_cas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        web_api,
        "read_genesis_preview",
        lambda *args, **kwargs: pytest.fail("same-site request reached preview CAS"),
    )
    run = "genesis-1234567890abcdef12345678"
    path = f"/api/genesis/{run}/preview/app.js"
    with _server() as (base, _):
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(
                _preview_request(base, path, fetch_site="same-site"),
                timeout=30,
            )
        assert refused.value.code == 403
        assert refused.value.headers["Location"] is None
        assert refused.value.headers["X-Content-Type-Options"] == "nosniff"
        assert "cross-origin" in json.loads(refused.value.read())["error"]


def test_preview_requires_exact_bound_authority_and_fetch_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        web_api,
        "read_genesis_preview",
        lambda *args, **kwargs: pytest.fail("inadmissible request reached preview CAS"),
    )
    run = "genesis-1234567890abcdef12345678"
    path = f"/api/genesis/{run}/preview/app.js"
    with _server() as (base, httpd):
        port = int(httpd.server_address[1])
        requests = (
            urllib.request.Request(
                base + path,
                headers={
                    "Host": f"localhost:{port}",
                    "Sec-Fetch-Site": "same-origin",
                },
            ),
            urllib.request.Request(
                base + path,
                headers={
                    "Host": f"127.0.0.1:{port + 1}",
                    "Sec-Fetch-Site": "same-origin",
                },
            ),
            urllib.request.Request(base + path),
            _preview_request(base, path, fetch_site="invalid"),
        )
        for request in requests:
            with pytest.raises(urllib.error.HTTPError) as refused:
                urllib.request.urlopen(request, timeout=30)
            assert refused.value.code == 403
            assert refused.value.headers["X-Content-Type-Options"] == "nosniff"


def test_preview_capability_is_server_and_run_bound_but_allows_opaque_assets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    def preview(
        run_id: str, relative_path: str, *, repo_root: Path
    ) -> tuple[bytes, str]:
        del repo_root
        calls.append((run_id, relative_path))
        return b"asset", "application/javascript; charset=utf-8"

    monkeypatch.setattr(web_api, "read_genesis_preview", preview)
    run = "genesis-1234567890abcdef12345678"
    root = f"/api/genesis/{run}/preview/"
    with _server() as (base, _):
        with urllib.request.urlopen(
            _preview_request(base, root), timeout=30
        ) as response:
            capability_url = response.geturl()
            assert response.status == 200
        capability_path = urllib.parse.urlsplit(capability_url).path
        assert re.fullmatch(
            rf"/api/genesis/{run}/preview/~cap-[0-9a-f]{{64}}/",
            capability_path,
        )

        # A sandboxed iframe has an opaque origin. Chromium may therefore mark
        # its relative subresources cross-site; the unguessable bearer path is
        # what admits those assets without relying on CORP.
        asset_url = urllib.parse.urljoin(capability_url, "app.js")
        asset_path = urllib.parse.urlsplit(asset_url).path
        with urllib.request.urlopen(
            _preview_request(base, asset_path, fetch_site="cross-site"),
            timeout=30,
        ) as response:
            assert response.status == 200
            assert response.read() == b"asset"

        other_run_path = asset_path.replace(
            run, "genesis-ffffffffffffffffffffffff", 1
        )
        with pytest.raises(urllib.error.HTTPError) as wrong_run:
            urllib.request.urlopen(
                _preview_request(base, other_run_path, fetch_site="cross-site"),
                timeout=30,
            )
        assert wrong_run.value.code == 404

        token_match = re.search(r"~cap-([0-9a-f]{64})", asset_path)
        assert token_match is not None
        token = token_match.group(1)
        replacement = ("0" if token[0] != "0" else "1") + token[1:]
        forged_path = asset_path.replace(token, replacement, 1)
        with pytest.raises(urllib.error.HTTPError) as forged:
            urllib.request.urlopen(
                _preview_request(base, forged_path, fetch_site="cross-site"),
                timeout=30,
            )
        assert forged.value.code == 404

    with _server() as (other_base, _):
        with pytest.raises(urllib.error.HTTPError) as wrong_server:
            urllib.request.urlopen(
                _preview_request(
                    other_base, asset_path, fetch_site="cross-site"
                ),
                timeout=30,
            )
        assert wrong_server.value.code == 404

    assert calls == [(run, ""), (run, "app.js")]


def test_get_genesis_preview_refuses_a_non_loopback_server_bind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        web_api,
        "read_genesis_preview",
        lambda *args, **kwargs: pytest.fail("remote request reached Genesis preview"),
    )
    run = "genesis-1234567890abcdef12345678"
    with _server("0.0.0.0") as (base, _):
        request = f"{base}/api/genesis/{run}/preview/"
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=30)
        assert caught.value.code == 403
        assert "loopback-only" in json.loads(caught.value.read())["error"]


def test_get_genesis_preview_maps_missing_and_unsafe_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def preview(
        run_id: str, relative_path: str, *, repo_root: Path
    ) -> tuple[bytes, str]:
        if ".." in relative_path:
            raise GenesisPreviewError("preview path is not safe")
        raise GenesisPreviewError("preview file does not exist")

    monkeypatch.setattr(web_api, "read_genesis_preview", preview)
    run = "genesis-1234567890abcdef12345678"
    with _server() as (base, _):
        missing = f"/api/genesis/{run}/preview/missing.js"
        try:
            urllib.request.urlopen(_preview_request(base, missing), timeout=30)
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
            assert "does not exist" in json.loads(exc.read())["error"]

        traversal = urllib.parse.quote("../secret", safe="")
        unsafe = f"/api/genesis/{run}/preview/{traversal}"
        try:
            urllib.request.urlopen(_preview_request(base, unsafe), timeout=30)
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
            assert "not safe" in json.loads(exc.read())["error"]


def test_cli_build_and_web_preview_share_invocation_authority_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authority_root = tmp_path / "authority"
    authority_root.mkdir()
    monkeypatch.chdir(authority_root)
    monkeypatch.setenv(
        "DAEDALUS_KILLSWITCH",
        str(tmp_path / "control" / "killswitch"),
    )

    assert entry._genesis(
        [
            "Build a local task board with search",
            "--target",
            "web",
            "--request-key",
            "genesis:http-cli-authority-coherence",
            "--json",
        ]
    ) == 0
    cli_result = json.loads(capsys.readouterr().out)["genesis"]
    preview_path = cli_result["preview"]["path"]

    with _server(authority_root=authority_root) as (base, _):
        with urllib.request.urlopen(
            _preview_request(base, preview_path, fetch_site="none"), timeout=30
        ) as response:
            assert response.status == 200
            assert b"<!doctype html>" in response.read()


def test_web_server_freezes_invocation_cwd_as_genesis_authority_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class Server:
        def __init__(self, address: object, handler: object) -> None:
            observed["bound"] = (address, handler)

        def serve_forever(self) -> None:
            observed["authority_root"] = self.daedalus_authority_root

        def server_close(self) -> None:
            observed["closed"] = True

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(web_api, "load_env", lambda: None)
    monkeypatch.setattr(web_api, "_resolve_bind", lambda *_args: "")
    monkeypatch.setattr(web_api, "_desktop_startup_nonce", lambda: "")
    monkeypatch.setattr(web_api, "ThreadingHTTPServer", Server)

    web_api.run("127.0.0.1", 9876)

    assert observed == {
        "bound": (("127.0.0.1", 9876), web_api.DaedalusHandler),
        "authority_root": tmp_path.resolve(),
        "closed": True,
    }


@pytest.mark.parametrize("delivery", ["archive", "preview"])
def test_genesis_delivery_reads_existing_uncheckpointed_wal_without_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, delivery: str,
) -> None:
    """A live web ledger must not hide its committed candidate in the WAL."""
    import hashlib
    import sqlite3
    from daedalus.kernel.attempt_ledger import AttemptLedger
    from daedalus.kernel.source_trees import SourceTreeStore
    from daedalus.orchestration.genesis import service
    from daedalus.spine.ledger import SpineLedger

    authority = tmp_path / "authority"
    authority.mkdir()
    database = authority / "runs" / "spine" / "spine.sqlite3"
    monkeypatch.setenv("DAEDALUS_SPINE_DB", str(database))
    monkeypatch.setenv("DAEDALUS_KILLSWITCH", str(tmp_path / "control" / "killswitch"))
    keeper = SpineLedger(database)
    keeper._conn.execute("PRAGMA wal_autocheckpoint=0")
    try:
        result = service.run_genesis(
            "Build a local task board with search",
            request_key=f"genesis:http-live-wal:{delivery}", repo_root=authority,
        )
        assert result["status"] == "preview-ready", result.get("blockers")
        digest = result["candidate"]["sha256"]
        wal = Path(str(database) + "-wal")
        shm = Path(str(database) + "-shm")
        assert wal.is_file() and wal.stat().st_size > 32 and shm.is_file()
        # The schema itself remains in the WAL, reproducing the fresh server
        # failure independently of whether a particular row was checkpointed.
        frozen = sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True)
        try:
            assert frozen.execute("SELECT name FROM sqlite_master WHERE name='intents'").fetchall() == []
        finally:
            frozen.close()
        before_db = database.read_bytes()
        before_wal = wal.read_bytes()
        before_files = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()}
        statements = []
        original_connect = sqlite3.connect

        def read_connection(path, *args, **kwargs):
            assert "mode=ro" in str(path), "delivery attempted a writable SQLite open"
            connection = original_connect(path, *args, **kwargs)
            connection.set_trace_callback(statements.append)
            return connection

        def forbidden(*args, **kwargs):
            pytest.fail("delivery attempted writer construction, initialization or execution")

        monkeypatch.setattr(sqlite3, "connect", read_connection)
        monkeypatch.setattr(SpineLedger, "__init__", forbidden)
        monkeypatch.setattr(AttemptLedger, "__init__", forbidden)
        monkeypatch.setattr(SourceTreeStore, "__init__", forbidden)
        monkeypatch.setattr(service, "acquire_effect_lease", forbidden)
        monkeypatch.setattr(service, "_ensure_genesis_switch", forbidden)
        monkeypatch.setattr(service, "_run_command", forbidden)
        with _server(authority_root=authority) as (_, httpd):
            if delivery == "archive":
                path = f'/api/genesis/{result["run_id"]}/source.zip?candidate_sha256={digest}'
            else:
                cap = web_api._genesis_preview_capability(httpd, result["run_id"])
                path = f'/api/genesis/{result["run_id"]}/preview/~cap-{cap}/index.html'
            status, headers, body = _source_response(httpd, path=path)
        assert status == 200, body.decode("utf-8", errors="replace")
        if delivery == "archive":
            assert headers["X-Daedalus-Candidate-Sha256"] == digest
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                manifest = archive.read("source-tree.json")
                assert hashlib.sha256(manifest).hexdigest() == digest
                for entry in json.loads(manifest)["entries"]:
                    source = archive.read("source/" + entry["path"])
                    assert hashlib.sha256(source).hexdigest() == entry["blob_sha256"]
        else:
            assert headers["Content-Type"].startswith("text/html")
            store = SourceTreeStore.open_existing(service.control_root(authority) / "genesis" / "source-cas")
            manifest = store.load_tree(service.ArtifactRef.from_sha256(digest))
            entry = next(row for row in manifest.entries if row.path == "index.html")
            assert body == store.read_bytes(service.ArtifactRef.from_sha256(entry.blob_sha256), max_bytes=entry.size)
        assert database.read_bytes() == before_db
        assert wal.read_bytes() == before_wal
        assert {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()} == before_files
        assert statements and any(sql.upper() == "BEGIN" for sql in statements)
        assert all(sql.lstrip().split()[0].upper() in {"SELECT", "PRAGMA", "BEGIN"} for sql in statements)
        assert all("checkpoint" not in sql.lower() for sql in statements)
        # Existing SHM state may change through SQLite bookkeeping, including
        # first-reader reconstruction. Durable DB/WAL contents stay unchanged;
        # the stable keeper/pair in this test also preserves the file set.
    finally:
        keeper.close()
