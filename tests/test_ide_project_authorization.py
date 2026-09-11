from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from daedalus import atomic
from daedalus.foundation import projects


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


def test_self_row_dot_resolves_to_the_registry_checkout_not_the_cwd(
    tmp_path: Path, project_registry: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``repo_root: "."`` is the checkout that OWNS the registry.

    projects/agent_env.json carries exactly that value on purpose (the row
    must stay valid in every clone and CI job), and before this test the
    effectful seam refused it as "not absolute on this host" -- so the
    product could never expose its own checkout to Ariadne. The self root is
    ``PROJECT_DIR.parent`` and must not depend on where the process runs.
    """
    project_registry.mkdir()
    (project_registry / "self.json").write_text(
        json.dumps({"name": "self", "repo_root": "."}), encoding="utf-8",
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    assert projects.self_checkout_root() == project_registry.parent
    assert projects.resolve_registered_project_root("self") == str(tmp_path.resolve())
    assert projects._registered_root_key({"repo_root": "."}) == projects._path_key(tmp_path)
    assert projects._registered_root_key({"repo_root": " . "}) == projects._path_key(tmp_path)


def test_other_relative_roots_still_fail_closed(
    tmp_path: Path, project_registry: Path,
) -> None:
    """Only the literal "." is the self row; every other relative value keeps
    the fail-closed rule (a Linux host must not reinterpret a stray relative
    path under its cwd, and neither may Windows). Such a row has no registry
    identity at all, so the locked row loader refuses it before the seam
    ever looks at the path -- measured, not assumed: the 'not absolute on
    this host' branch is defense in depth behind that refusal."""
    project_registry.mkdir()
    for index, relative in enumerate(("./", "sub/dir", "..", "./projects/..")):
        name = f"rel{index}"
        (project_registry / f"{name}.json").write_text(
            json.dumps({"name": name, "repo_root": relative}), encoding="utf-8",
        )
        assert projects._registered_root_key({"repo_root": relative}) is None
        with pytest.raises(projects.ProjectRegistryUnavailable, match="no valid repo_root"):
            projects.resolve_registered_project_root(name)
