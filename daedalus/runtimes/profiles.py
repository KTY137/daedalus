# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Strict, pure runtime-profile and conformance-envelope contracts for Gate 0.

Offline fixtures prove only the provider-neutral Daedalus protocol. They are
labelled ``offline-fixture`` and are refused by the default verifier; live
production evidence additionally needs an externally trusted exact envelope.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, ClassVar, Mapping, Sequence

from daedalus.kernel.runtime_conformance import (
    RuntimeConformanceError,
    verify_current_conformance,
)
from daedalus.schemas import (
    CanonicalContract,
    ContractProvenance,
    RuntimeCapabilities,
    RuntimeConformanceReceipt,
    RuntimeManifest,
    _identifier,
    _non_empty,
    _require_provenance_inputs,
    _revision,
    _sha256,
    _sorted_strings,
    _utc_timestamp,
)
from daedalus.spine.envelope import canonical_sha

RUNTIME_PROFILE_SCHEMA = "daedalus-runtime-profile-catalog/1"
REQUIRED_GATE0_RUNTIME_IDS = ("claude_code_cli", "codex_cli", "ollama_http")
_AUTHORITIES = frozenset({"offline-fixture", "live-runtime"})
_PROFILE_FIELDS = frozenset(
    {
        "runtime_id",
        "adapter_id",
        "adapter_module",
        "command",
        "mode",
        "declared_tools",
        "egress_transports",
        "workspace_modes",
        "cost_model",
        "capabilities",
    }
)
_CAPABILITY_FIELDS = frozenset(
    {
        "streaming",
        "tool_events",
        "structured_output",
        "timeout",
        "cancellation",
        "workspace_isolation",
        "cost_reporting",
        "workspace_write",
    }
)


def _strict_json(raw: str) -> Mapping[str, Any]:
    def object_from_pairs(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    value = json.loads(raw, object_pairs_hook=object_from_pairs)
    if not isinstance(value, Mapping):
        raise ValueError("runtime profile catalog must be a JSON object")
    return value


def _exact_fields(
    payload: Mapping[str, Any], expected: frozenset[str], label: str
) -> None:
    missing = sorted(expected - set(payload))
    unknown = sorted(set(payload) - expected)
    if missing or unknown:
        raise ValueError(
            f"{label} fields differ (missing={missing}, unknown={unknown})"
        )


@dataclass(frozen=True)
class RuntimeProfile:
    """Checked-in adapter metadata; never observational evidence."""

    runtime_id: str
    adapter_id: str
    adapter_module: str
    command: str
    mode: str
    declared_tools: tuple[str, ...]
    egress_transports: tuple[str, ...]
    workspace_modes: tuple[str, ...]
    cost_model: str
    capabilities: RuntimeCapabilities

    def __post_init__(self) -> None:
        object.__setattr__(self, "runtime_id", _identifier(self.runtime_id, "runtime_id"))
        object.__setattr__(self, "adapter_id", _identifier(self.adapter_id, "adapter_id"))
        object.__setattr__(
            self, "adapter_module", _identifier(self.adapter_module, "adapter_module")
        )
        object.__setattr__(
            self, "command", _non_empty(self.command, "command", max_length=300)
        )
        if self.mode not in {"cli", "local-http"}:
            raise ValueError("runtime profile mode must be cli or local-http")
        for field_name in ("declared_tools", "egress_transports", "workspace_modes"):
            object.__setattr__(
                self,
                field_name,
                _sorted_strings(
                    getattr(self, field_name), field_name, identifiers=True
                ),
            )
        object.__setattr__(
            self, "cost_model", _non_empty(self.cost_model, "cost_model", max_length=200)
        )
        RuntimeManifest(
            runtime_id=self.runtime_id,
            runtime_version="profile-validation",
            adapter_id=self.adapter_id,
            adapter_version="profile-validation",
            source_revision="0" * 40,
            assurance="declared",
            capabilities=self.capabilities,
            declared_tools=self.declared_tools,
            egress_transports=self.egress_transports,
            workspace_modes=self.workspace_modes,
            cost_model=self.cost_model,
            provenance=ContractProvenance(
                origin="runtimes.profile-validation",
                source_revision="0" * 40,
                created_at="2000-01-01T00:00:00+00:00",
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "runtime_id": self.runtime_id,
            "adapter_id": self.adapter_id,
            "adapter_module": self.adapter_module,
            "command": self.command,
            "mode": self.mode,
            "declared_tools": list(self.declared_tools),
            "egress_transports": list(self.egress_transports),
            "workspace_modes": list(self.workspace_modes),
            "cost_model": self.cost_model,
            "capabilities": {
                name: getattr(self.capabilities, name)
                for name in sorted(_CAPABILITY_FIELDS)
            },
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RuntimeProfile":
        if not isinstance(payload, Mapping):
            raise ValueError("runtime profile must be an object")
        _exact_fields(payload, _PROFILE_FIELDS, "runtime profile")
        capabilities = payload["capabilities"]
        if not isinstance(capabilities, Mapping):
            raise ValueError("runtime profile capabilities must be an object")
        _exact_fields(capabilities, _CAPABILITY_FIELDS, "runtime capability")
        return cls(
            runtime_id=payload["runtime_id"],
            adapter_id=payload["adapter_id"],
            adapter_module=payload["adapter_module"],
            command=payload["command"],
            mode=payload["mode"],
            declared_tools=payload["declared_tools"],
            egress_transports=payload["egress_transports"],
            workspace_modes=payload["workspace_modes"],
            cost_model=payload["cost_model"],
            capabilities=RuntimeCapabilities(**dict(capabilities)),
        )


def load_runtime_profiles(
    path: str | Path,
    *,
    required_runtime_ids: Sequence[str] = REQUIRED_GATE0_RUNTIME_IDS,
) -> Mapping[str, RuntimeProfile]:
    payload = _strict_json(Path(path).read_text(encoding="utf-8"))
    _exact_fields(payload, frozenset({"schema", "profiles"}), "runtime catalog")
    if payload["schema"] != RUNTIME_PROFILE_SCHEMA:
        raise ValueError(f"runtime catalog schema must be {RUNTIME_PROFILE_SCHEMA!r}")
    rows = payload["profiles"]
    if not isinstance(rows, list) or not rows:
        raise ValueError("runtime catalog profiles must be a non-empty array")
    profiles = [RuntimeProfile.from_dict(row) for row in rows]
    by_id = {profile.runtime_id: profile for profile in profiles}
    if len(by_id) != len(profiles):
        raise ValueError("runtime catalog contains duplicate runtime_id values")
    required = {
        _identifier(value, "required_runtime_id") for value in required_runtime_ids
    }
    missing = sorted(required - set(by_id))
    extra = sorted(set(by_id) - required)
    if missing or extra:
        raise ValueError(
            f"runtime catalog membership differs (missing={missing}, extra={extra})"
        )
    return MappingProxyType({key: by_id[key] for key in sorted(by_id)})


def materialize_runtime_manifest(
    profile: RuntimeProfile,
    *,
    runtime_version: str,
    adapter_version: str,
    source_revision: str,
    adapter_sha256: str,
    executable_sha256: str,
    environment_sha256: str,
    fixture_suite_sha256: str,
    created_at: str,
) -> RuntimeManifest:
    revision = _revision(source_revision, "source_revision")
    inputs = (
        profile.digest,
        _sha256(adapter_sha256, "adapter_sha256"),
        _sha256(executable_sha256, "executable_sha256"),
        _sha256(environment_sha256, "environment_sha256"),
        _sha256(fixture_suite_sha256, "fixture_suite_sha256"),
    )
    return RuntimeManifest(
        runtime_id=profile.runtime_id,
        runtime_version=runtime_version,
        adapter_id=profile.adapter_id,
        adapter_version=adapter_version,
        source_revision=revision,
        assurance="declared",
        capabilities=profile.capabilities,
        declared_tools=profile.declared_tools,
        egress_transports=profile.egress_transports,
        workspace_modes=profile.workspace_modes,
        cost_model=profile.cost_model,
        provenance=ContractProvenance(
            origin="runtimes.materialized-manifest",
            source_revision=revision,
            created_at=created_at,
            input_digests=tuple(sorted(inputs)),
            trace_id=profile.runtime_id,
        ),
    )


@dataclass(frozen=True)
class RuntimeProbeIdentity(CanonicalContract):
    CONTRACT_TYPE: ClassVar[str] = "daedalus.runtime-probe-identity"

    probe_id: str
    runtime_id: str
    authority: str
    runtime_manifest_sha256: str
    profile_sha256: str
    adapter_sha256: str
    executable_sha256: str
    environment_sha256: str
    fixture_suite_sha256: str
    source_revision: str
    collected_at: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "probe_id", _identifier(self.probe_id, "probe_id"))
        object.__setattr__(self, "runtime_id", _identifier(self.runtime_id, "runtime_id"))
        if self.authority not in _AUTHORITIES:
            raise ValueError("probe authority must be offline-fixture or live-runtime")
        for name in (
            "runtime_manifest_sha256",
            "profile_sha256",
            "adapter_sha256",
            "executable_sha256",
            "environment_sha256",
            "fixture_suite_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(
            self, "source_revision", _revision(self.source_revision, "source_revision")
        )
        object.__setattr__(
            self, "collected_at", _utc_timestamp(self.collected_at, "collected_at")
        )
        if self.provenance.source_revision != self.source_revision:
            raise ValueError("probe source revision contradicts provenance")
        if self.provenance.created_at != self.collected_at:
            raise ValueError("probe collected_at contradicts provenance.created_at")
        _require_provenance_inputs(
            self.provenance,
            (
                self.runtime_manifest_sha256,
                self.profile_sha256,
                self.adapter_sha256,
                self.executable_sha256,
                self.environment_sha256,
                self.fixture_suite_sha256,
            ),
            "runtime probe identity",
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RuntimeProbeIdentity":
        body = cls._contract_payload(payload)
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


def _probe_component_inputs(
    profile_sha256: str,
    adapter_sha256: str,
    executable_sha256: str,
    environment_sha256: str,
    fixture_suite_sha256: str,
) -> tuple[str, ...]:
    return (
        _sha256(profile_sha256, "profile_sha256"),
        _sha256(adapter_sha256, "adapter_sha256"),
        _sha256(executable_sha256, "executable_sha256"),
        _sha256(environment_sha256, "environment_sha256"),
        _sha256(fixture_suite_sha256, "fixture_suite_sha256"),
    )


def build_probe_identity(
    profile: RuntimeProfile,
    manifest: RuntimeManifest,
    *,
    probe_id: str,
    authority: str,
    adapter_sha256: str,
    executable_sha256: str,
    environment_sha256: str,
    fixture_suite_sha256: str,
    collected_at: str,
) -> RuntimeProbeIdentity:
    if (manifest.runtime_id, manifest.adapter_id) != (
        profile.runtime_id,
        profile.adapter_id,
    ):
        raise ValueError("runtime manifest belongs to another profile or adapter")
    components = _probe_component_inputs(
        profile.digest,
        adapter_sha256,
        executable_sha256,
        environment_sha256,
        fixture_suite_sha256,
    )
    missing = sorted(set(components) - set(manifest.provenance.input_digests))
    if missing:
        raise ValueError(
            "runtime manifest provenance does not bind probe component digest(s): "
            + ", ".join(missing)
        )
    return RuntimeProbeIdentity(
        probe_id=probe_id,
        runtime_id=profile.runtime_id,
        authority=authority,
        runtime_manifest_sha256=manifest.digest,
        profile_sha256=profile.digest,
        adapter_sha256=adapter_sha256,
        executable_sha256=executable_sha256,
        environment_sha256=environment_sha256,
        fixture_suite_sha256=fixture_suite_sha256,
        source_revision=manifest.source_revision,
        collected_at=collected_at,
        provenance=ContractProvenance(
            origin="runtimes.probe-identity",
            source_revision=manifest.source_revision,
            created_at=collected_at,
            input_digests=tuple(sorted((manifest.digest, *components))),
            trace_id=probe_id,
        ),
    )


@dataclass(frozen=True)
class RuntimeConformanceEnvelope(CanonicalContract):
    CONTRACT_TYPE: ClassVar[str] = "daedalus.runtime-conformance-envelope"

    envelope_id: str
    runtime_id: str
    authority: str
    status: str
    runtime_manifest_sha256: str
    probe_identity_sha256: str
    conformance_receipt_sha256: str
    source_revision: str
    created_at: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "envelope_id", _identifier(self.envelope_id, "envelope_id")
        )
        object.__setattr__(self, "runtime_id", _identifier(self.runtime_id, "runtime_id"))
        if self.authority not in _AUTHORITIES:
            raise ValueError("envelope authority must be offline-fixture or live-runtime")
        if self.status not in {"passed", "failed"}:
            raise ValueError("envelope status must be passed or failed")
        for name in (
            "runtime_manifest_sha256",
            "probe_identity_sha256",
            "conformance_receipt_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(
            self, "source_revision", _revision(self.source_revision, "source_revision")
        )
        object.__setattr__(
            self, "created_at", _utc_timestamp(self.created_at, "created_at")
        )
        if self.provenance.source_revision != self.source_revision:
            raise ValueError("envelope source revision contradicts provenance")
        if self.provenance.created_at != self.created_at:
            raise ValueError("envelope created_at contradicts provenance.created_at")
        _require_provenance_inputs(
            self.provenance,
            (
                self.runtime_manifest_sha256,
                self.probe_identity_sha256,
                self.conformance_receipt_sha256,
            ),
            "runtime conformance envelope",
        )

    @property
    def production_eligible(self) -> bool:
        return self.authority == "live-runtime" and self.status == "passed"

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any]
    ) -> "RuntimeConformanceEnvelope":
        body = cls._contract_payload(payload)
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


def _verify_manifest_probe_inputs(
    manifest: RuntimeManifest, identity: RuntimeProbeIdentity
) -> None:
    required = set(
        _probe_component_inputs(
            identity.profile_sha256,
            identity.adapter_sha256,
            identity.executable_sha256,
            identity.environment_sha256,
            identity.fixture_suite_sha256,
        )
    )
    missing = sorted(required - set(manifest.provenance.input_digests))
    if missing:
        raise RuntimeConformanceError(
            "runtime manifest provenance does not bind probe component digest(s): "
            + ", ".join(missing)
        )


def bind_conformance_envelope(
    manifest: RuntimeManifest,
    identity: RuntimeProbeIdentity,
    receipt: RuntimeConformanceReceipt,
    *,
    envelope_id: str,
    created_at: str,
) -> RuntimeConformanceEnvelope:
    if identity.runtime_id != manifest.runtime_id:
        raise RuntimeConformanceError("probe identity belongs to another runtime")
    if identity.runtime_manifest_sha256 != manifest.digest:
        raise RuntimeConformanceError("probe identity binds another runtime manifest")
    if identity.source_revision != manifest.source_revision:
        raise RuntimeConformanceError("probe identity binds another source revision")
    _verify_manifest_probe_inputs(manifest, identity)
    if receipt.runtime_manifest_sha256 != manifest.digest:
        raise RuntimeConformanceError("conformance receipt binds another manifest")
    if receipt.source_revision != manifest.source_revision:
        raise RuntimeConformanceError("conformance receipt binds another source revision")
    if identity.digest not in receipt.provenance.input_digests:
        raise RuntimeConformanceError(
            "conformance receipt provenance does not bind the probe identity"
        )
    return RuntimeConformanceEnvelope(
        envelope_id=envelope_id,
        runtime_id=manifest.runtime_id,
        authority=identity.authority,
        status=receipt.status,
        runtime_manifest_sha256=manifest.digest,
        probe_identity_sha256=identity.digest,
        conformance_receipt_sha256=receipt.digest,
        source_revision=manifest.source_revision,
        created_at=created_at,
        provenance=ContractProvenance(
            origin="runtimes.conformance-envelope",
            source_revision=manifest.source_revision,
            created_at=created_at,
            input_digests=tuple(sorted({manifest.digest, identity.digest, receipt.digest})),
            trace_id=envelope_id,
        ),
    )


def verify_runtime_envelope(
    envelope: RuntimeConformanceEnvelope,
    identity: RuntimeProbeIdentity,
    receipt: RuntimeConformanceReceipt,
    manifest: RuntimeManifest,
    *,
    now,
    require_live: bool = True,
) -> None:
    comparisons = {
        "runtime_id": (envelope.runtime_id, manifest.runtime_id),
        "authority": (envelope.authority, identity.authority),
        "status": (envelope.status, receipt.status),
        "runtime_manifest_sha256": (envelope.runtime_manifest_sha256, manifest.digest),
        "probe_identity_sha256": (envelope.probe_identity_sha256, identity.digest),
        "conformance_receipt_sha256": (
            envelope.conformance_receipt_sha256,
            receipt.digest,
        ),
        "source_revision": (envelope.source_revision, manifest.source_revision),
        "identity_manifest": (identity.runtime_manifest_sha256, manifest.digest),
        "identity_runtime": (identity.runtime_id, manifest.runtime_id),
        "identity_revision": (identity.source_revision, manifest.source_revision),
    }
    mismatches = sorted(
        name for name, (actual, expected) in comparisons.items() if actual != expected
    )
    if mismatches:
        raise RuntimeConformanceError(
            "runtime conformance envelope binding mismatch: " + ", ".join(mismatches)
        )
    _verify_manifest_probe_inputs(manifest, identity)
    if identity.digest not in receipt.provenance.input_digests:
        raise RuntimeConformanceError(
            "runtime receipt does not retain the probe identity digest"
        )
    if require_live and not envelope.production_eligible:
        raise RuntimeConformanceError(
            "offline fixture evidence cannot authorize a production runtime lease"
        )
    verify_current_conformance(receipt, manifest, now=now)


__all__ = [
    "REQUIRED_GATE0_RUNTIME_IDS",
    "RUNTIME_PROFILE_SCHEMA",
    "RuntimeConformanceEnvelope",
    "RuntimeProbeIdentity",
    "RuntimeProfile",
    "bind_conformance_envelope",
    "build_probe_identity",
    "load_runtime_profiles",
    "materialize_runtime_manifest",
    "verify_runtime_envelope",
]
