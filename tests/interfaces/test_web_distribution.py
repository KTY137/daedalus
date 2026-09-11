from __future__ import annotations

import json
from pathlib import Path

import pytest

from daedalus.interfaces.http import web_api


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIST = ROOT / "apps" / "web" / "dist"
PACKAGE_DIST = ROOT / "daedalus" / "resources" / "web_dist"
PACKAGE_JSON = ROOT / "apps" / "web" / "package.json"
RETIRED_SYNC_SCRIPT = (
    ROOT / "apps" / "web" / "scripts" / "sync-python-web-dist.mjs"
)


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _serve_static(monkeypatch: pytest.MonkeyPatch, root: Path, path: str) -> dict:
    captured: dict = {}
    handler = object.__new__(web_api.DaedalusHandler)
    handler._send_response_bytes = lambda body, **kwargs: captured.update(
        body=body, **kwargs
    )
    monkeypatch.setattr(web_api, "WEB_DIST", root)
    handler._send_static(path)
    return captured


def test_source_web_dist_precedes_package_fallback(tmp_path: Path) -> None:
    source = tmp_path / "source"
    package = tmp_path / "package"
    source.mkdir()
    package.mkdir()
    (source / "index.html").write_text("source", encoding="utf-8")
    (package / "index.html").write_text("package", encoding="utf-8")

    assert web_api._resolve_web_dist(source, package) == source


def test_package_web_dist_is_used_without_a_source_build(tmp_path: Path) -> None:
    source = tmp_path / "missing-source"
    package = tmp_path / "package"
    package.mkdir()
    (package / "index.html").write_text("package", encoding="utf-8")

    assert web_api._resolve_web_dist(source, package) == package


def test_committed_package_copy_is_an_exact_recursive_mirror() -> None:
    source_files = _files(SOURCE_DIST)
    package_files = _files(PACKAGE_DIST)

    assert "index.html" in source_files
    assert any(name.startswith("assets/") for name in source_files)
    assert package_files == source_files


def test_normal_web_build_has_no_unregistered_distribution_writer() -> None:
    package = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))

    assert "postbuild" not in package["scripts"]
    assert not RETIRED_SYNC_SCRIPT.exists()


def test_static_unknown_route_keeps_spa_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "index.html").write_text("agent-os", encoding="utf-8")

    response = _serve_static(monkeypatch, tmp_path, "/genesis/new")

    assert response["body"] == b"agent-os"
    assert response.get("status", 200) == 200


@pytest.mark.parametrize("path", ("/../outside.txt", "/%2e%2e/outside.txt"))
def test_static_traversal_is_not_served(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    web_dist = tmp_path / "web-dist"
    web_dist.mkdir()
    (web_dist / "index.html").write_text("agent-os", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("secret", encoding="utf-8")

    response = _serve_static(monkeypatch, web_dist, path)

    assert response["status"] == 404
    assert response["body"] == b"Not Found\n"
    assert b"secret" not in response["body"]


def test_encoded_static_traversal_is_blocked_through_get_router(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    web_dist = tmp_path / "web-dist"
    web_dist.mkdir()
    (web_dist / "index.html").write_text("agent-os", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("secret", encoding="utf-8")
    handler = object.__new__(web_api.DaedalusHandler)
    handler.path = "/%2e%2e/outside.txt"
    captured: dict = {}
    handler._send_response_bytes = lambda body, **kwargs: captured.update(
        body=body, **kwargs
    )
    monkeypatch.setattr(web_api, "WEB_DIST", web_dist)

    handler._handle_get()

    assert captured["status"] == 404
    assert captured["body"] == b"Not Found\n"


def test_static_symlink_escape_is_not_served(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    web_dist = tmp_path / "web-dist"
    web_dist.mkdir()
    (web_dist / "index.html").write_text("agent-os", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = web_dist / "linked.txt"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"host cannot create a test symlink/reparse point: {exc}")

    response = _serve_static(monkeypatch, web_dist, "/linked.txt")

    assert response["status"] == 404
    assert response["body"] == b"Not Found\n"
    assert b"secret" not in response["body"]
