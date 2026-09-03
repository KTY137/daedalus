"""Compose the authenticated provider ABI with executable evidence pre-effect.

G1-IKARUS-07D3 deliberately adds no second receipt schema or execution layer.
The boundary re-authenticates the signed per-call invocation ABI, reuses the
existing 07C executable binding to re-prove loaded repository objects, and then
requires both proofs to name one exact runtime/effect/provider subject.

It grants no lease, starts no Effect, persists no start, resolves no callable,
and invokes no provider code.  The existing
``ProviderRuntimeExecutableBindingReceipt`` remains the executable evidence; the
signed ABI remains the payload/target evidence.  A later broker cutover must
consume both immediately before durable start.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from daedalus.kernel.effects import EffectExecutionRequest
from daedalus.kernel.runtime_effects import RuntimeBoundEffectAuthorization
from daedalus.runtimes.provider.executable_object_registry import (
    ProviderExecutableObjectRegistry,
)
from daedalus.runtimes.provider.executable_pre_admission import (
    ProviderExecutablePreAdmissionReceipt,
)
from daedalus.runtimes.provider.invocation_abi import (
    ProviderInvocationABIContract,
    ProviderInvocationABIError,
)
from daedalus.runtimes.provider.invocation_authority import (
    ProviderInvocationObservationAuthority,
)
from daedalus.runtimes.provider.invocation_payload import ProviderInvocationPayload
from daedalus.runtimes.provider.observation import ProviderObservationBindingLedger
from daedalus.runtimes.provider.runtime_executable_binding import (
    ProviderRuntimeExecutableBindingError,
    ProviderRuntimeExecutableBindingReceipt,
    bind_provider_runtime_executable,
)


class ProviderRuntimeInvocationBindingError(RuntimeError):
    """Base class for pre-effect invocation/executable composition failures."""


class ProviderRuntimeInvocationBindingShapeError(ProviderRuntimeInvocationBindingError):
    """A supplied trust-root value does not have the exact required shape."""


class ProviderRuntimeInvocationBindingMismatch(ProviderRuntimeInvocationBindingError):
    """Authenticated ABI, executable, runtime, or effect subjects differ."""


def _require_same(label: str, comparisons: Mapping[str, tuple[Any, Any]]) -> None:
    mismatches = tuple(
        sorted(
            name
            for name, (actual, expected) in comparisons.items()
            if actual != expected
        )
    )
    if mismatches:
        raise ProviderRuntimeInvocationBindingMismatch(
            f"{label} mismatch: " + ", ".join(mismatches)
        )


def bind_provider_runtime_invocation(
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
    at: datetime,
) -> ProviderRuntimeExecutableBindingReceipt:
    """Verify ABI + executable conjunction without granting or starting an Effect."""

    if type(invocation_authority) is not ProviderInvocationObservationAuthority:
        raise ProviderRuntimeInvocationBindingShapeError(
            "invocation_authority must be exact ProviderInvocationObservationAuthority"
        )
    if type(invocation_payload) is not ProviderInvocationPayload:
        raise ProviderRuntimeInvocationBindingShapeError(
            "invocation_payload must be exact ProviderInvocationPayload"
        )
    if type(invocation_abi) is not ProviderInvocationABIContract:
        raise ProviderRuntimeInvocationBindingShapeError(
            "invocation_abi must be exact ProviderInvocationABIContract"
        )
    if type(observation_binding_ledger) is not ProviderObservationBindingLedger:
        raise ProviderRuntimeInvocationBindingShapeError(
            "observation_binding_ledger must be exact ProviderObservationBindingLedger"
        )
    if type(at) is not datetime or at.tzinfo is None or at.utcoffset() is None:
        raise ProviderRuntimeInvocationBindingShapeError(
            "at must be an exact timezone-aware datetime"
        )

    try:
        ProviderObservationBindingLedger.verify_invocation_abi_contract(
            observation_binding_ledger,
            invocation_abi,
            invocation_authority,
            invocation_payload,
            pre_admission,
            execution=execution,
            at=at,
        )
    except ProviderInvocationABIError as exc:
        raise ProviderRuntimeInvocationBindingMismatch(
            "provider invocation ABI did not authenticate pre-effect"
        ) from exc

    try:
        executable = bind_provider_runtime_executable(
            entrypoint_id,
            authorization=authorization,
            execution=execution,
            observation_authority=invocation_authority.observation_authority,
            observation_binding_ledger=observation_binding_ledger,
            executable_registry=executable_registry,
            pre_admission=pre_admission,
            at=at,
        )
    except ProviderRuntimeExecutableBindingError as exc:
        raise ProviderRuntimeInvocationBindingMismatch(
            "provider executable subject did not authenticate pre-effect"
        ) from exc
    if type(executable) is not ProviderRuntimeExecutableBindingReceipt:
        raise ProviderRuntimeInvocationBindingShapeError(
            "executable binding returned a non-exact receipt"
        )

    subject = invocation_authority.invocation_subject
    _require_same(
        "authenticated invocation/executable subject",
        {
            "provider_id": (executable.provider_id, invocation_abi.provider_id),
            "adapter_id": (executable.adapter_id, invocation_abi.adapter_id),
            "implementation_id": (
                executable.implementation_id,
                invocation_abi.implementation_id,
            ),
            "entrypoint_id": (executable.entrypoint_id, invocation_abi.entrypoint_id),
            "runtime_id": (executable.runtime_id, invocation_abi.runtime_id),
            "execution_id": (executable.execution_id, invocation_abi.execution_id),
            "idempotency_key": (
                executable.idempotency_key,
                invocation_abi.idempotency_key,
            ),
            "execution_request_sha256": (
                executable.execution_request_sha256,
                invocation_abi.execution_request_sha256,
            ),
            "lease_sha256": (executable.lease_sha256, invocation_abi.lease_sha256),
            "source_revision": (
                executable.source_revision,
                invocation_abi.source_revision,
            ),
            "pre_admission_sha256": (
                executable.pre_admission_sha256,
                invocation_abi.pre_admission_sha256,
            ),
            "invocation_authority_sha256": (
                executable.invocation_authority_sha256,
                invocation_authority.digest,
            ),
            "invocation_contract_sha256": (
                executable.invocation_contract_sha256,
                invocation_authority.invocation_contract_sha256,
            ),
            "invocation_subject_sha256": (
                executable.invocation_subject_sha256,
                subject.digest,
            ),
            "invoke_target": (executable.invoke_target, invocation_abi.invoke_target),
            "invoke_source_sha256": (
                executable.invoke_source_sha256,
                invocation_abi.invoke_source_sha256,
            ),
            "output_evidence_target": (
                executable.output_digests_target,
                invocation_abi.output_evidence_target,
            ),
            "output_evidence_source_sha256": (
                executable.output_digests_source_sha256,
                invocation_abi.output_evidence_source_sha256,
            ),
            "dependency_manifest_sha256": (
                executable.dependency_manifest_sha256,
                invocation_abi.dependency_manifest_sha256,
            ),
            "payload_digest": (
                invocation_payload.digest,
                invocation_abi.invocation_payload_sha256,
            ),
            "payload_schema": (
                invocation_payload.payload_schema_id,
                invocation_abi.payload_schema_id,
            ),
        },
    )
    return executable


__all__ = [
    "ProviderRuntimeInvocationBindingError",
    "ProviderRuntimeInvocationBindingMismatch",
    "ProviderRuntimeInvocationBindingShapeError",
    "bind_provider_runtime_invocation",
]
