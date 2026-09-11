"""Canonical pre-call pricing policy for budget admission.

Pricing answers only what one declared call must reserve before execution. It
does not persist ledger state, reserve money, install process interposers, or
perform provider/network effects. ``daedalus.budget`` remains the compatibility
facade while the remaining budget authorities are split in later packets.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


ENV_MAX_CALLS = "DAEDALUS_BUDGET_MAX_CALLS"
ENV_ON_UNKNOWN = "DAEDALUS_BUDGET_ON_UNKNOWN"
ENV_SUBSCRIPTIONS = "DAEDALUS_SUBSCRIPTION_VENDORS"

# Unknown cannot mean free. This deliberately exceeds the most expensive
# single call measured by the project.
UNKNOWN_CALL_USD = 5.00

# A child CLI that carries its own ``--max-budget-usd X`` cannot plausibly cost
# the flat vendor worst case -- but X is NOT a hard bound either. MEASURED
# 2026-09-08 on this host (docs/evidence/G1-IKARUS-36/probe3_opus.json):
# ``claude -p --max-budget-usd 0.25`` reported ``total_cost_usd`` $0.529010 --
# 2.12x its own cap -- before aborting with subtype ``error_max_budget_usd``.
# The reservation is therefore the declared cap times this overrun factor
# (headroom above the measured 2.12x), still clamped by the vendor worst case.
# An unknown price is not a free price, and a self-declared cap is not a
# guarantee: it is evidence that the call is smaller than the worst case.
CLI_BUDGET_CAP_OVERRUN_FACTOR = 3.0


class BudgetError(RuntimeError):
    """Base for every fail-closed budget refusal."""


class UnknownPrice(BudgetError):
    """Strict pricing mode could not establish a declared call price."""


@dataclass(frozen=True)
class VendorPrice:
    """Conservative upper bound and optional token prices for one vendor."""

    vendor: str
    per_call_worst_usd: float
    input_usd_per_mtok: float | None = None
    output_usd_per_mtok: float | None = None


_PRICES: dict[str, VendorPrice] = {
    # CLI session bounds are measured/assumed upper bounds, not live prices.
    "anthropic_cli": VendorPrice("anthropic_cli", 3.00),
    "openai_cli": VendorPrice("openai_cli", 2.00),
    "google_agy": VendorPrice("google_agy", 2.00),
    "anthropic_api": VendorPrice("anthropic_api", 0.50, 15.0, 75.0),
    "openai_api": VendorPrice("openai_api", 0.50, 10.0, 40.0),
    "deepseek": VendorPrice("deepseek", 0.05, 0.60, 1.80),
    "google_api": VendorPrice("google_api", 0.50, 10.0, 40.0),
    "remote_inference": VendorPrice("remote_inference", UNKNOWN_CALL_USD),
}

FREE_VENDORS = frozenset({"local", "local_inference"})


def subscription_vendors() -> frozenset[str]:
    """Return only known vendors explicitly declared flat-rate by the owner."""

    raw = os.environ.get(ENV_SUBSCRIPTIONS, "") or ""
    named = {part.strip().lower() for part in raw.split(",") if part.strip()}
    return frozenset(name for name in named if name in _PRICES)


@dataclass(frozen=True)
class Estimate:
    """Conservative price attributed before a call starts."""

    vendor: str
    model: str
    usd: float
    calls: int
    basis: str
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "vendor": self.vendor,
            "model": self.model,
            "usd": self.usd,
            "calls": self.calls,
            "basis": self.basis,
            "detail": self.detail,
        }


def _on_unknown_default() -> str:
    raw = (os.environ.get(ENV_ON_UNKNOWN) or "worst_case").strip().lower()
    return raw if raw in ("worst_case", "refuse") else "worst_case"


def price_call(
    vendor: str | None,
    model: str | None = None,
    *,
    calls: int = 1,
    host: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    on_unknown: str | None = None,
    cli_budget_cap_usd: float | None = None,
) -> Estimate:
    """Upper-bound call cost, returning zero only for proven free transport.

    ``cli_budget_cap_usd`` is the child CLI's OWN declared spend cap (the
    ``--max-budget-usd X`` in its argv). It narrows only the last, flat
    ``worst_case`` branch, and only downward: the free/trusted/subscription/
    unknown/token-priced answers are unchanged, because a self-declared cap
    says nothing about where the bytes go or whether a price is known. See
    :data:`CLI_BUDGET_CAP_OVERRUN_FACTOR` for why the cap is multiplied
    instead of used verbatim.
    """

    calls = max(1, int(calls))
    vendor = (vendor or "").strip().lower()
    model = (model or "").strip()
    mode = (on_unknown or _on_unknown_default()).strip().lower()

    if host is not None:
        # Host location outranks a provider label: this is pricing after the
        # canonical egress classifier, never a second host-trust authority.
        from ...sensitivity import is_loopback_host, lane_for_host

        if is_loopback_host(host):
            return Estimate(
                vendor or "local_inference",
                model,
                0.0,
                calls,
                "free_local",
                f"host {host} is this machine",
            )
        if lane_for_host(host) == "trusted":
            return Estimate(
                vendor or "local_inference",
                model,
                0.0,
                calls,
                "trusted_remote",
                f"host {host} is operator-declared trusted: $0, "
                "but still counted against the call cap",
            )
        vendor = vendor if vendor in _PRICES else "remote_inference"
        untrusted_endpoint = True
    else:
        untrusted_endpoint = False

    if vendor in FREE_VENDORS and host is None:
        vendor = "remote_inference"

    if vendor in subscription_vendors() and not untrusted_endpoint:
        return Estimate(
            vendor,
            model,
            0.0,
            calls,
            "subscription",
            f"'{vendor}' declared flat-rate via {ENV_SUBSCRIPTIONS}; billed $0 "
            f"but still {calls} call(s) against {ENV_MAX_CALLS}",
        )

    price = _PRICES.get(vendor)
    if price is None:
        if mode == "refuse":
            raise UnknownPrice(
                f"no price for vendor '{vendor or '?'}' model "
                f"'{model or '?'}' and {ENV_ON_UNKNOWN}=refuse"
            )
        return Estimate(
            vendor or "unknown",
            model,
            UNKNOWN_CALL_USD * calls,
            calls,
            "unknown",
            f"no price entry for '{vendor or '?'}'; charged the unknown-call "
            f"rate ${UNKNOWN_CALL_USD:.2f}",
        )

    if (
        input_tokens is not None
        and output_tokens is not None
        and price.input_usd_per_mtok is not None
        and price.output_usd_per_mtok is not None
    ):
        usd = (
            max(0, int(input_tokens))
            / 1_000_000
            * price.input_usd_per_mtok
            + max(0, int(output_tokens))
            / 1_000_000
            * price.output_usd_per_mtok
        )
        usd = max(usd, price.per_call_worst_usd * 0.01) * calls
        return Estimate(
            vendor,
            model,
            usd,
            calls,
            "priced",
            f"{input_tokens} in / {output_tokens} out tokens",
        )

    worst = price.per_call_worst_usd * calls
    if cli_budget_cap_usd is not None:
        try:
            cap = float(cli_budget_cap_usd)
        except (TypeError, ValueError):
            cap = 0.0
        if cap > 0 and cap == cap and cap != float("inf"):
            capped = cap * CLI_BUDGET_CAP_OVERRUN_FACTOR * calls
            if capped < worst:
                return Estimate(
                    vendor,
                    model,
                    capped,
                    calls,
                    "cli_budget_cap",
                    f"child CLI carries --max-budget-usd ${cap:.2f}; reserved "
                    f"{CLI_BUDGET_CAP_OVERRUN_FACTOR:g}x that (a cap is an "
                    f"abort switch, not a bound: measured 2.12x overrun) "
                    f"instead of the ${price.per_call_worst_usd:.2f} worst case",
                )
    return Estimate(
        vendor,
        model,
        worst,
        calls,
        "worst_case",
        f"flat upper bound ${price.per_call_worst_usd:.2f}/call",
    )


__all__ = [
    "BudgetError",
    "CLI_BUDGET_CAP_OVERRUN_FACTOR",
    "ENV_MAX_CALLS",
    "ENV_ON_UNKNOWN",
    "ENV_SUBSCRIPTIONS",
    "Estimate",
    "FREE_VENDORS",
    "UNKNOWN_CALL_USD",
    "UnknownPrice",
    "VendorPrice",
    "price_call",
    "subscription_vendors",
]
