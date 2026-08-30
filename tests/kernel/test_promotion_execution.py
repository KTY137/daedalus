# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import concurrent.futures
import dataclasses
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from daedalus.kernel.promotion import PromotionAuthorization
from daedalus.kernel.promotion_execution import (
    PromotionExecutionBindingMismatch,
    PromotionExecutionLedger,
    PromotionExecutionReplay,
    PromotionExecutionStateError,
    PromotionExecutionStart,
)
from daedalus.spine.envelope import canonical_sha
from daedalus.spine.ledger import SpineLedger


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


def refused_report(auth: PromotionAuthorization) -> dict[str, object]:
    return {
        "promoted": [],
        "refused": [
            {"task_id": "task-1", "promoted": False, "reason": "gate refused"}
        ],
        "not_gated": [],
        "integration_branch": None,
        "integration_revision": None,
        "authorization": auth.to_dict(),
    }


def faulted_report(auth: PromotionAuthorization) -> dict[str, object]:
    return {
        "promoted": [],
        "refused": [],
        "not_gated": [],
        "integration_branch": None,
        "integration_revision": None,
        "authorization": auth.to_dict(),
        "fault": "primary-checkout-fingerprint-changed",
    }


def test_start_is_persisted_once_and_restart_reports_pending(tmp_path) -> None:
    path = tmp_path / "spine.sqlite3"
    auth = authorization()
    first = PromotionExecutionLedger(path)
    begin = first.begin(
        auth,
        start_id="promotion-start-1",
        primary_checkout_before_sha256=PRIMARY,
    )
    assert begin.execute is True
    assert begin.completion is None
    assert first.pending() == (begin.start,)
    first.close()

    restarted = PromotionExecutionLedger(path)
    replay = restarted.begin(
        auth,
        start_id="promotion-start-1",
        primary_checkout_before_sha256=PRIMARY,
    )
    assert replay.execute is False
    assert replay.pending_reconciliation is True
    assert replay.start == begin.start
    assert restarted.pending() == (begin.start,)
    restarted.close()


def test_successful_terminal_receipt_is_exactly_replayable(tmp_path) -> None:
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
    assert completion.receipt.outcome == "succeeded"
    assert completion.receipt.primary_checkout_before_sha256 == PRIMARY
    assert completion.receipt.primary_checkout_after_sha256 == PRIMARY
    assert completion.report_dict() == report
    assert ledger.pending() == ()

    replay = ledger.begin(
        auth,
        start_id="promotion-start-1",
        primary_checkout_before_sha256=PRIMARY,
    )
    assert replay.execute is False
    assert replay.completion == completion
    exact = ledger.complete(
        begin.start,
        receipt_id="promotion-receipt-1",
        outcome="succeeded",
        report=report,
        integration_branch="integration/promotion-1",
        integration_revision=INTEGRATION,
        primary_checkout_after_sha256=PRIMARY,
    )
    assert exact == completion
    ledger.close()


def test_replay_refuses_changed_authorization_or_checkout_subject(tmp_path) -> None:
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    original = authorization()
    ledger.begin(
        original,
        start_id="promotion-start-1",
        primary_checkout_before_sha256=PRIMARY,
    )
    with pytest.raises(PromotionExecutionReplay):
        ledger.begin(
            authorization(live_target_revision="2" * 40),
            start_id="promotion-start-1",
            primary_checkout_before_sha256=PRIMARY,
        )
    with pytest.raises(PromotionExecutionReplay):
        ledger.begin(
            original,
            start_id="promotion-start-1",
            primary_checkout_before_sha256="3" * 64,
        )
    ledger.close()


def test_authorization_digest_is_recomputed_before_persistence(tmp_path) -> None:
    auth = dataclasses.replace(
        authorization(),
        authorization_sha256="0" * 64,
    )
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    with pytest.raises(
        PromotionExecutionBindingMismatch,
        match="authorization digest",
    ):
        ledger.begin(
            auth,
            start_id="promotion-start-1",
            primary_checkout_before_sha256=PRIMARY,
        )
    assert ledger.pending() == ()
    ledger.close()


def test_report_must_retain_exact_authorization_and_integration_identity(tmp_path) -> None:
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    auth = authorization()
    start = ledger.begin(
        auth,
        start_id="promotion-start-1",
        primary_checkout_before_sha256=PRIMARY,
    ).start

    substituted = successful_report(auth)
    substituted["authorization"] = authorization(
        live_target_revision="4" * 40
    ).to_dict()
    with pytest.raises(
        PromotionExecutionBindingMismatch,
        match="persisted authorization",
    ):
        ledger.complete(
            start,
            receipt_id="promotion-receipt-1",
            outcome="succeeded",
            report=substituted,
            integration_branch="integration/promotion-1",
            integration_revision=INTEGRATION,
            primary_checkout_after_sha256=PRIMARY,
        )

    wrong_revision = successful_report(auth)
    wrong_revision["integration_revision"] = "5" * 40
    with pytest.raises(
        PromotionExecutionBindingMismatch,
        match="integration revision",
    ):
        ledger.complete(
            start,
            receipt_id="promotion-receipt-1",
            outcome="succeeded",
            report=wrong_revision,
            integration_branch="integration/promotion-1",
            integration_revision=INTEGRATION,
            primary_checkout_after_sha256=PRIMARY,
        )
    ledger.close()


def test_primary_checkout_mutation_can_only_be_accounted_as_fault(tmp_path) -> None:
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    auth = authorization()
    start = ledger.begin(
        auth,
        start_id="promotion-start-1",
        primary_checkout_before_sha256=PRIMARY,
    ).start
    changed = "6" * 64
    with pytest.raises(
        PromotionExecutionBindingMismatch,
        match="changed the primary checkout",
    ):
        ledger.complete(
            start,
            receipt_id="promotion-receipt-1",
            outcome="succeeded",
            report=successful_report(auth),
            integration_branch="integration/promotion-1",
            integration_revision=INTEGRATION,
            primary_checkout_after_sha256=changed,
        )

    completion = ledger.complete(
        start,
        receipt_id="promotion-receipt-1",
        outcome="faulted",
        report=faulted_report(auth),
        primary_checkout_after_sha256=changed,
    )
    assert completion.receipt.outcome == "faulted"
    assert completion.receipt.primary_checkout_after_sha256 == changed
    ledger.close()


def test_refusal_has_no_integration_identity_and_is_terminal(tmp_path) -> None:
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    auth = authorization()
    start = ledger.begin(
        auth,
        start_id="promotion-start-1",
        primary_checkout_before_sha256=PRIMARY,
    ).start
    completion = ledger.complete(
        start,
        receipt_id="promotion-receipt-1",
        outcome="refused",
        report=refused_report(auth),
        primary_checkout_after_sha256=PRIMARY,
    )
    assert completion.receipt.integration_branch is None
    assert completion.receipt.integration_revision is None
    assert completion.receipt.outcome == "refused"
    ledger.close()


def test_changed_terminal_receipt_is_not_absorbed_as_idempotent(tmp_path) -> None:
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    auth = authorization()
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
    with pytest.raises(PromotionExecutionReplay):
        ledger.complete(
            start,
            receipt_id="promotion-receipt-2",
            outcome="refused",
            report=refused_report(auth),
            primary_checkout_after_sha256=PRIMARY,
        )
    ledger.close()


def test_concurrent_begin_has_one_persisted_winner(tmp_path) -> None:
    path = tmp_path / "spine.sqlite3"
    auth = authorization()

    def begin_once(_: int) -> bool:
        ledger = PromotionExecutionLedger(path)
        try:
            return ledger.begin(
                auth,
                start_id="promotion-start-1",
                primary_checkout_before_sha256=PRIMARY,
            ).execute
        finally:
            ledger.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(begin_once, range(4)))
    assert results.count(True) == 1
    assert results.count(False) == 3


def test_corrupt_terminal_event_fails_closed_after_restart(tmp_path) -> None:
    path = tmp_path / "spine.sqlite3"
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

    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE intent_events SET detail = ? WHERE state = 'COMPLETED'",
        ('{"effect_id":"' + "0" * 64 + '","result":{}}',),
    )
    connection.commit()
    connection.close()

    restarted = PromotionExecutionLedger(path)
    with pytest.raises(PromotionExecutionStateError):
        restarted.begin(
            auth,
            start_id="promotion-start-1",
            primary_checkout_before_sha256=PRIMARY,
        )
    restarted.close()


def test_malformed_contract_and_stale_kernel_clock_are_refused(tmp_path) -> None:
    auth = authorization()
    normal = PromotionExecutionLedger(tmp_path / "normal.sqlite3")
    start = normal.begin(
        auth,
        start_id="promotion-start-1",
        primary_checkout_before_sha256=PRIMARY,
    ).start
    payload = start.to_dict()
    payload["unknown"] = True
    with pytest.raises(ValueError, match="unknown"):
        PromotionExecutionStart.from_dict(payload)
    normal.close()

    stale = PromotionExecutionLedger(
        tmp_path / "stale.sqlite3",
        clock=lambda: datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    with pytest.raises(PromotionExecutionStateError, match="detached"):
        stale.begin(
            auth,
            start_id="promotion-start-1",
            primary_checkout_before_sha256=PRIMARY,
        )
    stale.close()


def test_read_only_event_store_cannot_be_used_as_execution_authority(tmp_path) -> None:
    path = tmp_path / "spine.sqlite3"
    writable = SpineLedger(path)
    writable.close()
    read_only = SpineLedger(path, read_only=True)
    with pytest.raises(
        PromotionExecutionStateError,
        match="writable canonical Event Store",
    ):
        PromotionExecutionLedger(read_only)
    read_only.close()
