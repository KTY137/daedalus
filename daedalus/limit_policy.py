"""Canonical owner-controlled execution limit policy.

The policy answers one narrow question: which Daedalus-owned *resource* caps
are enforced for newly admitted work?  It is deliberately separate from
authorization, containment, evidence, and promotion policy; those boundaries
are not axes here and therefore cannot be disabled through this contract.

The stored representation retains the owner's per-axis choices in every mode.
``bounded`` and ``unbounded_execution`` derive their effective values without
rewriting those choices, so switching back to ``custom`` restores them.  A
disabled cap is represented by an explicit ``False`` enforcement flag, never
by a numeric sentinel.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal


MODE_BOUNDED: Final = "bounded"
MODE_CUSTOM: Final = "custom"
MODE_UNBOUNDED_EXECUTION: Final = "unbounded_execution"

LIMIT_MODES: Final[tuple[str, ...]] = (
    MODE_BOUNDED,
    MODE_CUSTOM,
    MODE_UNBOUNDED_EXECUTION,
)

LIMIT_AXES: Final[tuple[str, ...]] = (
    "period_usd",
    "billable_calls",
    "mission_spend",
    "tokens",
    "wall_time",
    "attempts",
    "concurrency",
    "work_scope",
)

ENV_EXECUTION_LIMIT_POLICY: Final = "DAEDALUS_EXECUTION_LIMIT_POLICY"

LimitMode = Literal["bounded", "custom", "unbounded_execution"]


class LimitPolicyError(ValueError):
    """The supplied execution limit policy is not canonical or valid."""


def _require_exact_dict(
    value: object,
    *,
    expected_keys: tuple[str, ...],
    name: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LimitPolicyError(f"{name} must be an object")
    keys = set(value)
    expected = set(expected_keys)
    missing = sorted(expected - keys)
    extra = sorted((repr(key) for key in keys - expected))
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append(f"missing keys: {', '.join(missing)}")
        if extra:
            details.append(f"unknown keys: {', '.join(extra)}")
        raise LimitPolicyError(f"{name} has invalid shape ({'; '.join(details)})")
    return value


@dataclass(frozen=True, slots=True)
class LimitAxes:
    """Configured or effective enforcement flags for the eight canonical axes."""

    period_usd: bool = True
    billable_calls: bool = True
    mission_spend: bool = True
    tokens: bool = True
    wall_time: bool = True
    attempts: bool = True
    concurrency: bool = True
    work_scope: bool = True

    def __post_init__(self) -> None:
        for axis in LIMIT_AXES:
            if type(getattr(self, axis)) is not bool:
                raise LimitPolicyError(f"limit axis {axis!r} must be a boolean")

    @classmethod
    def uniform(cls, enforced: bool) -> "LimitAxes":
        if type(enforced) is not bool:
            raise LimitPolicyError("uniform enforcement value must be a boolean")
        return cls(**{axis: enforced for axis in LIMIT_AXES})

    @classmethod
    def from_dict(cls, value: object) -> "LimitAxes":
        data = _require_exact_dict(
            value,
            expected_keys=LIMIT_AXES,
            name="execution limit axes",
        )
        for axis in LIMIT_AXES:
            if type(data[axis]) is not bool:
                raise LimitPolicyError(f"limit axis {axis!r} must be a boolean")
        return cls(**{axis: data[axis] for axis in LIMIT_AXES})

    def as_dict(self) -> dict[str, bool]:
        """Return a new dict in canonical axis order."""

        return {axis: getattr(self, axis) for axis in LIMIT_AXES}


@dataclass(frozen=True, slots=True)
class ExecutionLimitPolicy:
    """Stored execution-limit mode plus retained per-axis configuration."""

    mode: LimitMode = MODE_BOUNDED
    configured: LimitAxes = field(default_factory=LimitAxes)

    def __post_init__(self) -> None:
        if type(self.mode) is not str or self.mode not in LIMIT_MODES:
            allowed = ", ".join(LIMIT_MODES)
            raise LimitPolicyError(
                f"execution limit mode must be one of: {allowed}"
            )
        if not isinstance(self.configured, LimitAxes):
            raise LimitPolicyError("configured execution limit axes must be LimitAxes")

    @property
    def effective(self) -> LimitAxes:
        """Enforcement flags after applying the selected policy mode."""

        if self.mode == MODE_BOUNDED:
            return LimitAxes.uniform(True)
        if self.mode == MODE_UNBOUNDED_EXECUTION:
            return LimitAxes.uniform(False)
        return self.configured

    def enforces(self, axis: str) -> bool:
        """Return whether one canonical resource axis is currently enforced."""

        if type(axis) is not str or axis not in LIMIT_AXES:
            raise LimitPolicyError(f"unknown execution limit axis: {axis!r}")
        return getattr(self.effective, axis)

    @classmethod
    def from_dict(cls, value: object) -> "ExecutionLimitPolicy":
        data = _require_exact_dict(
            value,
            expected_keys=("mode", "configured"),
            name="execution limit policy",
        )
        mode = data["mode"]
        if type(mode) is not str or mode not in LIMIT_MODES:
            allowed = ", ".join(LIMIT_MODES)
            raise LimitPolicyError(
                f"execution limit mode must be one of: {allowed}"
            )
        return cls(mode=mode, configured=LimitAxes.from_dict(data["configured"]))

    def as_dict(self) -> dict[str, Any]:
        """Return the deterministic persisted representation.

        Effective flags and the fingerprint are derived data and intentionally
        do not appear here.  This keeps ``from_dict(as_dict())`` exact and keeps
        one canonical byte representation for environment propagation.
        """

        return {
            "mode": self.mode,
            "configured": self.configured.as_dict(),
        }

    def to_env_value(self) -> str:
        """Encode the policy as compact, deterministic JSON."""

        return json.dumps(
            self.as_dict(),
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    @property
    def fingerprint_sha256(self) -> str:
        """Stable SHA-256 of the canonical stored representation."""

        return hashlib.sha256(self.to_env_value().encode("utf-8")).hexdigest()

    @classmethod
    def from_env_value(cls, value: str) -> "ExecutionLimitPolicy":
        """Decode one strict JSON environment value.

        Duplicate object keys and JavaScript-style non-finite constants are
        rejected rather than silently normalized.
        """

        if type(value) is not str:
            raise LimitPolicyError("execution limit policy environment value must be text")
        if not value.strip():
            return cls()

        def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, item in pairs:
                if key in result:
                    raise LimitPolicyError(
                        f"execution limit policy contains duplicate key {key!r}"
                    )
                result[key] = item
            return result

        def reject_non_finite(value_name: str) -> None:
            raise LimitPolicyError(
                f"execution limit policy contains invalid constant {value_name!r}"
            )

        try:
            decoded = json.loads(
                value,
                object_pairs_hook=reject_duplicate_keys,
                parse_constant=reject_non_finite,
            )
        except LimitPolicyError:
            raise
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise LimitPolicyError(
                f"execution limit policy environment value is invalid JSON: {exc}"
            ) from exc
        return cls.from_dict(decoded)


def load_from_env(
    environ: Mapping[str, str] | None = None,
) -> ExecutionLimitPolicy:
    """Load the canonical policy; a missing or empty value is bounded."""

    source = os.environ if environ is None else environ
    if not isinstance(source, Mapping):
        raise LimitPolicyError("environment must be a mapping")
    raw = source.get(ENV_EXECUTION_LIMIT_POLICY)
    if raw is None or raw == "":
        return ExecutionLimitPolicy()
    return ExecutionLimitPolicy.from_env_value(raw)


def store_in_env(
    policy: ExecutionLimitPolicy,
    environ: MutableMapping[str, str] | None = None,
) -> str:
    """Store the policy in the one canonical environment variable."""

    if not isinstance(policy, ExecutionLimitPolicy):
        raise LimitPolicyError("policy must be ExecutionLimitPolicy")
    target = os.environ if environ is None else environ
    if not isinstance(target, MutableMapping):
        raise LimitPolicyError("environment must be a mutable mapping")
    encoded = policy.to_env_value()
    target[ENV_EXECUTION_LIMIT_POLICY] = encoded
    return encoded


__all__ = [
    "ENV_EXECUTION_LIMIT_POLICY",
    "ExecutionLimitPolicy",
    "LIMIT_AXES",
    "LIMIT_MODES",
    "LimitAxes",
    "LimitMode",
    "LimitPolicyError",
    "MODE_BOUNDED",
    "MODE_CUSTOM",
    "MODE_UNBOUNDED_EXECUTION",
    "load_from_env",
    "store_in_env",
]
