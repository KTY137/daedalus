from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from daedalus import projects, web_api


@pytest.fixture
def project_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    registry = tmp_path / "projects"
    monkeypatch.setattr(projects, "PROJECT_DIR", registry)
    return registry


def test_registration_writes_only_canonical_minimal_config(
    tmp_path: Path, project_registry: Path,
) -> None:
    repo = tmp_path / "My Repository"
    repo.mkdir()

    result = projects.register_project(str(repo / ".." / repo.name))

    assert result == {
        "name": "my-repository",
        "repo_root": str(repo.resolve()),
        "created": True,
    }
    config = json.loads((project_registry / "my-repository.json").read_text("utf-8"))
    assert config == {"name": "my-repository", "repo_root": str(repo.resolve())}
    assert "policy" not in config
    assert "team" not in config


def test_same_canonical_path_is_idempotent_even_with_a_different_name(
    tmp_path: Path, project_registry: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    first = projects.register_project(repo, "first")
    before = (project_registry / "first.json").read_bytes()

    second = projects.register_project(repo / ".", "renamed")

    assert first["created"] is True
    assert second == {
        "name": "first",
        "repo_root": str(repo.resolve()),
        "created": False,
    }
    assert (project_registry / "first.json").read_bytes() == before
    assert not (project_registry / "renamed.json").exists()


@pytest.mark.parametrize("name", ["../escape", r"folder\\escape", ".", "..", ""])
def test_registration_refuses_traversal_names(
    name: str, tmp_path: Path, project_registry: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(projects.ProjectRegistrationError):
        projects.register_project(repo, name)

    assert not project_registry.exists()


def test_registration_refuses_missing_roots_and_files(
    tmp_path: Path, project_registry: Path,
) -> None:
    file_root = tmp_path / "file.txt"
    file_root.write_text("not a directory", encoding="utf-8")

    with pytest.raises(projects.ProjectRegistrationError, match="does not exist"):
        projects.register_project(tmp_path / "missing")
    with pytest.raises(projects.ProjectRegistrationError, match="not a directory"):
        projects.register_project(file_root)

    assert not project_registry.exists()


def test_explicit_name_collision_never_overwrites_existing_project(
    tmp_path: Path, project_registry: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    projects.register_project(first, "shared")
    before = (project_registry / "shared.json").read_bytes()

    with pytest.raises(projects.ProjectRegistrationError, match="already registered"):
        projects.register_project(second, "shared")

    assert (project_registry / "shared.json").read_bytes() == before


def test_derived_name_collision_gets_a_stable_safe_suffix(
    tmp_path: Path, project_registry: Path,
) -> None:
    first = tmp_path / "one" / "repo"
    second = tmp_path / "two" / "repo"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    projects.register_project(first)

    result = projects.register_project(second)

    assert result["name"].startswith("repo-")
    assert "/" not in result["name"] and "\\" not in result["name"]
    assert (project_registry / f"{result['name']}.json").exists()


def _post(base: str, body: object, *, raw: bytes | None = None) -> tuple[int, dict]:
    data = raw if raw is not None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        base + "/api/projects",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_post_projects_registers_and_returns_validation_errors_as_400(
    tmp_path: Path, project_registry: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    server = ThreadingHTTPServer(("127.0.0.1", 0), web_api.DaedalusHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, created = _post(base, {"repo_root": str(repo), "name": "UI Project"})
        assert status == 201
        assert created["ok"] is True
        assert created["project"] == "ui-project"
        assert created["registered_project"] == {
            "name": "ui-project",
            "repo_root": str(repo.resolve()),
        }
        assert created["created"] is True

        status, duplicate = _post(base, {"repo_root": str(repo)})
        assert status == 200
        assert duplicate["project"] == "ui-project"
        assert duplicate["created"] is False

        for body in ({}, {"repo_root": str(tmp_path / "missing")}, [str(repo)]):
            status, error = _post(base, body)
            assert status == 400
            assert error["ok"] is False
            assert error["error"]

        status, error = _post(base, None, raw=b"{not-json")
        assert status == 400
        assert error["ok"] is False
        assert "invalid JSON" in error["error"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)
