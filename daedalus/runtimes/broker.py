"""Execute one runtime provider call behind persisted runtime and effect authority.

This module is deliberately provider-neutral.  It composes the existing
``RuntimeBoundEffectAuthorization`` with one exact ``EffectExecutionRequest``
and a zero-argument provider callable.  The broker persists the lease grant and
start receipt before invoking external code, makes exact replay inert, and
persists a terminal receipt for success, failure, cancellation, or a post-call
runtime-trust loss.

It does not make an existing provider safe merely by existing.  A production
provider row may move to ``CENTRAL`` only after its public call path requires
this broker and no direct effectful bypass remains.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Generic, Iterable, Mapping, Sequence, TypeVar

from daedalus.kernel.effects import (
    EffectExecutionRequest,
    EffectTerminalReceipt,
    LeasedEffectStartReceipt,
)
from daedalus.kernel.runtime_effects import RuntimeBoundEffectAuthorization
from daedalus.spine.effect_boundary import EntrypointSpec, Wiring
from daedalus.spine.envelope import canonical_sha


T = TypeVar("T")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CANCEL_EXCEPTIONS = (KeyboardInterrupt, SystemExit, GeneratorExit)


class RuntimeProviderBrokerError(RuntimeError):
    """Base class for provider-broker boundary failures."""


class RuntimeProviderBindingMismatch(RuntimeProviderBrokerError):
    """The supplied authority does not name the requested provider entrypoint."""


class RuntimeProviderStateError(RuntimeProviderBrokerError):
    """The external call ran but its terminal state could not be persisted."""


@dataclass(frozen=True)
class RuntimeInvocationResult(Generic[T]):
    """One durable provider invocation result or an inert exact replay."""

    entrypoint_id: str
    runtime_id: str
    executed: bool
    start_receipt: LeasedEffectStartReceipt
    terminal_receipt: EffectTerminalReceipt | None
    value: T | None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _registry_map(
    registry: Mapping[str, EntrypointSpec] | Sequence[EntrypointSpec],
) -> Mapping[str, EntrypointSpec]:
    if isinstance(registry, Mapping):
        rows = dict(registry)
        if any(key != row.id for key, row in rows.items()):
            raise RuntimeProviderBindingMismatch(
                "runtime authorization registry contains mismatched key/id rows"
            )
        return rows
    rows = tuple(registry)
    if len({row.id for row in rows}) != len(rows):
        raise RuntimeProviderBindingMismatch(
            "runtime authorization registry contains duplicate entrypoint ids"
        )
    return {row.id: row for row in rows}


def _validate_binding(
    entrypoint_id: str,
    authorization: RuntimeBoundEffectAuthorization,
) -> EntrypointSpec:
    if not isinstance(entrypoint_id, str) or not entrypoint_id.strip():
        raise RuntimeProviderBindingMismatch("entrypoint_id must be non-empty")
    expected = entrypoint_id.strip()
    comparisons = {
        "request entrypoint": authorization.request.entrypoint_id,
        "lease entrypoint": authorization.capability.lease.entrypoint_id,
    }
    mismatches = sorted(
        label for label, actual in comparisons.items() if actual != expected
    )
    if mismatches:
        raise RuntimeProviderBindingMismatch(
            "runtime provider authority targets a different entrypoint: "
            + ", ".join(mismatches)
        )
    spec = _registry_map(authorization.registry).get(expected)
    if spec is None:
        raise RuntimeProviderBindingMismatch(
            "runtime provider entrypoint is absent from the authorization registry"
        )
    if spec.wiring is not Wiring.CENTRAL:
        raise RuntimeProviderBindingMismatch(
            "runtime provider entrypoint is not centrally wired"
        )
    if not spec.runtime_id:
        raise RuntimeProviderBindingMismatch(
            "runtime provider entrypoint has no runtime identity"
        )
    if spec.runtime_id != authorization.capability.runtime_id:
        raise RuntimeProviderBindingMismatch(
            "runtime provider identity does not match the bound capability"
        )
    return spec


def _exception_detail(phase: str, exc: BaseException) -> str:
    """Return a non-secret deterministic exception-class digest."""

    return canonical_sha(
        {
            "phase": phase,
            "exception_module": type(exc).__module__,
            "exception_type": type(exc).__qualname__,
        }
    )


def _normalize_output_digests(values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError("output digests must be an iterable of SHA-256 strings")
    normalized: list[str] = []
    for index, value in enumerate(values):
        if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
            raise ValueError(f"output digest {index} must be lowercase SHA-256")
        normalized.append(value)
    if len(set(normalized)) != len(normalized):
        raise ValueError("output digests must not contain duplicates")
    return tuple(sorted(normalized))


def _finish_or_raise_state(
    authorization: RuntimeBoundEffectAuthorization,
    start_receipt: LeasedEffectStartReceipt,
    *,
    outcome: str,
    output_digests: Iterable[str] = (),
    detail_sha256: str | None = None,
) -> EffectTerminalReceipt:
    try:
        return authorization.finish_effect(
            start_receipt,
            outcome=outcome,
            output_digests=output_digests,
            detail_sha256=detail_sha256,
        )
    except BaseException as exc:
        raise RuntimeProviderStateError(
            "runtime provider terminal receipt could not be persisted"
        ) from exc


def run_runtime_provider(
    entrypoint_id: str,
    *,
    authorization: RuntimeBoundEffectAuthorization,
    execution: EffectExecutionRequest,
    invoke: Callable[[], T],
    output_digests: Callable[[T], Iterable[str]] | None = None,
) -> RuntimeInvocationResult[T]:
    """Run one exact provider effect after durable grant/start authorization.

    ``invoke`` receives no authority object and is called only after the exact
    lease grant and start receipt exist.  Reusing the same execution identity
    returns ``executed=False`` and never calls the provider a second time.
    """

    if not callable(invoke):
        raise TypeError("invoke must be callable")
    spec = _validate_binding(entrypoint_id, authorization)

    # Grant is exact-replay idempotent.  Keeping it inside the broker prevents a
    # provider adapter from accidentally starting against an unpersisted lease.
    authorization.grant()
    start = authorization.begin_effect(execution)
    if not start.execute:
        return RuntimeInvocationResult(
            entrypoint_id=spec.id,
            runtime_id=spec.runtime_id,
            executed=False,
            start_receipt=start.receipt,
            terminal_receipt=None,
            value=None,
        )

    try:
        value = invoke()
    except BaseException as exc:
        outcome = "cancelled" if isinstance(exc, _CANCEL_EXCEPTIONS) else "failed"
        _finish_or_raise_state(
            authorization,
            start.receipt,
            outcome=outcome,
            detail_sha256=_exception_detail("provider-invoke", exc),
        )
        raise

    # Runtime evidence may expire or be quarantined while a long provider call
    # is running.  The effect cannot be undone, but its output is withheld and
    # the durable execution is not represented as successfully completed.
    try:
        authorization.verify(now=_utc_now())
    except BaseException as exc:
        _finish_or_raise_state(
            authorization,
            start.receipt,
            outcome="cancelled",
            detail_sha256=_exception_detail("post-invoke-runtime-verification", exc),
        )
        raise

    try:
        digests = (
            ()
            if output_digests is None
            else _normalize_output_digests(output_digests(value))
        )
    except BaseException as exc:
        _finish_or_raise_state(
            authorization,
            start.receipt,
            outcome="failed",
            detail_sha256=_exception_detail("output-evidence", exc),
        )
        raise

    terminal = _finish_or_raise_state(
        authorization,
        start.receipt,
        outcome="completed",
        output_digests=digests,
    )
    return RuntimeInvocationResult(
        entrypoint_id=spec.id,
        runtime_id=spec.runtime_id,
        executed=True,
        start_receipt=start.receipt,
        terminal_receipt=terminal,
        value=value,
    )


__all__ = [
    "RuntimeInvocationResult",
    "RuntimeProviderBindingMismatch",
    "RuntimeProviderBrokerError",
    "RuntimeProviderStateError",
    "run_runtime_provider",
]
