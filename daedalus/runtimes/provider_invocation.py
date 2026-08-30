# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Canonical provider/adapter identity for one runtime effect subject.

This module is intentionally non-executing.  It defines the exact immutable
identity that a later broker packet must authenticate and bind before selecting
or invoking an external provider adapter.  A subject is not an Effect Lease, a
runtime capability, an observation authority, or permission to execute code.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, Mapping

from daedalus.schemas import _identifier, _revision, _sha256
from daedalus.spine.envelope import canonical_sha


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
        return canonical_sha(self.to_dict())


__all__ = [
    "ProviderInvocationSubject",
    "ProviderInvocationSubjectError",
]
