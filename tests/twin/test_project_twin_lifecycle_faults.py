from __future__ import annotations

import hashlib
import multiprocessing
import os
from pathlib import Path

import pytest

from daedalus.kernel.artifacts import ArtifactRef
from daedalus.twin.genesis import ProjectTwinContractError, ProjectTwinManifest
from daedalus.twin.lifecycle_faults import LockedProjectTwinLifecycleStore


def _digest(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _revision(seed: str) -> str:
    return _digest(f"revision-{seed}")


def _manifest(revision: str, seed: str) -> ProjectTwinManifest:
    return ProjectTwinManifest(
        repository_id="KTY137/daedalus",
        source_revision=revision,
        source_artifact=ArtifactRef.from_sha256(_digest(f"source-{seed}")),
        source_forest_sha256=_digest(f"forest-{seed}"),
        fourfold_snapshot_sha256=_digest(f"snapshot-{seed}"),
        compiler_contract_sha256=_digest("compiler-a"),
        evidence_packet_sha256=_digest(f"evidence-{seed}"),
    )


def _append_worker(
    root: str,
    manifest: ProjectTwinManifest,
    expected_head: str,
    start_event,
    result_queue,
) -> None:
    store = LockedProjectTwinLifecycleStore(root)
    start_event.wait(timeout=10)
    try:
        store.append(manifest, expected_head_sha256=expected_head)
    except Exception as exc:  # child process reports structured outcome
        result_queue.put(("error", type(exc).__name__, str(exc)))
    else:
        result_queue.put(("ok", manifest.digest, ""))


def test_two_processes_cannot_both_commit_from_one_head(tmp_path: Path) -> None:
    store = LockedProjectTwinLifecycleStore(tmp_path)
    first = _manifest(_revision("first"), "first")
    left = _manifest(_revision("left"), "left")
    right = _manifest(_revision("right"), "right")
    store.append(first, expected_head_sha256=None)

    context = multiprocessing.get_context("fork")
    start_event = context.Event()
    result_queue = context.Queue()
    workers = [
        context.Process(
            target=_append_worker,
            args=(str(tmp_path), candidate, first.digest, start_event, result_queue),
        )
        for candidate in (left, right)
    ]
    for worker in workers:
        worker.start()
    start_event.set()
    for worker in workers:
        worker.join(timeout=20)
        assert worker.exitcode == 0

    outcomes = [result_queue.get(timeout=5) for _ in workers]
    assert sum(item[0] == "ok" for item in outcomes) == 1
    failures = [item for item in outcomes if item[0] == "error"]
    assert failures == [
        ("error", "ProjectTwinContractError", "Project Twin lifecycle head changed")
    ]

    manifests, transitions = store.load(first.repository_id)
    assert len(manifests) == len(transitions) == 2
    assert manifests[0] == first
    assert manifests[1].digest in {left.digest, right.digest}
    assert store.resolve_head(first.repository_id) == manifests[1]


def test_failure_before_atomic_replace_preserves_previous_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = LockedProjectTwinLifecycleStore(tmp_path)
    first = _manifest(_revision("first"), "first")
    second = _manifest(_revision("second"), "second")
    store.append(first, expected_head_sha256=None)

    def refuse_replace(source, destination):
        raise OSError("injected replace failure")

    monkeypatch.setattr(os, "replace", refuse_replace)
    with pytest.raises(OSError, match="injected replace failure"):
        store.append(second, expected_head_sha256=first.digest)

    assert store.resolve_head(first.repository_id) == first
    assert not tuple(tmp_path.glob("*.tmp"))
    assert not tuple(tmp_path.glob(".*.tmp"))


def test_stale_lock_file_is_not_treated_as_lock_ownership(tmp_path: Path) -> None:
    store = LockedProjectTwinLifecycleStore(tmp_path)
    first = _manifest(_revision("first"), "first")
    lock_path = store._lock_path(first.repository_id)
    lock_path.write_text("stale metadata is not authority", encoding="utf-8")

    store.append(first, expected_head_sha256=None)
    assert store.resolve_head(first.repository_id) == first


def test_missing_os_lock_support_refuses_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import daedalus.twin.lifecycle_faults as lifecycle_faults

    store = LockedProjectTwinLifecycleStore(tmp_path)
    first = _manifest(_revision("first"), "first")
    monkeypatch.setattr(lifecycle_faults, "fcntl", None)

    with pytest.raises(ProjectTwinContractError, match="locking is unavailable"):
        store.append(first, expected_head_sha256=None)
    assert not store._path(first.repository_id).exists()
