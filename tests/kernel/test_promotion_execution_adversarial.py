from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from daedalus.kernel.promotion import PromotionAuthorization
from daedalus.kernel.promotion_execution import (
    PromotionExecutionLedger,
    PromotionExecutionReceipt,
    PromotionExecutionReplay,
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


def refused_report(auth: PromotionAuthorization) -> dict[str, object]:
    return {
        "promoted": [],
        "refused": [{"task_id": "task-1", "promoted": False}],
        "not_gated": [],
        "integration_branch": None,
        "integration_revision": None,
        "authorization": auth.to_dict(),
    }


def _completed_detail(path) -> tuple[int, dict[str, object]]:
    connection = sqlite3.connect(path)
    row = connection.execute(
        "SELECT id, detail FROM intent_events WHERE state = 'COMPLETED'"
    ).fetchone()
    connection.close()
    assert row is not None
    value = json.loads(row[1])
    assert isinstance(value, dict)
    return int(row[0]), value


def _replace_detail(path, event_id: int, detail: dict[str, object]) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE intent_events SET detail = ? WHERE id = ?",
        (canonical_json(detail), event_id),
    )
    connection.commit()
    connection.close()


def test_changed_start_id_is_not_laundered_as_exact_replay(tmp_path) -> None:
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    auth = authorization()
    ledger.begin(
        auth,
        start_id="promotion-start-1",
        primary_checkout_before_sha256=PRIMARY,
    )
    with pytest.raises(PromotionExecutionReplay):
        ledger.begin(
            auth,
            start_id="promotion-start-2",
            primary_checkout_before_sha256=PRIMARY,
        )
    ledger.close()


def test_retained_report_is_structurally_immutable(tmp_path) -> None:
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
    with pytest.raises(TypeError):
        completion.report["refused"] = []
    refused = completion.report["refused"]
    assert isinstance(refused, tuple)
    with pytest.raises(AttributeError):
        refused.append({})
    assert completion.report_dict() == refused_report(auth)
    ledger.close()


def test_oversized_terminal_report_is_refused_before_event_store_write(tmp_path) -> None:
    path = tmp_path / "spine.sqlite3"
    ledger = PromotionExecutionLedger(path)
    auth = authorization()
    start = ledger.begin(
        auth,
        start_id="promotion-start-1",
        primary_checkout_before_sha256=PRIMARY,
    ).start
    report = refused_report(auth)
    report["blob"] = "x" * (4 * 1024 * 1024)
    with pytest.raises(PromotionExecutionStateError, match="exceeds"):
        ledger.complete(
            start,
            receipt_id="promotion-receipt-1",
            outcome="refused",
            report=report,
            primary_checkout_after_sha256=PRIMARY,
        )
    assert ledger.pending() == (start,)
    ledger.close()


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_report_values_refuse_before_terminal_write(
    tmp_path,
    bad_value: float,
) -> None:
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    auth = authorization()
    start = ledger.begin(
        auth,
        start_id="promotion-start-1",
        primary_checkout_before_sha256=PRIMARY,
    ).start
    report = refused_report(auth)
    report["bad"] = bad_value
    with pytest.raises(PromotionExecutionStateError, match="non-finite"):
        ledger.complete(
            start,
            receipt_id="promotion-receipt-1",
            outcome="refused",
            report=report,
            primary_checkout_after_sha256=PRIMARY,
        )
    assert ledger.pending() == (start,)
    ledger.close()


def test_non_string_report_key_is_not_coerced(tmp_path) -> None:
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    auth = authorization()
    start = ledger.begin(
        auth,
        start_id="promotion-start-1",
        primary_checkout_before_sha256=PRIMARY,
    ).start
    report = refused_report(auth)
    report[1] = "coercion-would-change-the-subject"  # type: ignore[index]
    with pytest.raises(PromotionExecutionStateError, match="non-string object key"):
        ledger.complete(
            start,
            receipt_id="promotion-receipt-1",
            outcome="refused",
            report=report,
            primary_checkout_after_sha256=PRIMARY,
        )
    assert ledger.pending() == (start,)
    ledger.close()


def test_non_json_report_value_is_refused(tmp_path) -> None:
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    auth = authorization()
    start = ledger.begin(
        auth,
        start_id="promotion-start-1",
        primary_checkout_before_sha256=PRIMARY,
    ).start
    report = refused_report(auth)
    report["bad"] = object()
    with pytest.raises(PromotionExecutionStateError, match="non-JSON value"):
        ledger.complete(
            start,
            receipt_id="promotion-receipt-1",
            outcome="refused",
            report=report,
            primary_checkout_after_sha256=PRIMARY,
        )
    assert ledger.pending() == (start,)
    ledger.close()


def test_persisted_completion_cannot_precede_its_start(tmp_path) -> None:
    path = tmp_path / "spine.sqlite3"
    ledger = PromotionExecutionLedger(path)
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
    ledger.close()

    event_id, detail = _completed_detail(path)
    result = detail["result"]
    assert isinstance(result, dict)
    receipt_payload = result["receipt"]
    assert isinstance(receipt_payload, dict)
    before_start = (
        datetime.fromisoformat(start.started_at) - timedelta(microseconds=1)
    ).astimezone(timezone.utc).isoformat(timespec="microseconds")
    receipt_payload["completed_at"] = before_start
    provenance = receipt_payload["provenance"]
    assert isinstance(provenance, dict)
    provenance["created_at"] = before_start
    receipt = PromotionExecutionReceipt.from_dict(receipt_payload)
    result["receipt"] = receipt.to_dict()
    detail["effect_id"] = receipt.digest
    _replace_detail(path, event_id, detail)

    restarted = PromotionExecutionLedger(path)
    with pytest.raises(PromotionExecutionStateError, match="precedes"):
        restarted.begin(
            auth,
            start_id="promotion-start-1",
            primary_checkout_before_sha256=PRIMARY,
        )
    restarted.close()


def test_persisted_report_semantics_are_revalidated_not_only_rehashed(tmp_path) -> None:
    path = tmp_path / "spine.sqlite3"
    ledger = PromotionExecutionLedger(path)
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
    ledger.close()

    event_id, detail = _completed_detail(path)
    result = detail["result"]
    assert isinstance(result, dict)
    receipt_payload = result["receipt"]
    assert isinstance(receipt_payload, dict)
    forged_report = refused_report(auth)
    forged_report["promoted"] = [{"task_id": "task-1", "promoted": True}]
    forged_report["refused"] = []
    old_report_sha = completion.receipt.report_sha256
    new_report_sha = canonical_sha(forged_report)
    receipt_payload["report_sha256"] = new_report_sha
    provenance = receipt_payload["provenance"]
    assert isinstance(provenance, dict)
    inputs = provenance["input_digests"]
    assert isinstance(inputs, list)
    provenance["input_digests"] = sorted(
        new_report_sha if value == old_report_sha else value for value in inputs
    )
    receipt = PromotionExecutionReceipt.from_dict(receipt_payload)
    result["receipt"] = receipt.to_dict()
    result["report"] = forged_report
    detail["effect_id"] = receipt.digest
    _replace_detail(path, event_id, detail)

    restarted = PromotionExecutionLedger(path)
    with pytest.raises(
        PromotionExecutionStateError,
        match="contradicts terminal receipt",
    ):
        restarted.begin(
            auth,
            start_id="promotion-start-1",
            primary_checkout_before_sha256=PRIMARY,
        )
    restarted.close()
