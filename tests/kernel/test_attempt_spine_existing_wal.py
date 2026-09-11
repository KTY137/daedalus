"""Live read admission uses the existing canonical store, without repairing it."""
from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from daedalus.kernel.attempt_contracts import AttemptStateError
from daedalus.kernel.attempt_spine_reader import read_attempt_intents
from daedalus.spine.ledger import SpineLedger


EFFECT_KEY = "attempt-lifecycle:existing-wal-read"


@pytest.fixture
def live_spine(tmp_path):
    spine = SpineLedger(tmp_path / "live" / "spine.sqlite3")
    spine._conn.execute("PRAGMA wal_autocheckpoint=0")
    intent = spine.record_intent(
        "attempt.lifecycle",
        {"start": {"started_at": datetime.now(timezone.utc).isoformat()}},
        effect_key=EFFECT_KEY,
    )
    try:
        yield spine, intent
    finally:
        spine.close()


def _files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_immutable_default_still_ignores_live_wal(live_spine):
    spine, _ = live_spine
    root = Path(spine.path).parent
    before = _files(root)
    with pytest.raises(AttemptStateError, match="cannot read attempt lifecycle"):
        read_attempt_intents(spine.path, immutable=True)
    assert _files(root) == before


def test_checkpointed_existing_wal_read_is_byte_inert(live_spine):
    spine, intent = live_spine
    spine.close()
    root = Path(spine.path).parent
    before = _files(root)
    assert set(before) == {"spine.sqlite3"}
    result = read_attempt_intents(spine.path, immutable=True, existing_wal=True)
    assert [row.id for row in result] == [intent.id]
    assert _files(root) == before


def test_empty_initialized_wal_read_preserves_durable_bytes(live_spine):
    spine, intent = live_spine
    spine._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    root = Path(spine.path).parent
    before = _files(root)
    assert before["spine.sqlite3-wal"] == b""
    result = read_attempt_intents(spine.path, existing_wal=True)
    assert [row.id for row in result] == [intent.id]
    after = _files(root)
    assert set(after) == set(before)
    assert after["spine.sqlite3"] == before["spine.sqlite3"]
    assert after["spine.sqlite3-wal"] == before["spine.sqlite3-wal"]


def test_valid_retained_pair_without_keeper_allows_transient_shm_reconstruction(
    tmp_path, live_spine,
):
    spine, intent = live_spine
    root = tmp_path / "retained-pair-without-keeper"
    root.mkdir()
    database = root / "spine.sqlite3"
    # No SQLite connection has ever been opened on this separate retained
    # pair. Its first reader may reconstruct the existing transient SHM index.
    for suffix in ("", "-wal", "-shm"):
        shutil.copyfile(str(spine.path) + suffix, str(database) + suffix)
    before = _files(root)
    assert set(before) == {"spine.sqlite3", "spine.sqlite3-wal", "spine.sqlite3-shm"}
    result = read_attempt_intents(database, immutable=True, existing_wal=True)
    assert [row.id for row in result] == [intent.id]
    assert [row.state for row in result] == ["INTENDED"]
    after = _files(root)
    assert set(after) == set(before)
    assert after["spine.sqlite3"] == before["spine.sqlite3"]
    assert after["spine.sqlite3-wal"] == before["spine.sqlite3-wal"]
    # Deliberately impose no byte-equality or read-mark-only restriction on SHM.


@pytest.mark.parametrize("damage", [
    "missing-wal", "missing-shm", "directory-shm", "short-wal", "empty-wal",
    "partial-frame", "bad-magic", "bad-wal-checksum", "short-shm",
    "bad-shm-checksum", "mismatched-shm-copy", "uninitialized-shm",
])
def test_malformed_sidecars_refuse_before_sqlite_can_rebuild_or_ignore_them(
    tmp_path, live_spine, monkeypatch, damage,
):
    spine, _ = live_spine
    root = tmp_path / "retained-copy"
    root.mkdir()
    database = root / "spine.sqlite3"
    for suffix in ("", "-wal", "-shm"):
        shutil.copyfile(str(spine.path) + suffix, str(database) + suffix)
    wal = Path(str(database) + "-wal")
    shm = Path(str(database) + "-shm")
    if damage in {"missing-wal", "missing-shm", "directory-shm"}:
        target = wal if damage == "missing-wal" else shm
        target.unlink()
        if damage == "directory-shm":
            target.mkdir()
    elif damage in {"short-wal", "empty-wal", "partial-frame"}:
        data = wal.read_bytes()
        wal.write_bytes(data[:15] if damage == "short-wal" else b"" if damage == "empty-wal" else data[:-1])
    elif damage in {"bad-magic", "bad-wal-checksum"}:
        data = bytearray(wal.read_bytes())
        data[0 if damage == "bad-magic" else 24] ^= 255
        wal.write_bytes(data)
    else:
        data = bytearray(shm.read_bytes())
        if damage == "short-shm":
            data = data[:96]
        elif damage == "bad-shm-checksum":
            data[40] ^= 255
            data[88] ^= 255
        elif damage == "mismatched-shm-copy":
            data[48] ^= 255
        else:
            data[12] = data[60] = 0
        shm.write_bytes(data)
    before = _files(root)

    def forbidden(*args, **kwargs):
        pytest.fail("invalid sidecars reached SQLite, which can ignore or rebuild them")

    monkeypatch.setattr(sqlite3, "connect", forbidden)
    with pytest.raises(AttemptStateError, match="existing WAL pair is invalid"):
        read_attempt_intents(database, existing_wal=True)
    assert _files(root) == before


def test_live_intent_and_events_use_one_committed_snapshot(live_spine, monkeypatch):
    spine, intent = live_spine
    original_connect = sqlite3.connect
    committed = False

    def trace(sql):
        nonlocal committed
        if "FROM intent_events" in sql and not committed:
            committed = True
            spine.mark_completed(
                intent.id,
                effect_id="observed-after-snapshot",
                result={"receipt": {"completed_at": datetime.now(timezone.utc).isoformat()}},
            )

    def traced_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(trace)
        return connection

    monkeypatch.setattr(sqlite3, "connect", traced_connect)
    snapshot = read_attempt_intents(spine.path, existing_wal=True)
    assert committed
    assert [row.state for row in snapshot] == ["INTENDED"]
    assert snapshot[0].result is None
    latest = read_attempt_intents(spine.path, existing_wal=True)
    assert [row.state for row in latest] == ["COMPLETED"]
    assert latest[0].effect_id == "observed-after-snapshot"
