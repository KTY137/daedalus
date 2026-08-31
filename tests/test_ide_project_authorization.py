from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from daedalus import atomic, projects


@pytest.fixture
def project_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    registry = tmp_path / "projects"
    monkeypatch.setattr(projects, "PROJECT_DIR", registry)
    return registry


def test_effectful_project_root_resolution_uses_exact_registry_stem(
    tmp_path: Path, project_registry: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    project_registry.mkdir()
    (project_registry / "atlas.json").write_text(
        json.dumps({
            "name": "untrusted-row-alias",
            "repo_root": str(repo.resolve()),
        }),
        encoding="utf-8",
    )

    assert projects.resolve_registered_project_root("atlas") == str(repo.resolve())
    with pytest.raises(projects.ProjectRowNotFound, match="unknown project"):
        projects.resolve_registered_project_root("untrusted-row-alias")


def test_effectful_project_root_resolution_refuses_request_paths_before_lock(
    tmp_path: Path, project_registry: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    class LockMustNotBeReached:
        def __init__(self, *args, **kwargs) -> None:
            pytest.fail("request path reached the registry lock")

    monkeypatch.setattr(projects, "ExclusiveFileLock", LockMustNotBeReached)
    for request_path in (str(repo.resolve()), "../repo", "folder/repo", ""):
        with pytest.raises(projects.ProjectRowUpdateError):
            projects.resolve_registered_project_root(request_path)
    assert not project_registry.exists()


def test_effectful_project_root_resolution_refuses_stale_and_foreign_rows(
    tmp_path: Path, project_registry: Path,
) -> None:
    stale = tmp_path / "stale"
    stale.mkdir()
    projects.register_project(stale, "stale")
    stale.rmdir()

    foreign_root = "/srv/foreign" if os.name == "nt" else r"C:\foreign\repo"
    (project_registry / "foreign.json").write_text(
        json.dumps({"name": "foreign", "repo_root": foreign_root}),
        encoding="utf-8",
    )

    with pytest.raises(projects.ProjectRegistrationError, match="unavailable"):
        projects.resolve_registered_project_root("stale")
    with pytest.raises(projects.ProjectRegistrationError, match="this host"):
        projects.resolve_registered_project_root("foreign")


def test_effectful_project_root_resolution_lock_failure_is_unavailable(
    tmp_path: Path, project_registry: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    projects.register_project(repo, "demo")

    class RefusingLock:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            raise atomic.FileLockUnavailable("injected contention")

        def __exit__(self, *args) -> bool:
            return False

    monkeypatch.setattr(projects, "ExclusiveFileLock", RefusingLock)
    with pytest.raises(projects.ProjectRegistryUnavailable, match="temporarily unavailable"):
        projects.resolve_registered_project_root("demo")
