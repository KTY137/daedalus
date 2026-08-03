"""Strict Gate-0 runtime profiles and conformance-evidence bindings.

This module is intentionally pure. It does not launch a vendor runtime, read
secrets, write evidence, or issue an Effect Lease. The existing
``daedalus.kernel.runtime_conformance`` harness remains the authority that
assembles content-addressed observations. This layer adds two missing pieces:

* versioned, strict profiles for each production runtime adapter; and
* an envelope that distinguishes deterministic offline contract fixtures from
  live runtime evidence that may authorize a production lease.

An offline fixture can prove that Daedalus' provider-neutral observation
protocol is internally coherent. It cannot prove that Claude, Codex, or Ollama
currently conforms, and ``verify_runtime_envelope`` refuses it by default.
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
REQUIRED_GATE0_RUNTIME_IDS = (
    "claude_code_cli",
    "codex_cli",
    "ollama_http",
)
_PROBE_AUTHORITIES = frozenset({"offline-fixture", "live-runtime"})
_PROFILE_KEYS = frozenset(
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
_CAPABILITY_KEYS = frozenset(
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


def _strict_json_object(raw: str) -> Mapping[str, Any]:
    def reject_duplicates(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, nested in pairs:
            if key in value:
                raise ValueError(f"duplicate JSON key {key!r}")
            value[key] = nested
        return value

    parsed = json.loads(raw, object_pairs_hook=reject_duplicates)
    if not isinstance(parsed, Mapping):
        raise ValueError("runtime profile catalog must be a JSON object")
    return parsed


@dataclass(frozen=True)
class RuntimeProfile:
    """A checked-in adapter profile, not runtime-conformance evidence."""

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
            self,
            "adapter_module",
            _identifier(self.adapter_module, "adapter_module"),
        )
        object.__setattr__(
            self, "command", _non_empty(self.command, "command", max_length=300)
        )
        if self.mode not in {"cli", "local-http"}:
            raise ValueError("runtime profile mode must be cli or local-http")
        object.__setattr__(
            self,
            "declared_tools",
            _sorted_strings(
                self.declared_tools, "declared_tools", identifiers=True
            ),
        )
        object.__setattr__(
            self,
            "egress_transports",
            _sorted_strings(
                self.egress_transports, "egress_transports", identifiers=True
            ),
        )
        object.__setattr__(
            self,
            "workspace_modes",
            _sorted_strings(
                self.workspace_modes, "workspace_modes", identifiers=True
            ),
        )
        object.__setattr__(
            self,
            "cost_model",
            _non_empty(self.cost_model, "cost_model", max_length=200),
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
                input_digests=(),
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
                for name in sorted(_CAPABILITY_KEYS)
            },
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RuntimeProfile":
        if not isinstance(payload, Mapping):
            raise ValueError("runtime profile must be an object")
        unknown = sorted(set(payload) - _PROFILE_KEYS)
        missing = sorted(_PROFILE_KEYS - set(payload))
        if unknown or missing:
            raise ValueError(
                f"runtime profile fields differ (missing={missing}, unknown={unknown})"
            )
        capabilities = payload["capabilities"]
        if not isinstance(capabilities, Mapping):
            raise ValueError("runtime profile capabilities must be an object")
        cap_unknown = sorted(set(capabilities) - _CAPABILITY_KEYS)
        cap_missing = sorted(_CAPABILITY_KEYS - set(capabilities))
        if cap_unknown or cap_missing:
            raise ValueError(
                "runtime profile capability fields differ "
                f"(missing={cap_missing}, unknown={cap_unknown})"
            )
        return cls(
            runtime_id=payload["runtime_id"],
            adapter_id=payload["adapter_id"],
            adapter_module=payload["adapter_module"],
            command=payload["command"],
            mode=payload["mode"],
            declared_tools=tuple(payload["declared_tools"]),
            egress_transports=tuple(payload["egress_transports"]),
            workspace_modes=tuple(payload["workspace_modes"]),
            cost_model=payload["cost_model"],
            capabilities=RuntimeCapabilities(**dict(capabilities)),
        )


def load_runtime_profiles(
    path: str | Path,
    *,
    required_runtime_ids: Sequence[str] = REQUIRED_GATE0_RUNTIME_IDS,
) -> Mapping[str, RuntimeProfile]:
    """Load one canonical profile per required runtime and refuse drift."""

    payload = _strict_json_object(Path(path).read_text(encoding="utf-8"))
    unknown = sorted(set(payload) - {"schema", "profiles"})
    missing = sorted({"schema", "profiles"} - set(payload))
    if unknown or missing:
        raise ValueError(
            f"runtime catalog fields differ (missing={missing}, unknown={unknown})"
        )
    if payload["schema"] != RUNTIME_PROFILE_SCHEMA:
        raise ValueError(
            f"runtime catalog schema must be {RUNTIME_PROFILE_SCHEMA!r}"
        )
    raw_profiles = payload["profiles"]
    if not isinstance(raw_profiles, list) or not raw_profiles:
        raise ValueError("runtime catalog profiles must be a non-empty array")
    profiles = [RuntimeProfile.from_dict(row) for row in raw_profiles]
    by_id = {profile.runtime_id: profile for profile in profiles}
    if len(by_id) != len(profiles):
        raise ValueError("runtime catalog contains duplicate runtime_id values")
    required = tuple(
        _identifier(value, "required_runtime_id") for value in required_runtime_ids
    )
    absent = sorted(set(required) - set(by_id))
    extra = sorted(set(by_id) - set(required))
    if absent or extra:
        raise ValueError(
            f"runtime catalog membership differs (missing={absent}, extra={extra})"
        )
    return MappingProxyType(
        {runtime_id: by_id[runtime_id] for runtime_id in sorted(by_id)}
    )


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
    """Bind a declared manifest to exact adapter/binary/environment identities."""

    digests = (
        profile.digest,
        _sha256(adapter_sha256, "adapter_sha256"),
        _sha256(executable_sha256, "executable_sha256"),
        _sha256(environment_sha256, "environment_sha256"),
        _sha256(fixture_suite_sha256, "fixture_suite_sha256"),
    )
    revision = _revision(source_revision, "source_revision")
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
            input_digests=tuple(sorted(digests)),
            trace_id=profile.runtime_id,
        ),
    )


@dataclass(frozen=True)
class RuntimeProbeIdentity(CanonicalContract):
    """Exact identity of the thing that produced conformance observations."""

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
        if self.authority not in _PROBE_AUTHORITIES:
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
            self,
            "source_revision",
            _revision(self.source_revision, "source_revision"),
        )
        object.__setattr__(
            self,
            "collected_at",
            _utc_timestamp(self.collected_at, "collected_at"),
        )
        if self.provenance.source_revision != self.source_revision:
            raise ValueError("probe source revision contradicts provenance")
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
    if manifest.runtime_id != profile.runtime_id:
        raise ValueError("runtime manifest belongs to another profile")
    if manifest.adapter_id != profile.adapter_id:
        raise ValueError("runtime manifest names another adapter")
    inputs = (
        manifest.digest,
        profile.digest,
        _sha256(adapter_sha256, "adapter_sha256"),
        _sha256(executable_sha256, "executable_sha256"),
        _sha256(environment_sha256, "environment_sha256"),
        _sha256(fixture_suite_sha256, "fixture_suite_sha256"),
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
            input_digests=tuple(sorted(inputs)),
            trace_id=probe_id,
        ),
    )


@dataclass(frozen=True)
class RuntimeConformanceEnvelope(CanonicalContract):
    """Authority-labelled binding of manifest, probe identity, and receipt."""

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
        if self.authority not in _PROBE_AUTHORITIES:
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
            self,
            "source_revision",
            _revision(self.source_revision, "source_revision"),
        )
        object.__setattr__(
            self, "created_at", _utc_timestamp(self.created_at, "created_at")
        )
        if self.provenance.source_revision != self.source_revision:
            raise ValueError("envelope source revision contradicts provenance")
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


def bind_conformance_envelope(
    manifest: RuntimeManifest,
    identity: RuntimeProbeIdentity,
    receipt: RuntimeConformanceReceipt,
    *,
    envelope_id: str,
    created_at: str,
) -> RuntimeConformanceEnvelope:
    """Bind exact observations without upgrading their authority."""

    if identity.runtime_id != manifest.runtime_id:
        raise RuntimeConformanceError("probe identity belongs to another runtime")
    if identity.runtime_manifest_sha256 != manifest.digest:
        raise RuntimeConformanceError("probe identity binds another runtime manifest")
    if identity.source_revision != manifest.source_revision:
        raise RuntimeConformanceError("probe identity binds another source revision")
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
            input_digests=tuple(
                sorted({manifest.digest, identity.digest, receipt.digest})
            ),
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
    """Verify exact identity and refuse offline evidence for production by default."""

    comparisons = {
        "runtime_id": (envelope.runtime_id, manifest.runtime_id),
        "authority": (envelope.authority, identity.authority),
        "status": (envelope.status, receipt.status),
        "runtime_manifest_sha256": (
            envelope.runtime_manifest_sha256,
            manifest.digest,
        ),
        "probe_identity_sha256": (
            envelope.probe_identity_sha256,
            identity.digest,
        ),
        "conformance_receipt_sha256": (
            envelope.conformance_receipt_sha256,
            receipt.digest,
        ),
        "source_revision": (envelope.source_revision, manifest.source_revision),
        "identity_manifest": (
            identity.runtime_manifest_sha256,
            manifest.digest,
        ),
        "identity_runtime": (identity.runtime_id, manifest.runtime_id),
        "identity_revision": (
            identity.source_revision,
            manifest.source_revision,
        ),
    }
    mismatches = sorted(
        name for name, (actual, expected) in comparisons.items() if actual != expected
    )
    if mismatches:
        raise RuntimeConformanceError(
            "runtime conformance envelope binding mismatch: "
            + ", ".join(mismatches)
        )
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
