from __future__ import annotations

import contextlib
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
from daedalus.spine.ledger import SpineError, SpineLedger


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


def test_factory_normalizes_canonical_opening_failure(tmp_path, monkeypatch) -> None:
    def fail_open(*args, **kwargs):
        raise SpineError("injected non-WAL opening failure")

    monkeypatch.setattr(durability, "_Gate0OpeningSpineLedger", fail_open)
    with pytest.raises(Gate0DurabilityError, match="could not be opened") as raised:
        durability.open_gate0_spine_writer(tmp_path / "state" / "spine.sqlite3")
    assert isinstance(raised.value.__cause__, SpineError)


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


class _ProbeBase:
    """Not ``object``: a direct ``object`` subclass also gets ``__dict__`` and
    ``__weakref__`` descriptors, which the class under test inherits instead."""


class _CompilerMetadataProbe(_ProbeBase):
    """Shaped exactly like the class under test: a docstring and one method."""

    def _apply_pragmas(self) -> None:  # pragma: no cover -- never called
        raise NotImplementedError


#: What CPython writes into ANY class body's ``__dict__`` on its own, MEASURED
#: from the probe above instead of enumerated by hand.
#:
#: The hand-written list this replaces was ``{"__module__", "__doc__"}``, and it
#: had been red since the day it was written (2026-08-04, bde0d0e1) on this
#: repository's own interpreter: CPython 3.13 also emits ``__firstlineno__`` and
#: ``__static_attributes__`` for every class, so the assertion was measuring the
#: compiler, not the subclass. Adding those two names to the literal set would
#: have gone green while re-arming the same trap for 3.14 -- and widening a
#: guard's expected set until it passes is the shape AGENTS.md calls a
#: release-blocking defect. Deriving the baseline keeps the claim the test
#: actually makes: this subclass adds ONE method and nothing else.
_COMPILER_METADATA = frozenset(_CompilerMetadataProbe.__dict__) - {"_apply_pragmas"}

# Carried over from the packet that fixed this same defect independently
# (G1-FIX-04, merged as 41e1b265): the probe may only ever excuse
# interpreter-owned dunders. Two agents reached the derive-it-from-a-probe
# answer without seeing each other's work, which is the strongest evidence
# available that it is the right one -- but a probe is only as good as what
# is allowed into it, and a future author who adds a real member here would
# silently widen the guard instead of arming it.
assert all(n.startswith("__") and n.endswith("__") for n in _COMPILER_METADATA), (
    f"the probe excused a non-dunder: {sorted(_COMPILER_METADATA)}"
)


def test_factory_is_only_an_opening_profile_not_a_second_ledger_authority() -> None:
    subclass = durability._Gate0OpeningSpineLedger
    assert subclass.__bases__ == (SpineLedger,)
    assert set(subclass.__dict__) - {"_apply_pragmas"} == _COMPILER_METADATA
    assert "__init__" not in subclass.__dict__
    source = inspect.getsource(subclass._apply_pragmas)
    assert "super()._apply_pragmas()" in source
    assert source.count("PRAGMA synchronous=FULL") == 1
    assert "CREATE TABLE" not in source
    assert "record_intent" not in subclass.__dict__
    assert "_Gate0OpeningSpineLedger" not in durability.__all__


def test_the_opening_profile_check_can_still_go_red() -> None:
    """The red proof for the derived baseline one test up.

    A baseline measured from the interpreter is only worth having if it still
    refuses the thing the guard exists to refuse. This is the second ledger
    authority the real subclass must never become; the same comparison rejects
    it, and rejects it for the added member rather than for a dunder.
    """

    class _SecondLedgerAuthority(SpineLedger):
        """A subclass that grew a write path of its own."""

        def _apply_pragmas(self) -> None:  # pragma: no cover -- never called
            raise NotImplementedError

        def record_intent(self, *args, **kwargs):  # pragma: no cover
            raise NotImplementedError

    leaked = set(_SecondLedgerAuthority.__dict__) - {"_apply_pragmas"}
    assert leaked != _COMPILER_METADATA
    assert leaked - _COMPILER_METADATA == {"record_intent"}


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

    with contextlib.closing(sqlite3.connect(path)) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT COUNT(*) FROM intents").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM intent_events").fetchone()[0] == 2
