"""G1-IDE-12: canonical, serialized rewrites of ``projects/*.json`` rows.

The project registry is small, but it is shared by the threaded web API and
multiple process entrypoints.  These tests pin the transaction boundary: one
fixed OS lock covers read/mutate/publish, and publication exposes either the
old JSON document or the complete new one.
"""
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
from typing import Any

import pytest

from daedalus import atomic, core
from daedalus.interfaces.http import web_api
from daedalus.foundation import projects
from daedalus.foundation.projects import ProjectRowUpdateError
from daedalus.orchestration import control_plane, hierarchy
from daedalus.spine import effect_boundary


ROOT = Path(__file__).resolve().parents[1]

_PROCESS_ROW_REWRITE_RACER = r"""
import json
import sys
import time
from pathlib import Path

from daedalus.foundation import projects
from daedalus.orchestration import control_plane, hierarchy

registry = Path(sys.argv[1])
row = Path(sys.argv[2])
operation = sys.argv[3]
projects.PROJECT_DIR = registry
real_read_text = Path.read_text

def synchronized_read(self, *args, **kwargs):
    text = real_read_text(self, *args, **kwargs)
    if self == row:
        (registry / ("read-" + operation)).write_text("ready", encoding="utf-8")
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            if len(list(registry.glob("read-*"))) >= 2:
                break
            time.sleep(0.01)
    return text

Path.read_text = synchronized_read
hierarchy.core.team_config = lambda project: {}
control_plane.unified_profiles = lambda project: {}
(registry / ("ready-" + operation)).write_text("ready", encoding="utf-8")
go = registry / "go"
deadline = time.monotonic() + 10.0
while not go.exists() and time.monotonic() < deadline:
    time.sleep(0.01)
if not go.exists():
    raise SystemExit("start signal timed out")
if operation == "team":
    hierarchy.save_team("demo", {"max_workers": 9})
else:
    control_plane.save_autonomy("demo", {"default": "autonomous"})
print(json.dumps({"ok": True, "operation": operation}), flush=True)
"""


@pytest.fixture
def project_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    registry = tmp_path / "projects"
    registry.mkdir()
    monkeypatch.setattr(projects, "PROJECT_DIR", registry)
    return registry


def _row(
    registry: Path,
    repo_root: Path,
    *,
    name: str = "demo",
    extra: dict[str, Any] | None = None,
) -> Path:
    data: dict[str, Any] = {"name": name, "repo_root": str(repo_root.resolve())}
    if extra:
        data.update(extra)
    path = registry / f"{name}.json"
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def _set_max_workers(team: dict[str, Any]) -> None:
    team["max_workers"] = 9


def _put(base: str, path: str, body: object) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode("utf-8"),
        method="PUT",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _serve_request(
    path: str, body: object,
) -> tuple[int, dict[str, Any]]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), web_api.DaedalusHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        return _put(base, path, body)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def test_disjoint_team_and_autonomy_writes_preserve_both_updates(
    tmp_path: Path,
    project_registry: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A timed read barrier makes the former lost-update race deterministic.

    Without the transaction lock both legacy writers read the same original
    row and each publishes a document missing the other's field.  With the
    lock, the first reader times out at this test-only barrier while holding
    the lock; the second reader can proceed only after the first publication.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    path = _row(
        project_registry,
        repo,
        extra={"team": {"max_workers": 3, "autonomy": {"default": "manual"}}},
    )
    first_reads = threading.Barrier(2)
    start = threading.Barrier(3)
    real_read_text = Path.read_text
    real_write_text = Path.write_text
    direct_target_write = threading.Lock()

    def synchronized_read(self: Path, *args: Any, **kwargs: Any) -> str:
        text = real_read_text(self, *args, **kwargs)
        if self == path:
            try:
                first_reads.wait(timeout=0.25)
            except threading.BrokenBarrierError:
                pass
        return text

    def serialized_direct_write(self: Path, *args: Any, **kwargs: Any) -> int:
        # If the old in-place writers are restored, publish each of their
        # complete stale documents in turn.  That rules out a coincidental
        # byte-level hybrid and guarantees the final document lacks one of the
        # two updates.  Atomic publishers write a sibling instead and never
        # take this test-only branch.
        if self == path:
            with direct_target_write:
                return real_write_text(self, *args, **kwargs)
        return real_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", synchronized_read)
    monkeypatch.setattr(Path, "write_text", serialized_direct_write)
    # Keep the test on persistence rather than the large response projections.
    monkeypatch.setattr(hierarchy.core, "team_config", lambda project: {})
    monkeypatch.setattr(control_plane, "unified_profiles", lambda project: {})

    def save_team() -> None:
        start.wait(timeout=5)
        hierarchy.save_team("demo", {"max_workers": 9})

    def save_autonomy() -> None:
        start.wait(timeout=5)
        control_plane.save_autonomy("demo", {"default": "autonomous"})

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(save_team), pool.submit(save_autonomy)]
        start.wait(timeout=5)
        for future in futures:
            future.result(timeout=10)

    final = json.loads(real_read_text(path, encoding="utf-8"))
    assert final["team"]["max_workers"] == 9
    assert final["team"]["autonomy"]["default"] == "autonomous"


def test_disjoint_team_and_autonomy_writes_compose_across_processes(
    tmp_path: Path,
    project_registry: Path,
) -> None:
    """The registry lock must serialize real interpreter processes too."""
    repo = tmp_path / "repo"
    repo.mkdir()
    path = _row(
        project_registry,
        repo,
        extra={"team": {"max_workers": 3, "autonomy": {"default": "manual"}}},
    )
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                _PROCESS_ROW_REWRITE_RACER,
                str(project_registry),
                str(path),
                operation,
            ],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for operation in ("team", "autonomy")
    ]
    try:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if all(
                (project_registry / f"ready-{operation}").exists()
                for operation in ("team", "autonomy")
            ):
                break
            time.sleep(0.02)
        else:
            pytest.fail("rewrite processes did not reach the start barrier")
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

    assert {result["operation"] for result in results} == {"team", "autonomy"}
    final = json.loads(path.read_text(encoding="utf-8"))
    assert final["team"]["max_workers"] == 9
    assert final["team"]["autonomy"]["default"] == "autonomous"
    # With one shared lock only the first process reaches its instrumented row
    # read before the bounded barrier expires.  The second re-reads afterwards.
    assert len(list(project_registry.glob("read-*"))) == 2
    assert not list(project_registry.glob("*.tmp"))


def test_reader_sees_old_json_until_complete_new_json_is_replaced(
    tmp_path: Path,
    project_registry: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    path = _row(project_registry, repo, extra={"team": {"max_workers": 3}})
    old_bytes = path.read_bytes()
    before_replace = threading.Event()
    allow_replace = threading.Event()
    writer_errors: list[BaseException] = []
    real_replace = atomic.replace_with_retry

    def paused_replace(
        tmp: str | Path,
        target: str | Path,
        retry_s: float = atomic.REPLACE_RETRY_S,
    ) -> None:
        assert Path(target) == path
        # The sibling is already a complete, valid new document, but it has
        # not become the authoritative row yet.
        staged = json.loads(Path(tmp).read_text(encoding="utf-8"))
        assert staged["team"]["max_workers"] == 9
        before_replace.set()
        if not allow_replace.wait(timeout=5):
            raise TimeoutError("test did not release the atomic replace")
        real_replace(tmp, target, retry_s)

    monkeypatch.setattr(atomic, "replace_with_retry", paused_replace)

    def write() -> None:
        try:
            projects.rewrite_project_team("demo", _set_max_workers)
        except BaseException as exc:  # surfaced in the asserting thread below
            writer_errors.append(exc)

    thread = threading.Thread(target=write)
    thread.start()
    try:
        assert before_replace.wait(timeout=5), "writer never reached atomic replace"
        observed = [json.loads(path.read_text(encoding="utf-8")) for _ in range(20)]
        assert path.read_bytes() == old_bytes
        assert {row["team"]["max_workers"] for row in observed} == {3}
    finally:
        allow_replace.set()
        thread.join(timeout=10)

    assert not thread.is_alive()
    assert writer_errors == []
    assert json.loads(path.read_text(encoding="utf-8"))["team"]["max_workers"] == 9
    assert not list(project_registry.glob("*.tmp"))


def test_parallel_read_rewrite_stress_observes_only_complete_states(
    tmp_path: Path,
    project_registry: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    path = _row(
        project_registry,
        repo,
        extra={"team": {"generation": 0, "marker": "0:" + "x" * 16384}},
    )
    start = threading.Barrier(4)
    finished = threading.Event()
    errors: list[tuple[str, BaseException]] = []
    observations = [0, 0, 0]
    read_conflicts = [0, 0, 0]

    def writer() -> None:
        try:
            start.wait(timeout=5)
            for generation in range(1, 31):
                def mutate(team: dict[str, Any], generation: int = generation) -> None:
                    team["generation"] = generation
                    team["marker"] = f"{generation}:" + "x" * 16384

                projects.rewrite_project_team("demo", mutate)
        except BaseException as exc:
            errors.append(("writer", exc))
        finally:
            finished.set()

    def reader(index: int) -> None:
        try:
            start.wait(timeout=5)
            while not finished.is_set() or observations[index] == 0:
                try:
                    text = path.read_text(encoding="utf-8")
                except PermissionError:
                    # A win32 open can briefly lose to MoveFileEx.  That is no
                    # byte observation; retry and continue proving that every
                    # successful lock-free read is a complete old/new document.
                    if os.name != "nt":
                        raise
                    read_conflicts[index] += 1
                    time.sleep(0.001)
                    continue
                data = json.loads(text)
                team = data["team"]
                generation = team["generation"]
                assert team["marker"] == f"{generation}:" + "x" * 16384
                observations[index] += 1
                # On Windows a CPython reader does not request FILE_SHARE_DELETE.
                # Yield between observations so the bounded publisher retry is
                # tested under contention without deliberately starving it.
                time.sleep(0.001)
        except BaseException as exc:
            errors.append((f"reader-{index}", exc))

    threads = [threading.Thread(target=writer)] + [
        threading.Thread(target=reader, args=(index,)) for index in range(3)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    assert all(count > 0 for count in observations), read_conflicts
    assert json.loads(path.read_text(encoding="utf-8"))["team"]["generation"] == 30
    assert not list(project_registry.glob("*.tmp"))


def test_registration_and_rewrite_contend_on_the_same_registry_lock(
    tmp_path: Path,
    project_registry: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    path = _row(project_registry, repo, extra={"team": {"max_workers": 3}})
    mutate_entered = threading.Event()
    allow_mutation = threading.Event()
    registration_finished = threading.Event()

    def paused_mutation(team: dict[str, Any]) -> None:
        mutate_entered.set()
        if not allow_mutation.wait(timeout=5):
            raise TimeoutError("test did not release the row mutation")
        team["max_workers"] = 9

    def rewrite() -> None:
        projects.rewrite_project_team("demo", paused_mutation)

    def register() -> dict[str, Any]:
        try:
            return projects.register_project(repo, "alias")
        finally:
            registration_finished.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        rewrite_future = pool.submit(rewrite)
        assert mutate_entered.wait(timeout=5), "rewrite never acquired the registry lock"
        register_future = pool.submit(register)
        assert not registration_finished.wait(timeout=0.2)
        allow_mutation.set()
        rewrite_future.result(timeout=10)
        registration = register_future.result(timeout=10)

    assert registration == {
        "name": "demo",
        "repo_root": str(repo.resolve()),
        "created": False,
    }
    assert json.loads(path.read_text(encoding="utf-8"))["team"]["max_workers"] == 9
    assert [row.name for row in project_registry.glob("*.json")] == ["demo.json"]


@pytest.mark.parametrize(
    "project",
    [
        "",
        "   ",
        ".",
        "..",
        "../escape",
        r"..\escape",
        "nested/name",
        "nul\x00stem",
        17,
        None,
        b"demo",
    ],
)
def test_rewrite_refuses_invalid_stems_without_touching_any_row(
    project: object,
    tmp_path: Path,
    project_registry: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    registered = _row(project_registry, repo)
    outside = tmp_path / "escape.json"
    outside.write_text(
        json.dumps({"name": "escape", "repo_root": str(repo.resolve())}),
        encoding="utf-8",
    )
    before_registered = registered.read_bytes()
    before_outside = outside.read_bytes()

    with pytest.raises(projects.ProjectRowUpdateError):
        projects.rewrite_project_team(project, _set_max_workers)  # type: ignore[arg-type]

    assert registered.read_bytes() == before_registered
    assert outside.read_bytes() == before_outside


@pytest.mark.parametrize(
    ("encoded_project", "expected_status"),
    [
        ("", 400),
        ("%2e%2e%2fescape", 400),
        ("%2e%2e%5cescape", 400),
        ("nul%00stem", 400),
        ("../escape", 404),
    ],
)
def test_put_refuses_encoded_and_literal_traversal_without_outside_write(
    encoded_project: str,
    expected_status: int,
    tmp_path: Path,
    project_registry: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    registered = _row(project_registry, repo)
    outside = tmp_path / "escape.json"
    outside.write_text(
        json.dumps({"name": "escape", "repo_root": str(repo.resolve())}),
        encoding="utf-8",
    )
    before_registered = registered.read_bytes()
    before_outside = outside.read_bytes()

    status, body = _serve_request(
        f"/api/projects/{encoded_project}/team", {"max_workers": 9},
    )

    assert status == expected_status
    assert body["ok"] is False
    assert registered.read_bytes() == before_registered
    assert outside.read_bytes() == before_outside


def test_rewrite_refuses_unknown_project_without_creating_it(
    tmp_path: Path,
    project_registry: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    registered = _row(project_registry, repo)
    before = registered.read_bytes()

    with pytest.raises(projects.ProjectRowNotFound, match="unknown project"):
        projects.rewrite_project_team("missing", _set_max_workers)

    assert registered.read_bytes() == before
    assert not (project_registry / "missing.json").exists()


def test_load_project_refuses_reader_traversal_without_reading_outside_registry(
    tmp_path: Path,
    project_registry: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "escape.json"
    outside.write_text(
        json.dumps({"name": "escape", "repo_root": str(repo.resolve())}),
        encoding="utf-8",
    )
    before = outside.read_bytes()

    with pytest.raises(projects.ProjectRowUpdateError):
        projects.load_project("../escape")

    assert outside.read_bytes() == before


def test_load_project_refuses_a_symlink_registry_row(
    tmp_path: Path,
    project_registry: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text(
        json.dumps({"name": "linked", "repo_root": str(repo.resolve())}),
        encoding="utf-8",
    )
    linked = project_registry / "linked.json"
    try:
        linked.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"this host cannot create a test symlink: {exc}")

    with pytest.raises(projects.ProjectRegistryUnavailable, match="direct file"):
        projects.load_project("linked")


@pytest.mark.parametrize(
    "contents",
    [
        b"{not-json",
        b"\xff\xfe",
        json.dumps([]).encode("utf-8"),
        json.dumps({"name": "demo"}).encode("utf-8"),
        json.dumps({"name": "demo", "repo_root": "relative/repo"}).encode("utf-8"),
        json.dumps({"name": "demo", "repo_root": 42}).encode("utf-8"),
        json.dumps({
            "name": "demo",
            "repo_root": "/srv/nul\x00repo" if os.name == "nt" else "C:\\nul\x00repo",
        }).encode("utf-8"),
    ],
)
def test_rewrite_fails_closed_on_an_invalid_persisted_row(
    contents: bytes,
    project_registry: Path,
) -> None:
    path = project_registry / "demo.json"
    path.write_bytes(contents)

    with pytest.raises(projects.ProjectRegistryUnavailable):
        projects.rewrite_project_team("demo", _set_max_workers)

    assert path.read_bytes() == contents
    assert not list(project_registry.glob("*.tmp"))


@pytest.mark.parametrize("invalid_team", [None, [], "team", 1])
def test_rewrite_fails_closed_when_persisted_team_is_not_an_object(
    invalid_team: object,
    tmp_path: Path,
    project_registry: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    path = _row(project_registry, repo, extra={"team": invalid_team})
    before = path.read_bytes()

    with pytest.raises(projects.ProjectRegistryUnavailable, match="team"):
        projects.rewrite_project_team("demo", _set_max_workers)

    assert path.read_bytes() == before


def test_rewrite_preserves_identity_policy_and_unknown_fields(
    tmp_path: Path,
    project_registry: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    original = {
        "name": "demo",
        "repo_root": str(repo.resolve()),
        "policy": {"write_roots": ["src"], "never_auto_merge": True},
        "unknown_top": {"nested": [1, 2, 3]},
        "team": {
            "default_lane": "local_only",
            "autonomy": {"default": "manual", "agents": {"qa": "semi_auto"}},
            "unknown_team": {"keep": True},
        },
    }
    path = project_registry / "demo.json"
    path.write_text(json.dumps(original, indent=2) + "\n", encoding="utf-8")

    updated = projects.rewrite_project_team("demo", _set_max_workers)

    expected = json.loads(json.dumps(original))
    expected["team"]["max_workers"] = 9
    assert updated == expected
    assert json.loads(path.read_text(encoding="utf-8")) == expected
    assert updated["name"] == original["name"]
    assert updated["repo_root"] == original["repo_root"]
    assert updated["policy"] == original["policy"]
    assert updated["unknown_top"] == original["unknown_top"]
    assert updated["team"]["autonomy"] == original["team"]["autonomy"]
    assert updated["team"]["unknown_team"] == original["team"]["unknown_team"]


def test_live_save_operations_preserve_identity_scope_policy_and_extensions(
    tmp_path: Path,
    project_registry: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    original = {
        "name": "demo",
        "repo_root": str(repo.resolve()),
        "center": ["src", "docs"],
        "policy": {"write_roots": ["src"], "never_auto_merge": True},
        "runtime": {"lane": "local_only"},
        "unknown_top": {"keep": [1, 2, 3]},
        "team": {
            "max_workers": 3,
            "default_lane": "local_only",
            "unknown_team": {"keep": True},
            "autonomy": {
                "default": "manual",
                "agents": {"old": "manual"},
                "capabilities": {"file_write": "manual"},
                "unknown_autonomy": "keep",
            },
        },
    }
    path = project_registry / "demo.json"
    path.write_text(json.dumps(original, indent=2) + "\n", encoding="utf-8")
    monkeypatch.setattr(hierarchy.core, "team_config", lambda project: {})
    monkeypatch.setattr(control_plane, "unified_profiles", lambda project: {})

    hierarchy.save_team(
        "demo",
        {
            "max_workers": 9,
            "name": "forbidden-name",
            "repo_root": str(tmp_path / "outside"),
            "center": ["outside"],
            "policy": {"never_auto_merge": False},
            "unknown_top": "replace",
        },
    )
    control_plane.save_autonomy(
        "demo",
        {
            "default": "autonomous",
            "agents": {"qa": "semi_auto"},
            "capabilities": {"file_write": "manual", "read_files": "semi_auto"},
            "repo_root": str(tmp_path / "outside"),
            "policy": {"never_auto_merge": False},
        },
    )

    final = json.loads(path.read_text(encoding="utf-8"))
    for key in ("name", "repo_root", "center", "policy", "runtime", "unknown_top"):
        assert final[key] == original[key]
    assert final["team"]["max_workers"] == 9
    assert final["team"]["default_lane"] == original["team"]["default_lane"]
    assert final["team"]["unknown_team"] == original["team"]["unknown_team"]
    assert final["team"]["autonomy"] == {
        "default": "autonomous",
        "agents": {"qa": "semi_auto"},
        "capabilities": {"file_write": "manual", "read_files": "semi_auto"},
        "unknown_autonomy": "keep",
    }


def test_lock_timeout_leaves_project_row_byte_identical(
    tmp_path: Path,
    project_registry: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    path = _row(project_registry, repo, extra={"team": {"max_workers": 3}})
    before = path.read_bytes()
    monkeypatch.setattr(projects, "PROJECT_REGISTRY_LOCK_TIMEOUT_S", 0.05)

    with atomic.ExclusiveFileLock(
        project_registry / ".registry.lock", timeout_s=0.0,
    ):
        with pytest.raises(projects.ProjectRegistryUnavailable, match="unavailable"):
            projects.rewrite_project_team("demo", _set_max_workers)

    assert path.read_bytes() == before
    assert not list(project_registry.glob("*.tmp"))


def test_mutator_exception_is_propagated_and_leaves_bytes_unchanged(
    tmp_path: Path,
    project_registry: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    path = _row(project_registry, repo, extra={"team": {"max_workers": 3}})
    before = path.read_bytes()

    class MutationBoom(RuntimeError):
        pass

    def fail_after_mutation(team: dict[str, Any]) -> None:
        team["max_workers"] = 99
        raise MutationBoom("injected mutation failure")

    with pytest.raises(MutationBoom, match="injected mutation failure"):
        projects.rewrite_project_team("demo", fail_after_mutation)

    assert path.read_bytes() == before
    assert not list(project_registry.glob("*.tmp"))


def test_unserializable_mutation_fails_without_publishing(
    tmp_path: Path,
    project_registry: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    path = _row(project_registry, repo, extra={"team": {"max_workers": 3}})
    before = path.read_bytes()

    def make_unserializable(team: dict[str, Any]) -> None:
        team["opaque"] = object()

    with pytest.raises(projects.ProjectRowUpdateError, match="serial"):
        projects.rewrite_project_team("demo", make_unserializable)

    assert path.read_bytes() == before
    assert not list(project_registry.glob("*.tmp"))


def test_put_registry_unavailable_maps_to_503_without_changing_row(
    tmp_path: Path,
    project_registry: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    path = _row(project_registry, repo, extra={"team": {"max_workers": 3}})
    before = path.read_bytes()

    class RefusingLock:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> None:
            raise atomic.FileLockUnavailable("injected contention")

        def __exit__(self, *args: Any) -> bool:
            return False

    monkeypatch.setattr(projects, "ExclusiveFileLock", RefusingLock)

    status, body = _serve_request(
        "/api/projects/demo/team", {"max_workers": 9},
    )

    assert status == 503
    assert body["ok"] is False
    assert path.read_bytes() == before


def test_exhausted_atomic_replace_maps_to_503_and_preserves_exact_old_bytes(
    tmp_path: Path,
    project_registry: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    path = _row(project_registry, repo, extra={"team": {"max_workers": 3}})
    before = path.read_bytes()
    real_replace_with_retry = atomic.replace_with_retry

    def refused_replace(tmp: object, target: object) -> None:
        raise PermissionError("injected sharing conflict")

    def exhausted_replace(
        tmp: str | Path,
        target: str | Path,
        retry_s: float = atomic.REPLACE_RETRY_S,
    ) -> None:
        real_replace_with_retry(tmp, target, retry_s=0.0)

    monkeypatch.setattr(atomic.os, "replace", refused_replace)
    monkeypatch.setattr(atomic, "replace_with_retry", exhausted_replace)

    status, body = _serve_request(
        "/api/projects/demo/team", {"max_workers": 9},
    )

    assert status == 503
    assert body["ok"] is False
    assert "could not be replaced" in body["error"]
    assert path.read_bytes() == before
    assert not list(project_registry.glob("*.tmp"))


def test_put_effect_start_precedes_lock_and_atomic_replace(
    tmp_path: Path,
    project_registry: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    path = _row(project_registry, repo, extra={"team": {"max_workers": 3}})
    events: list[str] = []
    real_begin = effect_boundary.begin_effect
    real_lock = projects.ExclusiveFileLock
    real_replace = atomic.replace_with_retry

    def observed_begin(*args: Any, **kwargs: Any) -> Any:
        receipt = real_begin(*args, **kwargs)
        events.append(f"begin:{receipt.entrypoint_id}")
        return receipt

    class ObservedLock:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._lock = real_lock(*args, **kwargs)

        def __enter__(self) -> Any:
            events.append("lock")
            return self._lock.__enter__()

        def __exit__(self, *args: Any) -> bool:
            return self._lock.__exit__(*args)

    def observed_replace(
        tmp: str | Path,
        target: str | Path,
        retry_s: float = atomic.REPLACE_RETRY_S,
    ) -> None:
        events.append("replace")
        real_replace(tmp, target, retry_s)

    monkeypatch.setattr(effect_boundary, "begin_effect", observed_begin)
    monkeypatch.setattr(projects, "ExclusiveFileLock", ObservedLock)
    monkeypatch.setattr(atomic, "replace_with_retry", observed_replace)

    status, body = _serve_request(
        "/api/projects/demo/team", {"max_workers": 9},
    )

    assert status == 200
    assert body["ok"] is True
    assert events == ["begin:web.mutations_put", "lock", "replace"]
    assert json.loads(path.read_text(encoding="utf-8"))["team"]["max_workers"] == 9


def test_refused_put_effect_start_prevents_lock_and_publish(
    tmp_path: Path,
    project_registry: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    path = _row(project_registry, repo, extra={"team": {"max_workers": 3}})
    before = path.read_bytes()
    events: list[str] = []

    def refused_begin(*args: Any, **kwargs: Any) -> Any:
        events.append("begin-refused")
        raise effect_boundary.EffectStartRefused("injected refusal")

    class UnexpectedLock:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            events.append("lock")

    def unexpected_replace(*args: Any, **kwargs: Any) -> None:
        events.append("replace")

    monkeypatch.setattr(effect_boundary, "begin_effect", refused_begin)
    monkeypatch.setattr(projects, "ExclusiveFileLock", UnexpectedLock)
    monkeypatch.setattr(atomic, "replace_with_retry", unexpected_replace)

    status, body = _serve_request(
        "/api/projects/demo/team", {"max_workers": 9},
    )

    assert status == 500
    assert body["ok"] is False
    assert events == ["begin-refused"]
    assert path.read_bytes() == before


# ---------------------------------------------------------------------------
# save_team value validation
#
# save_team key-filtered but never checked VALUES. That was survivable only
# while nothing could reach the endpoint. The cockpit now can, and an
# unvalidated write here poisons every READ path for the project -- see the
# first test, which proves the poison rather than asserting the guard alone.
# ---------------------------------------------------------------------------


def _team_row(registry: Path, repo: Path, team: dict[str, Any] | None = None) -> Path:
    return _row(registry, repo, extra={"team": team if team is not None else {"max_workers": 3}})


def test_a_non_numeric_max_workers_would_brick_every_read_and_is_refused(
    tmp_path: Path, project_registry: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fixture is not inert: it first shows the damage, then the guard."""
    repo = tmp_path / "repo"
    repo.mkdir()
    path = _team_row(project_registry, repo)

    # 1. The damage is real. Written directly, "abc" makes team_config raise --
    #    and team_config is what dashboard, hierarchy, routing and build all
    #    call, so the project becomes unreadable and the UI cannot undo it
    #    because the undo path reads first.
    projects.rewrite_project_team("demo", lambda team: team.update({"max_workers": "abc"}))
    with pytest.raises(ValueError):
        core.team_config("demo")

    # 2. The guard refuses it at the boundary instead.
    projects.rewrite_project_team("demo", lambda team: team.update({"max_workers": 3}))
    before = path.read_bytes()
    with pytest.raises(ProjectRowUpdateError, match="max_workers must be an integer"):
        hierarchy.save_team("demo", {"max_workers": "abc"})
    assert path.read_bytes() == before
    assert core.team_config("demo")["max_workers"] == 3


def test_active_agents_as_a_string_is_refused_not_exploded_into_letters(
    tmp_path: Path, project_registry: Path
) -> None:
    """core.team_config reads active_agents as [str(a) for a in value], so a
    stored string becomes one 'agent' per CHARACTER, silently."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _team_row(project_registry, repo)

    projects.rewrite_project_team("demo", lambda team: team.update({"active_agents": "claude"}))
    assert core.team_config("demo")["active_agents"] == list("claude")  # the damage

    projects.rewrite_project_team("demo", lambda team: team.update({"active_agents": []}))
    with pytest.raises(ProjectRowUpdateError, match="active_agents must be a list"):
        hierarchy.save_team("demo", {"active_agents": "claude"})
    assert core.team_config("demo")["active_agents"] == []


def test_default_lane_must_be_one_the_router_knows(
    tmp_path: Path, project_registry: Path
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _team_row(project_registry, repo)
    with pytest.raises(ProjectRowUpdateError, match="default_lane must be one of"):
        hierarchy.save_team("demo", {"default_lane": "nonsense"})
    for lane in core.KNOWN_LANES:
        hierarchy.save_team("demo", {"default_lane": lane})
        assert core.team_config("demo")["default_lane"] == lane


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (True, "max_workers must be an integer"),   # bool is an int in Python
        (0, "max_workers must be between"),
        (-1, "max_workers must be between"),
        (hierarchy.MAX_WORKERS_CEILING + 1, "max_workers must be between"),
        (3.5, "max_workers must be an integer"),
    ],
)
def test_max_workers_bounds(
    tmp_path: Path, project_registry: Path, value: Any, message: str
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _team_row(project_registry, repo)
    with pytest.raises(ProjectRowUpdateError, match=message):
        hierarchy.save_team("demo", {"max_workers": value})


def test_the_bounds_admit_their_own_edges(tmp_path: Path, project_registry: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _team_row(project_registry, repo)
    for value in (1, hierarchy.MAX_WORKERS_CEILING):
        hierarchy.save_team("demo", {"max_workers": value})
        assert core.team_config("demo")["max_workers"] == value


def test_ignored_fields_are_reported_rather_than_dropped_in_silence(
    tmp_path: Path, project_registry: Path
) -> None:
    """Unknown keys stay IGNORED -- that is what keeps a patch inside the team
    subtree -- but the caller is told, because an ignored field and a saved one
    look identical from the other side of the wire."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _team_row(project_registry, repo)
    result = hierarchy.save_team("demo", {"max_workers": 4, "repo_root": "/elsewhere", "nope": 1})
    assert result["ignored_fields"] == ["nope", "repo_root"]
    assert result["team"]["max_workers"] == 4


def test_semi_auto_flags_must_be_booleans(tmp_path: Path, project_registry: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _team_row(project_registry, repo)
    with pytest.raises(ProjectRowUpdateError, match="must be true or false"):
        hierarchy.save_team("demo", {"semi_auto": {"never_auto_write": "no"}})
    hierarchy.save_team("demo", {"semi_auto": {"never_auto_write": False}})
    assert core.team_config("demo")["semi_auto"]["never_auto_write"] is False
