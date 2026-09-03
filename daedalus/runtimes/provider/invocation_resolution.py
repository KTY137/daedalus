"""Read-only resolution of signed provider invocation authority.

This module composes the immutable invocation-registry manifest with the signed
provider invocation/observation authority. It authenticates the complete
runtime/effect subject, requires the exact manifest digest named by that
authority, resolves exactly one descriptor, and emits a deterministic receipt
binding the selected implementation identity.

Resolution is not execution. The module has no callback, adapter loader,
provider client, process/network API, effect writer, persistence, recovery,
promotion, merge or Gate authority. A later guarded executable registry may
consume the receipt only after exact-head verification of this preparatory
contract.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from daedalus.kernel.contracts.base import (
    _identifier,
    _revision,
    _sha256,
    _utc_timestamp,
)
from daedalus.kernel.effects import EffectExecutionRequest
from daedalus.runtimes.provider.invocation_authority import (
    ProviderInvocationAuthorityError,
    ProviderInvocationObservationAuthority,
    verify_provider_invocation_observation_authority,
)
from daedalus.runtimes.provider.invocation_registry import (
    ProviderAdapterDescriptor,
    ProviderInvocationRegistryError,
    ProviderInvocationRegistryManifest,
)
from daedalus.spine.envelope import canonical_sha


class ProviderInvocationResolutionError(RuntimeError):
    """Base class for exact provider invocation resolution failures."""


class ProviderInvocationResolutionBindingError(ProviderInvocationResolutionError):
    """Authority, registry, execution or receipt subjects do not bind."""


class ProviderInvocationResolutionAuthenticationError(
    ProviderInvocationResolutionError
):
    """The signed provider invocation authority did not authenticate."""


def _canonical_at(value: datetime) -> str:
    if not isinstance(value, datetime):
        raise ProviderInvocationResolutionBindingError(
            "verified_at must be datetime"
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProviderInvocationResolutionBindingError(
            "verified_at must be timezone-aware"
        )
    return _utc_timestamp(
        value.astimezone(timezone.utc).isoformat(timespec="microseconds"),
        "verified_at",
    )


@dataclass(frozen=True)
class ProviderInvocationResolutionReceipt:
    """Deterministic non-executing proof of one exact registry resolution."""

    registry_id: str
    registry_sha256: str
    source_revision: str
    authority_sha256: str
    observation_authority_sha256: str
    invocation_contract_id: str
    invocation_contract_sha256: str
    invocation_subject_sha256: str
    descriptor_sha256: str
    provider_id: str
    adapter_id: str
    implementation_id: str
    adapter_artifact_sha256: str
    adapter_config_sha256: str
    entrypoint_id: str
    runtime_id: str
    execution_id: str
    idempotency_key: str
    execution_request_sha256: str
    lease_sha256: str
    verified_at: str
    receipt_sha256: str

    def __post_init__(self) -> None:
        try:
            for field in (
                "registry_id",
                "invocation_contract_id",
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
                "registry_sha256",
                "authority_sha256",
                "observation_authority_sha256",
                "invocation_contract_sha256",
                "invocation_subject_sha256",
                "descriptor_sha256",
                "adapter_artifact_sha256",
                "adapter_config_sha256",
                "execution_request_sha256",
                "lease_sha256",
                "receipt_sha256",
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
                "verified_at",
                _utc_timestamp(self.verified_at, "verified_at"),
            )
        except (TypeError, ValueError) as exc:
            raise ProviderInvocationResolutionBindingError(
                "provider invocation resolution receipt is malformed"
            ) from exc
        expected = canonical_sha(self.unsigned_dict())
        if self.receipt_sha256 != expected:
            raise ProviderInvocationResolutionBindingError(
                "provider invocation resolution receipt digest mismatch"
            )

    def unsigned_dict(self) -> dict[str, str]:
        body = dataclasses.asdict(self)
        body.pop("receipt_sha256")
        return body

    def to_dict(self) -> dict[str, str]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "ProviderInvocationResolutionReceipt":
        expected = {
            "registry_id",
            "registry_sha256",
            "source_revision",
            "authority_sha256",
            "observation_authority_sha256",
            "invocation_contract_id",
            "invocation_contract_sha256",
            "invocation_subject_sha256",
            "descriptor_sha256",
            "provider_id",
            "adapter_id",
            "implementation_id",
            "adapter_artifact_sha256",
            "adapter_config_sha256",
            "entrypoint_id",
            "runtime_id",
            "execution_id",
            "idempotency_key",
            "execution_request_sha256",
            "lease_sha256",
            "verified_at",
            "receipt_sha256",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ProviderInvocationResolutionBindingError(
                "provider invocation resolution receipt fields are not exact"
            )
        try:
            return cls(**{field: payload[field] for field in expected})
        except ProviderInvocationResolutionError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProviderInvocationResolutionBindingError(
                "provider invocation resolution receipt is malformed"
            ) from exc

    @property
    def digest(self) -> str:
        return self.receipt_sha256


def _receipt_for(
    *,
    authority: ProviderInvocationObservationAuthority,
    manifest: ProviderInvocationRegistryManifest,
    descriptor: ProviderAdapterDescriptor,
    verified_at: str,
) -> ProviderInvocationResolutionReceipt:
    subject = authority.invocation_subject
    values = {
        "registry_id": manifest.registry_id,
        "registry_sha256": manifest.digest,
        "source_revision": manifest.source_revision,
        "authority_sha256": authority.digest,
        "observation_authority_sha256": authority.observation_authority.digest,
        "invocation_contract_id": authority.invocation_contract_id,
        "invocation_contract_sha256": authority.invocation_contract_sha256,
        "invocation_subject_sha256": subject.digest,
        "descriptor_sha256": descriptor.digest,
        "provider_id": descriptor.provider_id,
        "adapter_id": descriptor.adapter_id,
        "implementation_id": descriptor.implementation_id,
        "adapter_artifact_sha256": descriptor.adapter_artifact_sha256,
        "adapter_config_sha256": descriptor.adapter_config_sha256,
        "entrypoint_id": descriptor.entrypoint_id,
        "runtime_id": descriptor.runtime_id,
        "execution_id": subject.execution_id,
        "idempotency_key": subject.idempotency_key,
        "execution_request_sha256": subject.execution_request_sha256,
        "lease_sha256": subject.lease_sha256,
        "verified_at": verified_at,
    }
    return ProviderInvocationResolutionReceipt(
        **values,
        receipt_sha256=canonical_sha(values),
    )


def resolve_provider_invocation_authority(
    authority: ProviderInvocationObservationAuthority,
    manifest: ProviderInvocationRegistryManifest,
    *,
    authority_id: str,
    authority_keyring: Mapping[str, bytes | str],
    observation_keyring: Mapping[str, bytes | str],
    invocation_contract_id: str,
    entrypoint_id: str,
    runtime_id: str,
    execution: EffectExecutionRequest,
    lease_sha256: str,
    source_revision: str,
    at: datetime,
) -> ProviderInvocationResolutionReceipt:
    """Authenticate and resolve one exact non-executing invocation subject."""

    if type(authority) is not ProviderInvocationObservationAuthority:
        raise ProviderInvocationResolutionBindingError(
            "authority must be exact ProviderInvocationObservationAuthority"
        )
    if type(manifest) is not ProviderInvocationRegistryManifest:
        raise ProviderInvocationResolutionBindingError(
            "manifest must be exact ProviderInvocationRegistryManifest"
        )
    if type(execution) is not EffectExecutionRequest:
        raise ProviderInvocationResolutionBindingError(
            "execution must be exact EffectExecutionRequest"
        )
    verified_at = _canonical_at(at)
    try:
        expected_revision = _revision(source_revision, "source_revision")
    except (TypeError, ValueError) as exc:
        raise ProviderInvocationResolutionBindingError(
            "resolution source revision is malformed"
        ) from exc
    if manifest.source_revision != expected_revision:
        raise ProviderInvocationResolutionBindingError(
            "invocation registry source revision mismatch"
        )
    if authority.invocation_registry_sha256 != manifest.digest:
        raise ProviderInvocationResolutionBindingError(
            "signed invocation registry digest does not match manifest"
        )

    try:
        verify_provider_invocation_observation_authority(
            authority,
            authority_id=authority_id,
            authority_keyring=authority_keyring,
            observation_keyring=observation_keyring,
            invocation_subject=authority.invocation_subject,
            invocation_contract_id=invocation_contract_id,
            invocation_registry_sha256=manifest.digest,
            entrypoint_id=entrypoint_id,
            runtime_id=runtime_id,
            execution=execution,
            lease_sha256=lease_sha256,
            source_revision=expected_revision,
            at=at,
        )
    except ProviderInvocationAuthorityError as exc:
        raise ProviderInvocationResolutionAuthenticationError(
            "provider invocation authority did not authenticate"
        ) from exc

    try:
        descriptor = manifest.resolve(authority.invocation_subject)
    except ProviderInvocationRegistryError as exc:
        raise ProviderInvocationResolutionBindingError(
            "signed provider invocation subject did not resolve"
        ) from exc
    return _receipt_for(
        authority=authority,
        manifest=manifest,
        descriptor=descriptor,
        verified_at=verified_at,
    )


def verify_provider_invocation_resolution_receipt(
    receipt: ProviderInvocationResolutionReceipt,
    authority: ProviderInvocationObservationAuthority,
    manifest: ProviderInvocationRegistryManifest,
    *,
    authority_id: str,
    authority_keyring: Mapping[str, bytes | str],
    observation_keyring: Mapping[str, bytes | str],
    invocation_contract_id: str,
    entrypoint_id: str,
    runtime_id: str,
    execution: EffectExecutionRequest,
    lease_sha256: str,
    source_revision: str,
    at: datetime,
) -> None:
    """Re-authenticate all subjects and compare one exact retained receipt."""

    if type(receipt) is not ProviderInvocationResolutionReceipt:
        raise ProviderInvocationResolutionBindingError(
            "receipt must be exact ProviderInvocationResolutionReceipt"
        )
    expected = resolve_provider_invocation_authority(
        authority,
        manifest,
        authority_id=authority_id,
        authority_keyring=authority_keyring,
        observation_keyring=observation_keyring,
        invocation_contract_id=invocation_contract_id,
        entrypoint_id=entrypoint_id,
        runtime_id=runtime_id,
        execution=execution,
        lease_sha256=lease_sha256,
        source_revision=source_revision,
        at=at,
    )
    if receipt != expected:
        raise ProviderInvocationResolutionBindingError(
            "provider invocation resolution receipt subject mismatch"
        )


__all__ = [
    "ProviderInvocationResolutionAuthenticationError",
    "ProviderInvocationResolutionBindingError",
    "ProviderInvocationResolutionError",
    "ProviderInvocationResolutionReceipt",
    "resolve_provider_invocation_authority",
    "verify_provider_invocation_resolution_receipt",
]
