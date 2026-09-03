from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from daedalus import atomic
from daedalus.interfaces.http import web_api
from daedalus.foundation import projects
from daedalus.spine import effect_boundary


ROOT = Path(__file__).resolve().parents[1]

_PROCESS_REGISTRATION_RACER = r"""
import json
import sys
import time
from pathlib import Path

from daedalus.foundation import projects

repo = Path(sys.argv[1])
registry = Path(sys.argv[2])
name = sys.argv[3]
projects.PROJECT_DIR = registry
real_publish = projects.publish_bytes_once

def delayed_publish(path, data):
    (registry / ("publish-" + name)).write_text("ready", encoding="utf-8")
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if len(list(registry.glob("publish-*"))) >= 2:
            break
        time.sleep(0.01)
    return real_publish(path, data)

projects.publish_bytes_once = delayed_publish
registry.mkdir(parents=True, exist_ok=True)
(registry / ("ready-" + name)).write_text("ready", encoding="utf-8")
go = registry / "go"
deadline = time.monotonic() + 10.0
while not go.exists() and time.monotonic() < deadline:
    time.sleep(0.01)
if not go.exists():
    raise SystemExit("start signal timed out")
print(json.dumps(projects.register_project(repo, name)), flush=True)
"""

_LOCK_HOLDER = r"""
import sys
import time
from pathlib import Path

from daedalus.atomic import ExclusiveFileLock

lock_path = Path(sys.argv[1])
ready_path = Path(sys.argv[2])
with ExclusiveFileLock(lock_path, timeout_s=2.0):
    ready_path.write_text("locked", encoding="utf-8")
    time.sleep(60.0)
"""


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
    retry = projects.register_project(second)

    assert result["name"].startswith("repo-")
    assert "/" not in result["name"] and "\\" not in result["name"]
    assert (project_registry / f"{result['name']}.json").exists()
    assert retry == {
        "name": result["name"],
        "repo_root": str(second.resolve()),
        "created": False,
    }


@pytest.mark.parametrize(
    "contents",
    [
        b"{not-json",
        json.dumps({"name": "broken"}).encode("utf-8"),
        b"\xff\xfe",
    ],
)
def test_unverifiable_registry_row_blocks_registration_without_new_row(
    contents: bytes, tmp_path: Path, project_registry: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    project_registry.mkdir()
    broken = project_registry / "broken.json"
    broken.write_bytes(contents)

    with pytest.raises(projects.ProjectRegistryUnavailable, match="broken.json"):
        projects.register_project(repo, "new")

    assert list(project_registry.glob("*.json")) == [broken]
    assert broken.read_bytes() == contents


def test_preexisting_duplicate_root_identity_blocks_registration(
    tmp_path: Path, project_registry: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    project_registry.mkdir()
    for name in ("alpha", "beta"):
        (project_registry / f"{name}.json").write_text(
            json.dumps({"name": name, "repo_root": str(repo.resolve())}),
            encoding="utf-8",
        )

    with pytest.raises(projects.ProjectRegistryUnavailable, match="ambiguous"):
        projects.register_project(repo, "gamma")

    assert sorted(path.name for path in project_registry.glob("*.json")) == [
        "alpha.json", "beta.json",
    ]


@pytest.mark.parametrize("legacy_root", ["relative", "~/repo"])
def test_relative_registry_root_is_not_resolved_from_process_state(
    legacy_root: str, tmp_path: Path, project_registry: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "first" / "relative"
    repo.mkdir(parents=True)
    project_registry.mkdir()
    legacy = project_registry / "legacy.json"
    legacy.write_text(
        json.dumps({"name": "legacy", "repo_root": legacy_root}),
        encoding="utf-8",
    )
    monkeypatch.chdir(repo.parent)

    with pytest.raises(projects.ProjectRegistryUnavailable, match="valid repo_root"):
        projects.register_project(repo, "second")

    assert sorted(path.name for path in project_registry.glob("*.json")) == [
        "legacy.json",
    ]


def test_foreign_platform_absolute_root_is_stable_stale_registry_data(
    tmp_path: Path, project_registry: Path,
) -> None:
    repo = tmp_path / "native"
    repo.mkdir()
    project_registry.mkdir()
    foreign_root = "/srv/foreign" if os.name == "nt" else r"C:\foreign\repo"
    (project_registry / "foreign.json").write_text(
        json.dumps({"name": "foreign", "repo_root": foreign_root}),
        encoding="utf-8",
    )

    result = projects.register_project(repo, "native")

    assert result["created"] is True
    assert sorted(path.name for path in project_registry.glob("*.json")) == [
        "foreign.json", "native.json",
    ]


def test_same_root_registration_is_atomic_across_threads(
    tmp_path: Path, project_registry: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The old scan-then-publish race deterministically reached two publishers."""
    repo = tmp_path / "repo"
    repo.mkdir()
    start = threading.Barrier(3)
    prepublish = threading.Barrier(2)
    publish_calls: list[Path] = []
    real_publish = projects.publish_bytes_once

    def delayed_publish(path: Path, data: bytes) -> bool:
        publish_calls.append(Path(path))
        try:
            prepublish.wait(timeout=1.0)
        except threading.BrokenBarrierError:
            pass
        return real_publish(path, data)

    def register(name: str) -> dict:
        start.wait(timeout=5.0)
        return projects.register_project(repo, name)

    monkeypatch.setattr(projects, "publish_bytes_once", delayed_publish)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(register, name) for name in ("alpha", "beta")]
        start.wait(timeout=5.0)
        results = [future.result(timeout=10.0) for future in futures]

    assert len(publish_calls) == 1
    assert sorted(result["created"] for result in results) == [False, True]
    assert len({result["name"] for result in results}) == 1
    assert {result["repo_root"] for result in results} == {str(repo.resolve())}
    assert len(list(project_registry.glob("*.json"))) == 1


def test_same_root_registration_is_atomic_across_processes(
    tmp_path: Path, project_registry: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    project_registry.mkdir()
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                _PROCESS_REGISTRATION_RACER,
                str(repo),
                str(project_registry),
                name,
            ],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for name in ("alpha", "beta")
    ]
    try:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if all((project_registry / f"ready-{name}").exists()
                   for name in ("alpha", "beta")):
                break
            time.sleep(0.02)
        else:
            pytest.fail("registration processes did not reach the start barrier")
        (project_registry / "go").write_text("go", encoding="utf-8")

        results = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=20.0)
            assert process.returncode == 0, stderr
            results.append(json.loads(stdout.strip()))
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10.0)

    assert sorted(result["created"] for result in results) == [False, True]
    assert len({result["name"] for result in results}) == 1
    assert {result["repo_root"] for result in results} == {str(repo.resolve())}
    assert len(list(project_registry.glob("*.json"))) == 1
    assert len(list(project_registry.glob("publish-*"))) == 1
    assert not list(project_registry.glob("*.tmp"))


def test_file_lock_ignores_stale_filename_and_releases_after_process_kill(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "registry.lock"
    ready_path = tmp_path / "holder.ready"
    lock_path.write_bytes(b"stale filename is not ownership")
    before = lock_path.read_bytes()
    process = subprocess.Popen(
        [sys.executable, "-c", _LOCK_HOLDER, str(lock_path), str(ready_path)],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10.0
        while not ready_path.exists() and time.monotonic() < deadline:
            if process.poll() is not None:
                _, stderr = process.communicate()
                pytest.fail(f"lock holder exited before readiness: {stderr}")
            time.sleep(0.02)
        assert ready_path.exists(), "lock holder did not become ready"
        with pytest.raises(atomic.FileLockUnavailable):
            with atomic.ExclusiveFileLock(lock_path, timeout_s=0.05):
                pytest.fail("two processes held the same file lock")
        process.kill()
        process.communicate(timeout=10.0)
        with atomic.ExclusiveFileLock(lock_path, timeout_s=2.0):
            pass
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10.0)

    assert lock_path.exists()
    assert lock_path.read_bytes() == before


def test_registry_lock_timeout_fails_closed_before_publish(
    tmp_path: Path, project_registry: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    project_registry.mkdir()
    published: list[Path] = []
    real_publish = projects.publish_bytes_once

    def observed_publish(path: Path, data: bytes) -> bool:
        published.append(Path(path))
        return real_publish(path, data)

    monkeypatch.setattr(projects, "publish_bytes_once", observed_publish)
    monkeypatch.setattr(projects, "PROJECT_REGISTRY_LOCK_TIMEOUT_S", 0.05)
    with atomic.ExclusiveFileLock(project_registry / ".registry.lock", timeout_s=0.0):
        with pytest.raises(projects.ProjectRegistryUnavailable, match="unavailable"):
            projects.register_project(repo, "blocked")

    assert published == []
    assert not list(project_registry.glob("*.json"))


def test_file_lock_open_error_is_fail_closed(tmp_path: Path) -> None:
    parent_file = tmp_path / "not-a-directory"
    parent_file.write_text("file", encoding="utf-8")

    with pytest.raises(atomic.FileLockUnavailable, match="cannot open"):
        with atomic.ExclusiveFileLock(parent_file / "lock", timeout_s=0.0):
            pytest.fail("lock acquisition unexpectedly degraded to a no-op")


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


def test_concurrent_project_posts_return_one_created_identity(
    tmp_path: Path, project_registry: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    real_publish = projects.publish_bytes_once

    def delayed_publish(path: Path, data: bytes) -> bool:
        time.sleep(0.1)
        return real_publish(path, data)

    monkeypatch.setattr(projects, "publish_bytes_once", delayed_publish)
    server = ThreadingHTTPServer(("127.0.0.1", 0), web_api.DaedalusHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(
                lambda name: _post(
                    base, {"repo_root": str(repo), "name": name}
                ),
                ("alpha", "beta"),
            ))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)

    assert {(status, body["created"]) for status, body in replies} == {
        (201, True), (200, False),
    }
    assert len({body["project"] for _, body in replies}) == 1
    assert {body["registered_project"]["repo_root"] for _, body in replies} == {
        str(repo.resolve())
    }
    assert len(list(project_registry.glob("*.json"))) == 1


def test_registry_unavailable_maps_to_503(
    tmp_path: Path, project_registry: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    class RefusingLock:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            raise atomic.FileLockUnavailable("injected contention")

        def __exit__(self, *args) -> bool:
            return False

    monkeypatch.setattr(projects, "ExclusiveFileLock", RefusingLock)
    server = ThreadingHTTPServer(("127.0.0.1", 0), web_api.DaedalusHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, body = _post(base, {"repo_root": str(repo), "name": "blocked"})
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)

    assert status == 503
    assert body["ok"] is False
    assert "temporarily unavailable" in body["error"]
    assert not list(project_registry.glob("*.json"))


def test_web_effect_start_precedes_registry_lock_and_publish(
    tmp_path: Path, project_registry: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    events: list[str] = []
    real_begin = effect_boundary.begin_effect
    real_lock = projects.ExclusiveFileLock
    real_publish = projects.publish_bytes_once

    def observed_begin(*args, **kwargs):
        receipt = real_begin(*args, **kwargs)
        events.append(f"begin:{receipt.entrypoint_id}")
        return receipt

    class ObservedLock:
        def __init__(self, *args, **kwargs) -> None:
            self._lock = real_lock(*args, **kwargs)

        def __enter__(self):
            events.append("lock")
            return self._lock.__enter__()

        def __exit__(self, *args) -> bool:
            return self._lock.__exit__(*args)

    def observed_publish(path: Path, data: bytes) -> bool:
        events.append("publish")
        return real_publish(path, data)

    monkeypatch.setattr(effect_boundary, "begin_effect", observed_begin)
    monkeypatch.setattr(projects, "ExclusiveFileLock", ObservedLock)
    monkeypatch.setattr(projects, "publish_bytes_once", observed_publish)
    server = ThreadingHTTPServer(("127.0.0.1", 0), web_api.DaedalusHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, _ = _post(base, {"repo_root": str(repo), "name": "ordered"})
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)

    assert status == 201
    assert events == ["begin:web.mutations", "lock", "publish"]


def test_refused_web_effect_start_prevents_lock_and_publish(
    tmp_path: Path, project_registry: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    events: list[str] = []

    def refused_begin(*args, **kwargs):
        events.append("begin-refused")
        raise effect_boundary.EffectStartRefused("injected refusal")

    class UnexpectedLock:
        def __init__(self, *args, **kwargs) -> None:
            events.append("lock")

    def unexpected_publish(path: Path, data: bytes) -> bool:
        events.append("publish")
        return True

    monkeypatch.setattr(effect_boundary, "begin_effect", refused_begin)
    monkeypatch.setattr(projects, "ExclusiveFileLock", UnexpectedLock)
    monkeypatch.setattr(projects, "publish_bytes_once", unexpected_publish)
    server = ThreadingHTTPServer(("127.0.0.1", 0), web_api.DaedalusHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, body = _post(base, {"repo_root": str(repo), "name": "denied"})
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)

    assert status == 500
    assert body["ok"] is False
    assert events == ["begin-refused"]
    assert not project_registry.exists()


def test_project_list_distinguishes_registered_from_reachable(
    tmp_path: Path, project_registry: Path,
) -> None:
    present = tmp_path / "present"
    present.mkdir()
    project_registry.mkdir()
    (project_registry / "present.json").write_text(
        json.dumps({"name": "present", "repo_root": str(present)}), encoding="utf-8")
    (project_registry / "stale.json").write_text(
        json.dumps({"name": "stale", "repo_root": str(tmp_path / "missing")}),
        encoding="utf-8",
    )

    project_rows = web_api._project_list()["projects"]
    assert [row["name"] for row in project_rows] == ["present", "stale"]
    rows = {row["name"]: row for row in project_rows}

    assert rows["present"]["reachable"] is True
    assert rows["stale"]["reachable"] is False
