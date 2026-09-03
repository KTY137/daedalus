from __future__ import annotations

import dataclasses
import os
import runpy
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from daedalus.kernel.source_trees import SourceTreeStore
from daedalus.runtimes.provider.target_receipt_ledger import (
    ProviderTargetReceiptLedger,
    ProviderTargetReceiptRetentionBindingError,
    ProviderTargetReceiptRetentionStateError,
)
from daedalus.spine.ledger import SpineLedger

_HELPERS = runpy.run_path(
    str(Path(__file__).with_name("test_provider_target_receipt_ledger.py"))
)
_fixture = _HELPERS["_fixture"]
_issue = _HELPERS["_issue"]
_ledger = _HELPERS["_ledger"]
_retain = _HELPERS["_retain"]
_INDEX = "idx_provider_target_verification_receipt_effect_key"


def _index_sql(spine):
    with spine._lock:
        row = spine._conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name=?",
            (_INDEX,),
        ).fetchone()
    return None if row is None else str(row[0])


def _rows(spine, receipt):
    return spine.resolve_by_effect(
        "provider-target-verification-receipt:" + receipt.digest
    )


def test_invalid_receipt_cannot_install_retention_schema(tmp_path) -> None:
    fixture = _fixture(tmp_path / "fixture")
    receipt = dataclasses.replace(_issue(fixture), signature_sha256="0" * 64)
    _, spine, ledger = _ledger(tmp_path, fixture)
    assert _index_sql(spine) is None

    with pytest.raises(
        ProviderTargetReceiptRetentionBindingError,
        match="did not authenticate",
    ):
        _retain(ledger, receipt, fixture)

    assert _index_sql(spine) is None
    spine.close()


def test_foreign_same_name_index_is_not_trusted(tmp_path) -> None:
    fixture = _fixture(tmp_path / "fixture")
    receipt = _issue(fixture)
    _, spine, ledger = _ledger(tmp_path, fixture)
    with spine._txn() as connection:
        connection.execute(f"CREATE INDEX {_INDEX} ON intents(kind)")

    with pytest.raises(
        ProviderTargetReceiptRetentionStateError,
        match="foreign definition",
    ):
        _retain(ledger, receipt, fixture)

    assert "ON intents(kind)" in _index_sql(spine)
    spine.close()


def test_trace_substitution_refuses_completed_replay(tmp_path) -> None:
    fixture = _fixture(tmp_path / "fixture")
    receipt = _issue(fixture)
    _, spine, ledger = _ledger(tmp_path, fixture)
    result = _retain(ledger, receipt, fixture)
    with spine._txn() as connection:
        connection.execute(
            "UPDATE intents SET trace_id=? WHERE id=?",
            ("foreign-execution", result.intent_id),
        )

    with pytest.raises(
        ProviderTargetReceiptRetentionStateError,
        match="trace does not bind execution",
    ):
        _retain(ledger, receipt, fixture)
    spine.close()


def test_second_terminal_event_is_rejected_as_ambiguous(tmp_path) -> None:
    fixture = _fixture(tmp_path / "fixture")
    receipt = _issue(fixture)
    _, spine, ledger = _ledger(tmp_path, fixture)
    result = _retain(ledger, receipt, fixture)
    with spine._txn() as connection:
        connection.execute(
            "INSERT INTO intent_events(intent_id,state,ts,detail) VALUES(?,?,?,?)",
            (
                result.intent_id,
                "COMPLETED",
                "2026-08-05T02:00:01+00:00",
                '{"effect_id":null,"result":null}',
            ),
        )

    with pytest.raises(
        ProviderTargetReceiptRetentionStateError,
        match="event sequence is invalid",
    ):
        _retain(ledger, receipt, fixture)
    spine.close()


def test_post_commit_intent_error_recovers_exact_persisted_winner(
    tmp_path,
    monkeypatch,
) -> None:
    fixture = _fixture(tmp_path / "fixture")
    receipt = _issue(fixture)
    _, spine, ledger = _ledger(tmp_path, fixture)
    original = spine.record_intent

    def commit_then_disconnect(*args, **kwargs):
        original(*args, **kwargs)
        raise sqlite3.OperationalError("simulated disconnect after intent commit")

    monkeypatch.setattr(spine, "record_intent", commit_then_disconnect)
    result = _retain(ledger, receipt, fixture)

    assert result.executed is True
    rows = _rows(spine, receipt)
    assert len(rows) == 1
    assert rows[0].state == "COMPLETED"
    spine.close()


def test_pre_commit_terminal_error_stays_pending_and_replays(
    tmp_path,
    monkeypatch,
) -> None:
    fixture = _fixture(tmp_path / "fixture")
    receipt = _issue(fixture)
    _, spine, ledger = _ledger(tmp_path, fixture)
    original = spine.mark_completed

    def disconnect_before_commit(*args, **kwargs):
        raise sqlite3.OperationalError("simulated disconnect before terminal commit")

    monkeypatch.setattr(spine, "mark_completed", disconnect_before_commit)
    with pytest.raises(
        ProviderTargetReceiptRetentionStateError,
        match="terminal persistence is unresolved and requires replay",
    ):
        _retain(ledger, receipt, fixture)
    pending = _rows(spine, receipt)
    assert len(pending) == 1
    assert pending[0].state == "INTENDED"

    monkeypatch.setattr(spine, "mark_completed", original)
    replay = _retain(ledger, receipt, fixture)
    assert replay.executed is True
    assert _rows(spine, receipt)[0].state == "COMPLETED"
    spine.close()


def test_post_commit_terminal_error_is_reconciled_without_duplicate(
    tmp_path,
    monkeypatch,
) -> None:
    fixture = _fixture(tmp_path / "fixture")
    receipt = _issue(fixture)
    _, spine, ledger = _ledger(tmp_path, fixture)
    original = spine.mark_completed

    def commit_then_disconnect(*args, **kwargs):
        original(*args, **kwargs)
        raise sqlite3.OperationalError("simulated disconnect after terminal commit")

    monkeypatch.setattr(spine, "mark_completed", commit_then_disconnect)
    result = _retain(ledger, receipt, fixture)

    assert result.executed is True
    rows = _rows(spine, receipt)
    assert len(rows) == 1
    assert rows[0].state == "COMPLETED"
    spine.close()


def test_concurrent_same_subject_keeps_one_event_store_identity(tmp_path) -> None:
    fixture = _fixture(tmp_path / "fixture")
    receipt = _issue(fixture)
    _, spine, ledger = _ledger(tmp_path, fixture)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: _retain(ledger, receipt, fixture),
                range(2),
            )
        )

    assert {item.intent_id for item in results} == {results[0].intent_id}
    assert {item.artifact for item in results} == {results[0].artifact}
    rows = _rows(spine, receipt)
    assert len(rows) == 1
    assert rows[0].state == "COMPLETED"
    spine.close()


def test_event_store_hardlink_alias_into_primary_refuses_at_construction(
    tmp_path,
) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    source_store = SourceTreeStore(tmp_path / "cas")
    spine = SpineLedger(tmp_path / "state" / "spine.sqlite3")
    os.link(spine.path, primary / "spine.sqlite3")

    try:
        with pytest.raises(
            ProviderTargetReceiptRetentionBindingError,
            match="one filesystem identity",
        ):
            ProviderTargetReceiptLedger(
                spine,
                source_store,
                primary_checkout=primary,
            )
    finally:
        spine.close()


def test_late_event_store_hardlink_alias_refuses_before_schema_write(
    tmp_path,
) -> None:
    fixture = _fixture(tmp_path / "fixture")
    receipt = _issue(fixture)
    primary, spine, ledger = _ledger(tmp_path, fixture)
    os.link(spine.path, primary / "spine.sqlite3")
    assert _index_sql(spine) is None

    try:
        with pytest.raises(
            ProviderTargetReceiptRetentionBindingError,
            match="one filesystem identity",
        ):
            _retain(ledger, receipt, fixture)
        assert _index_sql(spine) is None
        assert _rows(spine, receipt) == []
    finally:
        spine.close()


def test_late_event_store_wal_alias_refuses_before_schema_write(tmp_path) -> None:
    fixture = _fixture(tmp_path / "fixture")
    receipt = _issue(fixture)
    primary, spine, ledger = _ledger(tmp_path, fixture)
    wal_path = Path(f"{spine.path}-wal")
    assert wal_path.is_file()
    os.link(wal_path, primary / "spine.sqlite3-wal")
    assert _index_sql(spine) is None

    try:
        with pytest.raises(
            ProviderTargetReceiptRetentionBindingError,
            match="one filesystem identity",
        ):
            _retain(ledger, receipt, fixture)
        assert _index_sql(spine) is None
        assert _rows(spine, receipt) == []
    finally:
        spine.close()
