from __future__ import annotations

import json
import os

import pytest

from daedalus.spine.envelope import canonical_json
from daedalus.twin.genesis import ProjectTwinContractError
from daedalus.twin.lifecycle import AtomicProjectTwinLifecycleStore


REPOSITORY = "KTY137/daedalus"


def _write_lock(store: AtomicProjectTwinLifecycleStore, payload: dict[str, object]) -> None:
    store._lock_path(REPOSITORY).write_text(canonical_json(payload), encoding="ascii")


def _payload(*, hostname: str = "host-a", pid: int = 999999, token: str = "a" * 32) -> dict[str, object]:
    return {
        "schema": "daedalus-project-twin-lock/1",
        "hostname": hostname,
        "pid": pid,
        "owner_token": token,
    }


def test_abandoned_same_host_lock_is_reclaimed(tmp_path):
    store = AtomicProjectTwinLifecycleStore(
        tmp_path,
        hostname="host-a",
        owner_alive=lambda pid: False,
    )
    _write_lock(store, _payload())

    with store._exclusive_writer(REPOSITORY):
        lock_payload = json.loads(store._lock_path(REPOSITORY).read_text("ascii"))
        assert lock_payload["hostname"] == "host-a"
        assert lock_payload["pid"] == os.getpid()
        assert lock_payload["owner_token"] != "a" * 32

    assert not store._lock_path(REPOSITORY).exists()


def test_live_same_host_lock_fails_closed(tmp_path):
    store = AtomicProjectTwinLifecycleStore(
        tmp_path,
        hostname="host-a",
        owner_alive=lambda pid: True,
    )
    _write_lock(store, _payload())

    with pytest.raises(ProjectTwinContractError, match="writer is already active"):
        with store._exclusive_writer(REPOSITORY):
            pass

    assert store._lock_path(REPOSITORY).exists()


def test_foreign_host_lock_is_never_reclaimed(tmp_path):
    store = AtomicProjectTwinLifecycleStore(
        tmp_path,
        hostname="host-a",
        owner_alive=lambda pid: False,
    )
    _write_lock(store, _payload(hostname="host-b"))

    with pytest.raises(ProjectTwinContractError, match="writer is already active"):
        with store._exclusive_writer(REPOSITORY):
            pass

    assert store._lock_path(REPOSITORY).exists()


@pytest.mark.parametrize(
    "raw, message",
    [
        (b"not-json", "malformed"),
        (canonical_json({"schema": "wrong"}).encode("ascii"), "schema is invalid"),
        (canonical_json(_payload(pid=0)).encode("ascii"), "pid is invalid"),
        (canonical_json(_payload(token="xyz")).encode("ascii"), "owner token is invalid"),
    ],
)
def test_malformed_lock_records_fail_closed(tmp_path, raw, message):
    store = AtomicProjectTwinLifecycleStore(
        tmp_path,
        hostname="host-a",
        owner_alive=lambda pid: False,
    )
    store._lock_path(REPOSITORY).write_bytes(raw)

    with pytest.raises(ProjectTwinContractError, match=message):
        with store._exclusive_writer(REPOSITORY):
            pass


def test_noncanonical_lock_record_fails_closed(tmp_path):
    store = AtomicProjectTwinLifecycleStore(
        tmp_path,
        hostname="host-a",
        owner_alive=lambda pid: False,
    )
    store._lock_path(REPOSITORY).write_text(json.dumps(_payload(), indent=2), encoding="ascii")

    with pytest.raises(ProjectTwinContractError, match="not canonically encoded"):
        with store._exclusive_writer(REPOSITORY):
            pass


def test_symlink_lock_is_never_followed_or_removed(tmp_path):
    store = AtomicProjectTwinLifecycleStore(
        tmp_path,
        hostname="host-a",
        owner_alive=lambda pid: False,
    )
    target = tmp_path / "target"
    target.write_text("keep", encoding="ascii")
    lock = store._lock_path(REPOSITORY)
    try:
        lock.symlink_to(target)
    except OSError:
        pytest.skip("symlinks unavailable")

    with pytest.raises(ProjectTwinContractError, match="cannot be a symlink"):
        with store._exclusive_writer(REPOSITORY):
            pass

    assert lock.is_symlink()
    assert target.read_text("ascii") == "keep"


def test_owner_never_unlinks_replaced_lock(tmp_path):
    store = AtomicProjectTwinLifecycleStore(tmp_path, hostname="host-a")
    replacement = canonical_json(_payload(hostname="host-b", token="b" * 32)).encode("ascii")

    with store._exclusive_writer(REPOSITORY):
        store._lock_path(REPOSITORY).write_bytes(replacement)

    assert store._lock_path(REPOSITORY).read_bytes() == replacement


def test_partial_lock_writes_are_completed(tmp_path, monkeypatch):
    import daedalus.twin.lifecycle as lifecycle

    store = AtomicProjectTwinLifecycleStore(tmp_path, hostname="host-a")
    real_write = os.write
    calls = []

    def partial_write(fd, data):
        chunk = bytes(data[:3])
        calls.append(len(chunk))
        return real_write(fd, chunk)

    monkeypatch.setattr(lifecycle.os, "write", partial_write)
    with store._exclusive_writer(REPOSITORY):
        payload = json.loads(store._lock_path(REPOSITORY).read_text("ascii"))
        assert payload["hostname"] == "host-a"
    assert len(calls) > 1
    assert not store._lock_path(REPOSITORY).exists()


def test_zero_progress_lock_write_fails_closed_and_cleans_up(tmp_path, monkeypatch):
    import daedalus.twin.lifecycle as lifecycle

    store = AtomicProjectTwinLifecycleStore(tmp_path, hostname="host-a")
    monkeypatch.setattr(lifecycle.os, "write", lambda fd, data: 0)

    with pytest.raises(ProjectTwinContractError, match="made no progress"):
        with store._exclusive_writer(REPOSITORY):
            pass
    assert not store._lock_path(REPOSITORY).exists()


def test_lock_directory_entries_are_fsynced_on_create_and_remove(tmp_path, monkeypatch):
    import stat
    import daedalus.twin.lifecycle as lifecycle

    store = AtomicProjectTwinLifecycleStore(tmp_path, hostname="host-a")
    real_fsync = os.fsync
    directory_fsyncs = []

    def record_fsync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            directory_fsyncs.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr(lifecycle.os, "fsync", record_fsync)
    with store._exclusive_writer(REPOSITORY):
        assert store._lock_path(REPOSITORY).exists()

    assert len(directory_fsyncs) >= 2
    assert not store._lock_path(REPOSITORY).exists()


def test_reclaimed_lock_removal_is_directory_fsynced(tmp_path, monkeypatch):
    import stat
    import daedalus.twin.lifecycle as lifecycle

    store = AtomicProjectTwinLifecycleStore(
        tmp_path, hostname="host-a", owner_alive=lambda pid: False
    )
    _write_lock(store, _payload())
    real_fsync = os.fsync
    directory_fsyncs = []

    def record_fsync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            directory_fsyncs.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr(lifecycle.os, "fsync", record_fsync)
    with store._exclusive_writer(REPOSITORY):
        pass

    assert len(directory_fsyncs) >= 3
    assert not store._lock_path(REPOSITORY).exists()
