from __future__ import annotations

import dataclasses
import inspect
import sqlite3

import pytest

import daedalus.spine.durability as durability
from daedalus.kernel import SourceTreeStore
from daedalus.kernel.attempts import AttemptLedger
from daedalus.spine import open_gate0_spine_writer
from daedalus.spine.durability import (
    Gate0DurabilityError,
    inspect_gate0_durability,
)
from daedalus.spine.ledger import SpineLedger


def test_factory_enters_full_before_generic_schema_migration(
    tmp_path, monkeypatch
) -> None:
    observed: list[int] = []
    real_migrate = SpineLedger._migrate

    def observed_migrate(self) -> None:
        observed.append(
            int(self._conn.execute("PRAGMA synchronous").fetchone()[0])
        )
        real_migrate(self)

    monkeypatch.setattr(SpineLedger, "_migrate", observed_migrate)
    writer = open_gate0_spine_writer(tmp_path / "state" / "spine.sqlite3")
    try:
        assert isinstance(writer, SpineLedger)
        assert observed == [2]
        assert inspect_gate0_durability(writer).satisfied is True
        tables = {
            row[0]
            for row in writer._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"spine_meta", "intents", "intent_events"} <= tables
        assert not any(name.startswith("gate0_") for name in tables)
    finally:
        writer.close()


def test_factory_does_not_change_legacy_default(tmp_path) -> None:
    legacy = SpineLedger(tmp_path / "legacy.sqlite3")
    try:
        assert inspect_gate0_durability(legacy).synchronous == 1
        assert inspect_gate0_durability(legacy).satisfied is False
    finally:
        legacy.close()

    admitted = open_gate0_spine_writer(tmp_path / "admitted.sqlite3")
    try:
        assert inspect_gate0_durability(admitted).synchronous == 2
        assert inspect_gate0_durability(admitted).satisfied is True
    finally:
        admitted.close()


def test_factory_clamps_timeout_and_refuses_malformed_timeout(tmp_path) -> None:
    writer = open_gate0_spine_writer(
        tmp_path / "state" / "spine.sqlite3",
        busy_timeout_ms=1,
    )
    try:
        assert inspect_gate0_durability(writer).busy_timeout_ms >= 30000
    finally:
        writer.close()

    with pytest.raises(Gate0DurabilityError, match="integer"):
        open_gate0_spine_writer(tmp_path / "bad.sqlite3", busy_timeout_ms="bad")


def test_factory_closes_writer_when_final_readback_is_weak(
    tmp_path, monkeypatch
) -> None:
    real_inspect = durability.inspect_gate0_durability
    closed: list[object] = []
    real_close = durability._Gate0OpeningSpineLedger.close

    def weak_readback(ledger):
        return dataclasses.replace(
            real_inspect(ledger),
            synchronous=1,
            satisfied=False,
        )

    def tracked_close(self) -> None:
        closed.append(self)
        real_close(self)

    monkeypatch.setattr(durability, "inspect_gate0_durability", weak_readback)
    monkeypatch.setattr(
        durability._Gate0OpeningSpineLedger,
        "close",
        tracked_close,
    )
    with pytest.raises(Gate0DurabilityError, match="opening readback"):
        open_gate0_spine_writer(tmp_path / "state" / "spine.sqlite3")
    assert len(closed) == 1


def test_attempt_path_uses_pre_migration_factory(tmp_path, monkeypatch) -> None:
    calls: list[object] = []
    real_open = durability.open_gate0_spine_writer

    def tracked_open(path, *, busy_timeout_ms=30000):
        calls.append(path)
        return real_open(path, busy_timeout_ms=busy_timeout_ms)

    import daedalus.kernel.attempt_ledger as attempt_module

    monkeypatch.setattr(attempt_module, "open_gate0_spine_writer", tracked_open)
    ledger = AttemptLedger(
        tmp_path / "state" / "attempts.sqlite3",
        SourceTreeStore(tmp_path / "cas"),
    )
    try:
        assert calls == [tmp_path / "state" / "attempts.sqlite3"]
        assert ledger.durability_status.satisfied is True
        assert inspect_gate0_durability(ledger.spine).synchronous == 2
    finally:
        ledger.spine.close()


def test_factory_is_only_an_opening_profile_not_a_second_ledger_authority() -> None:
    subclass = durability._Gate0OpeningSpineLedger
    assert subclass.__bases__ == (SpineLedger,)
    assert set(subclass.__dict__) - {
        "__module__",
        "__doc__",
        "_apply_pragmas",
    } == set()
    source = inspect.getsource(subclass._apply_pragmas)
    assert "super()._apply_pragmas()" in source
    assert source.count("PRAGMA synchronous=FULL") == 1
    assert "CREATE TABLE" not in source
    assert "record_intent" not in subclass.__dict__
    assert "_Gate0OpeningSpineLedger" not in durability.__all__


def test_factory_writer_remains_compatible_with_canonical_transactions(tmp_path) -> None:
    path = tmp_path / "state" / "spine.sqlite3"
    writer = open_gate0_spine_writer(path)
    try:
        intent = writer.record_intent(
            "factory.test",
            {"value": 1},
            effect_key="factory:test",
        )
        writer.mark_completed(intent.id, effect_id="effect-1", result={"ok": True})
    finally:
        writer.close()

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT COUNT(*) FROM intents").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM intent_events").fetchone()[0] == 2
