from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import sqlite3
import subprocess
import sys

import pytest

import daedalus.spine.durability as durability
from daedalus.spine.durability import (
    Gate0DurabilityError,
    enforce_gate0_durability,
    inspect_gate0_durability,
)
from daedalus.spine.ledger import ROOT, SpineLedger


def _sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_legacy_connection_is_honestly_not_gate0_durable(tmp_path) -> None:
    ledger = SpineLedger(tmp_path / "spine.sqlite3")
    try:
        status = inspect_gate0_durability(ledger)
        assert status.schema == "daedalus-gate0-spine-durability/1"
        assert status.journal_mode == "wal"
        assert status.synchronous == 1  # legacy NORMAL profile
        assert status.foreign_keys == 1
        assert status.satisfied is False
        assert status.to_dict()["satisfied"] is False
    finally:
        ledger.close()


def test_profile_hardens_the_exact_existing_connection_without_new_store(tmp_path) -> None:
    path = tmp_path / "state" / "spine.sqlite3"
    ledger = SpineLedger(path)
    try:
        first = ledger.record_intent(
            "durability.preexisting",
            {"value": 1},
            effect_key="durability:first",
        )
        database_before = path.resolve()
        status = enforce_gate0_durability(ledger)

        assert status.satisfied is True
        assert status.journal_mode == "wal"
        assert status.synchronous == 2  # FULL
        assert status.busy_timeout_ms >= 30000
        assert status.foreign_keys == 1
        assert path.resolve() == database_before
        assert ledger.get(first.id).payload == {"value": 1}

        second = ledger.record_intent(
            "durability.hardened",
            {"value": 2},
            effect_key="durability:second",
        )
        assert ledger.get(second.id).state == "INTENDED"
    finally:
        ledger.close()

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT COUNT(*) FROM intents").fetchone()[0] == 2
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert "intents" in tables
    assert "intent_events" in tables
    assert not any(name.startswith("gate0_") for name in tables)


def test_profile_is_idempotent_and_machine_readback_is_stable(tmp_path) -> None:
    ledger = SpineLedger(tmp_path / "spine.sqlite3")
    try:
        first = enforce_gate0_durability(ledger)
        second = enforce_gate0_durability(ledger)
        assert first == second
        assert json.dumps(first.to_dict(), sort_keys=True) == json.dumps(
            second.to_dict(), sort_keys=True
        )
    finally:
        ledger.close()


def test_each_new_writer_connection_must_explicitly_apply_profile(tmp_path) -> None:
    path = tmp_path / "spine.sqlite3"
    first = SpineLedger(path)
    try:
        assert enforce_gate0_durability(first).synchronous == 2
    finally:
        first.close()

    second = SpineLedger(path)
    try:
        # synchronous is connection-local; no hidden global claim survives.
        assert inspect_gate0_durability(second).synchronous == 1
        assert inspect_gate0_durability(second).satisfied is False
        assert enforce_gate0_durability(second).satisfied is True
    finally:
        second.close()


def test_read_only_connection_can_be_inspected_but_never_hardened_as_writer(
    tmp_path,
) -> None:
    path = tmp_path / "spine.sqlite3"
    writable = SpineLedger(path)
    writable.record_intent("read-only-seed", {"ok": True})
    writable.close()
    before = _sha(path)

    reader = SpineLedger(path, read_only=True)
    try:
        status = inspect_gate0_durability(reader)
        assert status.satisfied is False
        with pytest.raises(Gate0DurabilityError, match="read-only"):
            enforce_gate0_durability(reader)
    finally:
        reader.close()
    assert _sha(path) == before


def test_non_ledger_and_non_wal_connection_are_refused(tmp_path, monkeypatch) -> None:
    with pytest.raises(Gate0DurabilityError, match="SpineLedger"):
        inspect_gate0_durability(object())
    with pytest.raises(Gate0DurabilityError, match="SpineLedger"):
        enforce_gate0_durability(object())

    ledger = SpineLedger(tmp_path / "spine.sqlite3")
    real_read = durability._read_connection_status

    def non_wal(connection):
        return dataclasses.replace(real_read(connection), journal_mode="delete")

    try:
        monkeypatch.setattr(durability, "_read_connection_status", non_wal)
        with pytest.raises(Gate0DurabilityError, match="WAL"):
            enforce_gate0_durability(ledger)
    finally:
        ledger.close()


def test_profile_raises_when_atomic_readback_does_not_confirm_full(
    tmp_path, monkeypatch
) -> None:
    ledger = SpineLedger(tmp_path / "spine.sqlite3")
    real_read = durability._read_connection_status
    calls = 0

    def dishonest_readback(connection):
        nonlocal calls
        calls += 1
        status = real_read(connection)
        if calls > 1:
            return dataclasses.replace(
                status,
                synchronous=1,
                satisfied=False,
            )
        return status

    try:
        monkeypatch.setattr(
            durability, "_read_connection_status", dishonest_readback
        )
        with pytest.raises(Gate0DurabilityError, match="weaker"):
            enforce_gate0_durability(ledger)
    finally:
        ledger.close()


def test_closed_connection_errors_are_normalized(tmp_path) -> None:
    ledger = SpineLedger(tmp_path / "spine.sqlite3")
    ledger.close()
    with pytest.raises(Gate0DurabilityError, match="complete durability readback"):
        inspect_gate0_durability(ledger)
    with pytest.raises(Gate0DurabilityError, match="could not be applied"):
        enforce_gate0_durability(ledger)


_KILL_AFTER_COMMIT = r"""
import os
import sys
from daedalus.spine.durability import enforce_gate0_durability
from daedalus.spine.ledger import SpineLedger
ledger = SpineLedger(sys.argv[1])
status = enforce_gate0_durability(ledger)
assert status.synchronous == 2
ledger.record_intent(
    "durability.killed",
    {"fault": "process-exit"},
    effect_key="durability:killed",
)
sys.stdout.write("committed-full")
sys.stdout.flush()
os._exit(73)
"""


def test_full_profile_intent_survives_unclean_process_exit(tmp_path) -> None:
    path = tmp_path / "state" / "spine.sqlite3"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    process = subprocess.run(
        [sys.executable, "-c", _KILL_AFTER_COMMIT, str(path)],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )
    assert process.returncode == 73, process.stderr
    assert process.stdout == "committed-full"

    survivor = SpineLedger(path)
    try:
        assert enforce_gate0_durability(survivor).satisfied is True
        opened = survivor.resolve_by_effect("durability:killed")
        assert len(opened) == 1
        assert opened[0].payload == {"fault": "process-exit"}
        assert opened[0].state == "INTENDED"
        assert survivor._conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        survivor.close()
