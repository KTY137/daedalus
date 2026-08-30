"""Compose one authenticated provider invocation subject before any Effect start.

G1-IKARUS-07D3 joins the signed per-call invocation ABI to the already hardened
provider executable-object evidence.  The boundary deliberately remains
non-executing: it re-authenticates the invocation payload/ABI, re-proves the
loaded executable targets through the existing registry boundary, and requires
both views to name the exact same runtime/effect/provider subject.

This module is a composition boundary, not a second provider registry or an
execution authority.  It grants no lease, starts no Effect, persists no start,
resolves no callable, and invokes no provider code.  A later broker cutover may
call this function immediately before its durable start; until that cutover,
``callback_seam_removed`` and ``provider_execution_allowed`` remain explicitly
false.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from daedalus.kernel.effects import EffectExecutionRequest
from daedalus.kernel.runtime_effects import RuntimeBoundEffectAuthorization
from daedalus.runtimes.provider_executable_object_registry import (
    ProviderExecutableObjectRegistry,
)
from daedalus.runtimes.provider_executable_pre_admission import (
    ProviderExecutablePreAdmissionReceipt,
)
from daedalus.runtimes.provider_invocation_abi import (
    ProviderInvocationABIContract,
    ProviderInvocationABIError,
    verify_provider_invocation_abi_contract,
)
from daedalus.runtimes.provider_invocation_authority import (
    ProviderInvocationObservationAuthority,
)
from daedalus.runtimes.provider_invocation_payload import ProviderInvocationPayload
from daedalus.runtimes.provider_observation import ProviderObservationBindingLedger
from daedalus.runtimes.provider_runtime_executable_binding import (
    ProviderRuntimeExecutableBindingError,
    ProviderRuntimeExecutableBindingReceipt,
    bind_provider_runtime_executable,
)
from daedalus.schemas import _identifier, _revision, _sha256
from daedalus.spine.envelope import canonical_sha


_SCHEMA = "daedalus-provider-runtime-invocation-binding/1"
_TRUE_CLAIMS = (
    "invocation_authority_authenticated_before_effect",
    "invocation_payload_authenticated_before_effect",
    "invocation_abi_authenticated_before_effect",
    "registered_executable_objects_reverified",
    "provider_identity_bound",
    "runtime_effect_subject_bound",
    "payload_schema_bound",
    "admitted_targets_bound",
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


class ProviderRuntimeInvocationBindingError(RuntimeError):
    """Base class for pre-effect invocation/executable composition failures."""


class ProviderRuntimeInvocationBindingShapeError(ProviderRuntimeInvocationBindingError):
    """A supplied subject/evidence value does not have the exact required type."""


class ProviderRuntimeInvocationBindingMismatch(ProviderRuntimeInvocationBindingError):
    """Authenticated ABI, executable, runtime, or effect subjects differ."""


def _require_exact_types(
    authorization: RuntimeBoundEffectAuthorization,
    execution: EffectExecutionRequest,
    invocation_authority: ProviderInvocationObservationAuthority,
    invocation_payload: ProviderInvocationPayload,
    invocation_abi: ProviderInvocationABIContract,
    observation_binding_ledger: ProviderObservationBindingLedger,
    executable_registry: ProviderExecutableObjectRegistry,
    pre_admission: ProviderExecutablePreAdmissionReceipt,
) -> None:
    expected = (
        (authorization, RuntimeBoundEffectAuthorization, "authorization"),
        (execution, EffectExecutionRequest, "execution"),
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
        (
            executable_registry,
            ProviderExecutableObjectRegistry,
            "executable_registry",
        ),
        (
            pre_admission,
            ProviderExecutablePreAdmissionReceipt,
            "pre_admission",
        ),
    )
    for value, exact_type, label in expected:
        if type(value) is not exact_type:
            raise ProviderRuntimeInvocationBindingShapeError(
                f"{label} must be exact {exact_type.__name__}"
            )


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


def _ledger_authority_keyring(
    ledger: ProviderObservationBindingLedger,
) -> Mapping[str, bytes]:
    """Use the existing ledger trust root without exporting a new authority API.

    The observation ledger is already the canonical holder of provider authority
    verification keys.  This same-package composition reads that private material
    only to call the existing verifier; it never returns or persists the secrets.
    Exact ledger typing above prevents an arbitrary object from supplying a fake
    keyring through this seam.
    """

    rows = getattr(ledger, "_authority_keyring", None)
    if type(rows) is not dict or not rows:
        raise ProviderRuntimeInvocationBindingShapeError(
            "observation binding ledger has no canonical authority keyring"
        )
    if any(type(key) is not str or type(value) is not bytes for key, value in rows.items()):
        raise ProviderRuntimeInvocationBindingShapeError(
            "observation binding ledger authority keyring is malformed"
        )
    return rows


@dataclass(frozen=True)
class ProviderRuntimeInvocationBindingReceipt:
    """Non-authorizing proof of one exact payload/ABI/executable conjunction."""

    executable_binding_sha256: str
    invocation_abi_sha256: str
    invocation_payload_sha256: str
    pre_admission_sha256: str
    invocation_authority_sha256: str
    observation_authority_sha256: str
    invocation_contract_sha256: str
    invocation_subject_sha256: str
    invocation_registry_sha256: str
    provider_id: str
    adapter_id: str
    implementation_id: str
    payload_schema_id: str
    entrypoint_id: str
    runtime_id: str
    execution_id: str
    idempotency_key: str
    execution_request_sha256: str
    lease_sha256: str
    source_revision: str
    invoke_target: str
    invoke_source_sha256: str
    invoke_code_sha256: str
    output_evidence_target: str
    output_evidence_source_sha256: str
    output_evidence_code_sha256: str

    def __post_init__(self) -> None:
        try:
            for field in (
                "provider_id",
                "adapter_id",
                "implementation_id",
                "payload_schema_id",
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
                "executable_binding_sha256",
                "invocation_abi_sha256",
                "invocation_payload_sha256",
                "pre_admission_sha256",
                "invocation_authority_sha256",
                "observation_authority_sha256",
                "invocation_contract_sha256",
                "invocation_subject_sha256",
                "invocation_registry_sha256",
                "execution_request_sha256",
                "lease_sha256",
                "invoke_source_sha256",
                "invoke_code_sha256",
                "output_evidence_source_sha256",
                "output_evidence_code_sha256",
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
            for field in ("invoke_target", "output_evidence_target"):
                value = getattr(self, field)
                if type(value) is not str or not value or len(value) > 4096:
                    raise ValueError(f"{field} must be a bounded exact target string")
                if "\x00" in value or "\r" in value or "\n" in value:
                    raise ValueError(f"{field} contains a forbidden character")
        except (AttributeError, TypeError, ValueError) as exc:
            raise ProviderRuntimeInvocationBindingShapeError(
                "provider runtime invocation binding receipt is malformed"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": _SCHEMA,
            "executable_binding_sha256": self.executable_binding_sha256,
            "invocation_abi_sha256": self.invocation_abi_sha256,
            "invocation_payload_sha256": self.invocation_payload_sha256,
            "pre_admission_sha256": self.pre_admission_sha256,
            "invocation_authority_sha256": self.invocation_authority_sha256,
            "observation_authority_sha256": self.observation_authority_sha256,
            "invocation_contract_sha256": self.invocation_contract_sha256,
            "invocation_subject_sha256": self.invocation_subject_sha256,
            "invocation_registry_sha256": self.invocation_registry_sha256,
            "provider_id": self.provider_id,
            "adapter_id": self.adapter_id,
            "implementation_id": self.implementation_id,
            "payload_schema_id": self.payload_schema_id,
            "entrypoint_id": self.entrypoint_id,
            "runtime_id": self.runtime_id,
            "execution_id": self.execution_id,
            "idempotency_key": self.idempotency_key,
            "execution_request_sha256": self.execution_request_sha256,
            "lease_sha256": self.lease_sha256,
            "source_revision": self.source_revision,
            "invoke_target": self.invoke_target,
            "invoke_source_sha256": self.invoke_source_sha256,
            "invoke_code_sha256": self.invoke_code_sha256,
            "output_evidence_target": self.output_evidence_target,
            "output_evidence_source_sha256": self.output_evidence_source_sha256,
            "output_evidence_code_sha256": self.output_evidence_code_sha256,
            **{field: True for field in _TRUE_CLAIMS},
            **{field: False for field in _FALSE_CLAIMS},
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "ProviderRuntimeInvocationBindingReceipt":
        fields = {
            "executable_binding_sha256",
            "invocation_abi_sha256",
            "invocation_payload_sha256",
            "pre_admission_sha256",
            "invocation_authority_sha256",
            "observation_authority_sha256",
            "invocation_contract_sha256",
            "invocation_subject_sha256",
            "invocation_registry_sha256",
            "provider_id",
            "adapter_id",
            "implementation_id",
            "payload_schema_id",
            "entrypoint_id",
            "runtime_id",
            "execution_id",
            "idempotency_key",
            "execution_request_sha256",
            "lease_sha256",
            "source_revision",
            "invoke_target",
            "invoke_source_sha256",
            "invoke_code_sha256",
            "output_evidence_target",
            "output_evidence_source_sha256",
            "output_evidence_code_sha256",
        }
        if type(payload) is not dict or set(payload) != {
            "schema",
            *fields,
            *_TRUE_CLAIMS,
            *_FALSE_CLAIMS,
        }:
            raise ProviderRuntimeInvocationBindingShapeError(
                "provider runtime invocation binding fields are not exact"
            )
        if payload["schema"] != _SCHEMA:
            raise ProviderRuntimeInvocationBindingShapeError(
                "provider runtime invocation binding schema does not match"
            )
        for field in _TRUE_CLAIMS:
            if payload[field] is not True:
                raise ProviderRuntimeInvocationBindingShapeError(
                    f"provider runtime invocation binding lost claim: {field}"
                )
        for field in _FALSE_CLAIMS:
            if payload[field] is not False:
                raise ProviderRuntimeInvocationBindingShapeError(
                    f"provider runtime invocation binding escalated claim: {field}"
                )
        try:
            return cls(**{field: payload[field] for field in fields})
        except ProviderRuntimeInvocationBindingError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProviderRuntimeInvocationBindingShapeError(
                "provider runtime invocation binding receipt is malformed"
            ) from exc

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


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
) -> ProviderRuntimeInvocationBindingReceipt:
    """Authenticate payload/ABI/executable conjunction without starting an Effect."""

    _require_exact_types(
        authorization,
        execution,
        invocation_authority,
        invocation_payload,
        invocation_abi,
        observation_binding_ledger,
        executable_registry,
        pre_admission,
    )
    if type(at) is not datetime or at.tzinfo is None or at.utcoffset() is None:
        raise ProviderRuntimeInvocationBindingShapeError(
            "at must be an exact timezone-aware datetime"
        )

    try:
        verify_provider_invocation_abi_contract(
            invocation_abi,
            invocation_authority,
            invocation_payload,
            pre_admission,
            authority_id=observation_binding_ledger.authority_id,
            authority_keyring=_ledger_authority_keyring(observation_binding_ledger),
            observation_keyring=observation_binding_ledger.observation_keyring,
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
    try:
        expected_entrypoint = _identifier(entrypoint_id, "entrypoint_id")
        source_revision = _revision(
            authorization.capability.source_revision,
            "source_revision",
        )
        lease_sha256 = _sha256(
            authorization.capability.lease.digest,
            "lease_sha256",
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise ProviderRuntimeInvocationBindingShapeError(
            "runtime authorization subject is malformed"
        ) from exc

    _require_same(
        "authenticated invocation/executable subject",
        {
            "entrypoint_id": (invocation_abi.entrypoint_id, expected_entrypoint),
            "provider_id": (executable.provider_id, invocation_abi.provider_id),
            "adapter_id": (executable.adapter_id, invocation_abi.adapter_id),
            "implementation_id": (
                executable.implementation_id,
                invocation_abi.implementation_id,
            ),
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
            "lease_sha256": (executable.lease_sha256, lease_sha256),
            "abi_lease_sha256": (invocation_abi.lease_sha256, lease_sha256),
            "source_revision": (executable.source_revision, source_revision),
            "abi_source_revision": (invocation_abi.source_revision, source_revision),
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

    return ProviderRuntimeInvocationBindingReceipt(
        executable_binding_sha256=executable.digest,
        invocation_abi_sha256=invocation_abi.digest,
        invocation_payload_sha256=invocation_payload.digest,
        pre_admission_sha256=pre_admission.digest,
        invocation_authority_sha256=invocation_authority.digest,
        observation_authority_sha256=invocation_authority.observation_authority.digest,
        invocation_contract_sha256=invocation_authority.invocation_contract_sha256,
        invocation_subject_sha256=subject.digest,
        invocation_registry_sha256=invocation_authority.invocation_registry_sha256,
        provider_id=subject.provider_id,
        adapter_id=subject.adapter_id,
        implementation_id=pre_admission.implementation_id,
        payload_schema_id=invocation_payload.payload_schema_id,
        entrypoint_id=expected_entrypoint,
        runtime_id=subject.runtime_id,
        execution_id=execution.execution_id,
        idempotency_key=execution.idempotency_key,
        execution_request_sha256=execution.digest,
        lease_sha256=lease_sha256,
        source_revision=source_revision,
        invoke_target=executable.invoke_target,
        invoke_source_sha256=executable.invoke_source_sha256,
        invoke_code_sha256=executable.invoke_code_sha256,
        output_evidence_target=executable.output_digests_target,
        output_evidence_source_sha256=executable.output_digests_source_sha256,
        output_evidence_code_sha256=executable.output_digests_code_sha256,
    )


__all__ = [
    "ProviderRuntimeInvocationBindingError",
    "ProviderRuntimeInvocationBindingMismatch",
    "ProviderRuntimeInvocationBindingReceipt",
    "ProviderRuntimeInvocationBindingShapeError",
    "bind_provider_runtime_invocation",
]
