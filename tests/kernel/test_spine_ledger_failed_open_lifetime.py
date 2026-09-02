"""G1-FIX-06: a ``SpineLedger`` open that raises must not leak its connection.

The constructor is the only place that CAN release it. When ``__init__``
raises, the caller never binds a name to the half-built object, so there is no
``close()`` for anyone else to call -- and the outer Gate-0 opener in
``events/durability.py`` guards its cleanup with ``if "ledger" in locals()``,
which is exactly False in that case. Before the fix a failed open therefore had
no reaper at all and the handle waited on the garbage collector.

TWO INDEPENDENT SIGNALS, deliberately:

* the ``-wal``/``-shm`` companions, which exist exactly while a connection is
  open -- but which are VACUOUS for a failure that dies before WAL is ever
  established, so they are only asserted where a positive control proves they
  were created in the first place; and
* a rename of the database file, which Windows refuses with a sharing
  violation while a handle is open. ``test_the_rename_probe_detects_a_handle``
  is the control that keeps this from degrading into an assertion that rename
  always works.

NOTHING HERE MAY CALL ``gc.collect()`` BEFORE ASSERTING ABSENCE. Collecting
finalizes the leaked connection and makes these tests pass against the broken
tree. Note the opposite is also load-bearing and is why these are
deterministic: ``pytest.raises`` retains the traceback, which retains the
``__init__`` frame, which retains ``self`` -- so on an unfixed tree the leaked
connection is guaranteed to still be alive when the assertion runs.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from daedalus.kernel.events.durability import (
    Gate0DurabilityError,
    open_gate0_spine_writer,
)
from daedalus.kernel.events.ledger import SpineLedger


# --------------------------------------------------------------------------- #
# genuine failure shapes -- no monkeypatched method raises anywhere in here     #
# --------------------------------------------------------------------------- #
def _seed_foreign_intents_table(path: Path) -> None:
    """A real SQLite file carrying an ``intents`` table of a FOREIGN shape.

    This is the ledger pointed at the wrong database -- a path mistake, not a
    contrivance. It fails deep in ``_migrate``: ``_add_missing_columns`` sees a
    non-empty ``table_info`` and adds ``trace_id``, ``CREATE TABLE IF NOT
    EXISTS intents`` is then a no-op, and ``CREATE INDEX ... ON
    intents(effect_key)`` finds no such column.

    Crucially it fails AFTER ``journal_mode=WAL`` succeeded, so this shape has
    real ``-wal``/``-shm`` companions to lose.
    """
    seed = sqlite3.connect(str(path))
    try:
        seed.execute("CREATE TABLE intents (id INTEGER PRIMARY KEY)")
        seed.commit()
    finally:
        seed.close()


def _seed_not_a_database(path: Path) -> None:
    """A file that survives ``connect()`` and dies on the first file access.

    ``connect()`` is lazy about the file, and ``PRAGMA busy_timeout`` is pure
    connection state, so the open gets all the way to
    ``journal_mode=WAL`` before raising ``file is not a database`` -- the
    corrupt-cache shape. WAL is never established here, which is why this
    test asserts the handle and not the companions.
    """
    path.write_bytes(b"this file is not a database" * 64)


def _rename_is_blocked(path: Path) -> bool:
    """True when an open handle prevents renaming ``path``. Renames back."""
    moved = path.with_name(path.name + ".moved")
    try:
        os.rename(path, moved)
    except OSError:
        return True
    os.rename(moved, path)
    return False


# --------------------------------------------------------------------------- #
# the control: prove the probe can see a handle at all                         #
# --------------------------------------------------------------------------- #
def test_the_rename_probe_detects_a_handle(tmp_path: Path) -> None:
    """Without this, every assertion below could pass by rename always working."""
    db = tmp_path / "control.db"
    ledger = SpineLedger(db)
    try:
        assert _rename_is_blocked(db), (
            "the rename probe cannot see an OPEN ledger's handle, so its "
            "verdict about a failed open proves nothing on this platform"
        )
        assert db.with_name("control.db-wal").exists()
        assert db.with_name("control.db-shm").exists()
    finally:
        ledger.close()

    assert not _rename_is_blocked(db)
    assert not db.with_name("control.db-wal").exists()
    assert not db.with_name("control.db-shm").exists()


# --------------------------------------------------------------------------- #
# the guarded behaviour                                                        #
# --------------------------------------------------------------------------- #
def test_failed_migration_releases_the_connection_and_its_companions(
    tmp_path: Path,
) -> None:
    db = tmp_path / "foreign.db"
    _seed_foreign_intents_table(db)

    with pytest.raises(sqlite3.OperationalError) as excinfo:
        SpineLedger(db)
    # The diagnosis survives the cleanup; it is not replaced by a close error.
    assert "effect_key" in str(excinfo.value)

    assert not db.with_name("foreign.db-wal").exists(), (
        "the WAL companion outlived the failed open, so the connection is "
        "still open with no reaper"
    )
    assert not db.with_name("foreign.db-shm").exists()
    assert not _rename_is_blocked(db), (
        "the database file is still held by the connection a raising "
        "__init__ opened"
    )


def test_failed_pragma_on_a_non_database_releases_the_connection(
    tmp_path: Path,
) -> None:
    db = tmp_path / "corrupt.db"
    _seed_not_a_database(db)

    with pytest.raises(sqlite3.DatabaseError) as excinfo:
        SpineLedger(db)
    assert "not a database" in str(excinfo.value)

    # NOT asserted here: the absence of -wal/-shm. This failure happens
    # BEFORE journal_mode=WAL takes effect, so they never exist and their
    # absence would be true on a leaking tree too.
    assert not db.with_name("corrupt.db-wal").exists(), "guard premise changed"
    assert not _rename_is_blocked(db), (
        "the corrupt database file is still held by the connection a raising "
        "__init__ opened"
    )


def test_gate0_writer_open_does_not_leak_when_the_constructor_raises(
    tmp_path: Path,
) -> None:
    """The outer opener cannot compensate, so this only passes via the fix.

    ``open_gate0_spine_writer`` closes with ``if "ledger" in locals()``. That
    name is unbound when ``SpineLedger.__init__`` is the frame that raised, so
    the handle survives this call unless the constructor released it itself.
    """
    db = tmp_path / "gate0.db"
    _seed_foreign_intents_table(db)

    with pytest.raises(Gate0DurabilityError):
        open_gate0_spine_writer(db)

    assert not db.with_name("gate0.db-wal").exists()
    assert not db.with_name("gate0.db-shm").exists()
    assert not _rename_is_blocked(db)


def test_a_successful_open_is_unchanged(tmp_path: Path) -> None:
    """The handler must not fire on the happy path or weaken what it produces."""
    db = tmp_path / "ok.db"
    ledger = SpineLedger(db)
    try:
        found = ledger.pragmas()
        assert found["journal_mode"].lower() == "wal"
        assert found["foreign_keys"] == 1
        intent = ledger.record_intent("probe", {"a": 1}, effect_key="k")
        assert intent.id > 0
    finally:
        ledger.close()


# --------------------------------------------------------------------------- #
# the read-only branch                                                         #
# --------------------------------------------------------------------------- #
def test_read_only_open_fails_before_a_connection_exists(tmp_path: Path) -> None:
    """Pins the measurement the read-only handler's comment rests on.

    ``mode=ro`` opens eagerly, so the absent-file failure happens INSIDE
    ``connect()`` with no handle in existence -- there is nothing for the
    constructor to leak, which is why no red-provable read-only leak test
    exists in this file. If a future change makes this raise later than
    ``connect()``, this test fails and that claim must be re-measured.
    """
    missing = tmp_path / "never-created.db"
    with pytest.raises(sqlite3.OperationalError) as excinfo:
        SpineLedger(missing, read_only=True)
    assert "unable to open database file" in str(excinfo.value)
    assert not missing.exists()


def test_read_only_pragmas_do_not_touch_the_file(tmp_path: Path) -> None:
    """The other half of that measurement: neither pragma reads the database.

    A garbage file gets a fully constructed read-only ledger, because
    ``busy_timeout`` and ``query_only`` are per-connection state. That is why
    the read-only handler is documented as structural rather than as a closed
    leak.
    """
    db = tmp_path / "garbage-ro.db"
    _seed_not_a_database(db)
    ledger = SpineLedger(db, read_only=True)
    try:
        assert ledger.read_only is True
    finally:
        ledger.close()
