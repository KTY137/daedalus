"""Non-executing exact target manifest for provider adapter implementations.

This module extends an authenticated provider-invocation identity with exact
repository target and source-digest metadata.  It deliberately does not import,
load, resolve, or execute either target.  A later guarded loader must prove the
named targets against exact repository bytes and consume the resulting receipt
inside the runtime broker.
"""
from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

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
from daedalus.schemas import _identifier, _revision, _sha256
from daedalus.spine.envelope import canonical_sha


_TARGET_RE = re.compile(
    r"^daedalus(?:\.[a-z][a-z0-9_]*)*:"
    r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$"
)


class ProviderExecutableTargetError(RuntimeError):
    """Base class for provider executable-target manifest failures."""


class ProviderExecutableTargetShapeError(ProviderExecutableTargetError):
    """A descriptor, manifest, or projection is malformed."""


class ProviderExecutableTargetBindingError(ProviderExecutableTargetError):
    """An authenticated invocation identity does not match the manifest."""


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


def project_provider_executable_targets(
    authority: ProviderInvocationObservationAuthority,
    identity_registry: ProviderInvocationRegistryManifest,
    execution: EffectExecutionRequest,
    manifest: ProviderExecutableTargetManifest,
    *,
    authority_id: str,
    authority_keyring: Mapping[str, bytes | str],
    observation_keyring: Mapping[str, bytes | str],
    at,
) -> ProviderExecutableTargetProjection:
    """Authenticate the invocation, then join exact inert target metadata."""

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
    "ProviderExecutableTargetBindingError",
    "ProviderExecutableTargetDescriptor",
    "ProviderExecutableTargetError",
    "ProviderExecutableTargetManifest",
    "ProviderExecutableTargetProjection",
    "ProviderExecutableTargetShapeError",
    "build_provider_executable_target_manifest",
    "project_provider_executable_targets",
]
