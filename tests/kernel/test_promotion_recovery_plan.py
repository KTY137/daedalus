from __future__ import annotations

from types import SimpleNamespace

import pytest

import daedalus.kernel.promotion_recovery as recovery
from daedalus.kernel.promotion_effects import PromotionEffectCapability
from daedalus.kernel.promotion_execution import PromotionExecutionLedger
from daedalus.kernel.promotion_reconciliation import (
    PromotionReconciliationDisposition,
)
from daedalus.spine.envelope import canonical_sha


AUTHORIZATION_DIGEST = "a" * 64
EFFECT_START_DIGEST = "b" * 64
EFFECT_TERMINAL_DIGEST = "c" * 64
PROMOTION_START_DIGEST = "d" * 64
PROMOTION_TERMINAL_DIGEST = "e" * 64


def _capability() -> PromotionEffectCapability:
    capability = object.__new__(PromotionEffectCapability)
    object.__setattr__(
        capability,
        "promotion",
        SimpleNamespace(authorization_sha256=AUTHORIZATION_DIGEST),
    )
    return capability


def _ledger() -> PromotionExecutionLedger:
    return object.__new__(PromotionExecutionLedger)


def _projection(disposition: PromotionReconciliationDisposition):
    effect = None
    promotion = None
    if disposition is not PromotionReconciliationDisposition.FRESH:
        effect = SimpleNamespace(
            start=SimpleNamespace(receipt_sha256=EFFECT_START_DIGEST),
            terminal=(
                SimpleNamespace(receipt_sha256=EFFECT_TERMINAL_DIGEST)
                if disposition is PromotionReconciliationDisposition.COMPLETE
                else None
            ),
        )
    if disposition in {
        PromotionReconciliationDisposition.PROMOTION_PENDING,
        PromotionReconciliationDisposition.EFFECT_TERMINAL_REQUIRED,
        PromotionReconciliationDisposition.COMPLETE,
    }:
        promotion = SimpleNamespace(
            start=SimpleNamespace(digest=PROMOTION_START_DIGEST),
            completion=(
                SimpleNamespace(
                    receipt=SimpleNamespace(digest=PROMOTION_TERMINAL_DIGEST)
                )
                if disposition
                in {
                    PromotionReconciliationDisposition.EFFECT_TERMINAL_REQUIRED,
                    PromotionReconciliationDisposition.COMPLETE,
                }
                else None
            ),
        )
    return SimpleNamespace(
        disposition=disposition,
        effect_execution=effect,
        promotion_execution=promotion,
    )


@pytest.mark.parametrize(
    (
        "disposition",
        "action",
        "manual_reconciliation",
        "owner_required",
    ),
    [
        (
            PromotionReconciliationDisposition.FRESH,
            recovery.PromotionRecoveryAction.NONE,
            False,
            False,
        ),
        (
            PromotionReconciliationDisposition.EFFECT_ONLY_PENDING,
            recovery.PromotionRecoveryAction.OWNER_DECISION_BEFORE_EFFECT_CANCELLATION,
            True,
            True,
        ),
        (
            PromotionReconciliationDisposition.PROMOTION_PENDING,
            recovery.PromotionRecoveryAction.FORENSIC_PROMOTION_RECONCILIATION,
            True,
            False,
        ),
        (
            PromotionReconciliationDisposition.EFFECT_TERMINAL_REQUIRED,
            recovery.PromotionRecoveryAction.TERMINALIZE_EFFECT_FROM_RETAINED_EVIDENCE,
            False,
            False,
        ),
        (
            PromotionReconciliationDisposition.COMPLETE,
            recovery.PromotionRecoveryAction.REPLAY_RETAINED_REPORT,
            False,
            False,
        ),
    ],
)
def test_recovery_plan_maps_every_retained_state_exactly(
    monkeypatch,
    disposition,
    action,
    manual_reconciliation,
    owner_required,
) -> None:
    projection = _projection(disposition)
    monkeypatch.setattr(
        recovery,
        "inspect_promotion_reconciliation",
        lambda capability, ledger: projection,
    )

    plan = recovery.plan_promotion_recovery(_capability(), _ledger())
    wire = plan.to_dict()
    digest = wire.pop("plan_sha256")

    assert plan.disposition == disposition.value
    assert plan.action == action.value
    assert plan.automatic_external_reexecution is False
    assert plan.manual_reconciliation_required is manual_reconciliation
    assert plan.owner_decision_required is owner_required
    assert plan.promotion_authorization_sha256 == AUTHORIZATION_DIGEST
    assert digest == canonical_sha(wire)


def test_effect_only_plan_binds_start_and_exposes_no_terminal(monkeypatch) -> None:
    projection = _projection(PromotionReconciliationDisposition.EFFECT_ONLY_PENDING)
    monkeypatch.setattr(
        recovery,
        "inspect_promotion_reconciliation",
        lambda capability, ledger: projection,
    )

    plan = recovery.plan_promotion_recovery(_capability(), _ledger())

    assert plan.effect_start_receipt_sha256 == EFFECT_START_DIGEST
    assert plan.effect_terminal_receipt_sha256 is None
    assert plan.promotion_start_sha256 is None
    assert plan.promotion_terminal_sha256 is None


def test_complete_plan_binds_both_terminal_receipts(monkeypatch) -> None:
    projection = _projection(PromotionReconciliationDisposition.COMPLETE)
    monkeypatch.setattr(
        recovery,
        "inspect_promotion_reconciliation",
        lambda capability, ledger: projection,
    )

    plan = recovery.plan_promotion_recovery(_capability(), _ledger())

    assert plan.effect_terminal_receipt_sha256 == EFFECT_TERMINAL_DIGEST
    assert plan.promotion_terminal_sha256 == PROMOTION_TERMINAL_DIGEST


def test_malformed_authority_types_refuse_before_projection(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        recovery,
        "inspect_promotion_reconciliation",
        lambda *args: calls.append(args),
    )

    with pytest.raises(TypeError):
        recovery.plan_promotion_recovery(object(), _ledger())
    with pytest.raises(TypeError):
        recovery.plan_promotion_recovery(_capability(), object())

    assert calls == []
