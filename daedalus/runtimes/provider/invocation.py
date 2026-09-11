"""Canonical provider/adapter identity for one runtime effect subject.

This module is intentionally non-executing.  It defines the exact immutable
identity that a later broker packet must authenticate and bind before selecting
or invoking an external provider adapter.  A subject is not an Effect Lease, a
runtime capability, an observation authority, or permission to execute code.
"""
from __future__ import annotations

import dataclasses
import json
import hashlib
from dataclasses import dataclass
from typing import Any, Mapping

from daedalus.kernel.contracts.base import _identifier, _revision, _sha256


def _canonical_digest(value: Any) -> str:
    """Hash invocation identity bytes without a mutable cross-layer helper.

    Provider invocation subjects participate in the sealed runtime trust chain,
    so their identity must not depend on a replaceable helper imported from the
    broader spine layer.  Keep the byte recipe exactly aligned with the spine's
    canonical JSON contract while owning the tiny hashing primitive locally.
    """

    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


class ProviderInvocationSubjectError(ValueError):
    """The provider invocation identity is malformed or non-canonical."""


@dataclass(frozen=True)
class ProviderInvocationSubject:
    """Exact provider and adapter identity for one revision-bound execution.

    ``adapter_artifact_sha256`` identifies the executable adapter artifact or
    source tree selected by the runtime. ``adapter_config_sha256`` identifies
    the canonical non-secret adapter configuration. The remaining fields bind
    that implementation identity to one exact effect request and lease.
    """

    provider_id: str
    adapter_id: str
    adapter_artifact_sha256: str
    adapter_config_sha256: str
    entrypoint_id: str
    runtime_id: str
    execution_id: str
    idempotency_key: str
    execution_request_sha256: str
    lease_sha256: str
    source_revision: str

    def __post_init__(self) -> None:
        try:
            for field_name in (
                "provider_id",
                "adapter_id",
                "entrypoint_id",
                "runtime_id",
                "execution_id",
                "idempotency_key",
            ):
                object.__setattr__(
                    self,
                    field_name,
                    _identifier(getattr(self, field_name), field_name),
                )
            for field_name in (
                "adapter_artifact_sha256",
                "adapter_config_sha256",
                "execution_request_sha256",
                "lease_sha256",
            ):
                object.__setattr__(
                    self,
                    field_name,
                    _sha256(getattr(self, field_name), field_name),
                )
            object.__setattr__(
                self,
                "source_revision",
                _revision(self.source_revision, "source_revision"),
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise ProviderInvocationSubjectError(
                "provider invocation subject is malformed"
            ) from exc

    def to_dict(self) -> dict[str, str]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProviderInvocationSubject":
        expected = {
            "provider_id",
            "adapter_id",
            "adapter_artifact_sha256",
            "adapter_config_sha256",
            "entrypoint_id",
            "runtime_id",
            "execution_id",
            "idempotency_key",
            "execution_request_sha256",
            "lease_sha256",
            "source_revision",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ProviderInvocationSubjectError(
                "provider invocation subject fields are not exact"
            )
        try:
            return cls(**dict(payload))
        except (TypeError, ValueError) as exc:
            if isinstance(exc, ProviderInvocationSubjectError):
                raise
            raise ProviderInvocationSubjectError(
                "provider invocation subject fields are malformed"
            ) from exc

    @property
    def digest(self) -> str:
        return _canonical_digest(self.to_dict())


__all__ = [
    "ProviderInvocationSubject",
    "ProviderInvocationSubjectError",
]
