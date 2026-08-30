# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Compose provider/executable evidence before a runtime effect can start.

This boundary is deliberately non-executing.  It authenticates the exact
provider-observation authority, revalidates the exact registered executable
objects, and proves that both describe the same runtime/effect subject.  It
never grants an Effect Lease, starts an Effect, persists a provider start, or
calls provider code.

A broker cutover may consume this receipt as a prerequisite and then obtain the
already-admitted executable object through one canonical execution path.  This
module is not that execution path and does not make the object registry a
second provider authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from daedalus.kernel.effects import EffectExecutionRequest
from daedalus.kernel.runtime_effects import RuntimeBoundEffectAuthorization
from daedalus.runtimes.provider_executable_object_registry import (
    ProviderExecutableObjectAdmissionReceipt,
    ProviderExecutableObjectRegistry,
    ProviderExecutableObjectRegistryError,
)
from daedalus.runtimes.provider_executable_pre_admission import (
    ProviderExecutablePreAdmissionReceipt,
)
from daedalus.runtimes.provider_observation import (
    ProviderObservationAuthority,
    ProviderObservationAuthorityError,
    ProviderObservationBindingLedger,
)
from daedalus.schemas import _identifier, _revision, _sha256
from daedalus.spine.envelope import canonical_sha


_SCHEMA = "daedalus-provider-runtime-executable-binding/1"
_TRUE_CLAIMS = (
    "observation_authority_authenticated_before_effect",
    "registered_executable_objects_reverified",
    "provider_identity_bound",
    "runtime_effect_subject_bound",
    "invocation_contract_bound",
    "pre_effect_subject_verified",
)
_FALSE_CLAIMS = (
    "effect_lease_granted",
    "effect_started",
    "provider_start_persisted",
    "provider_code_executed",
    "provider_execution_allowed",
    "callback_seam_removed",
    "broker_invocation_performed",
    "automatic_reexecution_allowed",
    "owner_approval_issued",
    "promotion_authorized",
    "gate_transition_authorized",
    "closed",
)


class ProviderRuntimeExecutableBindingError(RuntimeError):
    """Base class for pre-effect provider/executable binding failures."""


class ProviderRuntimeExecutableBindingShapeError(ProviderRuntimeExecutableBindingError):
    """A supplied authority/evidence object has a non-exact or malformed shape."""


class ProviderRuntimeExecutableBindingMismatch(ProviderRuntimeExecutableBindingError):
    """Authenticated provider, executable, runtime, or effect subjects differ."""


def _canonical_pre_admission(
    value: ProviderExecutablePreAdmissionReceipt,
) -> ProviderExecutablePreAdmissionReceipt:
    if type(value) is not ProviderExecutablePreAdmissionReceipt:
        raise ProviderRuntimeExecutableBindingShapeError(
            "pre_admission must be exact ProviderExecutablePreAdmissionReceipt"
        )
    try:
        rebuilt = ProviderExecutablePreAdmissionReceipt.from_dict(value.to_dict())
    except Exception as exc:
        raise ProviderRuntimeExecutableBindingMismatch(
            "pre_admission is not canonical"
        ) from exc
    if rebuilt != value:
        raise ProviderRuntimeExecutableBindingMismatch(
            "pre_admission changed during canonical reconstruction"
        )
    return rebuilt


def _require_exact_boundary_types(
    authorization: RuntimeBoundEffectAuthorization,
    execution: EffectExecutionRequest,
    observation_authority: ProviderObservationAuthority,
    observation_binding_ledger: ProviderObservationBindingLedger,
    executable_registry: ProviderExecutableObjectRegistry,
) -> None:
    expected = (
        (authorization, RuntimeBoundEffectAuthorization, "authorization"),
        (execution, EffectExecutionRequest, "execution"),
        (
            observation_authority,
            ProviderObservationAuthority,
            "observation_authority",
        ),
        (
            observation_binding_ledger,
            ProviderObservationBindingLedger,
            "observation_binding_ledger",
        ),
        (
            executable_registry,
            ProviderExecutableObjectRegistry,
            "executable_registry",
        ),
    )
    for value, exact_type, label in expected:
        if type(value) is not exact_type:
            raise ProviderRuntimeExecutableBindingShapeError(
                f"{label} must be exact {exact_type.__name__}"
            )


def _mismatches(comparisons: Mapping[str, tuple[Any, Any]]) -> tuple[str, ...]:
    return tuple(
        sorted(
            name
            for name, (actual, expected) in comparisons.items()
            if actual != expected
        )
    )


def _require_same(label: str, comparisons: Mapping[str, tuple[Any, Any]]) -> None:
    mismatches = _mismatches(comparisons)
    if mismatches:
        raise ProviderRuntimeExecutableBindingMismatch(
            f"{label} mismatch: " + ", ".join(mismatches)
        )


@dataclass(frozen=True)
class ProviderRuntimeExecutableBindingReceipt:
    """Non-executing proof that one provider executable matches one effect subject."""

    pre_admission_sha256: str
    executable_admission_sha256: str
    observation_authority_sha256: str
    provider_id: str
    adapter_id: str
    implementation_id: str
    entrypoint_id: str
    runtime_id: str
    execution_id: str
    idempotency_key: str
    execution_request_sha256: str
    lease_sha256: str
    source_revision: str
    invocation_authority_sha256: str
    invocation_contract_sha256: str
    invocation_subject_sha256: str
    invoke_target: str
    invoke_source_sha256: str
    invoke_code_sha256: str
    output_digests_target: str
    output_digests_source_sha256: str
    output_digests_code_sha256: str

    def __post_init__(self) -> None:
        try:
            for field in (
                "provider_id",
                "adapter_id",
                "implementation_id",
                "entrypoint_id",
                "runtime_id",
                "execution_id",
                "idempotency_key",
            ):
                object.__setattr__(
                    self,
                    field,
                    _identifier(getattr(self, field), field),
                )
            for field in (
                "pre_admission_sha256",
                "executable_admission_sha256",
                "observation_authority_sha256",
                "execution_request_sha256",
                "lease_sha256",
                "invocation_authority_sha256",
                "invocation_contract_sha256",
                "invocation_subject_sha256",
                "invoke_source_sha256",
                "invoke_code_sha256",
                "output_digests_source_sha256",
                "output_digests_code_sha256",
            ):
                object.__setattr__(
                    self,
                    field,
                    _sha256(getattr(self, field), field),
                )
            object.__setattr__(
                self,
                "source_revision",
                _revision(self.source_revision, "source_revision"),
            )
            for field in ("invoke_target", "output_digests_target"):
                value = getattr(self, field)
                if type(value) is not str or not value or len(value) > 4096:
                    raise ValueError(f"{field} must be a bounded target string")
                if "\x00" in value or "\r" in value or "\n" in value:
                    raise ValueError(f"{field} contains a forbidden character")
        except (AttributeError, TypeError, ValueError) as exc:
            raise ProviderRuntimeExecutableBindingShapeError(
                "provider runtime executable binding receipt is malformed"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": _SCHEMA,
            "pre_admission_sha256": self.pre_admission_sha256,
            "executable_admission_sha256": self.executable_admission_sha256,
            "observation_authority_sha256": self.observation_authority_sha256,
            "provider_id": self.provider_id,
            "adapter_id": self.adapter_id,
            "implementation_id": self.implementation_id,
            "entrypoint_id": self.entrypoint_id,
            "runtime_id": self.runtime_id,
            "execution_id": self.execution_id,
            "idempotency_key": self.idempotency_key,
            "execution_request_sha256": self.execution_request_sha256,
            "lease_sha256": self.lease_sha256,
            "source_revision": self.source_revision,
            "invocation_authority_sha256": self.invocation_authority_sha256,
            "invocation_contract_sha256": self.invocation_contract_sha256,
            "invocation_subject_sha256": self.invocation_subject_sha256,
            "invoke_target": self.invoke_target,
            "invoke_source_sha256": self.invoke_source_sha256,
            "invoke_code_sha256": self.invoke_code_sha256,
            "output_digests_target": self.output_digests_target,
            "output_digests_source_sha256": self.output_digests_source_sha256,
            "output_digests_code_sha256": self.output_digests_code_sha256,
            **{field: True for field in _TRUE_CLAIMS},
            **{field: False for field in _FALSE_CLAIMS},
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "ProviderRuntimeExecutableBindingReceipt":
        fields = {
            "pre_admission_sha256",
            "executable_admission_sha256",
            "observation_authority_sha256",
            "provider_id",
            "adapter_id",
            "implementation_id",
            "entrypoint_id",
            "runtime_id",
            "execution_id",
            "idempotency_key",
            "execution_request_sha256",
            "lease_sha256",
            "source_revision",
            "invocation_authority_sha256",
            "invocation_contract_sha256",
            "invocation_subject_sha256",
            "invoke_target",
            "invoke_source_sha256",
            "invoke_code_sha256",
            "output_digests_target",
            "output_digests_source_sha256",
            "output_digests_code_sha256",
        }
        if not isinstance(payload, Mapping) or set(payload) != {
            "schema",
            *fields,
            *_TRUE_CLAIMS,
            *_FALSE_CLAIMS,
        }:
            raise ProviderRuntimeExecutableBindingShapeError(
                "provider runtime executable binding fields are not exact"
            )
        if payload["schema"] != _SCHEMA:
            raise ProviderRuntimeExecutableBindingShapeError(
                "provider runtime executable binding schema is wrong"
            )
        for field in _TRUE_CLAIMS:
            if payload[field] is not True:
                raise ProviderRuntimeExecutableBindingShapeError(
                    f"provider runtime executable binding lost claim: {field}"
                )
        for field in _FALSE_CLAIMS:
            if payload[field] is not False:
                raise ProviderRuntimeExecutableBindingShapeError(
                    f"provider runtime executable binding escalated claim: {field}"
                )
        try:
            return cls(**{field: payload[field] for field in fields})
        except ProviderRuntimeExecutableBindingError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProviderRuntimeExecutableBindingShapeError(
                "provider runtime executable binding receipt is malformed"
            ) from exc

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def bind_provider_runtime_executable(
    entrypoint_id: str,
    *,
    authorization: RuntimeBoundEffectAuthorization,
    execution: EffectExecutionRequest,
    observation_authority: ProviderObservationAuthority,
    observation_binding_ledger: ProviderObservationBindingLedger,
    executable_registry: ProviderExecutableObjectRegistry,
    pre_admission: ProviderExecutablePreAdmissionReceipt,
    at: datetime,
) -> ProviderRuntimeExecutableBindingReceipt:
    """Authenticate and compose one exact provider/executable subject pre-effect."""

    _require_exact_boundary_types(
        authorization,
        execution,
        observation_authority,
        observation_binding_ledger,
        executable_registry,
    )
    subject = _canonical_pre_admission(pre_admission)
    try:
        requested_entrypoint = _identifier(entrypoint_id, "entrypoint_id")
        capability = authorization.capability
        request = authorization.request
        lease = capability.lease
        runtime_id = _identifier(capability.runtime_id, "runtime_id")
        source_revision = _revision(capability.source_revision, "source_revision")
        lease_sha256 = _sha256(lease.digest, "lease_sha256")
    except (AttributeError, TypeError, ValueError) as exc:
        raise ProviderRuntimeExecutableBindingShapeError(
            "runtime authorization subject is malformed"
        ) from exc

    _require_same(
        "runtime/effect authorization",
        {
            "request.entrypoint_id": (request.entrypoint_id, requested_entrypoint),
            "lease.entrypoint_id": (lease.entrypoint_id, requested_entrypoint),
            "pre_admission.entrypoint_id": (
                subject.entrypoint_id,
                requested_entrypoint,
            ),
            "pre_admission.runtime_id": (subject.runtime_id, runtime_id),
            "pre_admission.execution_id": (
                subject.execution_id,
                execution.execution_id,
            ),
            "pre_admission.idempotency_key": (
                subject.idempotency_key,
                execution.idempotency_key,
            ),
            "pre_admission.lease_sha256": (subject.lease_sha256, lease_sha256),
            "pre_admission.source_revision": (
                subject.source_revision,
                source_revision,
            ),
        },
    )

    try:
        observation_binding_ledger.verify_authority(
            observation_authority,
            entrypoint_id=requested_entrypoint,
            runtime_id=runtime_id,
            execution=execution,
            lease_sha256=lease_sha256,
            source_revision=source_revision,
            at=at,
        )
    except (ProviderObservationAuthorityError, TypeError, ValueError) as exc:
        raise ProviderRuntimeExecutableBindingMismatch(
            "provider observation authority did not authenticate pre-effect"
        ) from exc

    _require_same(
        "provider observation subject",
        {
            "provider_id": (observation_authority.provider_id, subject.provider_id),
            "entrypoint_id": (
                observation_authority.entrypoint_id,
                requested_entrypoint,
            ),
            "runtime_id": (observation_authority.runtime_id, runtime_id),
            "execution_id": (
                observation_authority.execution_id,
                execution.execution_id,
            ),
            "idempotency_key": (
                observation_authority.idempotency_key,
                execution.idempotency_key,
            ),
            "execution_request_sha256": (
                observation_authority.execution_request_sha256,
                execution.digest,
            ),
            "lease_sha256": (observation_authority.lease_sha256, lease_sha256),
            "source_revision": (
                observation_authority.source_revision,
                source_revision,
            ),
        },
    )

    try:
        admission = executable_registry.verify_registered(subject)
    except ProviderExecutableObjectRegistryError as exc:
        raise ProviderRuntimeExecutableBindingMismatch(
            "registered provider executable did not reverify pre-effect"
        ) from exc
    if type(admission) is not ProviderExecutableObjectAdmissionReceipt:
        raise ProviderRuntimeExecutableBindingShapeError(
            "executable registry returned a non-exact admission receipt"
        )

    _require_same(
        "registered executable subject",
        {
            "pre_admission_sha256": (
                admission.pre_admission_sha256,
                subject.digest,
            ),
            "provider_id": (admission.provider_id, subject.provider_id),
            "adapter_id": (admission.adapter_id, subject.adapter_id),
            "implementation_id": (
                admission.implementation_id,
                subject.implementation_id,
            ),
            "entrypoint_id": (admission.entrypoint_id, requested_entrypoint),
            "runtime_id": (admission.runtime_id, runtime_id),
            "execution_id": (admission.execution_id, execution.execution_id),
            "idempotency_key": (
                admission.idempotency_key,
                execution.idempotency_key,
            ),
            "source_revision": (admission.source_revision, source_revision),
            "invoke_target": (admission.invoke_target, subject.invoke_target),
            "invoke_source_sha256": (
                admission.invoke_source_sha256,
                subject.invoke_source_sha256,
            ),
            "output_digests_target": (
                admission.output_digests_target,
                subject.output_digests_target,
            ),
            "output_digests_source_sha256": (
                admission.output_digests_source_sha256,
                subject.output_digests_source_sha256,
            ),
        },
    )

    return ProviderRuntimeExecutableBindingReceipt(
        pre_admission_sha256=subject.digest,
        executable_admission_sha256=admission.digest,
        observation_authority_sha256=observation_authority.digest,
        provider_id=subject.provider_id,
        adapter_id=subject.adapter_id,
        implementation_id=subject.implementation_id,
        entrypoint_id=requested_entrypoint,
        runtime_id=runtime_id,
        execution_id=execution.execution_id,
        idempotency_key=execution.idempotency_key,
        execution_request_sha256=execution.digest,
        lease_sha256=lease_sha256,
        source_revision=source_revision,
        invocation_authority_sha256=subject.invocation_authority_sha256,
        invocation_contract_sha256=subject.invocation_contract_sha256,
        invocation_subject_sha256=subject.invocation_subject_sha256,
        invoke_target=admission.invoke_target,
        invoke_source_sha256=admission.invoke_source_sha256,
        invoke_code_sha256=admission.invoke_code_sha256,
        output_digests_target=admission.output_digests_target,
        output_digests_source_sha256=admission.output_digests_source_sha256,
        output_digests_code_sha256=admission.output_digests_code_sha256,
    )


__all__ = [
    "ProviderRuntimeExecutableBindingError",
    "ProviderRuntimeExecutableBindingMismatch",
    "ProviderRuntimeExecutableBindingReceipt",
    "ProviderRuntimeExecutableBindingShapeError",
    "bind_provider_runtime_executable",
]
