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
