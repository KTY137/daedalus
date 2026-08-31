"""Fail-closed spend admission for provider calls."""

from __future__ import annotations

from typing import Any

from daedalus.kernel.policy.ledger import BudgetRefused, Reservation, reserve
from daedalus.kernel.policy.pricing import BudgetError

from .reporting import blocked_report


def budget_refusal_report(exc: BudgetError) -> dict[str, Any]:
    """The blocked report for a refused call, including the measured numbers."""

    detail = exc.as_dict() if isinstance(exc, BudgetRefused) else {"reason": str(exc)}
    return blocked_report(
        f"Refused by the spend ceiling: {exc}",
        "Raise DAEDALUS_BUDGET_USD deliberately, wait for the budget period to "
        "roll over, or route this task to a local lane.",
        budget=detail,
    )


def reserve_or_report(
    *,
    vendor: str,
    model: str | None,
    label: str,
    provider: str,
    persona: str,
    agent: str | None,
    calls: int = 1,
    host: str | None = None,
) -> tuple[Reservation | None, dict[str, Any] | None]:
    """Return a reservation or a valid blocked provider-report envelope."""

    try:
        res = reserve(vendor, model, label=label, calls=calls, host=host)
    except BudgetError as exc:
        return None, {
            "provider": provider,
            "persona": persona,
            "agent": agent,
            "report": budget_refusal_report(exc),
        }
    return res, None


__all__ = ["budget_refusal_report", "reserve_or_report"]
