"""Explicit reconciliation authority for promotion Effect-Lease terminals.

A completed promotion-execution receipt is durable evidence that the external
promotion attempt already reached a terminal outcome.  This module may append
only the corresponding top-level Effect-Lease terminal when the strict dual
read-only projection proves that this is the sole missing transition.  It does
not grant a lease, start or rerun promotion, invoke Git, mutate a checkout, or
create OwnerApproval.
"""
from __future__ import annotations

from dataclasses import dataclass

from daedalus.kernel.effects import EffectLeaseStateError, EffectTerminalReceipt
from daedalus.kernel.promotion_effects import PromotionEffectCapability
from daedalus.kernel.promotion_execution import PromotionExecutionLedger
from daedalus.kernel.promotion_reconciliation import (
    PromotionReconciliationDisposition,
    PromotionReconciliationProjection,
    inspect_promotion_reconciliation,
)


class PromotionEffectTerminalizationError(RuntimeError):
    """A promotion effect terminal cannot be reconciled from retained evidence."""


@dataclass(frozen=True)
class PromotionEffectTerminalizationResult:
    """Exact terminal receipt and final read-only reconciliation projection."""

    terminal: EffectTerminalReceipt
    reconciliation: PromotionReconciliationProjection
    replayed: bool

    def __post_init__(self) -> None:
        if not isinstance(self.terminal, EffectTerminalReceipt):
            raise ValueError("promotion terminalization requires an effect terminal")
        if not isinstance(self.reconciliation, PromotionReconciliationProjection):
            raise ValueError("promotion terminalization requires reconciliation evidence")
        if (
            self.reconciliation.disposition
            is not PromotionReconciliationDisposition.COMPLETE
        ):
            raise ValueError("promotion terminalization result must be complete")
        effect = self.reconciliation.effect_execution
        if effect is None or effect.terminal != self.terminal:
            raise ValueError("promotion terminalization result terminal mismatch")
        if type(self.replayed) is not bool:
            raise ValueError("promotion terminalization replayed flag must be boolean")


def _complete_result(
    projection: PromotionReconciliationProjection,
    *,
    replayed: bool,
) -> PromotionEffectTerminalizationResult:
    effect = projection.effect_execution
    if effect is None or effect.terminal is None:
        raise PromotionEffectTerminalizationError(
            "complete reconciliation is missing its effect terminal"
        )
    return PromotionEffectTerminalizationResult(
        terminal=effect.terminal,
        reconciliation=projection,
        replayed=replayed,
    )


def terminalize_promotion_effect(
    capability: PromotionEffectCapability,
    promotion_ledger: PromotionExecutionLedger,
) -> PromotionEffectTerminalizationResult:
    """Append only the exact terminal implied by durable promotion evidence.

    This is an explicit reconciliation authority rather than a bypass through
    ``NonRuntimeEffectAuthorization.finish_effect(COMPLETED)``.  The live
    facade intentionally requires an unexpired lease for fresh successful
    effects.  Here the external effect is already terminal and the strict
    promotion receipt, chronology, subject binding, report digest, and expected
    top-level terminal are revalidated immediately before and after the single
    accounting write.
    """

    if not isinstance(capability, PromotionEffectCapability):
        raise TypeError(
            "promotion effect terminalization requires PromotionEffectCapability"
        )
    if not isinstance(promotion_ledger, PromotionExecutionLedger):
        raise TypeError(
            "promotion effect terminalization requires PromotionExecutionLedger"
        )

    before = inspect_promotion_reconciliation(capability, promotion_ledger)
    if before.disposition is PromotionReconciliationDisposition.COMPLETE:
        return _complete_result(before, replayed=True)
    if (
        before.disposition
        is not PromotionReconciliationDisposition.EFFECT_TERMINAL_REQUIRED
    ):
        raise PromotionEffectTerminalizationError(
            "retained promotion state does not permit effect terminalization"
        )

    effect = before.effect_execution
    expected = before.expected_effect_terminal
    if effect is None or expected is None:
        raise PromotionEffectTerminalizationError(
            "terminalization-required projection is incomplete"
        )

    try:
        written = capability.authorization.effect_ledger.finish(
            effect.start,
            outcome=expected.outcome,
            output_digests=expected.output_digests,
            detail_sha256=expected.detail_sha256,
        )
    except EffectLeaseStateError as exc:
        # A concurrent reconciler may have installed the same exact terminal.
        # Only a complete strict re-projection converts that race into replay.
        after_race = inspect_promotion_reconciliation(capability, promotion_ledger)
        if after_race.disposition is PromotionReconciliationDisposition.COMPLETE:
            return _complete_result(after_race, replayed=True)
        raise PromotionEffectTerminalizationError(
            "effect terminalization lost a non-idempotent race"
        ) from exc

    after = inspect_promotion_reconciliation(capability, promotion_ledger)
    if after.disposition is not PromotionReconciliationDisposition.COMPLETE:
        raise PromotionEffectTerminalizationError(
            "effect terminal write did not produce complete reconciliation"
        )
    result = _complete_result(after, replayed=False)
    if result.terminal != written:
        raise PromotionEffectTerminalizationError(
            "persisted terminal differs from the terminalization write"
        )
    return result


__all__ = [
    "PromotionEffectTerminalizationError",
    "PromotionEffectTerminalizationResult",
    "terminalize_promotion_effect",
]
