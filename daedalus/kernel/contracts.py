"""Additive trust-kernel contracts built on the canonical Gate-0 wire language.

These records inherit :class:`daedalus.schemas.CanonicalContract`; they do not
create a second serialization or digest authority. They live under ``kernel``
so the Filetree migration can proceed strangler-style without a semantic and
mechanical rewrite of the legacy schema module in the same security packet.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Any, ClassVar, Mapping
from urllib.parse import urlsplit

from daedalus.schemas import (
    CanonicalContract,
    ContractProvenance,
    EffectScope,
    _egress_endpoint,
    _identifier,
    _non_empty,
    _require_provenance_inputs,
    _revision,
    _sha256,
    _sorted_strings,
    _utc_timestamp,
)
from daedalus.spine.envelope import canonical_sha


OFFLOAD_EXECUTION_EFFECTS = (
    "filesystem_write",
    "network_egress",
    "process_spawn",
    "spend",
)


def _command_argv(value: Any, name: str) -> tuple[str, ...]:
    """Freeze one exact subprocess argv without introducing shell parsing."""

    if isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be an argv sequence, not a command string")
    try:
        items = tuple(value)
    except TypeError as exc:
        raise ValueError(f"{name} must be an argv sequence") from exc
    if not items:
        raise ValueError(f"{name} must be non-empty")
    argv: list[str] = []
    for index, raw in enumerate(items):
        item = _non_empty(raw, f"{name}[{index}]", max_length=4000)
        if "\x00" in item:
            raise ValueError(f"{name}[{index}] contains a NUL byte")
        argv.append(item)
    return tuple(argv)


def _loopback_ollama_endpoint(value: Any) -> str:
    """Return one canonical, numeric HTTP loopback origin for Ollama."""

    endpoint = _egress_endpoint(value, "provider_endpoint")
    parsed = urlsplit(endpoint)
    if parsed.scheme != "http":
        raise ValueError("provider_endpoint must use http on numeric loopback")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("provider_endpoint must be an origin without path/query/fragment")
    try:
        address = ipaddress.ip_address(parsed.hostname or "")
        port = parsed.port
    except ValueError as exc:
        raise ValueError(
            "provider_endpoint must use a valid numeric loopback address and port"
        ) from exc
    if not address.is_loopback or port is None:
        raise ValueError(
            "provider_endpoint must use a numeric loopback address with explicit port"
        )
    host = f"[{address.compressed}]" if address.version == 6 else address.compressed
    return f"http://{host}:{port}"


@dataclass(frozen=True)
class OwnerApproval(CanonicalContract):
    """Authenticated, bounded and single-candidate owner authorization.

    The contract remains inert until a verifier authenticates the signature
    and a replay ledger consumes its nonce. It never applies a candidate.
    """

    CONTRACT_TYPE: ClassVar[str] = "daedalus.owner-approval"

    approval_id: str
    owner_id: str
    key_id: str
    operation: str
    nomination_receipt_sha256: str
    candidate_artifact_sha256: str
    evidence_packet_sha256: str
    base_revision: str
    target_ref: str
    expected_target_revision: str
    nonce: str
    issued_at: str
    expires_at: str
    signature_sha256: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        for name in ("approval_id", "owner_id", "key_id", "nonce"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        if self.operation != "promote-candidate":
            raise ValueError("owner approval operation must be promote-candidate")
        for name in (
            "nomination_receipt_sha256",
            "candidate_artifact_sha256",
            "evidence_packet_sha256",
            "signature_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(
            self, "base_revision", _revision(self.base_revision, "base_revision")
        )
        object.__setattr__(
            self,
            "expected_target_revision",
            _revision(self.expected_target_revision, "expected_target_revision"),
        )
        object.__setattr__(self, "target_ref", _identifier(self.target_ref, "target_ref"))
        object.__setattr__(self, "issued_at", _utc_timestamp(self.issued_at, "issued_at"))
        object.__setattr__(self, "expires_at", _utc_timestamp(self.expires_at, "expires_at"))
        if self.expires_at <= self.issued_at:
            raise ValueError("owner approval expires_at must be after issued_at")
        if self.provenance.source_revision != self.base_revision:
            raise ValueError(
                "owner approval base_revision must match provenance.source_revision"
            )
        _require_provenance_inputs(
            self.provenance,
            (
                self.nomination_receipt_sha256,
                self.candidate_artifact_sha256,
                self.evidence_packet_sha256,
            ),
            "owner approval",
        )

    def signing_dict(self) -> dict[str, Any]:
        body = self.to_dict()
        body.pop("signature_sha256")
        return body

    @property
    def signing_digest(self) -> str:
        return canonical_sha(self.signing_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OwnerApproval":
        body = cls._contract_payload(payload)
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class EffectLeaseRequest(CanonicalContract):
    """The exact effect scope submitted to the policy authority.

    A policy decision must bind this request's digest and identifier.  The
    request grants nothing by itself and is safe to persist or inspect.
    """

    CONTRACT_TYPE: ClassVar[str] = "daedalus.effect-lease-request"

    request_id: str
    mission_id: str
    attempt_id: str
    entrypoint_id: str
    requested_effects: tuple[str, ...]
    effect_scope: EffectScope
    idempotency_namespace: str
    kill_switch_generation: int
    runtime_manifest_sha256: str | None
    runtime_conformance_sha256: str | None
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        for name in (
            "request_id",
            "mission_id",
            "attempt_id",
            "entrypoint_id",
            "idempotency_namespace",
        ):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(
            self,
            "requested_effects",
            _sorted_strings(self.requested_effects, "requested_effects", identifiers=True),
        )
        if not self.requested_effects:
            raise ValueError("effect lease request must name at least one effect")
        if isinstance(self.kill_switch_generation, bool) or not isinstance(
            self.kill_switch_generation, int
        ) or self.kill_switch_generation < 0:
            raise ValueError("kill_switch_generation must be a non-negative integer")
        for name in ("runtime_manifest_sha256", "runtime_conformance_sha256"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _sha256(value, name))
        if (self.runtime_manifest_sha256 is None) != (
            self.runtime_conformance_sha256 is None
        ):
            raise ValueError(
                "runtime manifest and conformance digests must be supplied together"
            )
        if not self.effect_scope.has_effects:
            raise ValueError("effect lease request must carry a bounded effect scope")
        if not self.effect_scope.kill_switch_ref:
            raise ValueError("effect lease request requires a kill_switch_ref")
        required = []
        if self.runtime_manifest_sha256 is not None:
            required.extend(
                [self.runtime_manifest_sha256, self.runtime_conformance_sha256]
            )
        _require_provenance_inputs(
            self.provenance,
            tuple(value for value in required if value is not None),
            "effect lease request",
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EffectLeaseRequest":
        body = cls._contract_payload(payload)
        body["effect_scope"] = EffectScope.from_dict(body["effect_scope"])
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class EffectLease(CanonicalContract):
    """Authenticated, persisted and expiring authorization for one scope.

    The lease is inert until :class:`daedalus.kernel.effects.EffectLeaseLedger`
    validates and records an execution start.  It never performs the effect.
    """

    CONTRACT_TYPE: ClassVar[str] = "daedalus.effect-lease"

    lease_id: str
    request_id: str
    request_sha256: str
    policy_decision_id: str
    policy_decision_sha256: str
    registry_sha256: str
    entrypoint_id: str
    requested_effects: tuple[str, ...]
    effect_scope: EffectScope
    idempotency_namespace: str
    kill_switch_generation: int
    runtime_id: str
    runtime_manifest_sha256: str | None
    runtime_conformance_sha256: str | None
    issuer_key_id: str
    issued_at: str
    expires_at: str
    signature_sha256: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        for name in (
            "lease_id",
            "request_id",
            "policy_decision_id",
            "entrypoint_id",
            "idempotency_namespace",
            "issuer_key_id",
        ):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        if self.runtime_id:
            object.__setattr__(self, "runtime_id", _identifier(self.runtime_id, "runtime_id"))
        for name in (
            "request_sha256",
            "policy_decision_sha256",
            "registry_sha256",
            "signature_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(
            self,
            "requested_effects",
            _sorted_strings(self.requested_effects, "requested_effects", identifiers=True),
        )
        if not self.requested_effects:
            raise ValueError("effect lease must name at least one effect")
        if isinstance(self.kill_switch_generation, bool) or not isinstance(
            self.kill_switch_generation, int
        ) or self.kill_switch_generation < 0:
            raise ValueError("kill_switch_generation must be a non-negative integer")
        for name in ("runtime_manifest_sha256", "runtime_conformance_sha256"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _sha256(value, name))
        if (self.runtime_manifest_sha256 is None) != (
            self.runtime_conformance_sha256 is None
        ):
            raise ValueError(
                "runtime manifest and conformance digests must be supplied together"
            )
        object.__setattr__(self, "issued_at", _utc_timestamp(self.issued_at, "issued_at"))
        object.__setattr__(self, "expires_at", _utc_timestamp(self.expires_at, "expires_at"))
        if self.expires_at <= self.issued_at:
            raise ValueError("effect lease expires_at must be after issued_at")
        required = [self.request_sha256, self.policy_decision_sha256, self.registry_sha256]
        if self.runtime_manifest_sha256 is not None:
            required.extend(
                [self.runtime_manifest_sha256, self.runtime_conformance_sha256]
            )
        _require_provenance_inputs(
            self.provenance,
            tuple(value for value in required if value is not None),
            "effect lease",
        )

    def signing_dict(self) -> dict[str, Any]:
        body = self.to_dict()
        body.pop("signature_sha256")
        return body

    @property
    def signing_digest(self) -> str:
        return canonical_sha(self.signing_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EffectLease":
        body = cls._contract_payload(payload)
        body["effect_scope"] = EffectScope.from_dict(body["effect_scope"])
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class OffloadExecutionPlan(CanonicalContract):
    """Inert, immutable authorization input for one bounded local offload.

    The plan records what a later trusted authority may request.  It neither
    issues an Effect Lease nor performs a provider call.  The first supported
    slice is deliberately narrow: one pinned Ollama model at a numeric
    loopback origin, one model call, exact workspace targets, deterministic
    tool/verifier argv, and zero monetary spend.
    """

    CONTRACT_TYPE: ClassVar[str] = "daedalus.offload-execution-plan"

    plan_id: str
    spine_intent_id: int
    intent_sha256: str
    task_id: str
    task_sha256: str
    source_revision: str
    source_artifact_sha256: str
    worktree_id: str
    worktree_fingerprint_sha256: str
    provider_id: str
    model_id: str
    model_sha256: str
    provider_endpoint: str
    write_mode: str
    target_paths: tuple[str, ...]
    policy_decision_sha256: str
    availability_sha256: str
    routing_decision_sha256: str
    runtime_manifest_sha256: str
    runtime_conformance_sha256: str
    requested_effects: tuple[str, ...]
    effect_scope: EffectScope
    kill_switch_generation: int
    max_model_calls: int
    timeout_s: int
    max_cost_microusd: int
    tool_argv: tuple[str, ...]
    verifier_argv: tuple[str, ...]
    metrics_enabled: bool
    drafts_enabled: bool
    auto_mint_enabled: bool
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        for name in ("plan_id", "task_id", "worktree_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        if (
            isinstance(self.spine_intent_id, bool)
            or not isinstance(self.spine_intent_id, int)
            or self.spine_intent_id < 1
        ):
            raise ValueError("spine_intent_id must be a positive Spine ledger id")

        for name in (
            "intent_sha256",
            "task_sha256",
            "source_artifact_sha256",
            "worktree_fingerprint_sha256",
            "model_sha256",
            "policy_decision_sha256",
            "availability_sha256",
            "routing_decision_sha256",
            "runtime_manifest_sha256",
            "runtime_conformance_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))

        object.__setattr__(
            self, "source_revision", _revision(self.source_revision, "source_revision")
        )
        provider_id = _identifier(self.provider_id, "provider_id")
        if provider_id != "ollama":
            raise ValueError("the Gate-0 offload plan supports only provider_id='ollama'")
        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(self, "model_id", _identifier(self.model_id, "model_id"))
        object.__setattr__(
            self, "provider_endpoint", _loopback_ollama_endpoint(self.provider_endpoint)
        )
        if self.write_mode != "write":
            raise ValueError("offload execution plan write_mode must be 'write'")

        targets = _sorted_strings(self.target_paths, "target_paths", paths=True)
        if len(targets) != 1 or "." in targets:
            raise ValueError(
                "Gate-0 offload execution plan requires exactly one bounded target path"
            )
        object.__setattr__(self, "target_paths", targets)

        effects = _sorted_strings(
            self.requested_effects, "requested_effects", identifiers=True
        )
        if effects != OFFLOAD_EXECUTION_EFFECTS:
            raise ValueError(
                "offload execution plan requested_effects must exactly match "
                "the canonical python.offload entrypoint"
            )
        object.__setattr__(self, "requested_effects", effects)

        if (
            isinstance(self.max_model_calls, bool)
            or not isinstance(self.max_model_calls, int)
            or self.max_model_calls != 1
        ):
            raise ValueError("max_model_calls must be exactly 1 for the Gate-0 slice")
        if (
            isinstance(self.timeout_s, bool)
            or not isinstance(self.timeout_s, int)
            or self.timeout_s < 1
        ):
            raise ValueError("timeout_s must be a positive integer")
        if (
            isinstance(self.max_cost_microusd, bool)
            or not isinstance(self.max_cost_microusd, int)
            or self.max_cost_microusd != 0
        ):
            raise ValueError("max_cost_microusd must be zero for loopback Ollama")

        object.__setattr__(self, "tool_argv", _command_argv(self.tool_argv, "tool_argv"))
        object.__setattr__(
            self,
            "verifier_argv",
            _command_argv(self.verifier_argv, "verifier_argv"),
        )
        # argv[0] is a stable runtime-manifest tool id, not an ambient host
        # executable path.  The pinned runtime manifest resolves that id to an
        # exact binary; keeping the policy scope symbolic makes the wire
        # contract portable without weakening the manifest binding.
        declared_tools = tuple(sorted({self.tool_argv[0], self.verifier_argv[0]}))
        for index, tool in enumerate(declared_tools):
            _identifier(tool, f"argv executable[{index}]")

        if not isinstance(self.effect_scope, EffectScope):
            raise ValueError("effect_scope must be an EffectScope")
        scope = self.effect_scope
        if scope.read_only:
            raise ValueError("offload execution plan requires a write-capable effect scope")
        if scope.writable_paths != self.target_paths:
            raise ValueError("effect_scope.writable_paths must exactly match target_paths")
        if scope.egress_endpoints != (self.provider_endpoint,):
            raise ValueError(
                "effect_scope.egress_endpoints must contain only provider_endpoint"
            )
        if scope.tools != declared_tools:
            raise ValueError(
                "effect_scope.tools must exactly match tool/verifier argv executables"
            )
        if scope.secret_refs:
            raise ValueError("loopback Ollama offload cannot request secret_refs")
        if scope.max_cost_microusd != self.max_cost_microusd:
            raise ValueError("effect_scope cost must exactly match plan cost budget")
        if scope.max_concurrency != 1:
            raise ValueError("offload execution plan requires max_concurrency=1")
        if scope.timeout_s != self.timeout_s:
            raise ValueError("effect_scope timeout must exactly match plan timeout")
        if not scope.kill_switch_ref:
            raise ValueError("offload execution plan requires a kill_switch_ref")
        if (
            isinstance(self.kill_switch_generation, bool)
            or not isinstance(self.kill_switch_generation, int)
            or self.kill_switch_generation < 0
        ):
            raise ValueError("kill_switch_generation must be a non-negative integer")

        for name in ("metrics_enabled", "drafts_enabled", "auto_mint_enabled"):
            value = getattr(self, name)
            if not isinstance(value, bool):
                raise ValueError(f"{name} must be boolean")
            if value:
                raise ValueError(f"{name} must be false for the Gate-0 offload slice")

        if self.provenance.source_revision != self.source_revision:
            raise ValueError(
                "offload execution plan source_revision must match provenance"
            )
        _require_provenance_inputs(
            self.provenance,
            (
                self.intent_sha256,
                self.task_sha256,
                self.source_artifact_sha256,
                self.worktree_fingerprint_sha256,
                self.model_sha256,
                self.policy_decision_sha256,
                self.availability_sha256,
                self.routing_decision_sha256,
                self.runtime_manifest_sha256,
                self.runtime_conformance_sha256,
            ),
            "offload execution plan",
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OffloadExecutionPlan":
        body = cls._contract_payload(payload)
        body["effect_scope"] = EffectScope.from_dict(body["effect_scope"])
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)
