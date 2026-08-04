from __future__ import annotations

import dataclasses
import importlib.util
from pathlib import Path

import pytest

from daedalus.kernel.effects import EffectLeaseStateError
from daedalus.kernel.promotion_execution import PromotionExecutionLedger
from daedalus.kernel.promotion_reconciliation import PromotionReconciliationError
from daedalus.kernel.promotion_terminalization import (
    PromotionEffectTerminalizationError,
    PromotionEffectTerminalizationResult,
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
    "_promotion_terminalization_adversarial_effect_fixture",
    "test_promotion_effect_capability.py",
)
_PROMOTION = _load(
    "_promotion_terminalization_adversarial_execution_fixture",
    "test_promotion_replay_projection.py",
)
build_capability = _EFFECT.build_capability
authorization = _PROMOTION.authorization
successful_report = _PROMOTION.successful_report
PRIMARY = _PROMOTION.PRIMARY
INTEGRATION = _PROMOTION.INTEGRATION


def _prepared(tmp_path):
    auth = authorization()
    capability = build_capability(tmp_path, promotion_value=auth)
    capability.grant()
    capability.begin()
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    start = ledger.begin(
        auth,
        start_id="promotion-start-1",
        primary_checkout_before_sha256=PRIMARY,
    )
    ledger.complete(
        start.start,
        receipt_id="promotion-receipt-1",
        outcome="succeeded",
        report=successful_report(auth),
        integration_branch="integration/promotion-1",
        integration_revision=INTEGRATION,
        primary_checkout_after_sha256=PRIMARY,
    )
    return capability, ledger


def test_non_idempotent_terminalization_race_is_refused(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability, ledger = _prepared(tmp_path)

    def lose_without_terminal(*args, **kwargs):
        raise EffectLeaseStateError("simulated non-idempotent race")

    monkeypatch.setattr(
        capability.authorization.effect_ledger,
        "finish",
        lose_without_terminal,
    )
    try:
        with pytest.raises(
            PromotionEffectTerminalizationError,
            match="lost a non-idempotent race",
        ):
            terminalize_promotion_effect(capability, ledger)
    finally:
        ledger.close()


def test_wrong_terminal_installed_by_competing_writer_is_not_laundered(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability, ledger = _prepared(tmp_path)
    effect_ledger = capability.authorization.effect_ledger
    original_finish = effect_ledger.finish

    def install_wrong_terminal(start, **kwargs):
        return original_finish(
            start,
            outcome="failed",
            output_digests=(),
            detail_sha256="9" * 64,
        )

    monkeypatch.setattr(effect_ledger, "finish", install_wrong_terminal)
    try:
        with pytest.raises(
            PromotionReconciliationError,
            match="contradicts promotion terminal",
        ):
            terminalize_promotion_effect(capability, ledger)
    finally:
        ledger.close()


def test_writer_return_substitution_is_refused_after_exact_reprojection(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability, ledger = _prepared(tmp_path)
    effect_ledger = capability.authorization.effect_ledger
    original_finish = effect_ledger.finish

    def return_substituted_receipt(*args, **kwargs):
        persisted = original_finish(*args, **kwargs)
        return dataclasses.replace(persisted, receipt_sha256="8" * 64)

    monkeypatch.setattr(effect_ledger, "finish", return_substituted_receipt)
    try:
        with pytest.raises(
            PromotionEffectTerminalizationError,
            match="differs from the terminalization write",
        ):
            terminalize_promotion_effect(capability, ledger)
    finally:
        ledger.close()


def test_result_contract_refuses_nonboolean_replay_flag(tmp_path) -> None:
    capability, ledger = _prepared(tmp_path)
    try:
        complete = terminalize_promotion_effect(capability, ledger)
        with pytest.raises(ValueError, match="replayed flag"):
            PromotionEffectTerminalizationResult(
                terminal=complete.terminal,
                reconciliation=complete.reconciliation,
                replayed=1,  # type: ignore[arg-type]
            )
    finally:
        ledger.close()


def test_terminalization_does_not_consume_or_reissue_owner_approval(tmp_path) -> None:
    capability, ledger = _prepared(tmp_path)
    approval_digest = capability.promotion.approval_consumption_sha256
    try:
        result = terminalize_promotion_effect(capability, ledger)
        assert capability.promotion.approval_consumption_sha256 == approval_digest
        assert result.reconciliation.promotion_execution is not None
        assert (
            result.reconciliation.promotion_execution.start.approval_consumption_sha256
            == approval_digest
        )
    finally:
        ledger.close()
