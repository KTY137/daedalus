from __future__ import annotations

import concurrent.futures
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from daedalus.kernel.promotion import PromotionAuthorization
from daedalus.kernel.promotion_receipts import (
    PromotionBeginResult,
    PromotionLedger,
    PromotionReceipt,
    PromotionReceiptBindingMismatch,
    PromotionReceiptReplay,
    PromotionReceiptStateError,
    PromotionStartRecord,
)
from daedalus.spine.envelope import canonical_sha


NOW = datetime(2026, 8, 3, 20, 0, tzinfo=timezone.utc)
SOURCE = "a" * 40
TARGET = "b" * 40
INTEGRATION = "c" * 40
PRIMARY = "1" * 64
PRIMARY_CHANGED = "2" * 64


def authorization(**changes) -> PromotionAuthorization:
    body = dict(
        promotion_id="promotion-1",
        candidate_artifact_sha256="3" * 64,
        evidence_packet_sha256="4" * 64,
        source_revision=SOURCE,
        target_ref="refs/heads/experimental",
        live_target_revision=TARGET,
        approval_consumption_sha256="5" * 64,
    )
    explicit_digest = changes.pop("authorization_sha256", None)
    body.update(changes)
    return PromotionAuthorization(
        **body,
        authorization_sha256=explicit_digest or canonical_sha(body),
    )


def begin_result(ledger: PromotionLedger, **changes) -> PromotionBeginResult:
    values = dict(
        authorization=authorization(),
        start_id="start-1",
        primary_checkout_before_sha256=PRIMARY,
        started_at=NOW,
    )
    values.update(changes)
    return ledger.begin(**values)


def begin(ledger: PromotionLedger, **changes) -> PromotionStartRecord:
    result = begin_result(ledger, **changes)
    assert result.execute
    assert result.completion is None
    return result.start


def successful_report(**changes):
    value = {
        "promoted": [{"task_id": "task-1", "promoted": True}],
        "refused": [],
        "not_gated": [],
        "integration_branch": "kairos-integration-1",
    }
    value.update(changes)
    return value


def success(ledger: PromotionLedger, start: PromotionStartRecord, **changes):
    values = dict(
        receipt_id="receipt-1",
        outcome="succeeded",
        report=successful_report(),
        primary_checkout_after_sha256=PRIMARY,
        integration_branch="kairos-integration-1",
        integration_revision=INTEGRATION,
        completed_at=NOW + timedelta(seconds=2),
    )
    values.update(changes)
    return ledger.complete(start, **values)


def test_start_and_receipt_are_canonical_and_round_trip(tmp_path) -> None:
    ledger = PromotionLedger(tmp_path / "promotion.sqlite3")
    start = begin(ledger)
    completion = success(ledger, start)

    assert PromotionStartRecord.from_dict(start.to_dict()) == start
    assert PromotionReceipt.from_dict(completion.receipt.to_dict()) == completion.receipt
    assert completion.receipt.primary_checkout_unchanged
    assert completion.receipt.outcome == "succeeded"
    assert completion.receipt.integration_revision == INTEGRATION
    assert ledger.verify_receipt(completion) == completion


def test_begin_replay_never_reauthorizes_execution(tmp_path) -> None:
    ledger = PromotionLedger(tmp_path / "promotion.sqlite3")
    first = begin_result(ledger)
    assert first.execute

    pending_replay = begin_result(ledger)
    assert pending_replay.start == first.start
    assert not pending_replay.execute
    assert pending_replay.pending_reconciliation

    terminal = success(ledger, first.start)
    terminal_replay = begin_result(ledger)
    assert not terminal_replay.execute
    assert not terminal_replay.pending_reconciliation
    assert terminal_replay.completion == terminal


def test_changed_start_or_authorization_identity_is_refused(tmp_path) -> None:
    ledger = PromotionLedger(tmp_path / "promotion.sqlite3")
    begin(ledger)

    with pytest.raises(PromotionReceiptReplay):
        begin_result(ledger, start_id="start-2")
    with pytest.raises(PromotionReceiptReplay):
        begin_result(ledger, primary_checkout_before_sha256=PRIMARY_CHANGED)
    with pytest.raises(PromotionReceiptReplay):
        begin_result(
            ledger,
            authorization=authorization(promotion_id="promotion-2"),
        )


def test_forged_authorization_digest_is_refused_before_persistence(tmp_path) -> None:
    ledger = PromotionLedger(tmp_path / "promotion.sqlite3")
    with pytest.raises(PromotionReceiptBindingMismatch, match="digest"):
        begin_result(
            ledger,
            authorization=authorization(authorization_sha256="f" * 64),
        )
    assert ledger.pending() == ()


def test_terminal_receipt_is_exactly_replayable_and_conflicts_are_refused(tmp_path) -> None:
    ledger = PromotionLedger(tmp_path / "promotion.sqlite3")
    start = begin(ledger)
    first = success(ledger, start)
    assert success(ledger, start) == first

    with pytest.raises(PromotionReceiptReplay):
        success(ledger, start, receipt_id="receipt-2")
    with pytest.raises(PromotionReceiptReplay):
        success(
            ledger,
            start,
            outcome="refused",
            integration_branch=None,
            integration_revision=None,
            report={"promoted": [], "refused": [{"reason": "late refusal"}]},
        )


def test_success_requires_exact_integration_identity_and_report(tmp_path) -> None:
    ledger = PromotionLedger(tmp_path / "promotion.sqlite3")
    start = begin(ledger)

    with pytest.raises(ValueError, match="integration branch and revision"):
        success(ledger, start, integration_branch=None, integration_revision=None)
    with pytest.raises(ValueError, match="requires integration_branch"):
        success(ledger, start, integration_branch=None)
    with pytest.raises(ValueError, match="exactly one promoted"):
        success(ledger, start, report={"promoted": [], "refused": []})
    with pytest.raises(ValueError, match="branch mismatch"):
        success(
            ledger,
            start,
            report=successful_report(integration_branch="other-branch"),
        )


def test_primary_checkout_change_can_only_be_recorded_as_fault(tmp_path) -> None:
    ledger = PromotionLedger(tmp_path / "promotion.sqlite3")
    start = begin(ledger)

    with pytest.raises(ValueError, match="terminal outcome must be faulted"):
        success(ledger, start, primary_checkout_after_sha256=PRIMARY_CHANGED)

    completion = success(
        ledger,
        start,
        outcome="faulted",
        primary_checkout_after_sha256=PRIMARY_CHANGED,
        integration_branch=None,
        integration_revision=None,
        report={
            "promoted": [{"task_id": "task-1", "promoted": True}],
            "refused": [],
            "integration_branch": None,
        },
    )
    assert not completion.receipt.primary_checkout_unchanged
    assert completion.receipt.outcome == "faulted"


def test_fault_with_unchanged_primary_requires_explicit_fault_evidence(tmp_path) -> None:
    ledger = PromotionLedger(tmp_path / "promotion.sqlite3")
    start = begin(ledger)
    with pytest.raises(ValueError, match="explicit fault evidence"):
        success(
            ledger,
            start,
            outcome="faulted",
            integration_branch=None,
            integration_revision=None,
            report={"promoted": [], "refused": []},
        )
    completion = success(
        ledger,
        start,
        outcome="faulted",
        integration_branch=None,
        integration_revision=None,
        report={"promoted": [], "refused": [], "fault": "crash-reconciliation"},
    )
    assert completion.receipt.outcome == "faulted"


def test_refusal_may_be_terminal_without_an_integration_branch(tmp_path) -> None:
    ledger = PromotionLedger(tmp_path / "promotion.sqlite3")
    start = begin(ledger)
    completion = success(
        ledger,
        start,
        outcome="refused",
        integration_branch=None,
        integration_revision=None,
        report={"promoted": [], "refused": [{"reason": "gate failed"}]},
    )
    assert completion.receipt.outcome == "refused"
    assert completion.receipt.integration_branch is None
    assert completion.receipt.primary_checkout_unchanged


def test_pending_start_survives_restart_and_disappears_after_completion(tmp_path) -> None:
    path = tmp_path / "promotion.sqlite3"
    first = PromotionLedger(path)
    start = begin(first)
    assert first.pending() == (start,)

    restarted = PromotionLedger(path)
    replay = begin_result(restarted)
    assert replay.pending_reconciliation
    assert restarted.pending() == (start,)
    success(restarted, start)
    assert PromotionLedger(path).pending() == ()


def test_forged_or_foreign_start_cannot_complete(tmp_path) -> None:
    ledger = PromotionLedger(tmp_path / "promotion.sqlite3")
    persisted = begin(ledger)
    body = persisted.payload_dict()
    body["start_id"] = "forged"
    forged = PromotionStartRecord(**body, start_sha256=canonical_sha(body))
    with pytest.raises(PromotionReceiptBindingMismatch):
        success(ledger, forged)


def test_report_is_snapshotted_before_caller_mutation(tmp_path) -> None:
    ledger = PromotionLedger(tmp_path / "promotion.sqlite3")
    start = begin(ledger)
    report = successful_report()
    completion = success(ledger, start, report=report)
    report["promoted"][0]["promoted"] = False
    assert completion.report_dict()["promoted"][0]["promoted"] is True
    assert ledger.get_receipt(start.promotion_id) == completion


def test_tampered_receipt_json_or_digest_columns_are_refused(tmp_path) -> None:
    path = tmp_path / "promotion.sqlite3"
    ledger = PromotionLedger(path)
    completion = success(ledger, begin(ledger))

    with sqlite3.connect(path) as connection:
        payload = completion.receipt.to_dict()
        payload["outcome"] = "refused"
        connection.execute(
            "UPDATE promotion_receipts_v1 SET receipt_json=? WHERE promotion_id=?",
            (json.dumps(payload), completion.receipt.promotion_id),
        )
    with pytest.raises(PromotionReceiptStateError):
        PromotionLedger(path).get_receipt(completion.receipt.promotion_id)

    path2 = tmp_path / "promotion-digest.sqlite3"
    ledger2 = PromotionLedger(path2)
    completion2 = success(ledger2, begin(ledger2))
    with sqlite3.connect(path2) as connection:
        connection.execute(
            "UPDATE promotion_receipts_v1 SET receipt_sha256=? WHERE promotion_id=?",
            ("f" * 64, completion2.receipt.promotion_id),
        )
    with pytest.raises(PromotionReceiptStateError, match="receipt digest"):
        PromotionLedger(path2).get_receipt(completion2.receipt.promotion_id)


def test_corrupt_sqlite_fails_closed(tmp_path) -> None:
    path = tmp_path / "promotion.sqlite3"
    path.write_bytes(b"not sqlite")
    with pytest.raises(PromotionReceiptStateError):
        PromotionLedger(path)


def test_concurrent_begin_allows_exactly_one_execution_decision(tmp_path) -> None:
    path = tmp_path / "promotion.sqlite3"

    def start_once(_index: int):
        return begin_result(PromotionLedger(path))

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(start_once, range(8)))
    assert sum(result.execute for result in results) == 1
    assert all(result.start == results[0].start for result in results)


def test_concurrent_conflicting_completion_has_one_terminal_winner(tmp_path) -> None:
    path = tmp_path / "promotion.sqlite3"
    start = begin(PromotionLedger(path))

    def complete(index: int):
        ledger = PromotionLedger(path)
        try:
            return success(
                ledger,
                start,
                receipt_id=f"receipt-{index}",
                report=successful_report(index=index),
            )
        except PromotionReceiptReplay:
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(complete, range(8)))

    winners = [value for value in outcomes if value is not None]
    assert len(winners) == 1
    persisted = PromotionLedger(path).get_receipt(start.promotion_id)
    assert persisted == winners[0]
