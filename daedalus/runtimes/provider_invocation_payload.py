# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Canonical, non-executing payload identity for one provider invocation.

Provider adapters need per-call data (prompt/objective, workspace, model options,
etc.) without smuggling that data through Python closures. This module turns
that data into a small deterministic value object bound to one exact
:class:`ProviderInvocationSubject`.

The value is deliberately *not* an execution authority. A later broker packet
must bind ``ProviderInvocationPayload.digest`` into the signed provider
invocation/observation authority before ``begin_effect`` and before an admitted
adapter may consume it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from daedalus.runtimes.provider_invocation import ProviderInvocationSubject
from daedalus.schemas import _identifier, _sha256
from daedalus.spine.envelope import canonical_sha


_SCHEMA = "daedalus-provider-invocation-payload/1"
_MAX_DEPTH = 8
_MAX_NODES = 2048
_MAX_STRING = 16_384
_MAX_KEY = 200
_MAX_CANONICAL_BYTES = 65_536
_INT_MIN = -(2**63)
_INT_MAX = 2**63 - 1


class ProviderInvocationPayloadError(ValueError):
    """A provider invocation payload is malformed or non-canonical."""


def _normalize_json_value(
    value: Any,
    *,
    depth: int,
    nodes: list[int],
    path: str,
) -> Any:
    if depth > _MAX_DEPTH:
        raise ProviderInvocationPayloadError(
            "provider invocation payload exceeds depth limit"
        )
    nodes[0] += 1
    if nodes[0] > _MAX_NODES:
        raise ProviderInvocationPayloadError(
            "provider invocation payload exceeds node limit"
        )

    if value is None or type(value) is bool:
        return value
    if type(value) is int:
        if value < _INT_MIN or value > _INT_MAX:
            raise ProviderInvocationPayloadError(
                f"provider invocation payload integer at {path} exceeds int64"
            )
        return value
    if type(value) is str:
        if len(value) > _MAX_STRING:
            raise ProviderInvocationPayloadError(
                f"provider invocation payload string at {path} is too long"
            )
        if "\x00" in value:
            raise ProviderInvocationPayloadError(
                f"provider invocation payload string at {path} contains NUL"
            )
        return value
    if type(value) is list:
        return [
            _normalize_json_value(
                item,
                depth=depth + 1,
                nodes=nodes,
                path=f"{path}[{index}]",
            )
            for index, item in enumerate(value)
        ]
    if type(value) is dict:
        keys = tuple(value.keys())
        if any(
            type(key) is not str
            or not key
            or len(key) > _MAX_KEY
            or "\x00" in key
            for key in keys
        ):
            raise ProviderInvocationPayloadError(
                f"provider invocation payload object key at {path} is invalid"
            )
        normalized: dict[str, Any] = {}
        for key in sorted(keys):
            normalized[key] = _normalize_json_value(
                value[key],
                depth=depth + 1,
                nodes=nodes,
                path=f"{path}.{key}",
            )
        return normalized
    raise ProviderInvocationPayloadError(
        f"provider invocation payload value at {path} uses unsupported type"
    )


def _freeze(value: Any) -> Any:
    if type(value) is dict:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if type(value) is MappingProxyType:
        return {key: _thaw(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_thaw(item) for item in value]
    return value


def _canonical_body(body: Any) -> Mapping[str, Any]:
    if type(body) is not dict:
        raise ProviderInvocationPayloadError(
            "provider invocation payload body must be an exact dict"
        )
    normalized = _normalize_json_value(body, depth=0, nodes=[0], path="$body")
    if type(normalized) is not dict:
        raise ProviderInvocationPayloadError(
            "provider invocation payload body is malformed"
        )
    encoded = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    if len(encoded) > _MAX_CANONICAL_BYTES:
        raise ProviderInvocationPayloadError(
            "provider invocation payload exceeds canonical byte limit"
        )
    return _freeze(normalized)


@dataclass(frozen=True)
class ProviderInvocationPayload:
    """Canonical per-call data bound to one exact invocation subject digest."""

    provider_id: str
    adapter_id: str
    payload_schema_id: str
    invocation_subject_sha256: str
    body: Mapping[str, Any]

    def __post_init__(self) -> None:
        try:
            object.__setattr__(
                self,
                "provider_id",
                _identifier(self.provider_id, "provider_id"),
            )
            object.__setattr__(
                self,
                "adapter_id",
                _identifier(self.adapter_id, "adapter_id"),
            )
            object.__setattr__(
                self,
                "payload_schema_id",
                _identifier(self.payload_schema_id, "payload_schema_id"),
            )
            object.__setattr__(
                self,
                "invocation_subject_sha256",
                _sha256(
                    self.invocation_subject_sha256,
                    "invocation_subject_sha256",
                ),
            )
            object.__setattr__(self, "body", _canonical_body(self.body))
        except ProviderInvocationPayloadError:
            raise
        except (AttributeError, TypeError, ValueError) as exc:
            raise ProviderInvocationPayloadError(
                "provider invocation payload identity is malformed"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": _SCHEMA,
            "provider_id": self.provider_id,
            "adapter_id": self.adapter_id,
            "payload_schema_id": self.payload_schema_id,
            "invocation_subject_sha256": self.invocation_subject_sha256,
            "body": _thaw(self.body),
            "provider_execution_allowed": False,
            "effect_start_authorized": False,
            "callback_seam_removed": False,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProviderInvocationPayload":
        expected = {
            "schema",
            "provider_id",
            "adapter_id",
            "payload_schema_id",
            "invocation_subject_sha256",
            "body",
            "provider_execution_allowed",
            "effect_start_authorized",
            "callback_seam_removed",
        }
        if type(payload) is not dict or set(payload) != expected:
            raise ProviderInvocationPayloadError(
                "provider invocation payload fields are not exact"
            )
        if payload["schema"] != _SCHEMA:
            raise ProviderInvocationPayloadError(
                "provider invocation payload schema does not match"
            )
        for claim in (
            "provider_execution_allowed",
            "effect_start_authorized",
            "callback_seam_removed",
        ):
            if payload[claim] is not False:
                raise ProviderInvocationPayloadError(
                    f"provider invocation payload escalated claim: {claim}"
                )
        try:
            value = cls(
                provider_id=payload["provider_id"],
                adapter_id=payload["adapter_id"],
                payload_schema_id=payload["payload_schema_id"],
                invocation_subject_sha256=payload["invocation_subject_sha256"],
                body=payload["body"],
            )
        except ProviderInvocationPayloadError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProviderInvocationPayloadError(
                "provider invocation payload is malformed"
            ) from exc
        if value.to_dict() != payload:
            raise ProviderInvocationPayloadError(
                "provider invocation payload changed during canonical reconstruction"
            )
        return value

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def build_provider_invocation_payload(
    invocation_subject: ProviderInvocationSubject,
    *,
    payload_schema_id: str,
    body: dict[str, Any],
) -> ProviderInvocationPayload:
    """Bind canonical per-call data to an exact non-executing provider subject."""

    if type(invocation_subject) is not ProviderInvocationSubject:
        raise ProviderInvocationPayloadError(
            "invocation_subject must be exact ProviderInvocationSubject"
        )
    return ProviderInvocationPayload(
        provider_id=invocation_subject.provider_id,
        adapter_id=invocation_subject.adapter_id,
        payload_schema_id=payload_schema_id,
        invocation_subject_sha256=invocation_subject.digest,
        body=body,
    )


__all__ = [
    "ProviderInvocationPayload",
    "ProviderInvocationPayloadError",
    "build_provider_invocation_payload",
]
