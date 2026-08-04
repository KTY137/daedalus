"""Deterministic terminal reconciliation for an already-finished promotion.

This module closes one narrow crash window:

1. the exact top-level Effect Lease was durably started;
2. the exact promotion execution reached a strict persisted terminal report;
3. the process stopped before the top-level Effect-Lease terminal was written.

Reconciliation does not repeat the repository effect.  It recomputes the strict
cross-ledger decision, derives outcome/output/detail solely from retained
promotion evidence, and performs one compare-and-state terminal write through
the canonical Effect-Lease ledger.  The logical terminal time is the retained
promotion completion time, making concurrent/restarted reconciliation
byte-deterministic.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from daedalus.kernel.effects import (
    EffectLeaseStateError,
    EffectTerminalReceipt,
)
from daedalus.kernel.promotion_effect_replay import (
    PromotionEffectReplayDecision,
    PromotionEffectReplayMismatch,
    inspect_promotion_effect_replay,
)
from daedalus.kernel.promotion_effects import PromotionEffectCapability
from daedalus.kernel.promotion_execution import PromotionExecutionLedger


class PromotionEffectReconciliationRefused(RuntimeError):
    """Current persisted state cannot be reconciled by this narrow writer."""


class PromotionEffectReconciliationMismatch(RuntimeError):
    """A reconciliation write did not produce the exact retained decision."""


@dataclass(frozen=True)
class PromotionEffectReconciliationResult:
    """One exact terminal result; ``changed`` says whether this call wrote it."""

    decision: PromotionEffectReplayDecision
    terminal_receipt: EffectTerminalReceipt
    changed: bool

    def __post_init__(self) -> None:
        if self.decision.action != "replay_promotion_report":
            raise ValueError("reconciliation result requires replayable promotion report")
        if self.decision.effect is None:
            raise ValueError("reconciliation result requires persisted effect state")
        if self.decision.effect.terminal_receipt != self.terminal_receipt:
            raise ValueError("reconciliation result terminal does not match decision")
        if type(self.changed) is not bool:
            raise ValueError("reconciliation changed flag must be boolean")


def _completion_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise PromotionEffectReconciliationMismatch(
            "persisted promotion completion time is malformed"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PromotionEffectReconciliationMismatch(
            "persisted promotion completion time is not timezone-aware"
        )
    return parsed.astimezone(timezone.utc)


def _replayed_result(
    decision: PromotionEffectReplayDecision,
    *,
    changed: bool,
) -> PromotionEffectReconciliationResult:
    effect = decision.effect
    if effect is None or effect.terminal_receipt is None:
        raise PromotionEffectReconciliationMismatch(
            "replay decision is missing the exact Effect-Lease terminal"
        )
    return PromotionEffectReconciliationResult(
        decision=decision,
        terminal_receipt=effect.terminal_receipt,
        changed=changed,
    )


def reconcile_promotion_effect_terminal(
    capability: PromotionEffectCapability,
    promotion_ledger: PromotionExecutionLedger,
) -> PromotionEffectReconciliationResult:
    """Close only the retained-promotion/started-effect crash window.

    The function never starts an Effect Lease and never invokes promotion.  A
    previously reconciled exact terminal is replayed without writing.  Every
    other state, including ``fresh`` and either pending state, is refused.

    The terminal write intentionally uses the canonical ledger directly rather
    than live-authority completion: historical start authentication and exact
    promotion evidence were already checked by the read projections, and this
    path performs accounting only.  Expiry or later revocation therefore cannot
    erase the terminal truth of an effect that already happened, while no new
    external effect authority is recovered.
    """

    if not isinstance(capability, PromotionEffectCapability):
        raise TypeError(
            "promotion effect reconciliation requires PromotionEffectCapability"
        )
    if not isinstance(promotion_ledger, PromotionExecutionLedger):
        raise TypeError(
            "promotion effect reconciliation requires PromotionExecutionLedger"
        )

    decision = inspect_promotion_effect_replay(capability, promotion_ledger)
    if decision.action == "replay_promotion_report":
        return _replayed_result(decision, changed=False)
    if decision.action != "reconcile_effect_terminal":
        raise PromotionEffectReconciliationRefused(
            f"promotion effect reconciliation refused state {decision.action!r}"
        )

    effect = decision.effect
    promotion = decision.promotion
    if (
        effect is None
        or effect.terminal_receipt is not None
        or promotion is None
        or promotion.completion is None
        or decision.expected_effect_outcome is None
        or len(decision.expected_output_digests) != 1
        or decision.expected_detail_sha256 is None
    ):
        raise PromotionEffectReconciliationMismatch(
            "reconciliation decision is incomplete or contradictory"
        )

    finished_at = _completion_time(promotion.completion.receipt.completed_at)
    ledger = capability.authorization.effect_ledger
    try:
        written = ledger.finish(
            effect.start_receipt,
            outcome=decision.expected_effect_outcome,
            output_digests=decision.expected_output_digests,
            detail_sha256=decision.expected_detail_sha256,
            finished_at=finished_at,
        )
    except EffectLeaseStateError as exc:
        raced = inspect_promotion_effect_replay(capability, promotion_ledger)
        if raced.action != "replay_promotion_report":
            raise PromotionEffectReconciliationMismatch(
                "effect terminal changed concurrently to a non-replayable state"
            ) from exc
        return _replayed_result(raced, changed=False)

    replayed = inspect_promotion_effect_replay(capability, promotion_ledger)
    if replayed.action != "replay_promotion_report":
        raise PromotionEffectReconciliationMismatch(
            "reconciled terminal did not become an exact report replay"
        )
    result = _replayed_result(replayed, changed=True)
    if result.terminal_receipt != written:
        raise PromotionEffectReconciliationMismatch(
            "persisted reconciled terminal differs from returned receipt"
        )
    return result


__all__ = [
    "PromotionEffectReconciliationMismatch",
    "PromotionEffectReconciliationRefused",
    "PromotionEffectReconciliationResult",
    "reconcile_promotion_effect_terminal",
]
