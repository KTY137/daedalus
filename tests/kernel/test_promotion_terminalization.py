from __future__ import annotations

import importlib.util
from datetime import timedelta
from pathlib import Path

import pytest

import daedalus.kernel.authorization as authorization_module
from daedalus.kernel.effects import EffectLeaseExpired, EffectLeaseStateError
from daedalus.kernel.promotion_execution import PromotionExecutionLedger
from daedalus.kernel.promotion_reconciliation import (
    PromotionReconciliationDisposition,
    inspect_promotion_reconciliation,
)
from daedalus.kernel.promotion_terminalization import (
    PromotionEffectTerminalizationError,
    terminalize_promotion_effect,
)


def _load(name: str, filename: str):
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_EFFECT = _load(
    "_promotion_terminalization_effect_fixture",
    "test_promotion_effect_capability.py",
)
_PROMOTION = _load(
    "_promotion_terminalization_execution_fixture",
    "test_promotion_replay_projection.py",
)
build_capability = _EFFECT.build_capability
authorization = _PROMOTION.authorization
successful_report = _PROMOTION.successful_report
PRIMARY = _PROMOTION.PRIMARY
INTEGRATION = _PROMOTION.INTEGRATION
NOW = _EFFECT.NOW


def _begin_success(tmp_path):
    auth = authorization()
    capability = build_capability(tmp_path, promotion_value=auth)
    capability.grant()
    capability.begin()
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    promotion_start = ledger.begin(
        auth,
        start_id="promotion-start-1",
        primary_checkout_before_sha256=PRIMARY,
    )
    completion = ledger.complete(
        promotion_start.start,
        receipt_id="promotion-receipt-1",
        outcome="succeeded",
        report=successful_report(auth),
        integration_branch="integration/promotion-1",
        integration_revision=INTEGRATION,
        primary_checkout_after_sha256=PRIMARY,
    )
    return capability, ledger, completion


def test_success_terminalization_uses_exact_persisted_promotion_evidence(tmp_path) -> None:
    capability, ledger, completion = _begin_success(tmp_path)
    expected_outputs = tuple(
        sorted({completion.receipt.digest, completion.receipt.report_sha256})
    )
    try:
        result = terminalize_promotion_effect(capability, ledger)
        assert result.replayed is False
        assert result.terminal.outcome == "COMPLETED"
        assert result.terminal.output_digests == expected_outputs
        assert result.terminal.detail_sha256 == completion.receipt.digest
        assert (
            result.reconciliation.disposition
            is PromotionReconciliationDisposition.COMPLETE
        )
        assert (
            inspect_promotion_reconciliation(capability, ledger).disposition
            is PromotionReconciliationDisposition.COMPLETE
        )
    finally:
        ledger.close()


def test_terminalization_is_idempotent_after_exact_completion(tmp_path) -> None:
    capability, ledger, _ = _begin_success(tmp_path)
    try:
        first = terminalize_promotion_effect(capability, ledger)
        second = terminalize_promotion_effect(capability, ledger)
        assert first.replayed is False
        assert second.replayed is True
        assert second.terminal == first.terminal
        assert second.reconciliation == first.reconciliation
    finally:
        ledger.close()


def test_expired_live_success_authority_does_not_erase_durable_terminal_evidence(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability, ledger, completion = _begin_success(tmp_path)
    pending = inspect_promotion_reconciliation(capability, ledger)
    assert (
        pending.disposition
        is PromotionReconciliationDisposition.EFFECT_TERMINAL_REQUIRED
    )
    assert pending.effect_execution is not None

    monkeypatch.setattr(
        authorization_module,
        "_utc_now",
        lambda: NOW + timedelta(hours=2),
    )
    with pytest.raises(EffectLeaseExpired):
        capability.finish(
            pending.effect_execution.start,
            outcome="completed",
            output_digests=(completion.receipt.digest,),
            detail_sha256=completion.receipt.digest,
        )

    try:
        reconciled = terminalize_promotion_effect(capability, ledger)
        assert reconciled.replayed is False
        assert reconciled.terminal.outcome == "COMPLETED"
        assert reconciled.terminal.detail_sha256 == completion.receipt.digest
    finally:
        ledger.close()


@pytest.mark.parametrize(
    "prepare",
    ["fresh", "effect-only", "promotion-pending"],
)
def test_nonterminal_states_refuse_without_installing_effect_terminal(
    tmp_path,
    prepare: str,
) -> None:
    auth = authorization()
    capability = build_capability(tmp_path, promotion_value=auth)
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    if prepare != "fresh":
        capability.grant()
        capability.begin()
    if prepare == "promotion-pending":
        ledger.begin(
            auth,
            start_id="promotion-start-1",
            primary_checkout_before_sha256=PRIMARY,
        )
    before = inspect_promotion_reconciliation(capability, ledger)
    try:
        with pytest.raises(
            PromotionEffectTerminalizationError,
            match="does not permit",
        ):
            terminalize_promotion_effect(capability, ledger)
        after = inspect_promotion_reconciliation(capability, ledger)
        assert after == before
        assert after.effect_execution is None or after.effect_execution.terminal is None
    finally:
        ledger.close()


def test_concurrent_exact_terminalization_is_replayed(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability, ledger, _ = _begin_success(tmp_path)
    effect_ledger = capability.authorization.effect_ledger
    original_finish = effect_ledger.finish

    def concurrent_finish(*args, **kwargs):
        original_finish(*args, **kwargs)
        raise EffectLeaseStateError("simulated concurrent terminal writer")

    monkeypatch.setattr(effect_ledger, "finish", concurrent_finish)
    try:
        result = terminalize_promotion_effect(capability, ledger)
        assert result.replayed is True
        assert result.terminal.outcome == "COMPLETED"
        assert (
            result.reconciliation.disposition
            is PromotionReconciliationDisposition.COMPLETE
        )
    finally:
        ledger.close()


def test_wrong_inputs_are_refused_before_any_projection() -> None:
    with pytest.raises(TypeError, match="PromotionEffectCapability"):
        terminalize_promotion_effect(object(), object())
