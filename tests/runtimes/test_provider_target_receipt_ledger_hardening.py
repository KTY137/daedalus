from __future__ import annotations

import dataclasses
import runpy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from daedalus.runtimes.provider_target_receipt_ledger import (
    ProviderTargetReceiptRetentionBindingError,
    ProviderTargetReceiptRetentionStateError,
)


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
        connection.execute(
            f"CREATE INDEX {_INDEX} ON intents(kind)"
        )

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
    rows = spine.resolve_by_effect(
        "provider-target-verification-receipt:" + receipt.digest
    )
    assert len(rows) == 1
    assert rows[0].state == "COMPLETED"
    spine.close()
