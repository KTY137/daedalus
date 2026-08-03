"""Additive trust-kernel contracts built on the canonical Gate-0 wire language.

These records inherit :class:`daedalus.schemas.CanonicalContract`; they do not
create a second serialization or digest authority. They live under ``kernel``
so the Filetree migration can proceed strangler-style without a semantic and
mechanical rewrite of the legacy schema module in the same security packet.
"""
from __future__ import annotations

import ipaddress
import re
import unicodedata
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

OFFLOAD_MAX_METADATA_CALLS = 1
OFFLOAD_MAX_MODEL_CALLS = 1
OFFLOAD_MAX_RESPONSE_BYTES = 2_000_000
OFFLOAD_MAX_TOTAL_TIMEOUT_S = 3_600
OFFLOAD_NUM_CTX_MIN = 2_048
OFFLOAD_NUM_CTX_MAX = 131_072
OFFLOAD_NUM_PREDICT_MAX = 8_192

_WINDOWS_RESERVED_PATH_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
    }
)
_WINDOWS_INVALID_PATH_CHARS_RE = re.compile(r'[<>:"|?*\x00-\x1f]')
_WINDOWS_SHORT_NAME_RE = re.compile(r"~[0-9]+(?:\.|$)", re.IGNORECASE)


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
    canonical_loopbacks = {
        ipaddress.ip_address("127.0.0.1"),
        ipaddress.ip_address("::1"),
    }
    if address not in canonical_loopbacks or port is None or port < 1:
        raise ValueError(
            "provider_endpoint must use canonical loopback 127.0.0.1 or ::1 "
            "with an explicit port"
        )
    host = f"[{address.compressed}]" if address.version == 6 else address.compressed
    return f"http://{host}:{port}"


def _portable_target_path(value: Any, name: str = "target_path") -> str:
    """Validate one exact repository-relative path without normalization.

    The execution plan is portable across the supported host platforms.  A
    path that would normalize differently on POSIX and Windows is therefore
    refused instead of silently rewritten into a broader effect scope.
    """

    raw = _non_empty(value, name, max_length=500)
    if "\\" in raw:
        raise ValueError(f"{name} must use POSIX '/' separators")
    if raw.startswith("/") or raw.startswith("//"):
        raise ValueError(f"{name} must be repository-relative")
    if re.match(r"^[A-Za-z]:", raw):
        raise ValueError(f"{name} must not be drive-qualified")

    parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(
            f"{name} must not contain empty, current, or parent path components"
        )
    for index, part in enumerate(parts):
        if unicodedata.normalize("NFC", part) != part:
            raise ValueError(
                f"{name} component {index} must use canonical NFC Unicode"
            )
        if _WINDOWS_INVALID_PATH_CHARS_RE.search(part):
            raise ValueError(f"{name} component {index} contains a non-portable character")
        if part.endswith((".", " ")):
            raise ValueError(f"{name} component {index} must not end in dot or space")
        stem = part.split(".", 1)[0].upper()
        if stem in _WINDOWS_RESERVED_PATH_NAMES:
            raise ValueError(f"{name} component {index} is reserved on Windows")
        if _WINDOWS_SHORT_NAME_RE.search(part):
            raise ValueError(
                f"{name} component {index} could be a Windows 8.3 path alias"
            )
    return raw


def derive_offload_staging_path(
    *, attempt_id: str, workspace_id: str, target_path: str
) -> str:
    """Derive one exact same-directory staging path without a plan-digest cycle."""

    attempt = _identifier(attempt_id, "attempt_id")
    workspace = _identifier(workspace_id, "workspace_id")
    target = _portable_target_path(target_path)
    identity = canonical_sha(
        {
            "domain": "daedalus.offload-staging-identity/1",
            "attempt_id": attempt,
            "workspace_id": workspace,
            "target_path": target,
        }
    )
    parent, separator, _name = target.rpartition("/")
    filename = f".daedalus-offload-stage-{identity}.tmp"
    staging = f"{parent}/{filename}" if separator else filename
    return _portable_target_path(staging, "staging_path")


def offload_staging_path_sha256(staging_path: str) -> str:
    """Return the provenance identity of one canonical staging path."""

    staging = _portable_target_path(staging_path, "staging_path")
    return canonical_sha(
        {
            "domain": "daedalus.offload-staging-path/1",
            "staging_path": staging,
        }
    )


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
    # Optional for legacy/non-plan entrypoints.  Canonical plan executors must
    # set it and the policy then subjects this request's resulting digest.
    execution_plan_sha256: str | None = None

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
        if self.execution_plan_sha256 is not None:
            object.__setattr__(
                self,
                "execution_plan_sha256",
                _sha256(self.execution_plan_sha256, "execution_plan_sha256"),
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
        if self.execution_plan_sha256 is not None:
            required.append(self.execution_plan_sha256)
        _require_provenance_inputs(
            self.provenance,
            tuple(value for value in required if value is not None),
            "effect lease request",
        )

    def to_dict(self) -> dict[str, Any]:
        body = super().to_dict()
        # Preserve the existing v1 digest for non-plan entrypoints and old
        # persisted grants.  The field becomes explicit on the wire precisely
        # when a plan is actually bound.
        if self.execution_plan_sha256 is None:
            body.pop("execution_plan_sha256")
        return body

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
class OffloadExecutionPlanV2(CanonicalContract):
    """Historical v2 authority input retained for exact replay and audit.

    This is an inert claim, not filesystem evidence and not permission to run.
    A trusted execution seam must compare the target-before fields with a real
    regular UTF-8 file and bind the runtime tool bytes before consuming a
    lease.  ``expected_model_sha256`` is an expectation checked against the
    live model observation produced only after ``ledger.begin``; that later
    observation belongs in terminal/evidence output, never in this pre-effect
    plan.  The intentionally narrow Gate-0 slice permits one metadata call, one
    model call, one target, one verifier, canonical-loopback Ollama only, and no
    monetary cost.
    """

    CONTRACT_TYPE: ClassVar[str] = "daedalus.offload-execution-plan"
    CONTRACT_VERSION: ClassVar[str] = "2.0.0"

    spine_intent_id: int
    spine_intent_sha256: str
    mission_id: str
    attempt_id: str
    attempt_contract_sha256: str
    task_id: str
    task_sha256: str

    source_revision: str
    base_source_artifact_sha256: str
    workspace_id: str
    workspace_attestation_sha256: str
    workspace_observation_sha256: str

    target_path: str
    target_kind: str
    target_before_sha256: str
    target_before_size: int
    target_git_mode: str

    provider_id: str
    runtime_id: str
    provider_endpoint: str
    model_id: str
    expected_model_sha256: str

    prompt_template_sha256: str
    prompt_sha256: str
    response_schema_sha256: str
    ollama_request_sha256: str
    num_ctx: int
    num_predict: int
    seed: int
    temperature_milli: int
    keep_alive: str
    max_response_bytes: int
    max_metadata_calls: int
    max_model_calls: int

    attempt_policy_decision_sha256: str
    runtime_manifest_sha256: str
    runtime_conformance_sha256: str
    runtime_tool_binding_sha256: str

    verifier_argv: tuple[str, ...]
    verifier_timeout_s: int

    requested_effects: tuple[str, ...]
    effect_scope: EffectScope
    kill_switch_generation: int
    total_timeout_s: int
    max_cost_microusd: int
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        if (
            isinstance(self.spine_intent_id, bool)
            or not isinstance(self.spine_intent_id, int)
            or self.spine_intent_id < 1
        ):
            raise ValueError("spine_intent_id must be a positive Spine ledger id")
        for name in (
            "mission_id",
            "attempt_id",
            "task_id",
            "workspace_id",
        ):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))

        digest_fields = (
            "spine_intent_sha256",
            "attempt_contract_sha256",
            "task_sha256",
            "base_source_artifact_sha256",
            "workspace_attestation_sha256",
            "workspace_observation_sha256",
            "target_before_sha256",
            "expected_model_sha256",
            "prompt_template_sha256",
            "prompt_sha256",
            "response_schema_sha256",
            "ollama_request_sha256",
            "attempt_policy_decision_sha256",
            "runtime_manifest_sha256",
            "runtime_conformance_sha256",
            "runtime_tool_binding_sha256",
        )
        for name in digest_fields:
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(
            self, "source_revision", _revision(self.source_revision, "source_revision")
        )

        object.__setattr__(
            self, "target_path", _portable_target_path(self.target_path)
        )
        if self.target_kind != "existing-regular-utf8-file":
            raise ValueError(
                "target_kind must be exactly 'existing-regular-utf8-file'"
            )
        if (
            isinstance(self.target_before_size, bool)
            or not isinstance(self.target_before_size, int)
            or self.target_before_size < 0
        ):
            raise ValueError("target_before_size must be a non-negative integer")
        if self.target_git_mode not in {"100644", "100755"}:
            raise ValueError("target_git_mode must be '100644' or '100755'")

        provider_id = _identifier(self.provider_id, "provider_id")
        if provider_id != "ollama":
            raise ValueError("provider_id must be exactly 'ollama'")
        object.__setattr__(self, "provider_id", provider_id)
        runtime_id = _identifier(self.runtime_id, "runtime_id")
        if runtime_id != "ollama_http":
            raise ValueError("runtime_id must be exactly 'ollama_http'")
        object.__setattr__(self, "runtime_id", runtime_id)
        object.__setattr__(
            self, "provider_endpoint", _loopback_ollama_endpoint(self.provider_endpoint)
        )
        object.__setattr__(self, "model_id", _identifier(self.model_id, "model_id"))

        integer_bounds = (
            ("num_ctx", self.num_ctx, OFFLOAD_NUM_CTX_MIN, OFFLOAD_NUM_CTX_MAX),
            ("num_predict", self.num_predict, 1, OFFLOAD_NUM_PREDICT_MAX),
            ("seed", self.seed, 0, (2**63) - 1),
            ("max_response_bytes", self.max_response_bytes, 1, OFFLOAD_MAX_RESPONSE_BYTES),
            ("total_timeout_s", self.total_timeout_s, 1, OFFLOAD_MAX_TOTAL_TIMEOUT_S),
        )
        for name, value, minimum, maximum in integer_bounds:
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < minimum
                or value > maximum
            ):
                raise ValueError(
                    f"{name} must be an integer between {minimum} and {maximum}"
                )
        if self.num_predict >= self.num_ctx:
            raise ValueError("num_predict must be smaller than num_ctx")
        if (
            isinstance(self.temperature_milli, bool)
            or not isinstance(self.temperature_milli, int)
            or self.temperature_milli != 0
        ):
            raise ValueError("temperature_milli must be exactly 0")
        if self.keep_alive != "0":
            raise ValueError("keep_alive must be exactly '0'")
        for name, value, expected in (
            ("max_metadata_calls", self.max_metadata_calls, OFFLOAD_MAX_METADATA_CALLS),
            ("max_model_calls", self.max_model_calls, OFFLOAD_MAX_MODEL_CALLS),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value != expected:
                raise ValueError(f"{name} must be exactly {expected}")
        if (
            isinstance(self.max_cost_microusd, bool)
            or not isinstance(self.max_cost_microusd, int)
            or self.max_cost_microusd != 0
        ):
            raise ValueError("max_cost_microusd must be exactly 0")

        object.__setattr__(
            self,
            "verifier_argv",
            _command_argv(self.verifier_argv, "verifier_argv"),
        )
        _identifier(self.verifier_argv[0], "verifier_argv[0]")
        if (
            isinstance(self.verifier_timeout_s, bool)
            or not isinstance(self.verifier_timeout_s, int)
            or self.verifier_timeout_s < 1
            or self.verifier_timeout_s > self.total_timeout_s
        ):
            raise ValueError(
                "verifier_timeout_s must be positive and not exceed total_timeout_s"
            )

        effects = _sorted_strings(
            self.requested_effects, "requested_effects", identifiers=True
        )
        if effects != OFFLOAD_EXECUTION_EFFECTS:
            raise ValueError(
                "requested_effects must exactly match the canonical python.offload entrypoint"
            )
        object.__setattr__(self, "requested_effects", effects)
        if not isinstance(self.effect_scope, EffectScope):
            raise ValueError("effect_scope must be an EffectScope")
        scope = self.effect_scope
        if scope.read_only:
            raise ValueError("offload execution plan requires a write-capable effect scope")
        if scope.writable_paths != self._expected_writable_paths():
            raise ValueError(
                "effect_scope.writable_paths do not match the plan's exact write paths"
            )
        if scope.egress_endpoints != (self.provider_endpoint,):
            raise ValueError(
                "effect_scope.egress_endpoints must contain only provider_endpoint"
            )
        if scope.tools != (self.verifier_argv[0],):
            raise ValueError(
                "effect_scope.tools must contain only the symbolic verifier tool id"
            )
        if scope.secret_refs:
            raise ValueError("loopback Ollama offload cannot request secret_refs")
        if scope.max_cost_microusd != 0:
            raise ValueError("effect_scope.max_cost_microusd must be exactly 0")
        if scope.max_concurrency != 1:
            raise ValueError("effect_scope.max_concurrency must be exactly 1")
        if scope.timeout_s != self.total_timeout_s:
            raise ValueError("effect_scope.timeout_s must equal total_timeout_s")
        if not scope.kill_switch_ref:
            raise ValueError("offload execution plan requires a kill_switch_ref")
        if (
            isinstance(self.kill_switch_generation, bool)
            or not isinstance(self.kill_switch_generation, int)
            or self.kill_switch_generation < 0
        ):
            raise ValueError("kill_switch_generation must be a non-negative integer")

        if self.provenance.source_revision != self.source_revision:
            raise ValueError(
                "offload execution plan source_revision must match provenance"
            )
        _require_provenance_inputs(
            self.provenance,
            tuple(getattr(self, name) for name in digest_fields),
            "offload execution plan",
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OffloadExecutionPlanV2":
        body = cls._contract_payload(payload)
        body["effect_scope"] = EffectScope.from_dict(body["effect_scope"])
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)

    def _expected_writable_paths(self) -> tuple[str, ...]:
        return (self.target_path,)


@dataclass(frozen=True)
class OffloadExecutionPlan(OffloadExecutionPlanV2):
    """Current plan with one target and one exact atomic staging path.

    The staging path is derived from pre-plan canonical identities so it can be
    included in the lease scope without a digest cycle.  V2 remains decodable
    as inert history but is deliberately rejected by current offload authority.
    """

    CONTRACT_VERSION: ClassVar[str] = "3.0.0"

    staging_path: str
    staging_path_sha256: str

    def __post_init__(self) -> None:
        staging = _portable_target_path(self.staging_path, "staging_path")
        object.__setattr__(self, "staging_path", staging)
        expected = derive_offload_staging_path(
            attempt_id=self.attempt_id,
            workspace_id=self.workspace_id,
            target_path=self.target_path,
        )
        if staging != expected:
            raise ValueError("staging_path must equal the canonical derived path")
        if staging == self.target_path:
            raise ValueError("staging_path must differ from target_path")
        staging_sha = _sha256(self.staging_path_sha256, "staging_path_sha256")
        object.__setattr__(self, "staging_path_sha256", staging_sha)
        if staging_sha != offload_staging_path_sha256(staging):
            raise ValueError("staging_path_sha256 mismatches staging_path")
        super().__post_init__()
        _require_provenance_inputs(
            self.provenance,
            (staging_sha,),
            "offload execution plan staging path",
        )

    def _expected_writable_paths(self) -> tuple[str, ...]:
        return tuple(sorted((self.staging_path, self.target_path)))


def _loopback_ollama_endpoint_v1(value: Any) -> str:
    """Preserve the historical v1 numeric-127/8 endpoint interpretation."""

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
class OffloadExecutionPlanV1(CanonicalContract):
    """Historical v1 decoder retained for ledger and artifact replay.

    V1 is not accepted by the v2 authority and cannot be promoted into v2 by
    inventing target observations or runtime bindings.  The separate type keeps
    its original wire semantics available for audit without weakening v2.
    """

    CONTRACT_TYPE: ClassVar[str] = "daedalus.offload-execution-plan"
    CONTRACT_VERSION: ClassVar[str] = "1.0.0"

    plan_id: str
    spine_intent_id: int
    intent_sha256: str
    attempt_contract_sha256: str
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
    attempt_policy_decision_sha256: str
    availability_sha256: str
    routing_index_sha256: str
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

        digest_fields = (
            "intent_sha256",
            "attempt_contract_sha256",
            "task_sha256",
            "source_artifact_sha256",
            "worktree_fingerprint_sha256",
            "model_sha256",
            "attempt_policy_decision_sha256",
            "availability_sha256",
            "routing_index_sha256",
            "routing_decision_sha256",
            "runtime_manifest_sha256",
            "runtime_conformance_sha256",
        )
        for name in digest_fields:
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
            self,
            "provider_endpoint",
            _loopback_ollama_endpoint_v1(self.provider_endpoint),
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
            tuple(getattr(self, name) for name in digest_fields),
            "offload execution plan",
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OffloadExecutionPlanV1":
        body = cls._contract_payload(payload)
        body["effect_scope"] = EffectScope.from_dict(body["effect_scope"])
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


def decode_offload_execution_plan(
    payload: Mapping[str, Any],
) -> OffloadExecutionPlanV1 | OffloadExecutionPlanV2 | OffloadExecutionPlan:
    """Decode the exact historical or current wire version without coercion."""

    if not isinstance(payload, Mapping):
        raise ValueError("daedalus.offload-execution-plan must be an object")
    version = payload.get("contract_version")
    if version == OffloadExecutionPlanV1.CONTRACT_VERSION:
        return OffloadExecutionPlanV1.from_dict(payload)
    if version == OffloadExecutionPlanV2.CONTRACT_VERSION:
        return OffloadExecutionPlanV2.from_dict(payload)
    if version == OffloadExecutionPlan.CONTRACT_VERSION:
        return OffloadExecutionPlan.from_dict(payload)
    raise ValueError(f"unsupported offload execution plan version: {version!r}")
