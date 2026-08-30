# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

from daedalus.kernel.promotion import PromotionAuthorization
from daedalus.kernel.promotion_execution import (
    PromotionExecutionLedger,
    PromotionExecutionStateError,
)
from daedalus.spine.envelope import canonical_json, canonical_sha
from daedalus.spine.ledger import SpineLedger


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


def refused_report(auth: PromotionAuthorization) -> dict[str, object]:
    return {
        "promoted": [],
        "refused": [{"task_id": "task-1", "promoted": False}],
        "not_gated": [],
        "integration_branch": None,
        "integration_revision": None,
        "authorization": auth.to_dict(),
    }


def completed_ledger(path):
    auth = authorization()
    ledger = PromotionExecutionLedger(path)
    start = ledger.begin(
        auth,
        start_id="promotion-start-1",
        primary_checkout_before_sha256=PRIMARY,
    ).start
    ledger.complete(
        start,
        receipt_id="promotion-receipt-1",
        outcome="refused",
        report=refused_report(auth),
        primary_checkout_after_sha256=PRIMARY,
    )
    ledger.close()
    return auth


def _terminal_row(path) -> tuple[int, str]:
    connection = sqlite3.connect(path)
    row = connection.execute(
        "SELECT id, detail FROM intent_events WHERE state = 'COMPLETED'"
    ).fetchone()
    connection.close()
    assert row is not None
    return int(row[0]), str(row[1])


def _update_terminal(path, event_id: int, raw_detail: str) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE intent_events SET detail = ? WHERE id = ?",
        (raw_detail, event_id),
    )
    connection.commit()
    connection.close()


def test_duplicate_terminal_result_key_is_visible_and_refused(tmp_path) -> None:
    path = tmp_path / "spine.sqlite3"
    auth = completed_ledger(path)
    event_id, raw = _terminal_row(path)
    detail = json.loads(raw)
    result_raw = canonical_json(detail["result"])
    duplicate = (
        '{"effect_id":'
        + json.dumps(detail["effect_id"])
        + ',"result":'
        + result_raw
        + ',"result":'
        + result_raw
        + "}"
    )
    _update_terminal(path, event_id, duplicate)

    restarted = PromotionExecutionLedger(path)
    with pytest.raises(PromotionExecutionStateError, match="strict.*projection"):
        restarted.begin(
            auth,
            start_id="promotion-start-1",
            primary_checkout_before_sha256=PRIMARY,
        )
    with pytest.raises(PromotionExecutionStateError, match="strict.*projection"):
        restarted.pending()
    restarted.close()


def test_noncanonical_terminal_bytes_are_refused(tmp_path) -> None:
    path = tmp_path / "spine.sqlite3"
    auth = completed_ledger(path)
    event_id, raw = _terminal_row(path)
    pretty = json.dumps(json.loads(raw), indent=2, sort_keys=True)
    assert pretty != raw
    _update_terminal(path, event_id, pretty)

    restarted = PromotionExecutionLedger(path)
    with pytest.raises(PromotionExecutionStateError, match="strict.*projection"):
        restarted.begin(
            auth,
            start_id="promotion-start-1",
            primary_checkout_before_sha256=PRIMARY,
        )
    restarted.close()


def test_duplicate_start_payload_key_refuses_even_with_recomputed_digest(tmp_path) -> None:
    path = tmp_path / "spine.sqlite3"
    auth = authorization()
    ledger = PromotionExecutionLedger(path)
    ledger.begin(
        auth,
        start_id="promotion-start-1",
        primary_checkout_before_sha256=PRIMARY,
    )
    ledger.close()

    connection = sqlite3.connect(path)
    row = connection.execute(
        "SELECT id, payload FROM intents WHERE kind = 'promotion.execution'"
    ).fetchone()
    assert row is not None
    intent_id = int(row[0])
    payload = json.loads(str(row[1]))
    start_raw = canonical_json(payload["start"])
    schema_raw = json.dumps(payload["schema"])
    duplicate = (
        '{"schema":'
        + schema_raw
        + ',"schema":'
        + schema_raw
        + ',"start":'
        + start_raw
        + "}"
    )
    digest = hashlib.sha256(duplicate.encode("ascii")).hexdigest()
    connection.execute(
        "UPDATE intents SET payload = ?, payload_sha = ? WHERE id = ?",
        (duplicate, digest, intent_id),
    )
    connection.execute(
        "UPDATE intent_events SET detail = ? "
        "WHERE intent_id = ? AND state = 'INTENDED'",
        (canonical_json({"payload_sha": digest}), intent_id),
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


def test_foreign_kind_cannot_claim_reserved_promotion_effect_key(tmp_path) -> None:
    path = tmp_path / "spine.sqlite3"
    spine = SpineLedger(path)
    spine.record_intent(
        "foreign.lifecycle",
        {"foreign": True},
        effect_key="promotion.execution:promotion-1",
    )
    spine.close()

    ledger = PromotionExecutionLedger(path)
    with pytest.raises(
        PromotionExecutionStateError,
        match="another intent kind",
    ):
        ledger.begin(
            authorization(),
            start_id="promotion-start-1",
            primary_checkout_before_sha256=PRIMARY,
        )
    with pytest.raises(
        PromotionExecutionStateError,
        match="reserved promotion effect key",
    ):
        ledger.pending()
    ledger.close()


def test_third_event_cannot_hide_a_corrupt_terminal_history(tmp_path) -> None:
    path = tmp_path / "spine.sqlite3"
    auth = completed_ledger(path)
    connection = sqlite3.connect(path)
    row = connection.execute(
        "SELECT intent_id, ts FROM intent_events WHERE state = 'COMPLETED'"
    ).fetchone()
    assert row is not None
    connection.execute(
        "INSERT INTO intent_events(intent_id, state, ts, detail) VALUES(?,?,?,?)",
        (
            int(row[0]),
            "COMPLETED",
            str(row[1]),
            canonical_json({"effect_id": "0" * 64, "result": {}}),
        ),
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
    with pytest.raises(PromotionExecutionStateError, match="strict.*projection"):
        restarted.pending()
    restarted.close()


def test_generic_failed_transition_is_not_accepted_as_execution_receipt(tmp_path) -> None:
    path = tmp_path / "spine.sqlite3"
    auth = authorization()
    ledger = PromotionExecutionLedger(path)
    start = ledger.begin(
        auth,
        start_id="promotion-start-1",
        primary_checkout_before_sha256=PRIMARY,
    ).start
    intent = ledger._intent_for(start.promotion_id)
    assert intent is not None
    assert ledger.spine is not None
    ledger.spine.mark_failed(intent.id, "foreign terminal route")

    with pytest.raises(
        PromotionExecutionStateError,
        match="failed outside its contract",
    ):
        ledger.begin(
            auth,
            start_id="promotion-start-1",
            primary_checkout_before_sha256=PRIMARY,
        )
    with pytest.raises(
        PromotionExecutionStateError,
        match="failed outside its contract",
    ):
        ledger.pending()
    ledger.close()
