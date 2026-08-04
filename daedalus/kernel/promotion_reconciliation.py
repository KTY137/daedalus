"""Read-only reconciliation projection across both promotion lifecycles.

A live promotion is intended to persist a top-level Effect-Lease start before
its promotion-execution start. This module compares the two existing strict
read-only projections and classifies retained restart state. It never grants,
starts, finishes, reconciles, invokes Git, or authorizes automatic execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from daedalus.kernel.effects import EffectTerminalReceipt
from daedalus.kernel.promotion_effect_replay import (
    PromotionEffectReplayResult,
    inspect_promotion_effect_execution,
)
from daedalus.kernel.promotion_effects import PromotionEffectCapability
from daedalus.kernel.promotion_execution import (
    PromotionExecutionBeginResult,
    PromotionExecutionLedger,
    PromotionExecutionReceipt,
)
from daedalus.kernel.promotion_replay import inspect_promotion_execution
from daedalus.schemas import _sha256


class PromotionReconciliationDisposition(str, Enum):
    """Inert restart classifications across both promotion lifecycles."""

    FRESH = "fresh"
    EFFECT_ONLY_PENDING = "effect-only-pending-reconciliation"
    PROMOTION_PENDING = "promotion-pending-reconciliation"
    EFFECT_TERMINAL_REQUIRED = "effect-terminalization-required"
    COMPLETE = "complete"


class PromotionReconciliationError(RuntimeError):
    """The two retained promotion lifecycles contradict one another."""


@dataclass(frozen=True)
class ExpectedPromotionEffectTerminal:
    """Exact terminal material implied by a promotion-execution receipt."""

    outcome: str
    output_digests: tuple[str, ...]
    detail_sha256: str

    def __post_init__(self) -> None:
        if self.outcome not in {"COMPLETED", "FAILED", "CANCELLED"}:
            raise ValueError("expected promotion effect outcome is invalid")
        try:
            outputs = tuple(
                _sha256(value, "output_digest") for value in self.output_digests
            )
            detail = _sha256(self.detail_sha256, "detail_sha256")
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "expected promotion effect terminal contains a malformed digest"
            ) from exc
        if outputs != tuple(sorted(set(outputs))):
            raise ValueError("expected promotion outputs must be sorted and unique")
        object.__setattr__(self, "output_digests", outputs)
        object.__setattr__(self, "detail_sha256", detail)


@dataclass(frozen=True)
class PromotionReconciliationProjection:
    """One inert restart classification over both persisted authorities."""

    disposition: PromotionReconciliationDisposition
    effect_execution: PromotionEffectReplayResult | None
    promotion_execution: PromotionExecutionBeginResult | None
    expected_effect_terminal: ExpectedPromotionEffectTerminal | None

    def __post_init__(self) -> None:
        if not isinstance(
            self.disposition,
            PromotionReconciliationDisposition,
        ):
            raise ValueError("promotion reconciliation disposition is invalid")
        effect = self.effect_execution
        promotion = self.promotion_execution
        expected = self.expected_effect_terminal
        valid = {
            PromotionReconciliationDisposition.FRESH: (
                effect is None and promotion is None and expected is None
            ),
            PromotionReconciliationDisposition.EFFECT_ONLY_PENDING: (
                effect is not None
                and effect.terminal is None
                and promotion is None
                and expected is None
            ),
            PromotionReconciliationDisposition.PROMOTION_PENDING: (
                effect is not None
                and effect.terminal is None
                and promotion is not None
                and promotion.completion is None
                and expected is None
            ),
            PromotionReconciliationDisposition.EFFECT_TERMINAL_REQUIRED: (
                effect is not None
                and effect.terminal is None
                and promotion is not None
                and promotion.completion is not None
                and expected is not None
            ),
            PromotionReconciliationDisposition.COMPLETE: (
                effect is not None
                and effect.terminal is not None
                and promotion is not None
                and promotion.completion is not None
                and expected is not None
            ),
        }[self.disposition]
        if not valid:
            raise ValueError(
                "promotion reconciliation disposition contradicts retained state"
            )

    @property
    def automatic_execution_allowed(self) -> bool:
        """This read-only projection never grants replay or mutation authority."""

        return False


def _instant(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise PromotionReconciliationError(f"{label} is not ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PromotionReconciliationError(f"{label} is not timezone-aware")
    return parsed.astimezone(timezone.utc)


def _expected_terminal(
    receipt: PromotionExecutionReceipt,
) -> ExpectedPromotionEffectTerminal:
    if receipt.outcome == "succeeded":
        return ExpectedPromotionEffectTerminal(
            outcome="COMPLETED",
            output_digests=tuple(sorted({receipt.digest, receipt.report_sha256})),
            detail_sha256=receipt.digest,
        )
    if receipt.outcome == "refused":
        return ExpectedPromotionEffectTerminal(
            outcome="CANCELLED",
            output_digests=(),
            detail_sha256=receipt.digest,
        )
    if receipt.outcome == "faulted":
        return ExpectedPromotionEffectTerminal(
            outcome="FAILED",
            output_digests=(),
            detail_sha256=receipt.digest,
        )
    raise PromotionReconciliationError("promotion execution has an unknown outcome")


def _verify_terminal(
    actual: EffectTerminalReceipt,
    expected: ExpectedPromotionEffectTerminal,
) -> None:
    comparisons = {
        "outcome": (actual.outcome, expected.outcome),
        "output_digests": (actual.output_digests, expected.output_digests),
        "detail_sha256": (actual.detail_sha256, expected.detail_sha256),
    }
    mismatches = sorted(
        name for name, (observed, wanted) in comparisons.items() if observed != wanted
    )
    if mismatches:
        raise PromotionReconciliationError(
            "effect terminal contradicts promotion terminal: "
            + ", ".join(mismatches)
        )


def inspect_promotion_reconciliation(
    capability: PromotionEffectCapability,
    promotion_ledger: PromotionExecutionLedger,
) -> PromotionReconciliationProjection:
    """Classify exact retained state without writing or re-executing anything."""

    if not isinstance(capability, PromotionEffectCapability):
        raise TypeError("promotion reconciliation requires PromotionEffectCapability")
    if not isinstance(promotion_ledger, PromotionExecutionLedger):
        raise TypeError("promotion reconciliation requires PromotionExecutionLedger")

    effect = inspect_promotion_effect_execution(capability)
    promotion = inspect_promotion_execution(
        promotion_ledger,
        capability.promotion,
    )

    if effect is None and promotion is None:
        return PromotionReconciliationProjection(
            PromotionReconciliationDisposition.FRESH,
            None,
            None,
            None,
        )
    if effect is None:
        raise PromotionReconciliationError(
            "promotion execution exists without a top-level effect start"
        )
    if promotion is None:
        if effect.terminal is not None:
            raise PromotionReconciliationError(
                "effect terminal exists without a promotion-execution start"
            )
        return PromotionReconciliationProjection(
            PromotionReconciliationDisposition.EFFECT_ONLY_PENDING,
            effect,
            None,
            None,
        )

    effect_started = _instant(effect.start.started_at, "effect start time")
    promotion_started = _instant(
        promotion.start.started_at,
        "promotion-execution start time",
    )
    if effect_started > promotion_started:
        raise PromotionReconciliationError(
            "promotion-execution start precedes its top-level effect start"
        )

    if promotion.completion is None:
        if effect.terminal is not None:
            raise PromotionReconciliationError(
                "effect terminal exists while promotion execution is pending"
            )
        return PromotionReconciliationProjection(
            PromotionReconciliationDisposition.PROMOTION_PENDING,
            effect,
            promotion,
            None,
        )

    expected = _expected_terminal(promotion.completion.receipt)
    if effect.terminal is None:
        return PromotionReconciliationProjection(
            PromotionReconciliationDisposition.EFFECT_TERMINAL_REQUIRED,
            effect,
            promotion,
            expected,
        )

    promotion_finished = _instant(
        promotion.completion.receipt.completed_at,
        "promotion-execution completion time",
    )
    effect_finished = _instant(
        effect.terminal.finished_at,
        "effect terminal time",
    )
    if effect_finished < promotion_finished:
        raise PromotionReconciliationError(
            "top-level effect terminal precedes promotion completion"
        )
    _verify_terminal(effect.terminal, expected)
    return PromotionReconciliationProjection(
        PromotionReconciliationDisposition.COMPLETE,
        effect,
        promotion,
        expected,
    )


__all__ = [
    "ExpectedPromotionEffectTerminal",
    "PromotionReconciliationDisposition",
    "PromotionReconciliationError",
    "PromotionReconciliationProjection",
    "inspect_promotion_reconciliation",
]
