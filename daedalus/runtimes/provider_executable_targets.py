"""Non-executing exact target manifest for provider adapter implementations.

This module extends an authenticated provider-invocation identity with exact
repository target and source-digest metadata.  It deliberately does not import,
load, resolve, or execute either target.  A later guarded loader must prove the
named targets against exact repository bytes and consume the resulting receipt
inside the runtime broker.
"""
from __future__ import annotations

import dataclasses
import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from daedalus.kernel.contracts.base import _identifier, _revision, _sha256
from daedalus.kernel.effects import EffectExecutionRequest
from daedalus.runtimes.provider_invocation_authority import (
    ProviderInvocationObservationAuthority,
)
from daedalus.runtimes.provider_invocation_identity import (
    ProviderInvocationIdentityError,
    ProviderInvocationIdentityProjection,
    project_provider_invocation_identity,
)
from daedalus.runtimes.provider_invocation_registry import (
    ProviderInvocationRegistryManifest,
)
from daedalus.runtimes.provider_observation import _normalize_keyring
from daedalus.spine.envelope import canonical_sha


_TARGET_RE = re.compile(
    r"^daedalus(?:\.[a-z][a-z0-9_]*)*:"
    r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$"
)


class ProviderExecutableTargetError(RuntimeError):
    """Base class for provider executable-target manifest failures."""


class ProviderExecutableTargetShapeError(ProviderExecutableTargetError):
    """A descriptor, manifest, authority, or projection is malformed."""


class ProviderExecutableTargetBindingError(ProviderExecutableTargetError):
    """An authenticated invocation identity does not match the target binding."""


class ProviderExecutableTargetSignatureError(ProviderExecutableTargetError):
    """The executable-target authority signature did not authenticate."""


def _secret_bytes(secret: bytes | str, label: str) -> bytes:
    if isinstance(secret, str):
        value = secret.encode("utf-8")
    elif isinstance(secret, bytes):
        value = secret
    else:
        raise ProviderExecutableTargetShapeError(
            f"{label} must be bytes or str"
        )
    if len(value) < 32:
        raise ProviderExecutableTargetShapeError(
            f"{label} must contain at least 32 bytes"
        )
    return value


def _signature(digest: str, secret: bytes | str, label: str) -> str:
    return hmac.new(
        _secret_bytes(secret, label),
        digest.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def _target(value: Any, label: str) -> str:
    if not isinstance(value, str) or _TARGET_RE.fullmatch(value) is None:
        raise ProviderExecutableTargetShapeError(
            f"{label} must be a canonical Daedalus Python target"
        )
    return value


@dataclass(frozen=True, order=True)
class ProviderExecutableTargetDescriptor:
    """Exact inert metadata for one provider implementation's two targets."""

    provider_id: str
    adapter_id: str
    implementation_id: str
    entrypoint_id: str
    runtime_id: str
    source_revision: str
    identity_descriptor_sha256: str
    adapter_artifact_sha256: str
    adapter_config_sha256: str
    invoke_target: str
    invoke_source_sha256: str
    output_digests_target: str
    output_digests_source_sha256: str

    def __post_init__(self) -> None:
        try:
            for field in (
                "provider_id",
                "adapter_id",
                "implementation_id",
                "entrypoint_id",
                "runtime_id",
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
                "identity_descriptor_sha256",
                "adapter_artifact_sha256",
                "adapter_config_sha256",
                "invoke_source_sha256",
                "output_digests_source_sha256",
            ):
                object.__setattr__(
                    self,
                    field,
                    _sha256(getattr(self, field), field),
                )
            object.__setattr__(
                self,
                "invoke_target",
                _target(self.invoke_target, "invoke_target"),
            )
            object.__setattr__(
                self,
                "output_digests_target",
                _target(self.output_digests_target, "output_digests_target"),
            )
        except ProviderExecutableTargetError:
            raise
        except (AttributeError, TypeError, ValueError) as exc:
            raise ProviderExecutableTargetShapeError(
                "provider executable target descriptor is malformed"
            ) from exc

    def to_dict(self) -> dict[str, str]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "ProviderExecutableTargetDescriptor":
        expected = {
            "provider_id",
            "adapter_id",
            "implementation_id",
            "entrypoint_id",
            "runtime_id",
            "source_revision",
            "identity_descriptor_sha256",
            "adapter_artifact_sha256",
            "adapter_config_sha256",
            "invoke_target",
            "invoke_source_sha256",
            "output_digests_target",
            "output_digests_source_sha256",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ProviderExecutableTargetShapeError(
                "provider executable target descriptor fields are not exact"
            )
        try:
            return cls(**{field: payload[field] for field in expected})
        except ProviderExecutableTargetError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProviderExecutableTargetShapeError(
                "provider executable target descriptor is malformed"
            ) from exc

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class ProviderExecutableTargetManifest:
    """Canonical revision-bound manifest of provider target metadata."""

    manifest_id: str
    source_revision: str
    identity_registry_sha256: str
    descriptors: tuple[ProviderExecutableTargetDescriptor, ...]

    def __post_init__(self) -> None:
        try:
            object.__setattr__(
                self,
                "manifest_id",
                _identifier(self.manifest_id, "manifest_id"),
            )
            object.__setattr__(
                self,
                "source_revision",
                _revision(self.source_revision, "source_revision"),
            )
            object.__setattr__(
                self,
                "identity_registry_sha256",
                _sha256(
                    self.identity_registry_sha256,
                    "identity_registry_sha256",
                ),
            )
        except (TypeError, ValueError) as exc:
            raise ProviderExecutableTargetShapeError(
                "provider executable target manifest identity is malformed"
            ) from exc
        if type(self.descriptors) is not tuple or not self.descriptors:
            raise ProviderExecutableTargetShapeError(
                "provider executable target descriptors must be a non-empty exact tuple"
            )
        if any(
            type(item) is not ProviderExecutableTargetDescriptor
            for item in self.descriptors
        ):
            raise ProviderExecutableTargetShapeError(
                "provider executable target manifest contains non-exact descriptors"
            )
        canonical = tuple(
            sorted(
                self.descriptors,
                key=lambda item: (item.provider_id, item.implementation_id),
            )
        )
        if self.descriptors != canonical:
            raise ProviderExecutableTargetShapeError(
                "provider executable target descriptors are not canonically ordered"
            )
        provider_ids = tuple(item.provider_id for item in self.descriptors)
        if len(set(provider_ids)) != len(provider_ids):
            raise ProviderExecutableTargetShapeError(
                "provider executable target provider IDs must be unique"
            )
        descriptor_digests = tuple(
            item.identity_descriptor_sha256 for item in self.descriptors
        )
        if len(set(descriptor_digests)) != len(descriptor_digests):
            raise ProviderExecutableTargetShapeError(
                "provider executable identity descriptor digests must be unique"
            )
        stale = tuple(
            item.provider_id
            for item in self.descriptors
            if item.source_revision != self.source_revision
        )
        if stale:
            raise ProviderExecutableTargetShapeError(
                "provider executable target source revision mismatch: "
                + ", ".join(stale)
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "daedalus-provider-executable-target-manifest/1",
            "manifest_id": self.manifest_id,
            "source_revision": self.source_revision,
            "identity_registry_sha256": self.identity_registry_sha256,
            "descriptors": [item.to_dict() for item in self.descriptors],
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "ProviderExecutableTargetManifest":
        expected = {
            "schema",
            "manifest_id",
            "source_revision",
            "identity_registry_sha256",
            "descriptors",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ProviderExecutableTargetShapeError(
                "provider executable target manifest fields are not exact"
            )
        if payload["schema"] != "daedalus-provider-executable-target-manifest/1":
            raise ProviderExecutableTargetShapeError(
                "provider executable target manifest schema does not match"
            )
        rows = payload["descriptors"]
        if not isinstance(rows, list):
            raise ProviderExecutableTargetShapeError(
                "provider executable target descriptors must be a list"
            )
        try:
            return cls(
                manifest_id=payload["manifest_id"],
                source_revision=payload["source_revision"],
                identity_registry_sha256=payload["identity_registry_sha256"],
                descriptors=tuple(
                    ProviderExecutableTargetDescriptor.from_dict(item)
                    for item in rows
                ),
            )
        except ProviderExecutableTargetError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProviderExecutableTargetShapeError(
                "provider executable target manifest is malformed"
            ) from exc

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())

    def descriptor_for_provider(
        self,
        provider_id: str,
    ) -> ProviderExecutableTargetDescriptor:
        try:
            expected = _identifier(provider_id, "provider_id")
        except (TypeError, ValueError) as exc:
            raise ProviderExecutableTargetBindingError(
                "provider executable target lookup identity is malformed"
            ) from exc
        matches = tuple(
            item for item in self.descriptors if item.provider_id == expected
        )
        if len(matches) != 1:
            raise ProviderExecutableTargetBindingError(
                "provider executable target is not registered exactly once"
            )
        return matches[0]


@dataclass(frozen=True)
class ProviderExecutableTargetAuthority:
    """Signed exact target-manifest binding rooted in invocation authority."""

    authority_key_id: str
    target_contract_id: str
    invocation_authority_sha256: str
    invocation_contract_sha256: str
    invocation_identity_sha256: str
    identity_registry_sha256: str
    identity_descriptor_sha256: str
    target_manifest_sha256: str
    target_descriptor_sha256: str
    provider_id: str
    adapter_id: str
    implementation_id: str
    entrypoint_id: str
    runtime_id: str
    execution_id: str
    idempotency_key: str
    lease_sha256: str
    source_revision: str
    signature_sha256: str

    def __post_init__(self) -> None:
        try:
            for field in (
                "authority_key_id",
                "target_contract_id",
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
                "invocation_authority_sha256",
                "invocation_contract_sha256",
                "invocation_identity_sha256",
                "identity_registry_sha256",
                "identity_descriptor_sha256",
                "target_manifest_sha256",
                "target_descriptor_sha256",
                "lease_sha256",
                "signature_sha256",
            ):
                object.__setattr__(
                    self,
                    field,
                    _sha256(getattr(self, field), field),
                )
        except (AttributeError, TypeError, ValueError) as exc:
            raise ProviderExecutableTargetShapeError(
                "provider executable target authority is malformed"
            ) from exc

    def to_dict(self) -> dict[str, str]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "ProviderExecutableTargetAuthority":
        expected = {field.name for field in dataclasses.fields(cls)}
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ProviderExecutableTargetShapeError(
                "provider executable target authority fields are not exact"
            )
        try:
            return cls(**{field: payload[field] for field in expected})
        except ProviderExecutableTargetError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProviderExecutableTargetShapeError(
                "provider executable target authority is malformed"
            ) from exc

    @property
    def signing_digest(self) -> str:
        body = self.to_dict()
        body["signature_sha256"] = "0" * 64
        return canonical_sha(body)

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class ProviderExecutableTargetProjection:
    """Inert exact target metadata joined to one authenticated identity."""

    provider_id: str
    adapter_id: str
    implementation_id: str
    entrypoint_id: str
    runtime_id: str
    source_revision: str
    identity_sha256: str
    identity_registry_sha256: str
    identity_descriptor_sha256: str
    target_manifest_sha256: str
    target_descriptor_sha256: str
    adapter_artifact_sha256: str
    adapter_config_sha256: str
    invoke_target: str
    invoke_source_sha256: str
    output_digests_target: str
    output_digests_source_sha256: str

    def __post_init__(self) -> None:
        try:
            for field in (
                "provider_id",
                "adapter_id",
                "implementation_id",
                "entrypoint_id",
                "runtime_id",
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
                "identity_sha256",
                "identity_registry_sha256",
                "identity_descriptor_sha256",
                "target_manifest_sha256",
                "target_descriptor_sha256",
                "adapter_artifact_sha256",
                "adapter_config_sha256",
                "invoke_source_sha256",
                "output_digests_source_sha256",
            ):
                object.__setattr__(
                    self,
                    field,
                    _sha256(getattr(self, field), field),
                )
            object.__setattr__(
                self,
                "invoke_target",
                _target(self.invoke_target, "invoke_target"),
            )
            object.__setattr__(
                self,
                "output_digests_target",
                _target(self.output_digests_target, "output_digests_target"),
            )
        except ProviderExecutableTargetError:
            raise
        except (AttributeError, TypeError, ValueError) as exc:
            raise ProviderExecutableTargetShapeError(
                "provider executable target projection is malformed"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "daedalus-provider-executable-target-projection/1",
            **dataclasses.asdict(self),
            "targets_structurally_verified": False,
            "provider_execution_allowed": False,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "ProviderExecutableTargetProjection":
        fields = {field.name for field in dataclasses.fields(cls)}
        expected = {
            "schema",
            *fields,
            "targets_structurally_verified",
            "provider_execution_allowed",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ProviderExecutableTargetShapeError(
                "provider executable target projection fields are not exact"
            )
        if payload["schema"] != "daedalus-provider-executable-target-projection/1":
            raise ProviderExecutableTargetShapeError(
                "provider executable target projection schema does not match"
            )
        if payload["targets_structurally_verified"] is not False:
            raise ProviderExecutableTargetShapeError(
                "target projection cannot claim structural verification"
            )
        if payload["provider_execution_allowed"] is not False:
            raise ProviderExecutableTargetShapeError(
                "target projection cannot authorize provider execution"
            )
        try:
            return cls(**{field: payload[field] for field in fields})
        except ProviderExecutableTargetError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProviderExecutableTargetShapeError(
                "provider executable target projection is malformed"
            ) from exc

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def build_provider_executable_target_manifest(
    *,
    manifest_id: str,
    source_revision: str,
    identity_registry_sha256: str,
    descriptors: Iterable[ProviderExecutableTargetDescriptor],
) -> ProviderExecutableTargetManifest:
    """Canonicalize exact descriptors without importing or resolving targets."""

    if isinstance(descriptors, (str, bytes, Mapping)):
        raise ProviderExecutableTargetShapeError(
            "descriptors must be an iterable of exact target descriptors"
        )
    try:
        rows = tuple(descriptors)
    except (TypeError, RuntimeError) as exc:
        raise ProviderExecutableTargetShapeError(
            "provider executable target descriptors could not be materialized"
        ) from exc
    if any(type(item) is not ProviderExecutableTargetDescriptor for item in rows):
        raise ProviderExecutableTargetShapeError(
            "descriptors must contain exact ProviderExecutableTargetDescriptor values"
        )
    return ProviderExecutableTargetManifest(
        manifest_id=manifest_id,
        source_revision=source_revision,
        identity_registry_sha256=identity_registry_sha256,
        descriptors=tuple(
            sorted(rows, key=lambda item: (item.provider_id, item.implementation_id))
        ),
    )


def _identity_and_target_descriptor(
    authority: ProviderInvocationObservationAuthority,
    identity_registry: ProviderInvocationRegistryManifest,
    execution: EffectExecutionRequest,
    manifest: ProviderExecutableTargetManifest,
    *,
    authority_id: str,
    authority_keyring: Mapping[str, bytes | str],
    observation_keyring: Mapping[str, bytes | str],
    at,
) -> tuple[
    ProviderInvocationIdentityProjection,
    ProviderExecutableTargetDescriptor,
]:
    if type(manifest) is not ProviderExecutableTargetManifest:
        raise ProviderExecutableTargetBindingError(
            "manifest must be exact ProviderExecutableTargetManifest"
        )
    try:
        identity = project_provider_invocation_identity(
            authority,
            identity_registry,
            execution,
            authority_id=authority_id,
            authority_keyring=authority_keyring,
            observation_keyring=observation_keyring,
            at=at,
        )
    except ProviderInvocationIdentityError as exc:
        raise ProviderExecutableTargetBindingError(
            "provider invocation identity did not authenticate"
        ) from exc
    if manifest.source_revision != identity.source_revision:
        raise ProviderExecutableTargetBindingError(
            "provider executable target source revision mismatch"
        )
    if manifest.identity_registry_sha256 != identity.registry_sha256:
        raise ProviderExecutableTargetBindingError(
            "provider executable target identity registry mismatch"
        )
    descriptor = manifest.descriptor_for_provider(identity.provider_id)
    comparisons = {
        "provider_id": (descriptor.provider_id, identity.provider_id),
        "adapter_id": (descriptor.adapter_id, identity.adapter_id),
        "implementation_id": (
            descriptor.implementation_id,
            identity.implementation_id,
        ),
        "entrypoint_id": (descriptor.entrypoint_id, identity.entrypoint_id),
        "runtime_id": (descriptor.runtime_id, identity.runtime_id),
        "source_revision": (
            descriptor.source_revision,
            identity.source_revision,
        ),
        "identity_descriptor_sha256": (
            descriptor.identity_descriptor_sha256,
            identity.descriptor_sha256,
        ),
        "adapter_artifact_sha256": (
            descriptor.adapter_artifact_sha256,
            identity.adapter_artifact_sha256,
        ),
        "adapter_config_sha256": (
            descriptor.adapter_config_sha256,
            identity.adapter_config_sha256,
        ),
    }
    mismatches = tuple(
        sorted(
            field
            for field, (registered, authenticated) in comparisons.items()
            if registered != authenticated
        )
    )
    if mismatches:
        raise ProviderExecutableTargetBindingError(
            "provider executable target descriptor differs from authenticated "
            "identity: " + ", ".join(mismatches)
        )
    return identity, descriptor


def _authority_values(
    *,
    authority: ProviderInvocationObservationAuthority,
    identity: ProviderInvocationIdentityProjection,
    manifest: ProviderExecutableTargetManifest,
    descriptor: ProviderExecutableTargetDescriptor,
    target_contract_id: str,
) -> dict[str, str]:
    try:
        authority_key_id = _identifier(
            authority.observation_authority.authority_key_id,
            "authority_key_id",
        )
        contract_id = _identifier(
            target_contract_id,
            "target_contract_id",
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise ProviderExecutableTargetBindingError(
            "provider executable target authority subject is malformed"
        ) from exc
    return {
        "authority_key_id": authority_key_id,
        "target_contract_id": contract_id,
        "invocation_authority_sha256": authority.digest,
        "invocation_contract_sha256": authority.invocation_contract_sha256,
        "invocation_identity_sha256": identity.digest,
        "identity_registry_sha256": identity.registry_sha256,
        "identity_descriptor_sha256": identity.descriptor_sha256,
        "target_manifest_sha256": manifest.digest,
        "target_descriptor_sha256": descriptor.digest,
        "provider_id": identity.provider_id,
        "adapter_id": identity.adapter_id,
        "implementation_id": identity.implementation_id,
        "entrypoint_id": identity.entrypoint_id,
        "runtime_id": identity.runtime_id,
        "execution_id": identity.execution_id,
        "idempotency_key": identity.idempotency_key,
        "lease_sha256": identity.lease_sha256,
        "source_revision": identity.source_revision,
    }


def issue_provider_executable_target_authority(
    authority: ProviderInvocationObservationAuthority,
    identity_registry: ProviderInvocationRegistryManifest,
    execution: EffectExecutionRequest,
    manifest: ProviderExecutableTargetManifest,
    *,
    target_contract_id: str,
    authority_id: str,
    authority_keyring: Mapping[str, bytes | str],
    observation_keyring: Mapping[str, bytes | str],
    authority_secret: bytes | str,
    at,
) -> ProviderExecutableTargetAuthority:
    """Authenticate the invocation and sign its exact target manifest."""

    identity, descriptor = _identity_and_target_descriptor(
        authority,
        identity_registry,
        execution,
        manifest,
        authority_id=authority_id,
        authority_keyring=authority_keyring,
        observation_keyring=observation_keyring,
        at=at,
    )
    values = _authority_values(
        authority=authority,
        identity=identity,
        manifest=manifest,
        descriptor=descriptor,
        target_contract_id=target_contract_id,
    )
    placeholder = ProviderExecutableTargetAuthority(
        **values,
        signature_sha256="0" * 64,
    )
    return dataclasses.replace(
        placeholder,
        signature_sha256=_signature(
            placeholder.signing_digest,
            authority_secret,
            "authority_secret",
        ),
    )


def project_provider_executable_targets(
    target_authority: ProviderExecutableTargetAuthority,
    authority: ProviderInvocationObservationAuthority,
    identity_registry: ProviderInvocationRegistryManifest,
    execution: EffectExecutionRequest,
    manifest: ProviderExecutableTargetManifest,
    *,
    target_contract_id: str,
    authority_id: str,
    authority_keyring: Mapping[str, bytes | str],
    observation_keyring: Mapping[str, bytes | str],
    at,
) -> ProviderExecutableTargetProjection:
    """Authenticate invocation and signed target binding, then project inertly."""

    if type(target_authority) is not ProviderExecutableTargetAuthority:
        raise ProviderExecutableTargetBindingError(
            "target_authority must be exact ProviderExecutableTargetAuthority"
        )
    if type(manifest) is not ProviderExecutableTargetManifest:
        raise ProviderExecutableTargetBindingError(
            "manifest must be exact ProviderExecutableTargetManifest"
        )
    try:
        identity = project_provider_invocation_identity(
            authority,
            identity_registry,
            execution,
            authority_id=authority_id,
            authority_keyring=authority_keyring,
            observation_keyring=observation_keyring,
            at=at,
        )
    except ProviderInvocationIdentityError as exc:
        raise ProviderExecutableTargetBindingError(
            "provider invocation identity did not authenticate"
        ) from exc
    try:
        keys = dict(
            _normalize_keyring(
                authority_keyring,
                label="authority_keyring",
            )
        )
        contract = _identifier(target_contract_id, "target_contract_id")
    except (TypeError, ValueError) as exc:
        raise ProviderExecutableTargetBindingError(
            "provider executable target verification inputs are malformed"
        ) from exc
    secret = keys.get(target_authority.authority_key_id)
    if secret is None:
        raise ProviderExecutableTargetSignatureError(
            "provider executable target authority key is unknown"
        )
    signature = _signature(
        target_authority.signing_digest,
        secret,
        "authority_keyring secret",
    )
    if not hmac.compare_digest(target_authority.signature_sha256, signature):
        raise ProviderExecutableTargetSignatureError(
            "provider executable target authority signature mismatch"
        )
    early = {
        "authority_key_id": (
            target_authority.authority_key_id,
            authority.observation_authority.authority_key_id,
        ),
        "target_contract_id": (
            target_authority.target_contract_id,
            contract,
        ),
        "invocation_authority_sha256": (
            target_authority.invocation_authority_sha256,
            authority.digest,
        ),
        "invocation_contract_sha256": (
            target_authority.invocation_contract_sha256,
            authority.invocation_contract_sha256,
        ),
        "invocation_identity_sha256": (
            target_authority.invocation_identity_sha256,
            identity.digest,
        ),
        "identity_registry_sha256": (
            target_authority.identity_registry_sha256,
            identity.registry_sha256,
        ),
        "identity_descriptor_sha256": (
            target_authority.identity_descriptor_sha256,
            identity.descriptor_sha256,
        ),
        "target_manifest_sha256": (
            target_authority.target_manifest_sha256,
            manifest.digest,
        ),
        "provider_id": (target_authority.provider_id, identity.provider_id),
        "adapter_id": (target_authority.adapter_id, identity.adapter_id),
        "implementation_id": (
            target_authority.implementation_id,
            identity.implementation_id,
        ),
        "entrypoint_id": (
            target_authority.entrypoint_id,
            identity.entrypoint_id,
        ),
        "runtime_id": (target_authority.runtime_id, identity.runtime_id),
        "execution_id": (
            target_authority.execution_id,
            identity.execution_id,
        ),
        "idempotency_key": (
            target_authority.idempotency_key,
            identity.idempotency_key,
        ),
        "lease_sha256": (
            target_authority.lease_sha256,
            identity.lease_sha256,
        ),
        "source_revision": (
            target_authority.source_revision,
            identity.source_revision,
        ),
    }
    early_mismatches = tuple(
        sorted(
            field
            for field, (actual, required) in early.items()
            if actual != required
        )
    )
    if early_mismatches:
        raise ProviderExecutableTargetBindingError(
            "provider executable target authority binding mismatch before "
            "target lookup: " + ", ".join(early_mismatches)
        )
    if manifest.source_revision != identity.source_revision:
        raise ProviderExecutableTargetBindingError(
            "provider executable target source revision mismatch"
        )
    if manifest.identity_registry_sha256 != identity.registry_sha256:
        raise ProviderExecutableTargetBindingError(
            "provider executable target identity registry mismatch"
        )
    descriptor = manifest.descriptor_for_provider(identity.provider_id)
    descriptor_comparisons = {
        "target_descriptor_sha256": (
            target_authority.target_descriptor_sha256,
            descriptor.digest,
        ),
        "provider_id": (descriptor.provider_id, identity.provider_id),
        "adapter_id": (descriptor.adapter_id, identity.adapter_id),
        "implementation_id": (
            descriptor.implementation_id,
            identity.implementation_id,
        ),
        "entrypoint_id": (descriptor.entrypoint_id, identity.entrypoint_id),
        "runtime_id": (descriptor.runtime_id, identity.runtime_id),
        "source_revision": (
            descriptor.source_revision,
            identity.source_revision,
        ),
        "identity_descriptor_sha256": (
            descriptor.identity_descriptor_sha256,
            identity.descriptor_sha256,
        ),
        "adapter_artifact_sha256": (
            descriptor.adapter_artifact_sha256,
            identity.adapter_artifact_sha256,
        ),
        "adapter_config_sha256": (
            descriptor.adapter_config_sha256,
            identity.adapter_config_sha256,
        ),
    }
    mismatches = tuple(
        sorted(
            field
            for field, (registered, authenticated) in descriptor_comparisons.items()
            if registered != authenticated
        )
    )
    if mismatches:
        raise ProviderExecutableTargetBindingError(
            "provider executable target descriptor differs from authenticated "
            "authority or identity: " + ", ".join(mismatches)
        )
    return ProviderExecutableTargetProjection(
        provider_id=identity.provider_id,
        adapter_id=identity.adapter_id,
        implementation_id=identity.implementation_id,
        entrypoint_id=identity.entrypoint_id,
        runtime_id=identity.runtime_id,
        source_revision=identity.source_revision,
        identity_sha256=identity.digest,
        identity_registry_sha256=identity.registry_sha256,
        identity_descriptor_sha256=identity.descriptor_sha256,
        target_manifest_sha256=manifest.digest,
        target_descriptor_sha256=descriptor.digest,
        adapter_artifact_sha256=identity.adapter_artifact_sha256,
        adapter_config_sha256=identity.adapter_config_sha256,
        invoke_target=descriptor.invoke_target,
        invoke_source_sha256=descriptor.invoke_source_sha256,
        output_digests_target=descriptor.output_digests_target,
        output_digests_source_sha256=descriptor.output_digests_source_sha256,
    )


__all__ = [
    "ProviderExecutableTargetAuthority",
    "ProviderExecutableTargetBindingError",
    "ProviderExecutableTargetDescriptor",
    "ProviderExecutableTargetError",
    "ProviderExecutableTargetManifest",
    "ProviderExecutableTargetProjection",
    "ProviderExecutableTargetShapeError",
    "ProviderExecutableTargetSignatureError",
    "build_provider_executable_target_manifest",
    "issue_provider_executable_target_authority",
    "project_provider_executable_targets",
]
