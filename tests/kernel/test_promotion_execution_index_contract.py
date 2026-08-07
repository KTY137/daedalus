from __future__ import annotations

import sqlite3

import pytest

from daedalus.kernel.promotion import PromotionAuthorization
from daedalus.kernel.promotion_execution import (
    PromotionExecutionLedger,
    PromotionExecutionStateError,
)
from daedalus.spine.envelope import canonical_sha
from daedalus.spine.ledger import SpineLedger


REVISION = "a" * 40
TARGET = "b" * 40
CANDIDATE = "c" * 64
EVIDENCE = "d" * 64
CONSUMPTION = "e" * 64
PRIMARY = "f" * 64
INDEX_NAME = "idx_promotion_execution_effect_key"


def authorization() -> PromotionAuthorization:
    body = {
        "promotion_id": "promotion-1",
        "candidate_artifact_sha256": CANDIDATE,
        "evidence_packet_sha256": EVIDENCE,
        "source_revision": REVISION,
        "target_ref": "experimental",
        "live_target_revision": TARGET,
        "approval_consumption_sha256": CONSUMPTION,
    }
    return PromotionAuthorization(
        **body,
        authorization_sha256=canonical_sha(body),
    )


def _prepare(path, index_sql: str) -> None:
    spine = SpineLedger(path)
    spine.close()
    connection = sqlite3.connect(path)
    connection.execute(index_sql)
    connection.commit()
    connection.close()


def _assert_refused(path) -> None:
    ledger = PromotionExecutionLedger(path)
    with pytest.raises(PromotionExecutionStateError, match="strict.*projection"):
        ledger.begin(
            authorization(),
            start_id="promotion-start-1",
            primary_checkout_before_sha256=PRIMARY,
        )
    ledger.close()


def test_same_named_nonunique_index_is_not_trusted(tmp_path) -> None:
    path = tmp_path / "spine.sqlite3"
    _prepare(
        path,
        f"CREATE INDEX {INDEX_NAME} ON intents(effect_key) "
        "WHERE kind = 'promotion.execution'",
    )
    _assert_refused(path)


def test_same_named_nonpartial_index_is_not_trusted(tmp_path) -> None:
    path = tmp_path / "spine.sqlite3"
    _prepare(
        path,
        f"CREATE UNIQUE INDEX {INDEX_NAME} ON intents(effect_key)",
    )
    _assert_refused(path)


def test_same_named_wrong_predicate_is_not_trusted(tmp_path) -> None:
    path = tmp_path / "spine.sqlite3"
    _prepare(
        path,
        f"CREATE UNIQUE INDEX {INDEX_NAME} ON intents(effect_key) "
        "WHERE kind = 'other.lifecycle'",
    )
    _assert_refused(path)


def test_same_named_wrong_column_is_not_trusted(tmp_path) -> None:
    path = tmp_path / "spine.sqlite3"
    _prepare(
        path,
        f"CREATE UNIQUE INDEX {INDEX_NAME} ON intents(kind) "
        "WHERE kind = 'promotion.execution'",
    )
    _assert_refused(path)


def test_exact_index_shape_allows_empty_read_and_first_start(tmp_path) -> None:
    path = tmp_path / "spine.sqlite3"
    ledger = PromotionExecutionLedger(path)
    assert ledger.pending() == ()
    result = ledger.begin(
        authorization(),
        start_id="promotion-start-1",
        primary_checkout_before_sha256=PRIMARY,
    )
    assert result.execute is True
    assert ledger.pending() == (result.start,)
    ledger.close()
