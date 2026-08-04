"""Pure cross-ledger replay decision for one sealed promotion effect.

The Effect-Lease ledger and promotion Event Store retain different truths:

* the Effect-Lease ledger says whether external authority was never started,
  remains pending, or reached one terminal state;
* the promotion Event Store says whether the exact repository mutation never
  received a durable start, remains pending reconciliation, or retained one
  terminal report.

A restart boundary must inspect both before deciding whether fresh execution is
permitted, whether reconciliation is required, or whether a retained report may
be replayed.  This module joins the two strict read projections without writing
to either authority and without invoking promotion.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from daedalus.kernel.effect_replay import (
    EffectExecutionReplaySnapshot,
    inspect_effect_execution,
)
from daedalus.kernel.promotion_effects import PromotionEffectCapability
from daedalus.kernel.promotion_execution import (
    PromotionExecutionBeginResult,
    PromotionExecutionLedger,
)
from daedalus.kernel.promotion_replay import inspect_promotion_execution


_ACTIONS = frozenset(
    {
        "fresh",
        "pending_reconciliation",
        "reconcile_effect_terminal",
        "replay_promotion_report",
        "replay_effect_terminal_without_report",
    }
)


class PromotionEffectReplayMismatch(RuntimeError):
    """Effect and promotion persistence contradict one exact execution subject."""


@dataclass(frozen=True)
class PromotionEffectReplayDecision:
    """One inert replay decision with no capability to perform an effect."""

    action: str
    effect: EffectExecutionReplaySnapshot | None
    promotion: PromotionExecutionBeginResult | None
    expected_output_digests: tuple[str, ...] = ()
    expected_detail_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.action not in _ACTIONS:
            raise ValueError("unknown promotion effect replay action")
        if tuple(sorted(set(self.expected_output_digests))) != (
            self.expected_output_digests
        ):
            raise ValueError("expected output digests must be sorted and unique")
        if self.action in {
            "reconcile_effect_terminal",
            "replay_promotion_report",
        }:
            if len(self.expected_output_digests) != 1:
                raise ValueError("promotion report action requires one output digest")
            if self.expected_detail_sha256 is None:
                raise ValueError("promotion report action requires receipt detail")
        elif self.expected_output_digests or self.expected_detail_sha256 is not None:
            raise ValueError("non-report replay action cannot carry report bindings")

    @property
    def permits_fresh_execution(self) -> bool:
        return self.action == "fresh"

    @property
    def requires_reconciliation(self) -> bool:
        return self.action in {
            "pending_reconciliation",
            "reconcile_effect_terminal",
        }


def _parse_utc(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise PromotionEffectReplayMismatch(f"{label} is not ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PromotionEffectReplayMismatch(f"{label} is not timezone-aware")
    return parsed.astimezone(timezone.utc)


def _promotion_report_bindings(
    promotion: PromotionExecutionBeginResult,
) -> tuple[tuple[str, ...], str]:
    completion = promotion.completion
    if completion is None:
        raise PromotionEffectReplayMismatch(
            "promotion report binding requires a terminal completion"
        )
    report_sha256 = completion.receipt.report_sha256
    receipt_sha256 = completion.receipt.digest
    return (report_sha256,), receipt_sha256


def _enforce_start_order(
    effect: EffectExecutionReplaySnapshot,
    promotion: PromotionExecutionBeginResult,
) -> None:
    if _parse_utc(
        promotion.start.started_at,
        "promotion start",
    ) < _parse_utc(effect.start_receipt.started_at, "effect start"):
        raise PromotionEffectReplayMismatch(
            "promotion start precedes its top-level Effect-Lease start"
        )


def _enforce_terminal_order(
    effect: EffectExecutionReplaySnapshot,
    promotion: PromotionExecutionBeginResult,
) -> None:
    if effect.terminal_receipt is None or promotion.completion is None:
        raise PromotionEffectReplayMismatch(
            "terminal chronology requires both terminal receipts"
        )
    if _parse_utc(
        effect.terminal_receipt.finished_at,
        "effect terminal",
    ) < _parse_utc(
        promotion.completion.receipt.completed_at,
        "promotion terminal",
    ):
        raise PromotionEffectReplayMismatch(
            "top-level Effect-Lease terminal precedes promotion terminal"
        )


def inspect_promotion_effect_replay(
    capability: PromotionEffectCapability,
    promotion_ledger: PromotionExecutionLedger,
) -> PromotionEffectReplayDecision:
    """Join exact effect and promotion persistence into one fail-closed action.

    The only action that permits a future caller to attempt a fresh Effect-Lease
    start is ``fresh``, which requires both projections to be absent.  Every
    pending state remains reconciliation-only.  A retained promotion report is
    replayable only when a completed top-level receipt binds its report digest,
    promotion-receipt digest and lifecycle chronology exactly.
    """

    if not isinstance(capability, PromotionEffectCapability):
        raise TypeError(
            "promotion effect replay requires PromotionEffectCapability"
        )
    if not isinstance(promotion_ledger, PromotionExecutionLedger):
        raise TypeError(
            "promotion effect replay requires PromotionExecutionLedger"
        )

    effect = inspect_effect_execution(
        capability.authorization,
        capability.execution,
    )
    promotion = inspect_promotion_execution(
        promotion_ledger,
        capability.promotion,
    )

    if effect is None:
        if promotion is not None:
            raise PromotionEffectReplayMismatch(
                "promotion execution exists without top-level Effect-Lease start"
            )
        return PromotionEffectReplayDecision(
            action="fresh",
            effect=None,
            promotion=None,
        )

    if promotion is not None:
        _enforce_start_order(effect, promotion)

    if effect.state == "STARTED":
        if promotion is None or promotion.completion is None:
            return PromotionEffectReplayDecision(
                action="pending_reconciliation",
                effect=effect,
                promotion=promotion,
            )
        outputs, detail = _promotion_report_bindings(promotion)
        return PromotionEffectReplayDecision(
            action="reconcile_effect_terminal",
            effect=effect,
            promotion=promotion,
            expected_output_digests=outputs,
            expected_detail_sha256=detail,
        )

    if effect.terminal_receipt is None:
        raise PromotionEffectReplayMismatch(
            "terminal Effect-Lease state has no terminal receipt"
        )

    if promotion is None:
        if effect.state in {"FAILED", "CANCELLED"}:
            return PromotionEffectReplayDecision(
                action="replay_effect_terminal_without_report",
                effect=effect,
                promotion=None,
            )
        raise PromotionEffectReplayMismatch(
            "completed Effect-Lease has no persisted promotion report"
        )

    if promotion.completion is None:
        raise PromotionEffectReplayMismatch(
            "terminal Effect-Lease contradicts pending promotion execution"
        )
    if effect.state != "COMPLETED":
        raise PromotionEffectReplayMismatch(
            "failed or cancelled Effect Lease contradicts terminal promotion report"
        )

    outputs, detail = _promotion_report_bindings(promotion)
    terminal = effect.terminal_receipt
    mismatches = []
    if terminal.output_digests != outputs:
        mismatches.append("output_digests")
    if terminal.detail_sha256 != detail:
        mismatches.append("detail_sha256")
    if mismatches:
        raise PromotionEffectReplayMismatch(
            "top-level Effect-Lease terminal does not bind promotion report: "
            + ", ".join(mismatches)
        )
    _enforce_terminal_order(effect, promotion)
    return PromotionEffectReplayDecision(
        action="replay_promotion_report",
        effect=effect,
        promotion=promotion,
        expected_output_digests=outputs,
        expected_detail_sha256=detail,
    )


__all__ = [
    "PromotionEffectReplayDecision",
    "PromotionEffectReplayMismatch",
    "inspect_promotion_effect_replay",
]
