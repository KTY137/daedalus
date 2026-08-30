# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ast
import inspect
import sqlite3

import pytest

import daedalus.kernel.attempt_ledger as attempt_ledger_module
from daedalus.kernel.attempts import AttemptLedger, AttemptStateError
from daedalus.kernel.source_trees import SourceTreeStore
from daedalus.spine.durability import (
    Gate0DurabilityError,
    inspect_gate0_durability,
)
from daedalus.spine.ledger import SpineLedger


def _store(tmp_path) -> SourceTreeStore:
    return SourceTreeStore(tmp_path / "cas")


def test_attempt_ledger_admits_exact_writer_at_full_durability(tmp_path) -> None:
    ledger = AttemptLedger(tmp_path / "state" / "spine.sqlite3", _store(tmp_path))
    try:
        assert ledger.durability_status.satisfied is True
        assert ledger.durability_status.synchronous == 2
        assert inspect_gate0_durability(ledger.spine) == ledger.durability_status
        index = ledger.spine._conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' "
            "AND name='idx_attempt_lifecycle_effect_key'"
        ).fetchone()
        assert index is not None
        assert "WHERE kind = 'attempt.lifecycle'" in index[0]
    finally:
        ledger.spine.close()


def test_injected_legacy_writer_is_hardened_before_attempt_schema_write(tmp_path) -> None:
    spine = SpineLedger(tmp_path / "state" / "spine.sqlite3")
    try:
        assert inspect_gate0_durability(spine).synchronous == 1
        ledger = AttemptLedger(spine, _store(tmp_path))
        assert ledger.spine is spine
        assert inspect_gate0_durability(spine).satisfied is True
        assert inspect_gate0_durability(spine).synchronous == 2
    finally:
        spine.close()


def test_attempt_index_uses_no_second_sqlite_writer_connection(
    tmp_path, monkeypatch
) -> None:
    spine = SpineLedger(tmp_path / "state" / "spine.sqlite3")

    def forbidden_connection(*args, **kwargs):
        raise AssertionError("Attempt admission opened a second SQLite writer")

    try:
        monkeypatch.setattr(
            attempt_ledger_module.sqlite3,
            "connect",
            forbidden_connection,
        )
        ledger = AttemptLedger(spine, _store(tmp_path))
        assert ledger.spine is spine
        assert ledger.durability_status.satisfied is True
    finally:
        spine.close()


def test_durability_refusal_precedes_attempt_index_install(
    tmp_path, monkeypatch
) -> None:
    path = tmp_path / "state" / "spine.sqlite3"
    spine = SpineLedger(path)

    def refuse(_ledger):
        raise Gate0DurabilityError("injected weak readback")

    try:
        monkeypatch.setattr(
            attempt_ledger_module,
            "enforce_gate0_durability",
            refuse,
        )
        with pytest.raises(AttemptStateError, match="durability profile"):
            AttemptLedger(spine, _store(tmp_path))
        index = spine._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' "
            "AND name='idx_attempt_lifecycle_effect_key'"
        ).fetchone()
        assert index is None
    finally:
        spine.close()


def test_read_only_spine_is_refused_without_attempt_schema_mutation(tmp_path) -> None:
    path = tmp_path / "state" / "spine.sqlite3"
    writer = SpineLedger(path)
    writer.close()

    reader = SpineLedger(path, read_only=True)
    try:
        with pytest.raises(AttemptStateError, match="writable"):
            AttemptLedger(reader, _store(tmp_path))
    finally:
        reader.close()

    with sqlite3.connect(path) as connection:
        index = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' "
            "AND name='idx_attempt_lifecycle_effect_key'"
        ).fetchone()
    assert index is None


def test_source_orders_admission_before_schema_and_reuses_canonical_transaction() -> None:
    source = inspect.getsource(attempt_ledger_module.AttemptLedger)
    tree = ast.parse(source)
    init = next(
        node
        for node in tree.body[0].body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "__init__"
    )
    calls = [
        node
        for node in ast.walk(init)
        if isinstance(node, ast.Call)
    ]
    enforce_line = next(
        call.lineno
        for call in calls
        if isinstance(call.func, ast.Name)
        and call.func.id == "enforce_gate0_durability"
    )
    install_line = next(
        call.lineno
        for call in calls
        if isinstance(call.func, ast.Attribute)
        and call.func.attr == "_install_single_start_invariant"
    )
    assert enforce_line < install_line

    install = inspect.getsource(
        attempt_ledger_module.AttemptLedger._install_single_start_invariant
    )
    assert "self.spine._txn()" in install
    assert "sqlite3.connect" not in install
    assert "PRAGMA synchronous" not in install
