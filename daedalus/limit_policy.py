"""Compatibility facade for :mod:`daedalus.kernel.policy.limits`.

This module intentionally contains no policy state or implementation. Existing
imports receive the exact same class and function objects as the canonical
kernel owner.
"""

from daedalus.kernel.policy.limits import (
    ENV_EXECUTION_LIMIT_POLICY,
    LIMIT_AXES,
    LIMIT_MODES,
    MODE_BOUNDED,
    MODE_CUSTOM,
    MODE_UNBOUNDED_EXECUTION,
    ExecutionLimitPolicy,
    LimitAxes,
    LimitMode,
    LimitPolicyError,
    load_from_env,
    store_in_env,
)

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
]
