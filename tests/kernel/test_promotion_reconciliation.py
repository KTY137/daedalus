from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from daedalus.kernel.promotion_execution import PromotionExecutionLedger
from daedalus.kernel.promotion_reconciliation import (
    COMPLETE,
    EFFECT_ONLY_PENDING,
    EFFECT_TERMINAL_REQUIRED,
    FRESH,
    PROMOTION_PENDING,
    PromotionReconciliationError,
    inspect_promotion_reconciliation,
)


def _load(name: str, filename: str):
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_EFFECT = _load(
    "_promotion_reconciliation_effect_fixture",
    "test_promotion_effect_capability.py",
)
_PROMOTION = _load(
    "_promotion_reconciliation_execution_fixture",
    "test_promotion_replay_projection.py",
)
build_capability = _EFFECT.build_capability
authorization = _PROMOTION.authorization
successful_report = _PROMOTION.successful_report
PRIMARY = _PROMOTION.PRIMARY
INTEGRATION = _PROMOTION.INTEGRATION


def _begin_promotion(ledger: PromotionExecutionLedger, auth):
    return ledger.begin(
        auth,
        start_id="promotion-start-1",
        primary_checkout_before_sha256=PRIMARY,
    )


def _complete_success(ledger: PromotionExecutionLedger, begin, auth):
    return ledger.complete(
        begin.start,
        receipt_id="promotion-receipt-1",
        outcome="succeeded",
        report=successful_report(auth),
        integration_branch="integration/promotion-1",
        integration_revision=INTEGRATION,
        primary_checkout_after_sha256=PRIMARY,
    )


def test_fresh_state_is_inert(tmp_path) -> None:
    auth = authorization()
    capability = build_capability(tmp_path, promotion_value=auth)
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    try:
        projection = inspect_promotion_reconciliation(capability, ledger)
        assert projection.disposition == FRESH
        assert projection.effect_execution is None
        assert projection.promotion_execution is None
        assert projection.expected_effect_terminal is None
        assert projection.automatic_execution_allowed is False
    finally:
        ledger.close()


def test_effect_only_start_is_reconciliation_only(tmp_path) -> None:
    auth = authorization()
    capability = build_capability(tmp_path, promotion_value=auth)
    capability.grant()
    capability.begin()
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    try:
        projection = inspect_promotion_reconciliation(capability, ledger)
        assert projection.disposition == EFFECT_ONLY_PENDING
        assert projection.effect_execution is not None
        assert projection.promotion_execution is None
        assert projection.automatic_execution_allowed is False
    finally:
        ledger.close()


def test_promotion_start_without_effect_start_is_refused(tmp_path) -> None:
    auth = authorization()
    capability = build_capability(tmp_path, promotion_value=auth)
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    _begin_promotion(ledger, auth)
    try:
        with pytest.raises(PromotionReconciliationError, match="without a top-level"):
            inspect_promotion_reconciliation(capability, ledger)
    finally:
        ledger.close()


def test_both_pending_starts_remain_reconciliation_only(tmp_path) -> None:
    auth = authorization()
    capability = build_capability(tmp_path, promotion_value=auth)
    capability.grant()
    capability.begin()
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    _begin_promotion(ledger, auth)
    try:
        projection = inspect_promotion_reconciliation(capability, ledger)
        assert projection.disposition == PROMOTION_PENDING
        assert projection.effect_execution is not None
        assert projection.promotion_execution is not None
        assert projection.promotion_execution.completion is None
        assert projection.automatic_execution_allowed is False
    finally:
        ledger.close()


def test_promotion_terminal_requires_exact_effect_terminalization(tmp_path) -> None:
    auth = authorization()
    capability = build_capability(tmp_path, promotion_value=auth)
    capability.grant()
    capability.begin()
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    begin = _begin_promotion(ledger, auth)
    completion = _complete_success(ledger, begin, auth)
    try:
        projection = inspect_promotion_reconciliation(capability, ledger)
        assert projection.disposition == EFFECT_TERMINAL_REQUIRED
        expected = projection.expected_effect_terminal
        assert expected is not None
        assert expected.outcome == "COMPLETED"
        assert expected.output_digests == tuple(
            sorted({completion.receipt.digest, completion.receipt.report_sha256})
        )
        assert expected.detail_sha256 == completion.receipt.digest
        assert projection.automatic_execution_allowed is False
    finally:
        ledger.close()


def test_matching_terminals_project_complete(tmp_path) -> None:
    auth = authorization()
    capability = build_capability(tmp_path, promotion_value=auth)
    capability.grant()
    effect_start = capability.begin()
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    promotion_begin = _begin_promotion(ledger, auth)
    completion = _complete_success(ledger, promotion_begin, auth)
    outputs = tuple(sorted({completion.receipt.digest, completion.receipt.report_sha256}))
    capability.finish(
        effect_start.receipt,
        outcome="completed",
        output_digests=outputs,
        detail_sha256=completion.receipt.digest,
    )
    try:
        projection = inspect_promotion_reconciliation(capability, ledger)
        assert projection.disposition == COMPLETE
        assert projection.expected_effect_terminal is not None
        assert projection.effect_execution is not None
        assert projection.effect_execution.terminal is not None
        assert projection.effect_execution.terminal.output_digests == outputs
        assert projection.automatic_execution_allowed is False
    finally:
        ledger.close()


def test_terminal_outcome_substitution_is_refused(tmp_path) -> None:
    auth = authorization()
    capability = build_capability(tmp_path, promotion_value=auth)
    capability.grant()
    effect_start = capability.begin()
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    promotion_begin = _begin_promotion(ledger, auth)
    completion = _complete_success(ledger, promotion_begin, auth)
    capability.finish(
        effect_start.receipt,
        outcome="failed",
        detail_sha256=completion.receipt.digest,
    )
    try:
        with pytest.raises(PromotionReconciliationError, match="outcome"):
            inspect_promotion_reconciliation(capability, ledger)
    finally:
        ledger.close()


def test_effect_terminal_while_promotion_pending_is_refused(tmp_path) -> None:
    auth = authorization()
    capability = build_capability(tmp_path, promotion_value=auth)
    capability.grant()
    effect_start = capability.begin()
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    _begin_promotion(ledger, auth)
    capability.finish(effect_start.receipt, outcome="failed")
    try:
        with pytest.raises(PromotionReconciliationError, match="while promotion"):
            inspect_promotion_reconciliation(capability, ledger)
    finally:
        ledger.close()


def test_promotion_start_before_effect_start_is_refused(tmp_path) -> None:
    auth = authorization()
    capability = build_capability(tmp_path, promotion_value=auth)
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    _begin_promotion(ledger, auth)
    capability.grant()
    capability.begin()
    try:
        with pytest.raises(PromotionReconciliationError, match="precedes"):
            inspect_promotion_reconciliation(capability, ledger)
    finally:
        ledger.close()


def test_wrong_inputs_are_refused_before_projection() -> None:
    with pytest.raises(TypeError, match="PromotionEffectCapability"):
        inspect_promotion_reconciliation(object(), object())
