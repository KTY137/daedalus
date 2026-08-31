"""Execution-limit shaping shared by provider runtimes."""

from __future__ import annotations

import itertools
from collections.abc import Iterator

from daedalus.kernel.policy.limits import (
    ExecutionLimitPolicy,
    LimitPolicyError,
    load_from_env,
)


def bounded_execution_limit_policy(
    policy: ExecutionLimitPolicy | None,
) -> ExecutionLimitPolicy:
    """Return an explicit policy for internal helpers without reading env.

    Environment fallback belongs only at a provider's direct ``run`` admission.
    Internal helpers default to the legacy bounded behaviour so calling one in a
    test or from another already-admitted path cannot recapture mutable process
    configuration halfway through a request.
    """

    if policy is None:
        return ExecutionLimitPolicy()
    if not isinstance(policy, ExecutionLimitPolicy):
        raise LimitPolicyError(
            "execution_limit_policy must be an ExecutionLimitPolicy"
        )
    return policy


def admit_execution_limit_policy(
    policy: ExecutionLimitPolicy | None,
) -> ExecutionLimitPolicy:
    """Capture the policy once at a provider's direct admission boundary."""

    return load_from_env() if policy is None else bounded_execution_limit_policy(policy)


def attempt_numbers(
    policy: ExecutionLimitPolicy | None,
    bounded_attempts: int,
) -> Iterator[int]:
    """Yield bounded attempt numbers, or an open iterator when attempts are off.

    There is deliberately no large-number stand-in for unlimited execution.
    A finite fake (or a real provider that eventually succeeds) terminates the
    open iterator through the caller's ordinary ``break``/``return`` path.
    """

    resolved = bounded_execution_limit_policy(policy)
    if bounded_attempts <= 0:
        raise ValueError("bounded_attempts must be positive")
    if resolved.enforces("attempts"):
        return iter(range(bounded_attempts))
    return itertools.count()


def provider_http_timeout(
    policy: ExecutionLimitPolicy | None,
    timeout_s: float | None,
    *,
    bounded_default: float = 300.0,
) -> float | None:
    """Return a real deadline or ``None``; never encode unlimited as a number."""

    resolved = bounded_execution_limit_policy(policy)
    if not resolved.enforces("wall_time"):
        return None
    return bounded_default if timeout_s is None else float(timeout_s)


__all__ = [
    "admit_execution_limit_policy",
    "attempt_numbers",
    "bounded_execution_limit_policy",
    "provider_http_timeout",
]
