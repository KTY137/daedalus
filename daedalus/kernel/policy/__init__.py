"""Kernel-owned policy contracts.

The concrete owners hold their implementations: :mod:`.limits` owns the
execution-limit policy, :mod:`.pricing` owns vendor prices and estimates, and
:mod:`.ledger` owns the period ledger, reservations and spend envelopes. This
package only preserves the historical reexports, loading an owner when (and
only when) one of its names is requested.

Importing one owner must not drag in the others. Requesting an execution-limit
name previously pulled the budget ledger and pricing tables into every process
that touched policy, which defeated the lazy kernel facade above it.
"""

from importlib import import_module as _import_module


# Ordered exactly like the pre-facade ``__all__``: export order is a
# compatibility contract independent of module grouping.
_EXPORT_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("limits", (
        "ENV_EXECUTION_LIMIT_POLICY",
        "LIMIT_AXES",
        "LIMIT_MODES",
        "MODE_BOUNDED",
        "MODE_CUSTOM",
        "MODE_UNBOUNDED_EXECUTION",
        "ExecutionLimitPolicy",
        "LimitAxes",
        "LimitMode",
        "LimitPolicyError",
        "load_from_env",
        "store_in_env",
    )),
    ("pricing", (
        "BudgetError",
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
    )),
    ("ledger", (
        "BudgetRefused",
        "BudgetState",
        "BudgetUnavailable",
        "DEFAULT_CEILING_USD",
        "DEFAULT_ENVELOPE_TTL_S",
        "DEFAULT_LEDGER_PATH",
        "DEFAULT_MAX_CALLS",
        "ENV_CEILING",
        "ENV_ENVELOPE",
        "ENV_LEDGER",
        "ENV_PERIOD",
        "ENV_PERIOD_CEILING_ENABLED",
        "Ledger",
        "Reservation",
        "SpendEnvelope",
        "open_envelope",
        "reserve",
        "reset_default_ledger",
    )),
)

_EXPORTS: dict[str, str] = {
    _name: _owner for _owner, _names in _EXPORT_GROUPS for _name in _names
}

__all__ = [
    "ENV_EXECUTION_LIMIT_POLICY",
    "LIMIT_AXES",
    "LIMIT_MODES",
    "MODE_BOUNDED",
    "MODE_CUSTOM",
    "MODE_UNBOUNDED_EXECUTION",
    "ExecutionLimitPolicy",
    "LimitAxes",
    "LimitMode",
    "LimitPolicyError",
    "load_from_env",
    "store_in_env",
    "BudgetError",
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
    "BudgetRefused",
    "BudgetState",
    "BudgetUnavailable",
    "DEFAULT_CEILING_USD",
    "DEFAULT_ENVELOPE_TTL_S",
    "DEFAULT_LEDGER_PATH",
    "DEFAULT_MAX_CALLS",
    "ENV_CEILING",
    "ENV_ENVELOPE",
    "ENV_LEDGER",
    "ENV_PERIOD",
    "ENV_PERIOD_CEILING_ENABLED",
    "Ledger",
    "Reservation",
    "SpendEnvelope",
    "open_envelope",
    "reserve",
    "reset_default_ledger",
]


def __getattr__(name: str):
    """Resolve one reexport by loading only the owner that holds it."""
    owner = _EXPORTS.get(name)
    if owner is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(_import_module(f"{__name__}.{owner}"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
