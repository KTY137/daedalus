"""Authenticated provider invocation ABI contract for Ikarus runtime cutover.

This module binds one already-authenticated provider invocation authority to the
canonical per-call payload introduced by G1-IKARUS-07D1 and to the fixed
provider executable/output-evidence targets proven by provider pre-admission.

It is deliberately not an execution authority: it starts no Effect, resolves no
callable, imports no provider module and invokes no provider code.  The ABI
contract is signed with the same provider authority key that authenticates the
existing ProviderInvocationObservationAuthority, so the payload/target binding
is subordinate to the canonical runtime/effect/provider trust chain rather than
a second provider registry or policy system.
"""
from __future__ import annotations

import dataclasses
import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from daedalus.kernel.contracts.base import _identifier, _revision, _sha256
from daedalus.kernel.effects import EffectExecutionRequest
from daedalus.runtimes.provider.executable_pre_admission import (
    ProviderExecutablePreAdmissionReceipt,
)
from daedalus.runtimes.provider.invocation_authority import (
    ProviderInvocationAuthorityError,
    ProviderInvocationObservationAuthority,
    verify_provider_invocation_observation_authority,
)
from daedalus.runtimes.provider.invocation_payload import ProviderInvocationPayload
from daedalus.runtimes.provider.observation import _normalize_keyring
from daedalus.spine.envelope import canonical_sha


_SCHEMA = "daedalus-provider-invocation-abi/2"
_TRUE_CLAIMS = (
    "parent_invocation_authority_authenticated",
    "payload_digest_authenticated",
    "payload_schema_bound",
    "admitted_invoke_target_bound",
    "admitted_output_evidence_target_bound",
    "runtime_effect_subject_bound",
)
_FALSE_CLAIMS = (
    "provider_execution_allowed",
    "effect_start_authorized",
    "callback_seam_removed",
    "broker_invocation_performed",
    "automatic_reexecution_allowed",
    "owner_approval_issued",
    "promotion_authorized",
    "gate_transition_authorized",
    "closed",
)


class ProviderInvocationABIError(RuntimeError):
    """Base class for authenticated provider invocation ABI failures."""


class ProviderInvocationABIShapeError(ProviderInvocationABIError):
    """An ABI input or serialized contract has a non-exact shape."""


class ProviderInvocationABIBindingError(ProviderInvocationABIError):
    """The payload, executable evidence and signed provider subject differ."""


class ProviderInvocationABISignatureError(ProviderInvocationABIError):
    """The ABI extension signature does not authenticate."""


def _target(value: Any, label: str) -> str:
    if type(value) is not str or not value or len(value) > 4096:
        raise ProviderInvocationABIShapeError(
            f"{label} must be a bounded exact target string"
        )
    if "\x00" in value or "\r" in value or "\n" in value:
        raise ProviderInvocationABIShapeError(f"{label} contains a forbidden character")
    return value


def _secret_bytes(secret: bytes | str, label: str) -> bytes:
    if isinstance(secret, str):
        value = secret.encode("utf-8")
    elif isinstance(secret, bytes):
        value = secret
    else:
        raise ProviderInvocationABIShapeError(f"{label} must be bytes or str")
    if len(value) < 32:
        raise ProviderInvocationABIShapeError(
            f"{label} must contain at least 32 bytes"
        )
    return value


def _signature(digest: str, secret: bytes | str, label: str) -> str:
    return hmac.new(
        _secret_bytes(secret, label),
        digest.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def _canonical_keyring(
    keyring: Mapping[str, bytes | str],
    *,
    label: str,
) -> dict[str, bytes]:
    """Snapshot one untrusted keyring before authentication and signing."""

    try:
        return dict(_normalize_keyring(keyring, label=label))
    except (TypeError, ValueError) as exc:
        raise ProviderInvocationABIShapeError(f"{label} is malformed") from exc


def _canonical_signing_key(
    authority: ProviderInvocationObservationAuthority,
    authority_keyring: Mapping[str, bytes],
) -> bytes:
    key_id = authority.observation_authority.authority_key_id
    secret = authority_keyring.get(key_id)
    if secret is None:
        raise ProviderInvocationABISignatureError(
            "provider invocation ABI authority key is unknown"
        )
    return secret


def _require_exact_inputs(
    authority: ProviderInvocationObservationAuthority,
    payload: ProviderInvocationPayload,
    pre_admission: ProviderExecutablePreAdmissionReceipt,
    execution: EffectExecutionRequest,
) -> None:
    expected = (
        (authority, ProviderInvocationObservationAuthority, "authority"),
        (payload, ProviderInvocationPayload, "payload"),
        (
            pre_admission,
            ProviderExecutablePreAdmissionReceipt,
            "pre_admission",
        ),
        (execution, EffectExecutionRequest, "execution"),
    )
    for value, exact_type, label in expected:
        if type(value) is not exact_type:
            raise ProviderInvocationABIShapeError(
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
        raise ProviderInvocationABIBindingError(
            f"{label} mismatch: " + ", ".join(mismatches)
        )


def _authenticate_parent(
    authority: ProviderInvocationObservationAuthority,
    *,
    authority_id: str,
    authority_keyring: Mapping[str, bytes | str],
    observation_keyring: Mapping[str, bytes | str],
    entrypoint_id: str,
    runtime_id: str,
    execution: EffectExecutionRequest,
    lease_sha256: str,
    source_revision: str,
    at: datetime,
) -> None:
    try:
        verify_provider_invocation_observation_authority(
            authority,
            authority_id=authority_id,
            authority_keyring=authority_keyring,
            observation_keyring=observation_keyring,
            invocation_subject=authority.invocation_subject,
            invocation_contract_id=authority.invocation_contract_id,
            invocation_registry_sha256=authority.invocation_registry_sha256,
            entrypoint_id=entrypoint_id,
            runtime_id=runtime_id,
            execution=execution,
            lease_sha256=lease_sha256,
            source_revision=source_revision,
            at=at,
        )
    except (ProviderInvocationAuthorityError, TypeError, ValueError) as exc:
        raise ProviderInvocationABIBindingError(
            "parent provider invocation authority did not authenticate"
        ) from exc


def _validate_conjunction(
    authority: ProviderInvocationObservationAuthority,
    payload: ProviderInvocationPayload,
    pre_admission: ProviderExecutablePreAdmissionReceipt,
    execution: EffectExecutionRequest,
) -> None:
    subject = authority.invocation_subject
    _require_same(
        "invocation payload",
        {
            "provider_id": (payload.provider_id, subject.provider_id),
            "adapter_id": (payload.adapter_id, subject.adapter_id),
            "invocation_subject_sha256": (
                payload.invocation_subject_sha256,
                subject.digest,
            ),
        },
    )
    _require_same(
        "pre-admission provider subject",
        {
            "provider_id": (pre_admission.provider_id, subject.provider_id),
            "adapter_id": (pre_admission.adapter_id, subject.adapter_id),
            "entrypoint_id": (pre_admission.entrypoint_id, subject.entrypoint_id),
            "runtime_id": (pre_admission.runtime_id, subject.runtime_id),
            "execution_id": (pre_admission.execution_id, subject.execution_id),
            "idempotency_key": (
                pre_admission.idempotency_key,
                subject.idempotency_key,
            ),
            "lease_sha256": (pre_admission.lease_sha256, subject.lease_sha256),
            "source_revision": (
                pre_admission.source_revision,
                subject.source_revision,
            ),
            "invocation_authority_sha256": (
                pre_admission.invocation_authority_sha256,
                authority.digest,
            ),
            "invocation_contract_sha256": (
                pre_admission.invocation_contract_sha256,
                authority.invocation_contract_sha256,
            ),
            "invocation_subject_sha256": (
                pre_admission.invocation_subject_sha256,
                subject.digest,
            ),
            "identity_registry_sha256": (
                pre_admission.identity_registry_sha256,
                authority.invocation_registry_sha256,
            ),
            "adapter_artifact_sha256": (
                pre_admission.adapter_artifact_sha256,
                subject.adapter_artifact_sha256,
            ),
            "adapter_config_sha256": (
                pre_admission.adapter_config_sha256,
                subject.adapter_config_sha256,
            ),
            "execution_request_sha256": (
                subject.execution_request_sha256,
                execution.digest,
            ),
        },
    )


@dataclass(frozen=True)
class ProviderInvocationABIContract:
    """Signed ABI extension binding payload identity to admitted fixed targets."""

    provider_id: str
    adapter_id: str
    implementation_id: str
    payload_schema_id: str
    invocation_payload_sha256: str
    source_revision: str
    entrypoint_id: str
    runtime_id: str
    execution_id: str
    idempotency_key: str
    execution_request_sha256: str
    lease_sha256: str
    parent_authority_sha256: str
    observation_authority_sha256: str
    parent_invocation_contract_sha256: str
    invocation_subject_sha256: str
    invocation_registry_sha256: str
    pre_admission_sha256: str
    invoke_target: str
    invoke_source_sha256: str
    output_evidence_target: str
    output_evidence_source_sha256: str
    dependency_manifest_sha256: str
    authority_key_id: str
    signature_sha256: str

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
                "authority_key_id",
            ):
                object.__setattr__(
                    self,
                    field,
                    _identifier(getattr(self, field), field),
                )
            for field in (
                "invocation_payload_sha256",
                "execution_request_sha256",
                "lease_sha256",
                "parent_authority_sha256",
                "observation_authority_sha256",
                "parent_invocation_contract_sha256",
                "invocation_subject_sha256",
                "invocation_registry_sha256",
                "pre_admission_sha256",
                "invoke_source_sha256",
                "output_evidence_source_sha256",
                "dependency_manifest_sha256",
                "signature_sha256",
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
            object.__setattr__(
                self,
                "invoke_target",
                _target(self.invoke_target, "invoke_target"),
            )
            object.__setattr__(
                self,
                "output_evidence_target",
                _target(self.output_evidence_target, "output_evidence_target"),
            )
        except ProviderInvocationABIError:
            raise
        except (AttributeError, TypeError, ValueError) as exc:
            raise ProviderInvocationABIShapeError(
                "provider invocation ABI contract is malformed"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": _SCHEMA,
            "provider_id": self.provider_id,
            "adapter_id": self.adapter_id,
            "implementation_id": self.implementation_id,
            "payload_schema_id": self.payload_schema_id,
            "invocation_payload_sha256": self.invocation_payload_sha256,
            "source_revision": self.source_revision,
            "entrypoint_id": self.entrypoint_id,
            "runtime_id": self.runtime_id,
            "execution_id": self.execution_id,
            "idempotency_key": self.idempotency_key,
            "execution_request_sha256": self.execution_request_sha256,
            "lease_sha256": self.lease_sha256,
            "parent_authority_sha256": self.parent_authority_sha256,
            "observation_authority_sha256": self.observation_authority_sha256,
            "parent_invocation_contract_sha256": (
                self.parent_invocation_contract_sha256
            ),
            "invocation_subject_sha256": self.invocation_subject_sha256,
            "invocation_registry_sha256": self.invocation_registry_sha256,
            "pre_admission_sha256": self.pre_admission_sha256,
            "invoke_target": self.invoke_target,
            "invoke_source_sha256": self.invoke_source_sha256,
            "output_evidence_target": self.output_evidence_target,
            "output_evidence_source_sha256": self.output_evidence_source_sha256,
            "dependency_manifest_sha256": self.dependency_manifest_sha256,
            "authority_key_id": self.authority_key_id,
            "signature_sha256": self.signature_sha256,
            **{field: True for field in _TRUE_CLAIMS},
            **{field: False for field in _FALSE_CLAIMS},
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProviderInvocationABIContract":
        fields = {
            "provider_id",
            "adapter_id",
            "implementation_id",
            "payload_schema_id",
            "invocation_payload_sha256",
            "source_revision",
            "entrypoint_id",
            "runtime_id",
            "execution_id",
            "idempotency_key",
            "execution_request_sha256",
            "lease_sha256",
            "parent_authority_sha256",
            "observation_authority_sha256",
            "parent_invocation_contract_sha256",
            "invocation_subject_sha256",
            "invocation_registry_sha256",
            "pre_admission_sha256",
            "invoke_target",
            "invoke_source_sha256",
            "output_evidence_target",
            "output_evidence_source_sha256",
            "dependency_manifest_sha256",
            "authority_key_id",
            "signature_sha256",
        }
        if type(payload) is not dict or set(payload) != {
            "schema",
            *fields,
            *_TRUE_CLAIMS,
            *_FALSE_CLAIMS,
        }:
            raise ProviderInvocationABIShapeError(
                "provider invocation ABI fields are not exact"
            )
        if payload["schema"] != _SCHEMA:
            raise ProviderInvocationABIShapeError(
                "provider invocation ABI schema does not match"
            )
        for field in _TRUE_CLAIMS:
            if payload[field] is not True:
                raise ProviderInvocationABIShapeError(
                    f"provider invocation ABI lost claim: {field}"
                )
        for field in _FALSE_CLAIMS:
            if payload[field] is not False:
                raise ProviderInvocationABIShapeError(
                    f"provider invocation ABI escalated claim: {field}"
                )
        try:
            return cls(**{field: payload[field] for field in fields})
        except ProviderInvocationABIError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProviderInvocationABIShapeError(
                "provider invocation ABI contract is malformed"
            ) from exc

    @property
    def signing_digest(self) -> str:
        body = self.to_dict()
        body["signature_sha256"] = "0" * 64
        return canonical_sha(body)

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def issue_provider_invocation_abi_contract(
    authority: ProviderInvocationObservationAuthority,
    payload: ProviderInvocationPayload,
    pre_admission: ProviderExecutablePreAdmissionReceipt,
    *,
    dependency_manifest_sha256: str,
    authority_id: str,
    authority_keyring: Mapping[str, bytes | str],
    observation_keyring: Mapping[str, bytes | str],
    execution: EffectExecutionRequest,
    at: datetime,
) -> ProviderInvocationABIContract:
    """Issue the signed payload/target ABI extension after parent authentication."""

    _require_exact_inputs(authority, payload, pre_admission, execution)
    authority_rows = _canonical_keyring(
        authority_keyring,
        label="authority_keyring",
    )
    observation_rows = _canonical_keyring(
        observation_keyring,
        label="observation_keyring",
    )
    subject = authority.invocation_subject
    _authenticate_parent(
        authority,
        authority_id=authority_id,
        authority_keyring=authority_rows,
        observation_keyring=observation_rows,
        entrypoint_id=subject.entrypoint_id,
        runtime_id=subject.runtime_id,
        execution=execution,
        lease_sha256=subject.lease_sha256,
        source_revision=subject.source_revision,
        at=at,
    )
    _validate_conjunction(authority, payload, pre_admission, execution)

    placeholder = ProviderInvocationABIContract(
        provider_id=subject.provider_id,
        adapter_id=subject.adapter_id,
        implementation_id=pre_admission.implementation_id,
        payload_schema_id=payload.payload_schema_id,
        invocation_payload_sha256=payload.digest,
        source_revision=subject.source_revision,
        entrypoint_id=subject.entrypoint_id,
        runtime_id=subject.runtime_id,
        execution_id=subject.execution_id,
        idempotency_key=subject.idempotency_key,
        execution_request_sha256=subject.execution_request_sha256,
        lease_sha256=subject.lease_sha256,
        parent_authority_sha256=authority.digest,
        observation_authority_sha256=authority.observation_authority.digest,
        parent_invocation_contract_sha256=authority.invocation_contract_sha256,
        invocation_subject_sha256=subject.digest,
        invocation_registry_sha256=authority.invocation_registry_sha256,
        pre_admission_sha256=pre_admission.digest,
        invoke_target=pre_admission.invoke_target,
        invoke_source_sha256=pre_admission.invoke_source_sha256,
        output_evidence_target=pre_admission.output_digests_target,
        output_evidence_source_sha256=pre_admission.output_digests_source_sha256,
        dependency_manifest_sha256=dependency_manifest_sha256,
        authority_key_id=authority.observation_authority.authority_key_id,
        signature_sha256="0" * 64,
    )
    return dataclasses.replace(
        placeholder,
        signature_sha256=_signature(
            placeholder.signing_digest,
            _canonical_signing_key(authority, authority_rows),
            "authority_keyring secret",
        ),
    )


def verify_provider_invocation_abi_contract(
    contract: ProviderInvocationABIContract,
    authority: ProviderInvocationObservationAuthority,
    payload: ProviderInvocationPayload,
    pre_admission: ProviderExecutablePreAdmissionReceipt,
    *,
    authority_id: str,
    authority_keyring: Mapping[str, bytes | str],
    observation_keyring: Mapping[str, bytes | str],
    execution: EffectExecutionRequest,
    at: datetime,
) -> None:
    """Re-authenticate parent authority and exact payload/target ABI binding."""

    if type(contract) is not ProviderInvocationABIContract:
        raise ProviderInvocationABIShapeError(
            "contract must be exact ProviderInvocationABIContract"
        )
    _require_exact_inputs(authority, payload, pre_admission, execution)
    authority_rows = _canonical_keyring(
        authority_keyring,
        label="authority_keyring",
    )
    observation_rows = _canonical_keyring(
        observation_keyring,
        label="observation_keyring",
    )
    subject = authority.invocation_subject
    _authenticate_parent(
        authority,
        authority_id=authority_id,
        authority_keyring=authority_rows,
        observation_keyring=observation_rows,
        entrypoint_id=subject.entrypoint_id,
        runtime_id=subject.runtime_id,
        execution=execution,
        lease_sha256=subject.lease_sha256,
        source_revision=subject.source_revision,
        at=at,
    )
    _validate_conjunction(authority, payload, pre_admission, execution)

    secret = authority_rows.get(contract.authority_key_id)
    if secret is None:
        raise ProviderInvocationABISignatureError(
            "provider invocation ABI authority key is unknown"
        )
    expected_signature = _signature(
        contract.signing_digest,
        secret,
        "authority_keyring secret",
    )
    if not hmac.compare_digest(contract.signature_sha256, expected_signature):
        raise ProviderInvocationABISignatureError(
            "provider invocation ABI signature mismatch"
        )

    expected = issue_provider_invocation_abi_contract(
        authority,
        payload,
        pre_admission,
        dependency_manifest_sha256=contract.dependency_manifest_sha256,
        authority_id=authority_id,
        authority_keyring=authority_rows,
        observation_keyring=observation_rows,
        execution=execution,
        at=at,
    )
    if contract != expected:
        raise ProviderInvocationABIBindingError(
            "provider invocation ABI contract subject mismatch"
        )


__all__ = [
    "ProviderInvocationABIBindingError",
    "ProviderInvocationABIContract",
    "ProviderInvocationABIError",
    "ProviderInvocationABIShapeError",
    "ProviderInvocationABISignatureError",
    "issue_provider_invocation_abi_contract",
    "verify_provider_invocation_abi_contract",
]
