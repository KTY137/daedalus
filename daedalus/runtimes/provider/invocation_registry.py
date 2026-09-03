"""Immutable non-executing provider invocation registry manifest.

A registry manifest gives one provider ID exactly one adapter identity,
implementation identity, artifact digest, configuration digest, runtime
entrypoint and source revision.  It can resolve only an exact
``ProviderInvocationSubject`` and exposes no callback or dynamic loader.

The manifest digest is intended to be signed by
``ProviderInvocationObservationAuthority`` and later consumed by a separately
guarded executable registry.  This module does not execute providers, import
adapter artifacts, start effects, persist state, recover, promote, or close a
Gate.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from daedalus.kernel.contracts.base import _identifier, _revision, _sha256
from daedalus.runtimes.provider.invocation import ProviderInvocationSubject
from daedalus.spine.envelope import canonical_sha


class ProviderInvocationRegistryError(RuntimeError):
    """Base class for exact provider invocation registry failures."""


class ProviderInvocationRegistryShapeError(ProviderInvocationRegistryError):
    """A manifest or descriptor is malformed or noncanonical."""


class ProviderInvocationRegistryResolutionError(ProviderInvocationRegistryError):
    """A subject does not resolve to its provider's exact descriptor."""


@dataclass(frozen=True, order=True)
class ProviderAdapterDescriptor:
    """Non-executing exact adapter and implementation identity."""

    provider_id: str
    adapter_id: str
    implementation_id: str
    adapter_artifact_sha256: str
    adapter_config_sha256: str
    entrypoint_id: str
    runtime_id: str
    source_revision: str

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
            for field in (
                "adapter_artifact_sha256",
                "adapter_config_sha256",
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
        except (TypeError, ValueError) as exc:
            raise ProviderInvocationRegistryShapeError(
                "provider adapter descriptor is malformed"
            ) from exc

    def to_dict(self) -> dict[str, str]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProviderAdapterDescriptor":
        expected = {
            "provider_id",
            "adapter_id",
            "implementation_id",
            "adapter_artifact_sha256",
            "adapter_config_sha256",
            "entrypoint_id",
            "runtime_id",
            "source_revision",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ProviderInvocationRegistryShapeError(
                "provider adapter descriptor fields are not exact"
            )
        try:
            return cls(**{field: payload[field] for field in expected})
        except ProviderInvocationRegistryError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProviderInvocationRegistryShapeError(
                "provider adapter descriptor is malformed"
            ) from exc

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())

    def mismatch_fields(
        self,
        subject: ProviderInvocationSubject,
    ) -> tuple[str, ...]:
        if type(subject) is not ProviderInvocationSubject:
            raise ProviderInvocationRegistryResolutionError(
                "subject must be exact ProviderInvocationSubject"
            )
        comparisons = {
            "provider_id": (self.provider_id, subject.provider_id),
            "adapter_id": (self.adapter_id, subject.adapter_id),
            "adapter_artifact_sha256": (
                self.adapter_artifact_sha256,
                subject.adapter_artifact_sha256,
            ),
            "adapter_config_sha256": (
                self.adapter_config_sha256,
                subject.adapter_config_sha256,
            ),
            "entrypoint_id": (self.entrypoint_id, subject.entrypoint_id),
            "runtime_id": (self.runtime_id, subject.runtime_id),
            "source_revision": (
                self.source_revision,
                subject.source_revision,
            ),
        }
        return tuple(
            sorted(
                field
                for field, (registered, requested) in comparisons.items()
                if registered != requested
            )
        )


@dataclass(frozen=True)
class ProviderInvocationRegistryManifest:
    """Canonical one-provider-to-one-implementation registry manifest."""

    registry_id: str
    source_revision: str
    descriptors: tuple[ProviderAdapterDescriptor, ...]

    def __post_init__(self) -> None:
        try:
            object.__setattr__(
                self,
                "registry_id",
                _identifier(self.registry_id, "registry_id"),
            )
            object.__setattr__(
                self,
                "source_revision",
                _revision(self.source_revision, "source_revision"),
            )
        except (TypeError, ValueError) as exc:
            raise ProviderInvocationRegistryShapeError(
                "provider invocation registry identity is malformed"
            ) from exc
        if type(self.descriptors) is not tuple or not self.descriptors:
            raise ProviderInvocationRegistryShapeError(
                "registry descriptors must be a non-empty exact tuple"
            )
        if any(type(item) is not ProviderAdapterDescriptor for item in self.descriptors):
            raise ProviderInvocationRegistryShapeError(
                "registry descriptors must contain exact descriptor values"
            )
        if self.descriptors != tuple(
            sorted(self.descriptors, key=lambda item: item.provider_id)
        ):
            raise ProviderInvocationRegistryShapeError(
                "registry descriptors must be ordered by provider_id"
            )
        provider_ids = tuple(item.provider_id for item in self.descriptors)
        if len(set(provider_ids)) != len(provider_ids):
            raise ProviderInvocationRegistryShapeError(
                "registry provider IDs must be unique"
            )
        stale = tuple(
            item.provider_id
            for item in self.descriptors
            if item.source_revision != self.source_revision
        )
        if stale:
            raise ProviderInvocationRegistryShapeError(
                "registry descriptor source revision mismatch: "
                + ", ".join(stale)
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "daedalus-provider-invocation-registry/1",
            "registry_id": self.registry_id,
            "source_revision": self.source_revision,
            "descriptors": [item.to_dict() for item in self.descriptors],
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "ProviderInvocationRegistryManifest":
        expected = {
            "schema",
            "registry_id",
            "source_revision",
            "descriptors",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ProviderInvocationRegistryShapeError(
                "provider invocation registry fields are not exact"
            )
        if payload["schema"] != "daedalus-provider-invocation-registry/1":
            raise ProviderInvocationRegistryShapeError(
                "provider invocation registry schema does not match"
            )
        descriptors = payload["descriptors"]
        if not isinstance(descriptors, list):
            raise ProviderInvocationRegistryShapeError(
                "provider invocation registry descriptors must be a list"
            )
        try:
            return cls(
                registry_id=payload["registry_id"],
                source_revision=payload["source_revision"],
                descriptors=tuple(
                    ProviderAdapterDescriptor.from_dict(item)
                    for item in descriptors
                ),
            )
        except ProviderInvocationRegistryError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProviderInvocationRegistryShapeError(
                "provider invocation registry is malformed"
            ) from exc

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())

    def descriptor_for_provider(self, provider_id: str) -> ProviderAdapterDescriptor:
        try:
            expected_provider = _identifier(provider_id, "provider_id")
        except (TypeError, ValueError) as exc:
            raise ProviderInvocationRegistryResolutionError(
                "provider lookup identity is malformed"
            ) from exc
        matches = tuple(
            item for item in self.descriptors if item.provider_id == expected_provider
        )
        if len(matches) != 1:
            raise ProviderInvocationRegistryResolutionError(
                "provider is not registered exactly once"
            )
        return matches[0]

    def resolve(
        self,
        subject: ProviderInvocationSubject,
    ) -> ProviderAdapterDescriptor:
        if type(subject) is not ProviderInvocationSubject:
            raise ProviderInvocationRegistryResolutionError(
                "subject must be exact ProviderInvocationSubject"
            )
        descriptor = self.descriptor_for_provider(subject.provider_id)
        mismatches = descriptor.mismatch_fields(subject)
        if mismatches:
            raise ProviderInvocationRegistryResolutionError(
                "provider invocation subject differs from registry descriptor: "
                + ", ".join(mismatches)
            )
        return descriptor


def build_provider_invocation_registry_manifest(
    *,
    registry_id: str,
    source_revision: str,
    descriptors: Iterable[ProviderAdapterDescriptor],
) -> ProviderInvocationRegistryManifest:
    """Build the canonical ordering without weakening exact manifest parsing."""

    if isinstance(descriptors, (str, bytes, Mapping)):
        raise ProviderInvocationRegistryShapeError(
            "descriptors must be an iterable of exact descriptor values"
        )
    try:
        rows = tuple(descriptors)
    except (TypeError, RuntimeError) as exc:
        raise ProviderInvocationRegistryShapeError(
            "descriptors could not be materialized"
        ) from exc
    if any(type(item) is not ProviderAdapterDescriptor for item in rows):
        raise ProviderInvocationRegistryShapeError(
            "descriptors must contain exact ProviderAdapterDescriptor values"
        )
    return ProviderInvocationRegistryManifest(
        registry_id=registry_id,
        source_revision=source_revision,
        descriptors=tuple(sorted(rows, key=lambda item: item.provider_id)),
    )


__all__ = [
    "ProviderAdapterDescriptor",
    "ProviderInvocationRegistryError",
    "ProviderInvocationRegistryManifest",
    "ProviderInvocationRegistryResolutionError",
    "ProviderInvocationRegistryShapeError",
    "build_provider_invocation_registry_manifest",
]
