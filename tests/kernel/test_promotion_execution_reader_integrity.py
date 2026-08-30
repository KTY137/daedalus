# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import sqlite3

import pytest

from daedalus.kernel.promotion import PromotionAuthorization
from daedalus.kernel.promotion_execution import (
    PromotionExecutionLedger,
    PromotionExecutionStateError,
)
from daedalus.spine.envelope import canonical_json, canonical_sha


REVISION = "a" * 40
TARGET = "b" * 40
CANDIDATE = "c" * 64
EVIDENCE = "d" * 64
CONSUMPTION = "e" * 64
PRIMARY = "f" * 64


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


def _started(path):
    auth = authorization()
    ledger = PromotionExecutionLedger(path)
    ledger.begin(
        auth,
        start_id="promotion-start-1",
        primary_checkout_before_sha256=PRIMARY,
    )
    ledger.close()
    return auth


def test_substituted_payload_digest_refuses_before_contract_hydration(tmp_path) -> None:
    path = tmp_path / "spine.sqlite3"
    auth = _started(path)
    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE intents SET payload_sha = ? WHERE kind = 'promotion.execution'",
        ("0" * 64,),
    )
    connection.commit()
    connection.close()

    restarted = PromotionExecutionLedger(path)
    with pytest.raises(PromotionExecutionStateError, match="strict.*projection"):
        restarted.begin(
            auth,
            start_id="promotion-start-1",
            primary_checkout_before_sha256=PRIMARY,
        )
    restarted.close()


def test_start_event_must_bind_exact_payload_digest(tmp_path) -> None:
    path = tmp_path / "spine.sqlite3"
    auth = _started(path)
    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE intent_events SET detail = ? WHERE state = 'INTENDED'",
        (canonical_json({"payload_sha": "0" * 64}),),
    )
    connection.commit()
    connection.close()

    restarted = PromotionExecutionLedger(path)
    with pytest.raises(PromotionExecutionStateError, match="strict.*projection"):
        restarted.begin(
            auth,
            start_id="promotion-start-1",
            primary_checkout_before_sha256=PRIMARY,
        )
    restarted.close()


def test_first_event_must_be_intended(tmp_path) -> None:
    path = tmp_path / "spine.sqlite3"
    auth = _started(path)
    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE intent_events SET state = 'UNKNOWN' WHERE state = 'INTENDED'"
    )
    connection.commit()
    connection.close()

    restarted = PromotionExecutionLedger(path)
    with pytest.raises(PromotionExecutionStateError, match="strict.*projection"):
        restarted.begin(
            auth,
            start_id="promotion-start-1",
            primary_checkout_before_sha256=PRIMARY,
        )
    restarted.close()


def test_start_event_time_must_equal_intent_row_time(tmp_path) -> None:
    path = tmp_path / "spine.sqlite3"
    auth = _started(path)
    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE intent_events SET ts = '2000-01-01T00:00:00+00:00' "
        "WHERE state = 'INTENDED'"
    )
    connection.commit()
    connection.close()

    restarted = PromotionExecutionLedger(path)
    with pytest.raises(PromotionExecutionStateError, match="strict.*projection"):
        restarted.begin(
            auth,
            start_id="promotion-start-1",
            primary_checkout_before_sha256=PRIMARY,
        )
    restarted.close()
