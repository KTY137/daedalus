from __future__ import annotations

import dataclasses
import sqlite3

import pytest

from daedalus.kernel.promotion import PromotionAuthorization
from daedalus.kernel.promotion_execution import (
    PromotionExecutionBindingMismatch,
    PromotionExecutionLedger,
    PromotionExecutionStateError,
)
from daedalus.kernel.promotion_replay import (
    PromotionReplayProjectionMismatch,
    inspect_promotion_execution,
)
from daedalus.spine.envelope import canonical_sha


REVISION = "a" * 40
TARGET = "b" * 40
CANDIDATE = "c" * 64
EVIDENCE = "d" * 64
CONSUMPTION = "e" * 64
PRIMARY = "f" * 64
INTEGRATION = "1" * 40


def authorization(**changes: str) -> PromotionAuthorization:
    body = {
        "promotion_id": "promotion-1",
        "candidate_artifact_sha256": CANDIDATE,
        "evidence_packet_sha256": EVIDENCE,
        "source_revision": REVISION,
        "target_ref": "experimental",
        "live_target_revision": TARGET,
        "approval_consumption_sha256": CONSUMPTION,
    }
    body.update(changes)
    return PromotionAuthorization(
        **body,
        authorization_sha256=canonical_sha(body),
    )


def successful_report(auth: PromotionAuthorization) -> dict[str, object]:
    return {
        "promoted": [{"task_id": "task-1", "promoted": True}],
        "refused": [],
        "not_gated": [],
        "integration_branch": "integration/promotion-1",
        "integration_revision": INTEGRATION,
        "authorization": auth.to_dict(),
        "cleanup_error": None,
    }


def test_missing_start_returns_none_without_creating_one(tmp_path) -> None:
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    try:
        assert inspect_promotion_execution(ledger, authorization()) is None
        assert ledger.pending() == ()
    finally:
        ledger.close()


def test_pending_start_is_projected_without_primary_fingerprint_input(tmp_path) -> None:
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    auth = authorization()
    begin = ledger.begin(
        auth,
        start_id="promotion-start-1",
        primary_checkout_before_sha256=PRIMARY,
    )
    try:
        replay = inspect_promotion_execution(ledger, auth)
        assert replay is not None
        assert replay.execute is False
        assert replay.start == begin.start
        assert replay.completion is None
        assert replay.pending_reconciliation is True
    finally:
        ledger.close()


def test_terminal_report_is_returned_from_strict_persisted_decoder(tmp_path) -> None:
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    auth = authorization()
    begin = ledger.begin(
        auth,
        start_id="promotion-start-1",
        primary_checkout_before_sha256=PRIMARY,
    )
    report = successful_report(auth)
    completion = ledger.complete(
        begin.start,
        receipt_id="promotion-receipt-1",
        outcome="succeeded",
        report=report,
        integration_branch="integration/promotion-1",
        integration_revision=INTEGRATION,
        primary_checkout_after_sha256=PRIMARY,
    )
    try:
        replay = inspect_promotion_execution(ledger, auth)
        assert replay is not None
        assert replay.execute is False
        assert replay.completion == completion
        assert replay.completion.report_dict() == report
    finally:
        ledger.close()


@pytest.mark.parametrize(
    "changed",
    [
        {"candidate_artifact_sha256": "2" * 64},
        {"evidence_packet_sha256": "3" * 64},
        {"source_revision": "4" * 40},
        {"target_ref": "main"},
        {"live_target_revision": "5" * 40},
        {"approval_consumption_sha256": "6" * 64},
    ],
)
def test_changed_authorization_cannot_read_retained_report(tmp_path, changed) -> None:
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    original = authorization()
    start = ledger.begin(
        original,
        start_id="promotion-start-1",
        primary_checkout_before_sha256=PRIMARY,
    ).start
    ledger.complete(
        start,
        receipt_id="promotion-receipt-1",
        outcome="succeeded",
        report=successful_report(original),
        integration_branch="integration/promotion-1",
        integration_revision=INTEGRATION,
        primary_checkout_after_sha256=PRIMARY,
    )
    try:
        with pytest.raises(
            PromotionReplayProjectionMismatch,
            match="contradicts authorization",
        ):
            inspect_promotion_execution(ledger, authorization(**changed))
    finally:
        ledger.close()


def test_changed_promotion_identity_is_an_absent_subject_not_a_cross_read(tmp_path) -> None:
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    original = authorization()
    ledger.begin(
        original,
        start_id="promotion-start-1",
        primary_checkout_before_sha256=PRIMARY,
    )
    try:
        assert (
            inspect_promotion_execution(
                ledger,
                authorization(promotion_id="promotion-2"),
            )
            is None
        )
    finally:
        ledger.close()


def test_malformed_authorization_is_refused_before_event_lookup(tmp_path) -> None:
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    malformed = dataclasses.replace(
        authorization(),
        authorization_sha256="0" * 64,
    )
    try:
        with pytest.raises(
            PromotionExecutionBindingMismatch,
            match="authorization digest",
        ):
            inspect_promotion_execution(ledger, malformed)
        assert ledger.pending() == ()
    finally:
        ledger.close()


def test_corrupt_retained_start_is_not_projected(tmp_path) -> None:
    path = tmp_path / "spine.sqlite3"
    ledger = PromotionExecutionLedger(path)
    auth = authorization()
    ledger.begin(
        auth,
        start_id="promotion-start-1",
        primary_checkout_before_sha256=PRIMARY,
    )
    ledger.close()

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE intents SET payload='{}' WHERE kind='promotion.execution'"
        )

    restarted = PromotionExecutionLedger(path)
    try:
        with pytest.raises(PromotionExecutionStateError):
            inspect_promotion_execution(restarted, auth)
    finally:
        restarted.close()


def test_inspection_cannot_call_writer_methods(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    auth = authorization()
    ledger.begin(
        auth,
        start_id="promotion-start-1",
        primary_checkout_before_sha256=PRIMARY,
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("replay inspection reached a writer method")

    monkeypatch.setattr(ledger, "begin", forbidden)
    monkeypatch.setattr(ledger, "complete", forbidden)
    monkeypatch.setattr(ledger.spine, "record_intent", forbidden)
    monkeypatch.setattr(ledger.spine, "mark_completed", forbidden)
    try:
        replay = inspect_promotion_execution(ledger, auth)
        assert replay is not None
        assert replay.pending_reconciliation is True
    finally:
        ledger.close()
