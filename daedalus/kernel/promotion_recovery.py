"""Read-only operator recovery plan for persisted promotion lifecycles.

The plan turns the strict cross-ledger reconciliation projection into a bounded,
machine-readable operator decision.  It never starts, finishes, retries or
promotes anything and never treats a pending state as permission to re-execute.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from daedalus.spine.envelope import canonical_sha

from .promotion_effects import PromotionEffectCapability
from .promotion_execution import PromotionExecutionLedger
from .promotion_reconciliation import (
    PromotionReconciliationDisposition,
    inspect_promotion_reconciliation,
)


class PromotionRecoveryAction(str, Enum):
    """The sole next operator action admitted for one retained state."""

    NONE = "none"
    OWNER_DECISION_BEFORE_EFFECT_CANCELLATION = (
        "owner-decision-before-effect-cancellation"
    )
    FORENSIC_PROMOTION_RECONCILIATION = "forensic-promotion-reconciliation"
    TERMINALIZE_EFFECT_FROM_RETAINED_EVIDENCE = (
        "terminalize-effect-from-retained-evidence"
    )
    REPLAY_RETAINED_REPORT = "replay-retained-report"


_ACTION_BY_DISPOSITION = {
    PromotionReconciliationDisposition.FRESH: PromotionRecoveryAction.NONE,
    PromotionReconciliationDisposition.EFFECT_ONLY_PENDING: (
        PromotionRecoveryAction.OWNER_DECISION_BEFORE_EFFECT_CANCELLATION
    ),
    PromotionReconciliationDisposition.PROMOTION_PENDING: (
        PromotionRecoveryAction.FORENSIC_PROMOTION_RECONCILIATION
    ),
    PromotionReconciliationDisposition.EFFECT_TERMINAL_REQUIRED: (
        PromotionRecoveryAction.TERMINALIZE_EFFECT_FROM_RETAINED_EVIDENCE
    ),
    PromotionReconciliationDisposition.COMPLETE: (
        PromotionRecoveryAction.REPLAY_RETAINED_REPORT
    ),
}


@dataclass(frozen=True, slots=True)
class PromotionRecoveryPlan:
    """Exact read-only recovery decision bound to retained lifecycle evidence."""

    schema: str
    promotion_authorization_sha256: str
    disposition: str
    action: str
    automatic_external_reexecution: bool
    owner_decision_required: bool
    effect_start_receipt_sha256: str | None
    effect_terminal_receipt_sha256: str | None
    promotion_start_sha256: str | None
    promotion_terminal_sha256: str | None
    plan_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "promotion_authorization_sha256": self.promotion_authorization_sha256,
            "disposition": self.disposition,
            "action": self.action,
            "automatic_external_reexecution": self.automatic_external_reexecution,
            "owner_decision_required": self.owner_decision_required,
            "effect_start_receipt_sha256": self.effect_start_receipt_sha256,
            "effect_terminal_receipt_sha256": self.effect_terminal_receipt_sha256,
            "promotion_start_sha256": self.promotion_start_sha256,
            "promotion_terminal_sha256": self.promotion_terminal_sha256,
            "plan_sha256": self.plan_sha256,
        }


def plan_promotion_recovery(
    capability: PromotionEffectCapability,
    promotion_ledger: PromotionExecutionLedger,
) -> PromotionRecoveryPlan:
    """Project the exact non-automatic operator action for one promotion."""

    if not isinstance(capability, PromotionEffectCapability):
        raise TypeError("promotion recovery requires PromotionEffectCapability")
    if not isinstance(promotion_ledger, PromotionExecutionLedger):
        raise TypeError("promotion recovery requires PromotionExecutionLedger")

    projection = inspect_promotion_reconciliation(capability, promotion_ledger)
    action = _ACTION_BY_DISPOSITION.get(projection.disposition)
    if action is None:
        raise RuntimeError("promotion recovery encountered an unknown disposition")

    effect = projection.effect_execution
    promotion = projection.promotion_execution
    body = {
        "schema": "daedalus-promotion-recovery-plan/1",
        "promotion_authorization_sha256": (
            capability.promotion.authorization_sha256
        ),
        "disposition": projection.disposition.value,
        "action": action.value,
        "automatic_external_reexecution": False,
        "owner_decision_required": projection.disposition
        in {
            PromotionReconciliationDisposition.EFFECT_ONLY_PENDING,
            PromotionReconciliationDisposition.PROMOTION_PENDING,
        },
        "effect_start_receipt_sha256": (
            None if effect is None else effect.start.receipt_sha256
        ),
        "effect_terminal_receipt_sha256": (
            None
            if effect is None or effect.terminal is None
            else effect.terminal.receipt_sha256
        ),
        "promotion_start_sha256": (
            None if promotion is None else promotion.start.digest
        ),
        "promotion_terminal_sha256": (
            None
            if promotion is None or promotion.completion is None
            else promotion.completion.receipt.digest
        ),
    }
    return PromotionRecoveryPlan(
        **body,
        plan_sha256=canonical_sha(body),
    )


__all__ = [
    "PromotionRecoveryAction",
    "PromotionRecoveryPlan",
    "plan_promotion_recovery",
]
