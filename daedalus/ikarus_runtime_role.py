# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Immutable runtime-role bindings for the Ikarus supervisor.

This is a dispatch port, not another runtime, effect, policy, trust, provider,
or tool registry.  It owns no process and performs no I/O.  A caller constructs
one local registry and hands the same structural bindings to planning and
dispatch.  The supervisor remains the harness and ``TaskAttempt`` remains the
only execution path.

Only ``fixture`` bindings are executable in work packet G1-IKARUS-02.  A real
runtime is represented as ``source-only`` until a later packet connects its
exact admitted manifest, effect lease, observation authority and executable
target through the canonical broker.  Treating declaration as authority would
be the bypass this module exists to prevent.

The shape is informed by the bounded upstream study recorded in
``docs/research/hermes-agent-v2026.8.19-provenance.json``.  No upstream code is
copied: in particular this registry is caller-local, immutable and rejects
collisions instead of providing a process-global mutable dispatch authority.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Iterable, Mapping


RUNTIME_ROLE_BINDING_SCHEMA = "daedalus-ikarus-runtime-role/1"
INPROCESS_RUNTIME_ID = "inprocess"
FIXTURE_EXECUTION_MODE = "fixture"
SOURCE_ONLY_EXECUTION_MODE = "source-only"

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
_EXECUTION_MODES = frozenset({FIXTURE_EXECUTION_MODE, SOURCE_ONLY_EXECUTION_MODE})


class RuntimeRoleRegistryError(ValueError):
    """A runtime-role descriptor or registry is ambiguous or malformed."""


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER_RE.fullmatch(value) is None:
        raise RuntimeRoleRegistryError(
            f"{name} must match {_IDENTIFIER_RE.pattern!r}"
        )
    return value


def _required_text(value: Any, name: str, *, max_length: int = 500) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeRoleRegistryError(f"{name} must be a non-empty string")
    if len(value) > max_length:
        raise RuntimeRoleRegistryError(f"{name} exceeds {max_length} characters")
    if "\x00" in value:
        raise RuntimeRoleRegistryError(f"{name} contains a NUL byte")
    return value


def _canonical(body: Mapping[str, Any]) -> str:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class RuntimeRoleBinding:
    """One structural ``(role, runtime_id)`` binding.

    The record is deliberately DATA ONLY. Executable factories remain on the
    pre-existing :class:`daedalus.ikarus_supervisor.RoleHarness` seam and are
    looked up by :attr:`harness_key`, which contains this binding's full
    digest. Exact executable bytes and a conformance receipt must join the
    canonical runtime authority before any non-fixture mode can be introduced.
    """

    role: str
    runtime_id: str
    adapter_id: str
    adapter_version: str
    source_revision: str
    origin: str
    execution_mode: str
    refusal_reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", _identifier(self.role, "role"))
        object.__setattr__(
            self, "runtime_id", _identifier(self.runtime_id, "runtime_id")
        )
        if self.runtime_id == INPROCESS_RUNTIME_ID:
            raise RuntimeRoleRegistryError(
                f"runtime_id {INPROCESS_RUNTIME_ID!r} is reserved for legacy "
                "in-process role harnesses"
            )
        object.__setattr__(self, "adapter_id", _identifier(self.adapter_id, "adapter_id"))
        object.__setattr__(
            self,
            "adapter_version",
            _required_text(self.adapter_version, "adapter_version", max_length=200),
        )
        object.__setattr__(
            self,
            "source_revision",
            _required_text(self.source_revision, "source_revision", max_length=200),
        )
        object.__setattr__(
            self, "origin", _required_text(self.origin, "origin", max_length=1000)
        )
        if (
            not isinstance(self.execution_mode, str)
            or self.execution_mode not in _EXECUTION_MODES
        ):
            raise RuntimeRoleRegistryError(
                "execution_mode must be one of " + ", ".join(sorted(_EXECUTION_MODES))
            )

        if self.execution_mode == FIXTURE_EXECUTION_MODE:
            if not self.runtime_id.startswith("fixture."):
                raise RuntimeRoleRegistryError(
                    "fixture runtime_id must use the synthetic 'fixture.' namespace"
                )
            if not self.adapter_id.startswith("fixture."):
                raise RuntimeRoleRegistryError(
                    "fixture adapter_id must use the synthetic 'fixture.' namespace"
                )
            if not self.origin.startswith("fixture://"):
                raise RuntimeRoleRegistryError(
                    "fixture origin must use the synthetic 'fixture://' scheme"
                )
            if not isinstance(self.refusal_reason, str) or self.refusal_reason != "":
                raise RuntimeRoleRegistryError(
                    "an executable fixture binding requires an empty string "
                    "refusal_reason"
                )
        else:
            object.__setattr__(
                self,
                "refusal_reason",
                _required_text(
                    self.refusal_reason, "refusal_reason", max_length=1000
                ),
            )

    @property
    def executable(self) -> bool:
        return self.execution_mode == FIXTURE_EXECUTION_MODE

    def subject(self) -> dict[str, str]:
        """Return the complete versioned subject; never include callables."""

        return {
            "schema": RUNTIME_ROLE_BINDING_SCHEMA,
            "role": self.role,
            "runtime_id": self.runtime_id,
            "adapter_id": self.adapter_id,
            "adapter_version": self.adapter_version,
            "source_revision": self.source_revision,
            "origin": self.origin,
            "execution_mode": self.execution_mode,
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical(self.subject()).encode("utf-8")).hexdigest()

    @property
    def harness_key(self) -> str:
        """Exact key for the existing RoleHarness mapping.

        A role-only key can never satisfy an explicit runtime selection, and a
        key for an older descriptor cannot satisfy a newer version.
        """

        return runtime_role_harness_key(
            self.role,
            self.runtime_id,
            self.digest,
        )


def runtime_role_harness_key(
    role: str,
    runtime_id: str,
    binding_sha256: str,
) -> str:
    """Derive the only RoleHarness key accepted for one binding digest."""

    role = _identifier(role, "role")
    runtime_id = _identifier(runtime_id, "runtime_id")
    if (
        not isinstance(binding_sha256, str)
        or len(binding_sha256) != 64
        or any(char not in "0123456789abcdef" for char in binding_sha256)
    ):
        raise RuntimeRoleRegistryError(
            "binding_sha256 must be lowercase SHA-256"
        )
    return f"runtime-role:{role}:{runtime_id}:{binding_sha256}"


@dataclass(frozen=True)
class RuntimeRoleSnapshot:
    """Primitive snapshot retained across a multi-item supervisor run.

    Python's ``frozen=True`` prevents normal reassignment but is not a security
    boundary. The supervisor therefore snapshots every descriptor before the
    first runner is invoked and never consults caller-owned binding objects
    between item dispatches.
    """

    schema: str
    role: str
    runtime_id: str
    adapter_id: str
    adapter_version: str
    source_revision: str
    origin: str
    execution_mode: str
    refusal_reason: str
    digest: str

    @classmethod
    def from_binding(cls, binding: RuntimeRoleBinding) -> "RuntimeRoleSnapshot":
        if type(binding) is not RuntimeRoleBinding:
            raise RuntimeRoleRegistryError(
                "runtime snapshot requires an exact RuntimeRoleBinding"
            )
        # Reconstruct to re-run validation. A caller can technically bypass a
        # frozen dataclass with object.__setattr__; such a mutation must become
        # a refusal, not a newly executable descriptor.
        validated = RuntimeRoleBinding(
            role=binding.role,
            runtime_id=binding.runtime_id,
            adapter_id=binding.adapter_id,
            adapter_version=binding.adapter_version,
            source_revision=binding.source_revision,
            origin=binding.origin,
            execution_mode=binding.execution_mode,
            refusal_reason=binding.refusal_reason,
        )
        subject = validated.subject()
        digest = hashlib.sha256(
            _canonical(subject).encode("utf-8")
        ).hexdigest()
        return cls(
            schema=str(subject["schema"]),
            role=str(subject["role"]),
            runtime_id=str(subject["runtime_id"]),
            adapter_id=str(subject["adapter_id"]),
            adapter_version=str(subject["adapter_version"]),
            source_revision=str(subject["source_revision"]),
            origin=str(subject["origin"]),
            execution_mode=str(subject["execution_mode"]),
            refusal_reason=str(validated.refusal_reason),
            digest=digest,
        )

    @property
    def executable(self) -> bool:
        return self.execution_mode == FIXTURE_EXECUTION_MODE

    @property
    def harness_key(self) -> str:
        return runtime_role_harness_key(
            self.role,
            self.runtime_id,
            self.digest,
        )


@dataclass(frozen=True)
class RuntimeRoleRegistry:
    """One immutable, duplicate-rejecting registry supplied by the caller."""

    bindings: tuple[RuntimeRoleSnapshot, ...]
    _by_key: Mapping[tuple[str, str], tuple[str, ...]] = field(
        init=False, repr=False, compare=False
    )

    def __init__(self, bindings: Iterable[RuntimeRoleBinding]) -> None:
        if isinstance(bindings, (str, bytes)):
            raise RuntimeRoleRegistryError("bindings must be descriptor objects")
        try:
            rows = tuple(bindings)
        except TypeError as exc:
            raise RuntimeRoleRegistryError("bindings must be iterable") from exc
        if any(type(row) is not RuntimeRoleBinding for row in rows):
            raise RuntimeRoleRegistryError(
                "every registry row must be an exact RuntimeRoleBinding"
            )
        snapshots: list[RuntimeRoleSnapshot] = []
        index: dict[tuple[str, str], tuple[str, ...]] = {}
        for row in rows:
            snapshot = RuntimeRoleSnapshot.from_binding(row)
            key = (snapshot.role, snapshot.runtime_id)
            if key in index:
                raise RuntimeRoleRegistryError(
                    "duplicate runtime-role binding for "
                    f"role={snapshot.role!r} runtime_id={snapshot.runtime_id!r}"
                )
            # Store immutable primitive tuples, never the caller's binding and
            # never even the public snapshot object. Resolution reconstructs a
            # fresh snapshot, so object.__setattr__ against either caller-owned
            # object cannot mutate registry truth after construction.
            index[key] = (
                snapshot.schema,
                snapshot.role,
                snapshot.runtime_id,
                snapshot.adapter_id,
                snapshot.adapter_version,
                snapshot.source_revision,
                snapshot.origin,
                snapshot.execution_mode,
                snapshot.refusal_reason,
                snapshot.digest,
            )
            snapshots.append(snapshot)
        object.__setattr__(self, "bindings", tuple(snapshots))
        object.__setattr__(self, "_by_key", MappingProxyType(index))

    @staticmethod
    def _from_record(record: tuple[str, ...]) -> RuntimeRoleSnapshot:
        try:
            (
                schema,
                role,
                runtime_id,
                adapter_id,
                adapter_version,
                source_revision,
                origin,
                execution_mode,
                refusal_reason,
                stored_digest,
            ) = record
        except (TypeError, ValueError) as exc:
            raise RuntimeRoleRegistryError(
                "runtime registry record is malformed"
            ) from exc
        if schema != RUNTIME_ROLE_BINDING_SCHEMA:
            raise RuntimeRoleRegistryError(
                "runtime registry record has an unknown schema"
            )
        validated = RuntimeRoleSnapshot.from_binding(
            RuntimeRoleBinding(
                role=role,
                runtime_id=runtime_id,
                adapter_id=adapter_id,
                adapter_version=adapter_version,
                source_revision=source_revision,
                origin=origin,
                execution_mode=execution_mode,
                refusal_reason=refusal_reason,
            )
        )
        if validated.digest != stored_digest:
            raise RuntimeRoleRegistryError(
                "runtime registry record digest does not match its subject"
            )
        return validated

    def find(self, role: str, runtime_id: str) -> RuntimeRoleSnapshot | None:
        """Resolve without fallback; an absent exact pair returns ``None``."""

        key = (str(role), str(runtime_id))
        record = self._by_key.get(key)
        if record is None:
            return None
        snapshot = self._from_record(record)
        if (snapshot.role, snapshot.runtime_id) != key:
            raise RuntimeRoleRegistryError(
                "runtime registry lookup key does not match its subject"
            )
        return snapshot

    def snapshot(self, role: str, runtime_id: str) -> RuntimeRoleSnapshot | None:
        """Return a primitive copy, or ``None`` without any fallback."""

        return self.find(role, runtime_id)

    def __len__(self) -> int:
        return len(self.bindings)


__all__ = [
    "FIXTURE_EXECUTION_MODE",
    "INPROCESS_RUNTIME_ID",
    "RUNTIME_ROLE_BINDING_SCHEMA",
    "SOURCE_ONLY_EXECUTION_MODE",
    "RuntimeRoleBinding",
    "RuntimeRoleRegistry",
    "RuntimeRoleRegistryError",
    "RuntimeRoleSnapshot",
    "runtime_role_harness_key",
]
