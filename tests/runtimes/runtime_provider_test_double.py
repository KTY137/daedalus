"""Test-only callback fixture for legacy runtime lifecycle/fault coverage.

This module deliberately lives below ``tests/``.  Setuptools excludes that
tree, so an installed Daedalus package contains no callback-taking runtime
broker.  Production-provider tests use the sealed registry operation instead.
"""
from __future__ import annotations

from typing import Callable, Iterable, TypeVar

import daedalus.runtimes.broker as _production_broker
from daedalus.kernel.effects import EffectExecutionRequest
from daedalus.kernel.runtime_effects import RuntimeBoundEffectAuthorization
from daedalus.runtimes.broker import (
    RuntimeInvocationResult,
    RuntimeProviderBindingMismatch,
    RuntimeProviderReconciliationRequired,
    RuntimeProviderTrustFenceError,
    _CANCEL_EXCEPTIONS,
    _cancel_for_trust_loss,
    _exception_detail,
    _finish_completed_under_runtime_fence,
    _finish_or_raise_state,
    _normalize_output_digests,
    _prepare_observation_authority_after_start,
    _production_observation_binding,
    _validate_binding,
)
from daedalus.runtimes.provider.observation import (
    ProviderObservationAuthority,
    ProviderObservationBindingLedger,
)


T = TypeVar("T")


def run_runtime_provider_test_double(
    entrypoint_id: str,
    *,
    authorization: RuntimeBoundEffectAuthorization,
    execution: EffectExecutionRequest,
    invoke: Callable[[], T],
    output_digests: Callable[[T], Iterable[str]],
    observation_authority: ProviderObservationAuthority | None = None,
    observation_binding_ledger: ProviderObservationBindingLedger | None = None,
) -> RuntimeInvocationResult[T]:
    """Exercise historical lifecycle cases without shipping a callback seam."""

    if not callable(invoke):
        raise TypeError("invoke must be callable")
    if not callable(output_digests):
        raise TypeError("output_digests must be callable")
    if type(execution) is not EffectExecutionRequest:
        raise RuntimeProviderBindingMismatch(
            "execution must be an exact EffectExecutionRequest"
        )
    observation_binding = _production_observation_binding(
        authorization,
        observation_authority,
        observation_binding_ledger,
    )
    spec = _validate_binding(entrypoint_id, authorization)

    authorization.grant()
    start = authorization.begin_effect(execution)
    authority, binding_ledger = observation_binding
    _prepare_observation_authority_after_start(
        spec=spec,
        authorization=authorization,
        execution=execution,
        start_receipt=start.receipt,
        authority=authority,
        ledger=binding_ledger,
        replay=not start.execute,
        at=_production_broker._utc_now(),
    )
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

    try:
        authorization.verify()
    except BaseException as exc:
        _cancel_for_trust_loss(
            authorization,
            start.receipt,
            phase="post-invoke-runtime-verification",
            error=exc,
        )
        raise

    try:
        digests = _normalize_output_digests(output_digests(value))
    except BaseException as exc:
        raise RuntimeProviderReconciliationRequired(
            entrypoint_id=spec.id,
            runtime_id=spec.runtime_id,
            start_receipt=start.receipt,
            phase="output-evidence",
            cause_sha256=_exception_detail("output-evidence", exc),
        ) from exc

    try:
        authorization.verify()
    except BaseException as exc:
        _cancel_for_trust_loss(
            authorization,
            start.receipt,
            phase="pre-terminal-runtime-verification",
            error=exc,
        )
        raise

    try:
        terminal = _finish_completed_under_runtime_fence(
            authorization,
            start.receipt,
            output_digests=digests,
        )
    except RuntimeProviderTrustFenceError as exc:
        _cancel_for_trust_loss(
            authorization,
            start.receipt,
            phase="terminal-runtime-fence",
            error=exc,
        )
        raise

    return RuntimeInvocationResult(
        entrypoint_id=spec.id,
        runtime_id=spec.runtime_id,
        executed=True,
        start_receipt=start.receipt,
        terminal_receipt=terminal,
        value=value,
    )


__all__ = ["run_runtime_provider_test_double"]
