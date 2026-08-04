"""Narrow restart authority for terminalizing one retained promotion effect.

This module does not authorize or execute promotion.  It consumes the strict
cross-ledger reconciliation projection and permits exactly one bookkeeping
write when a canonical promotion-execution terminal already exists but its
outer Effect-Lease execution is still ``STARTED``.

The special authority is required for the successful crash window: a process
may persist the promotion terminal and terminate before the outer
``COMPLETED`` receipt is written.  Requiring the original lease to remain
unexpired and unrevoked would make that durable history impossible to close.
This module therefore bypasses *current* execution authority only for the exact
terminal material cryptographically and structurally implied by the retained
promotion receipt.  It cannot begin an effect, alter promotion state, invoke
Git, expose automatic execution, or choose terminal output.
"""
from __future__ import annotations

from datetime import datetime, timezone

from daedalus.kernel.effects import EffectLeaseStateError, EffectTerminalReceipt
from daedalus.kernel.promotion_effects import PromotionEffectCapability
from daedalus.kernel.promotion_execution import PromotionExecutionLedger
from daedalus.kernel.promotion_reconciliation import (
    PromotionReconciliationDisposition,
    PromotionReconciliationError,
    inspect_promotion_reconciliation,
)


class PromotionTerminalizationError(RuntimeError):
    """Retained state does not permit exact outer-effect terminalization."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _instant(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise PromotionTerminalizationError(f"{label} is not ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PromotionTerminalizationError(f"{label} is not timezone-aware")
    return parsed.astimezone(timezone.utc)


def _complete_terminal(
    capability: PromotionEffectCapability,
    promotion_ledger: PromotionExecutionLedger,
) -> EffectTerminalReceipt | None:
    """Return an exact retained complete terminal, otherwise ``None``.

    Re-running the strict projection after a competing writer is the only
    accepted idempotency path.  A terminal that does not bind the promotion
    receipt causes the projection itself to refuse.
    """

    projection = inspect_promotion_reconciliation(capability, promotion_ledger)
    if projection.disposition is not PromotionReconciliationDisposition.COMPLETE:
        return None
    if projection.effect_execution is None or projection.effect_execution.terminal is None:
        raise PromotionTerminalizationError(
            "complete promotion reconciliation omitted its effect terminal"
        )
    return projection.effect_execution.terminal


def reconcile_promotion_effect_terminal(
    capability: PromotionEffectCapability,
    promotion_ledger: PromotionExecutionLedger,
) -> EffectTerminalReceipt:
    """Persist or replay the one terminal implied by retained promotion state.

    The function is intentionally not a method on ``PromotionEffectCapability``:
    normal capability completion still enforces current authority for a live
    success.  This separately reviewed restart path is admitted only after both
    strict read-only ledgers prove that promotion completed and the outer effect
    alone remains pending.
    """

    if not isinstance(capability, PromotionEffectCapability):
        raise TypeError("promotion terminalization requires PromotionEffectCapability")
    if not isinstance(promotion_ledger, PromotionExecutionLedger):
        raise TypeError("promotion terminalization requires PromotionExecutionLedger")

    projection = inspect_promotion_reconciliation(capability, promotion_ledger)
    if projection.disposition is PromotionReconciliationDisposition.COMPLETE:
        if projection.effect_execution is None or projection.effect_execution.terminal is None:
            raise PromotionTerminalizationError(
                "complete promotion reconciliation omitted its effect terminal"
            )
        return projection.effect_execution.terminal
    if (
        projection.disposition
        is not PromotionReconciliationDisposition.EFFECT_TERMINAL_REQUIRED
    ):
        raise PromotionTerminalizationError(
            "promotion state is not eligible for outer-effect terminalization: "
            f"{projection.disposition.value}"
        )
    if (
        projection.effect_execution is None
        or projection.effect_execution.terminal is not None
        or projection.promotion_execution is None
        or projection.promotion_execution.completion is None
        or projection.expected_effect_terminal is None
    ):
        raise PromotionTerminalizationError(
            "terminalization projection is internally incomplete"
        )

    start = projection.effect_execution.start
    expected = projection.expected_effect_terminal
    finished_at = _utc_now()
    promotion_finished_at = _instant(
        projection.promotion_execution.completion.receipt.completed_at,
        "promotion completion time",
    )
    if finished_at < promotion_finished_at:
        raise PromotionTerminalizationError(
            "current clock precedes retained promotion completion; refusing "
            "a chronologically invalid effect terminal"
        )
    try:
        written = capability.authorization.effect_ledger.finish(
            start,
            outcome=expected.outcome,
            output_digests=expected.output_digests,
            detail_sha256=expected.detail_sha256,
            finished_at=finished_at,
        )
    except EffectLeaseStateError:
        # A concurrent reconciler may have terminalized the exact same retained
        # start.  Only the strict complete projection may convert that race into
        # an idempotent replay; every contradictory terminal remains an error.
        retained = _complete_terminal(capability, promotion_ledger)
        if retained is None:
            raise
        return retained

    try:
        retained = _complete_terminal(capability, promotion_ledger)
    except PromotionReconciliationError as exc:
        raise PromotionTerminalizationError(
            "written effect terminal does not reconcile with promotion evidence"
        ) from exc
    if retained is None:
        raise PromotionTerminalizationError(
            "effect terminal write did not produce a complete retained lifecycle"
        )
    if retained.receipt_sha256 != written.receipt_sha256:
        raise PromotionTerminalizationError(
            "retained effect terminal differs from the receipt just written"
        )
    return retained


__all__ = [
    "PromotionTerminalizationError",
    "reconcile_promotion_effect_terminal",
]
