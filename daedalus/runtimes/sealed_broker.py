"""Sealed provider execution staged beside the legacy callback broker.

This module is the bounded D4 migration seam.  It reuses the canonical broker's
Effect lifecycle and terminal-fence helpers, but caller-selected ``invoke`` and
``output_digests`` callables never cross this API.  A fresh execution must bind
one authenticated invocation ABI to one pre-admitted executable-object registry
before grant/start, then the registry executes its detached sealed operation only
after the exact durable STARTED receipt exists.

The existing :mod:`daedalus.runtimes.broker` callback entrypoint remains live in
this packet so current providers are not broken mid-migration.  The next cutover
must move production providers to :func:`run_sealed_runtime_provider` and then
remove the callback signature rather than retaining two production authorities.
"""
from __future__ import annotations

from typing import TypeVar

from daedalus.kernel.effects import EffectExecutionRequest
from daedalus.kernel.runtime_effects import RuntimeBoundEffectAuthorization
from daedalus.runtimes import broker as lifecycle
from daedalus.runtimes.provider_executable_object_registry import (
    ProviderExecutableObjectRegistry,
    ProviderExecutableObjectRegistryError,
    ProviderSealedOutputEvidenceError,
)
from daedalus.runtimes.provider_executable_pre_admission import (
    ProviderExecutablePreAdmissionReceipt,
)
from daedalus.runtimes.provider_invocation_abi import ProviderInvocationABIContract
from daedalus.runtimes.provider_invocation_authority import (
    ProviderInvocationObservationAuthority,
)
from daedalus.runtimes.provider_invocation_payload import ProviderInvocationPayload
from daedalus.runtimes.provider_observation import ProviderObservationBindingLedger
from daedalus.runtimes.provider_runtime_invocation_binding import (
    ProviderRuntimeInvocationBindingError,
    bind_provider_runtime_invocation,
)


T = TypeVar("T")


def run_sealed_runtime_provider(
    entrypoint_id: str,
    *,
    authorization: RuntimeBoundEffectAuthorization,
    execution: EffectExecutionRequest,
    invocation_authority: ProviderInvocationObservationAuthority,
    invocation_payload: ProviderInvocationPayload,
    invocation_abi: ProviderInvocationABIContract,
    observation_binding_ledger: ProviderObservationBindingLedger,
    executable_registry: ProviderExecutableObjectRegistry,
    pre_admission: ProviderExecutablePreAdmissionReceipt,
) -> lifecycle.RuntimeInvocationResult[T]:
    """Execute one authenticated fixed provider operation through the kernel.

    Sequential exact replay remains ahead of executable re-verification.  A
    fresh execution, however, must prove the sealed dependency snapshot and the
    signed ABI/executable conjunction before ``authorization.grant()`` or
    ``begin_effect()`` can run.
    """

    try:
        ProviderExecutableObjectRegistry._verify_verifier_environment()
    except ProviderExecutableObjectRegistryError as exc:
        raise lifecycle.RuntimeProviderBindingMismatch(
            "sealed provider verifier environment changed before effect start"
        ) from exc
    if type(execution) is not EffectExecutionRequest:
        raise lifecycle.RuntimeProviderBindingMismatch(
            "execution must be an exact EffectExecutionRequest"
        )
    if type(authorization) is not RuntimeBoundEffectAuthorization:
        raise lifecycle.RuntimeProviderBindingMismatch(
            "authorization must be an exact RuntimeBoundEffectAuthorization"
        )
    exact_types = (
        (
            invocation_authority,
            ProviderInvocationObservationAuthority,
            "invocation_authority",
        ),
        (invocation_payload, ProviderInvocationPayload, "invocation_payload"),
        (invocation_abi, ProviderInvocationABIContract, "invocation_abi"),
        (
            observation_binding_ledger,
            ProviderObservationBindingLedger,
            "observation_binding_ledger",
        ),
        (executable_registry, ProviderExecutableObjectRegistry, "executable_registry"),
        (pre_admission, ProviderExecutablePreAdmissionReceipt, "pre_admission"),
    )
    for value, expected, label in exact_types:
        if type(value) is not expected:
            raise lifecycle.RuntimeProviderBindingMismatch(
                f"{label} must be exact {expected.__name__}"
            )

    # A replay is identified without touching the sealed executable namespace.
    # Fresh work verifies dependencies first so substituted interpreter/module
    # primitives cannot redirect the subject checks which follow.
    prior_state = authorization.effect_ledger.execution_state(execution.execution_id)
    if prior_state is None:
        try:
            ProviderExecutableObjectRegistry._verify_sealed_operation(
                executable_registry,
                pre_admission,
                invocation_payload,
            )
        except ProviderExecutableObjectRegistryError as exc:
            raise lifecycle.RuntimeProviderBindingMismatch(
                "sealed provider invocation did not authenticate before effect start"
            ) from exc

    spec = lifecycle._validate_binding(entrypoint_id, authorization)
    subject = invocation_authority.invocation_subject
    mismatches = sorted(
        name
        for name, (actual, expected) in {
            "entrypoint_id": (subject.entrypoint_id, spec.id),
            "runtime_id": (subject.runtime_id, spec.runtime_id),
            "execution_id": (subject.execution_id, execution.execution_id),
            "idempotency_key": (subject.idempotency_key, execution.idempotency_key),
            "execution_request_sha256": (
                subject.execution_request_sha256,
                execution.digest,
            ),
            "lease_sha256": (
                subject.lease_sha256,
                authorization.capability.lease.digest,
            ),
            "source_revision": (
                subject.source_revision,
                authorization.capability.source_revision,
            ),
        }.items()
        if actual != expected
    )
    if mismatches:
        raise lifecycle.RuntimeProviderBindingMismatch(
            "provider invocation subject mismatch: " + ", ".join(mismatches)
        )

    if prior_state is None:
        instant = lifecycle._utc_now()
        try:
            bind_provider_runtime_invocation(
                entrypoint_id,
                authorization=authorization,
                execution=execution,
                invocation_authority=invocation_authority,
                invocation_payload=invocation_payload,
                invocation_abi=invocation_abi,
                observation_binding_ledger=observation_binding_ledger,
                executable_registry=executable_registry,
                pre_admission=pre_admission,
                at=instant,
            )
        except (
            ProviderRuntimeInvocationBindingError,
            ProviderExecutableObjectRegistryError,
        ) as exc:
            raise lifecycle.RuntimeProviderBindingMismatch(
                "sealed provider invocation did not authenticate before effect start"
            ) from exc

    authorization.grant()
    start = authorization.begin_effect(execution)
    lifecycle._prepare_observation_authority_after_start(
        spec=spec,
        authorization=authorization,
        execution=execution,
        start_receipt=start.receipt,
        authority=invocation_authority.observation_authority,
        ledger=observation_binding_ledger,
        replay=not start.execute,
        at=lifecycle._utc_now(),
    )
    if not start.execute:
        return lifecycle.RuntimeInvocationResult(
            entrypoint_id=spec.id,
            runtime_id=spec.runtime_id,
            executed=False,
            start_receipt=start.receipt,
            terminal_receipt=None,
            value=None,
        )

    try:
        value, raw_digests = ProviderExecutableObjectRegistry._execute_sealed_operation(
            executable_registry,
            pre_admission,
            invocation_payload,
            authorization=authorization,
            execution=execution,
            start_receipt=start.receipt,
        )
    except ProviderSealedOutputEvidenceError as exc:
        raise lifecycle.RuntimeProviderReconciliationRequired(
            entrypoint_id=spec.id,
            runtime_id=spec.runtime_id,
            start_receipt=start.receipt,
            phase="output-evidence",
            cause_sha256=lifecycle._exception_detail("output-evidence", exc),
        ) from exc
    except BaseException as exc:
        outcome = "cancelled" if isinstance(exc, lifecycle._CANCEL_EXCEPTIONS) else "failed"
        lifecycle._finish_or_raise_state(
            authorization,
            start.receipt,
            outcome=outcome,
            detail_sha256=lifecycle._exception_detail("provider-invoke", exc),
        )
        raise

    try:
        authorization.verify()
    except BaseException as exc:
        lifecycle._cancel_for_trust_loss(
            authorization,
            start.receipt,
            phase="post-invoke-runtime-verification",
            error=exc,
        )
        raise

    try:
        digests = lifecycle._normalize_output_digests(raw_digests)
    except BaseException as exc:
        raise lifecycle.RuntimeProviderReconciliationRequired(
            entrypoint_id=spec.id,
            runtime_id=spec.runtime_id,
            start_receipt=start.receipt,
            phase="output-evidence",
            cause_sha256=lifecycle._exception_detail("output-evidence", exc),
        ) from exc

    try:
        authorization.verify()
    except BaseException as exc:
        lifecycle._cancel_for_trust_loss(
            authorization,
            start.receipt,
            phase="pre-terminal-runtime-verification",
            error=exc,
        )
        raise

    try:
        terminal = lifecycle._finish_completed_under_runtime_fence(
            authorization,
            start.receipt,
            output_digests=digests,
        )
    except lifecycle.RuntimeProviderTrustFenceError as exc:
        lifecycle._cancel_for_trust_loss(
            authorization,
            start.receipt,
            phase="terminal-runtime-fence",
            error=exc,
        )
        raise

    return lifecycle.RuntimeInvocationResult(
        entrypoint_id=spec.id,
        runtime_id=spec.runtime_id,
        executed=True,
        start_receipt=start.receipt,
        terminal_receipt=terminal,
        value=value,
    )


__all__ = ["run_sealed_runtime_provider"]
