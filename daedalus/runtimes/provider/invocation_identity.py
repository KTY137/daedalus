"""Read-only authentication projection for one exact provider invocation identity.

This module composes the signed invocation-observation authority with the
revision-bound provider registry manifest.  It authenticates one exact provider,
adapter, implementation, artifact, configuration, runtime effect subject and
source revision, then returns an inert content-addressed projection.

The projection is not an Effect Lease, a runtime-conformance receipt, a provider
callback, permission to execute, recovery authority, promotion authority, or
Gate evidence.  A later broker packet must compare it with the exact runtime
authorization before ``begin_effect`` and invoke only through a separately
guarded executable registry.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, Mapping

from daedalus.kernel.contracts.base import _identifier, _revision, _sha256
from daedalus.kernel.effects import EffectExecutionRequest
from daedalus.runtimes.provider.invocation_authority import (
    ProviderInvocationAuthorityError,
    ProviderInvocationObservationAuthority,
    verify_provider_invocation_observation_authority,
)
from daedalus.runtimes.provider.invocation_registry import (
    ProviderInvocationRegistryError,
    ProviderInvocationRegistryManifest,
)
from daedalus.spine.envelope import canonical_sha


PROVIDER_INVOCATION_CONTRACT_ID = "provider-invocation-contract"


class ProviderInvocationIdentityError(RuntimeError):
    """Base class for exact provider invocation identity projection failures."""


class ProviderInvocationIdentityAuthenticationError(ProviderInvocationIdentityError):
    """The signed authority did not authenticate for the supplied registry."""


class ProviderInvocationIdentityBindingError(ProviderInvocationIdentityError):
    """The authenticated subject did not resolve to one exact registry row."""


@dataclass(frozen=True)
class ProviderInvocationIdentityProjection:
    """Inert exact identity derived from authenticated authority and registry."""

    provider_id: str
    adapter_id: str
    implementation_id: str
    entrypoint_id: str
    runtime_id: str
    execution_id: str
    idempotency_key: str
    source_revision: str
    authority_sha256: str
    observation_authority_sha256: str
    invocation_contract_sha256: str
    invocation_subject_sha256: str
    registry_sha256: str
    descriptor_sha256: str
    execution_request_sha256: str
    lease_sha256: str
    adapter_artifact_sha256: str
    adapter_config_sha256: str

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
            object.__setattr__(
                self,
                "source_revision",
                _revision(self.source_revision, "source_revision"),
            )
            for field in (
                "authority_sha256",
                "observation_authority_sha256",
                "invocation_contract_sha256",
                "invocation_subject_sha256",
                "registry_sha256",
                "descriptor_sha256",
                "execution_request_sha256",
                "lease_sha256",
                "adapter_artifact_sha256",
                "adapter_config_sha256",
            ):
                object.__setattr__(
                    self,
                    field,
                    _sha256(getattr(self, field), field),
                )
        except (AttributeError, TypeError, ValueError) as exc:
            raise ProviderInvocationIdentityBindingError(
                "provider invocation identity projection is malformed"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "daedalus-provider-invocation-identity/1",
            **dataclasses.asdict(self),
            "runtime_effect_authorized": False,
            "provider_execution_allowed": False,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "ProviderInvocationIdentityProjection":
        expected = {
            "schema",
            "provider_id",
            "adapter_id",
            "implementation_id",
            "entrypoint_id",
            "runtime_id",
            "execution_id",
            "idempotency_key",
            "source_revision",
            "authority_sha256",
            "observation_authority_sha256",
            "invocation_contract_sha256",
            "invocation_subject_sha256",
            "registry_sha256",
            "descriptor_sha256",
            "execution_request_sha256",
            "lease_sha256",
            "adapter_artifact_sha256",
            "adapter_config_sha256",
            "runtime_effect_authorized",
            "provider_execution_allowed",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ProviderInvocationIdentityBindingError(
                "provider invocation identity projection fields are not exact"
            )
        if payload["schema"] != "daedalus-provider-invocation-identity/1":
            raise ProviderInvocationIdentityBindingError(
                "provider invocation identity projection schema does not match"
            )
        if payload["runtime_effect_authorized"] is not False:
            raise ProviderInvocationIdentityBindingError(
                "identity projection cannot authorize a runtime effect"
            )
        if payload["provider_execution_allowed"] is not False:
            raise ProviderInvocationIdentityBindingError(
                "identity projection cannot authorize provider execution"
            )
        values = {
            field: payload[field]
            for field in expected
            if field
            not in {
                "schema",
                "runtime_effect_authorized",
                "provider_execution_allowed",
            }
        }
        try:
            return cls(**values)
        except ProviderInvocationIdentityError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProviderInvocationIdentityBindingError(
                "provider invocation identity projection is malformed"
            ) from exc

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def project_provider_invocation_identity(
    authority: ProviderInvocationObservationAuthority,
    registry: ProviderInvocationRegistryManifest,
    execution: EffectExecutionRequest,
    *,
    authority_id: str,
    authority_keyring: Mapping[str, bytes | str],
    observation_keyring: Mapping[str, bytes | str],
    at,
) -> ProviderInvocationIdentityProjection:
    """Authenticate first, then resolve one exact non-executing registry row."""

    if type(authority) is not ProviderInvocationObservationAuthority:
        raise ProviderInvocationIdentityBindingError(
            "authority must be exact ProviderInvocationObservationAuthority"
        )
    if type(registry) is not ProviderInvocationRegistryManifest:
        raise ProviderInvocationIdentityBindingError(
            "registry must be exact ProviderInvocationRegistryManifest"
        )
    if type(execution) is not EffectExecutionRequest:
        raise ProviderInvocationIdentityBindingError(
            "execution must be exact EffectExecutionRequest"
        )

    subject = authority.invocation_subject
    try:
        verify_provider_invocation_observation_authority(
            authority,
            authority_id=authority_id,
            authority_keyring=authority_keyring,
            observation_keyring=observation_keyring,
            invocation_subject=subject,
            invocation_contract_id=PROVIDER_INVOCATION_CONTRACT_ID,
            invocation_registry_sha256=registry.digest,
            entrypoint_id=subject.entrypoint_id,
            runtime_id=subject.runtime_id,
            execution=execution,
            lease_sha256=subject.lease_sha256,
            source_revision=subject.source_revision,
            at=at,
        )
    except ProviderInvocationAuthorityError as exc:
        raise ProviderInvocationIdentityAuthenticationError(
            "provider invocation authority did not authenticate"
        ) from exc

    if registry.source_revision != subject.source_revision:
        raise ProviderInvocationIdentityBindingError(
            "provider invocation registry source revision mismatch"
        )
    try:
        descriptor = registry.resolve(subject)
    except ProviderInvocationRegistryError as exc:
        raise ProviderInvocationIdentityBindingError(
            "provider invocation subject did not resolve exactly"
        ) from exc

    return ProviderInvocationIdentityProjection(
        provider_id=descriptor.provider_id,
        adapter_id=descriptor.adapter_id,
        implementation_id=descriptor.implementation_id,
        entrypoint_id=descriptor.entrypoint_id,
        runtime_id=descriptor.runtime_id,
        execution_id=subject.execution_id,
        idempotency_key=subject.idempotency_key,
        source_revision=subject.source_revision,
        authority_sha256=authority.digest,
        observation_authority_sha256=authority.observation_authority.digest,
        invocation_contract_sha256=authority.invocation_contract_sha256,
        invocation_subject_sha256=subject.digest,
        registry_sha256=registry.digest,
        descriptor_sha256=descriptor.digest,
        execution_request_sha256=execution.digest,
        lease_sha256=subject.lease_sha256,
        adapter_artifact_sha256=descriptor.adapter_artifact_sha256,
        adapter_config_sha256=descriptor.adapter_config_sha256,
    )


__all__ = [
    "PROVIDER_INVOCATION_CONTRACT_ID",
    "ProviderInvocationIdentityAuthenticationError",
    "ProviderInvocationIdentityBindingError",
    "ProviderInvocationIdentityError",
    "ProviderInvocationIdentityProjection",
    "project_provider_invocation_identity",
]
