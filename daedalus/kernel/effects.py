"""Persisted, scope-bounded Effect Leases for the Gate-0 trust kernel.

The lease layer is deliberately inert with respect to real effects.  It
persists authorization before an effect may start, validates a request against
one exact policy decision and one exact entrypoint-registry revision, and
returns an execution flag that prevents replay from causing a second effect.
Legacy callers are migrated in later Work Packets; this module refuses to issue
leases for rows that are not already marked ``CENTRAL``.
"""
from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping, Sequence

from daedalus.kernel.contracts import EffectLease, EffectLeaseRequest
from daedalus.schemas import (
    ContractProvenance,
    EffectScope,
    PolicyDecision,
    _egress_endpoint,
    _identifier,
    _repo_path,
    _sha256,
    _sorted_strings,
)
from daedalus.spine.effect_boundary import (
    REGISTRY_BY_ID,
    Effect,
    EntrypointSpec,
    GuardDecision,
    Wiring,
    begin_effect,
    registry_sha256,
)
from daedalus.spine.envelope import canonical_json, canonical_sha

_MAX_LEASE_TTL = timedelta(hours=24)
_TERMINAL_STATES = frozenset({"COMPLETED", "FAILED", "CANCELLED"})


class EffectLeaseError(RuntimeError):
    """Base class for fail-closed lease failures."""


class EffectLeaseSignatureError(EffectLeaseError):
    pass


class EffectLeaseExpired(EffectLeaseError):
    pass


class EffectLeaseBindingMismatch(EffectLeaseError):
    pass


class EffectLeaseScopeError(EffectLeaseError):
    pass


class EffectLeaseReplay(EffectLeaseError):
    pass


class EffectLeaseStateError(EffectLeaseError):
    pass


class EffectReconciliationRequired(EffectLeaseStateError):
    """A started external effect could not publish its terminal receipt.

    The durable ``STARTED`` row is intentionally retained as an indeterminate
    state.  Re-entering the same execution remains inert, so an operator can
    reconcile the external outcome without risking a duplicate effect.
    """

    def __init__(
        self,
        *,
        execution_id: str,
        start_receipt_sha256: str,
        phase: str,
    ) -> None:
        self.execution_id = _identifier(execution_id, "execution_id")
        self.start_receipt_sha256 = _sha256(
            start_receipt_sha256, "start_receipt_sha256"
        )
        self.phase = _identifier(phase, "reconciliation phase")
        super().__init__(
            "effect execution requires reconciliation after terminal "
            f"persistence failed during {self.phase}: {self.execution_id} "
            f"(start receipt {self.start_receipt_sha256})"
        )


class EffectLeaseConcurrencyError(EffectLeaseError):
    pass


@dataclass(frozen=True)
class EffectExecutionRequest:
    """The exact narrowed scope of one attempted external effect."""

    execution_id: str
    idempotency_key: str
    requested_effects: tuple[str, ...]
    writable_paths: tuple[str, ...] = ()
    egress_endpoints: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    secret_refs: tuple[str, ...] = ()
    max_cost_microusd: int = 0
    kill_switch_ref: str = ""
    kill_switch_generation: int = 0
    execution_plan_sha256: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "execution_id", _identifier(self.execution_id, "execution_id"))
        object.__setattr__(
            self, "idempotency_key", _identifier(self.idempotency_key, "idempotency_key")
        )
        object.__setattr__(
            self,
            "requested_effects",
            _sorted_strings(self.requested_effects, "requested_effects", identifiers=True),
        )
        if not self.requested_effects:
            raise ValueError("execution request must name at least one effect")
        object.__setattr__(
            self,
            "writable_paths",
            _sorted_strings(self.writable_paths, "writable_paths", paths=True),
        )
        if isinstance(self.egress_endpoints, (str, bytes)):
            raise ValueError("egress_endpoints must be a sequence")
        endpoints = tuple(
            sorted(
                _egress_endpoint(value, f"egress_endpoints[{index}]")
                for index, value in enumerate(self.egress_endpoints)
            )
        )
        if len(set(endpoints)) != len(endpoints):
            raise ValueError("egress_endpoints must not contain duplicates")
        object.__setattr__(self, "egress_endpoints", endpoints)
        object.__setattr__(
            self, "tools", _sorted_strings(self.tools, "tools", identifiers=True)
        )
        object.__setattr__(
            self,
            "secret_refs",
            _sorted_strings(self.secret_refs, "secret_refs", identifiers=True),
        )
        if isinstance(self.max_cost_microusd, bool) or not isinstance(
            self.max_cost_microusd, int
        ) or self.max_cost_microusd < 0:
            raise ValueError("max_cost_microusd must be a non-negative integer")
        if self.kill_switch_ref:
            object.__setattr__(
                self,
                "kill_switch_ref",
                _identifier(self.kill_switch_ref, "kill_switch_ref"),
            )
        if isinstance(self.kill_switch_generation, bool) or not isinstance(
            self.kill_switch_generation, int
        ) or self.kill_switch_generation < 0:
            raise ValueError("kill_switch_generation must be a non-negative integer")
        if self.execution_plan_sha256 is not None:
            object.__setattr__(
                self,
                "execution_plan_sha256",
                _sha256(self.execution_plan_sha256, "execution_plan_sha256"),
            )
        # Validate names against the canonical Effect enum without changing
        # their deterministic sorted representation.
        for value in self.requested_effects:
            try:
                Effect(value)
            except ValueError as exc:
                raise ValueError(f"unknown requested effect {value!r}") from exc

    def to_dict(self) -> dict[str, object]:
        body = dataclasses.asdict(self)
        if self.execution_plan_sha256 is None:
            body.pop("execution_plan_sha256")
        return body

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class LeasedEffectStartReceipt:
    lease_sha256: str
    execution_id: str
    idempotency_key: str
    execution_request_sha256: str
    boundary_receipt_sha256: str
    started_at: str
    receipt_sha256: str

    def __post_init__(self) -> None:
        for name in ("execution_id", "idempotency_key"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        for name in (
            "lease_sha256",
            "execution_request_sha256",
            "boundary_receipt_sha256",
            "receipt_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        canonical_started = _timestamp(_parse_utc(self.started_at, "started_at"))
        if canonical_started != self.started_at:
            raise EffectLeaseBindingMismatch(
                "start receipt timestamp is not canonical UTC"
            )
        body = self.to_dict()
        claimed = body.pop("receipt_sha256")
        if canonical_sha(body) != claimed:
            raise EffectLeaseBindingMismatch("start receipt digest mismatch")

    def to_dict(self) -> dict[str, str]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class EffectStartResult:
    receipt: LeasedEffectStartReceipt
    execute: bool


@dataclass(frozen=True)
class EffectTerminalReceipt:
    lease_sha256: str
    execution_id: str
    start_receipt_sha256: str
    outcome: str
    output_digests: tuple[str, ...]
    detail_sha256: str | None
    finished_at: str
    receipt_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "execution_id", _identifier(self.execution_id, "execution_id")
        )
        for name in (
            "lease_sha256",
            "start_receipt_sha256",
            "receipt_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        normalized_outcome = str(self.outcome).upper()
        if normalized_outcome not in _TERMINAL_STATES or normalized_outcome != self.outcome:
            raise EffectLeaseBindingMismatch(
                "terminal receipt outcome must be canonical and terminal"
            )
        if isinstance(self.output_digests, (str, bytes)):
            raise EffectLeaseBindingMismatch(
                "terminal output_digests must be a sequence"
            )
        outputs = tuple(
            sorted({_sha256(value, "output_digest") for value in self.output_digests})
        )
        if tuple(self.output_digests) != outputs:
            raise EffectLeaseBindingMismatch(
                "terminal output_digests must be sorted and unique"
            )
        object.__setattr__(self, "output_digests", outputs)
        if self.detail_sha256 is not None:
            object.__setattr__(
                self,
                "detail_sha256",
                _sha256(self.detail_sha256, "detail_sha256"),
            )
        canonical_finished = _timestamp(
            _parse_utc(self.finished_at, "finished_at")
        )
        if canonical_finished != self.finished_at:
            raise EffectLeaseBindingMismatch(
                "terminal receipt timestamp is not canonical UTC"
            )
        body = self.to_dict()
        claimed = body.pop("receipt_sha256")
        if canonical_sha(body) != claimed:
            raise EffectLeaseBindingMismatch("terminal receipt digest mismatch")

    def to_dict(self) -> dict[str, object]:
        return {
            **dataclasses.asdict(self),
            "output_digests": list(self.output_digests),
        }


@dataclass(frozen=True)
class PersistedEffectGrant:
    """Authenticated contracts recovered from one persisted lease grant.

    Issuer secrets are intentionally absent.  A caller must supply the current
    keyring and kill-switch generation to :meth:`EffectLeaseLedger.load_grant`,
    which re-runs signature, policy, registry, expiry and scope verification
    before returning this record.
    """

    lease: EffectLease
    request: EffectLeaseRequest
    policy_decision: PolicyDecision
    revoked_at: str | None = None
    revocation_reason: str | None = None


@dataclass(frozen=True)
class PersistedEffectExecution:
    """One exact execution row recovered for restart/reconciliation."""

    request: EffectExecutionRequest
    start_receipt: LeasedEffectStartReceipt
    state: str
    terminal_receipt: EffectTerminalReceipt | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_utc(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EffectLeaseBindingMismatch(f"{label} is not ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EffectLeaseBindingMismatch(f"{label} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _as_utc(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return _as_utc(value, "timestamp").isoformat(timespec="microseconds")


def _secret_bytes(secret: bytes | str) -> bytes:
    value = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
    if len(value) < 32:
        raise ValueError("effect lease issuer secret must contain at least 32 bytes")
    return value


def _signature(signing_digest: str, secret: bytes | str) -> str:
    return hmac.new(
        _secret_bytes(secret), signing_digest.encode("ascii"), hashlib.sha256
    ).hexdigest()


def _registry_map(
    registry: Mapping[str, EntrypointSpec] | Sequence[EntrypointSpec],
) -> Mapping[str, EntrypointSpec]:
    if isinstance(registry, Mapping):
        rows = dict(registry)
        mismatched = sorted(key for key, value in rows.items() if key != value.id)
        if mismatched:
            raise EffectLeaseBindingMismatch(
                "entrypoint registry contains mismatched key/id rows: "
                + ", ".join(mismatched)
            )
        return rows
    rows = list(registry)
    if len({row.id for row in rows}) != len(rows):
        raise EffectLeaseBindingMismatch("entrypoint registry contains duplicate ids")
    return {row.id: row for row in rows}


def _scope_requirements(effects: Iterable[str], scope: EffectScope) -> None:
    try:
        values = {Effect(value) for value in effects}
    except ValueError as exc:
        raise EffectLeaseScopeError("effect scope contains an unknown effect") from exc
    if values & {Effect.FILESYSTEM_WRITE, Effect.REPOSITORY_MUTATION}:
        if scope.read_only or not scope.writable_paths:
            raise EffectLeaseScopeError("write effects require bounded writable_paths")
    if values & {Effect.NETWORK_EGRESS, Effect.LISTEN_SOCKET}:
        if not scope.egress_endpoints:
            raise EffectLeaseScopeError("network effects require explicit egress_endpoints")
    if values & {Effect.PROCESS_SPAWN, Effect.PROCESS_CONTROL}:
        if not scope.tools:
            raise EffectLeaseScopeError("process effects require explicit tools")
    if Effect.SECRETS in values and not scope.secret_refs:
        raise EffectLeaseScopeError("secret effects require explicit secret_refs")
    if Effect.SPEND in values and scope.max_cost_microusd is None:
        raise EffectLeaseScopeError("spend effects require an explicit cost ceiling")
    if not scope.kill_switch_ref:
        raise EffectLeaseScopeError("effectful scope requires a kill_switch_ref")
    if scope.timeout_s is None:
        raise EffectLeaseScopeError("effectful scope requires a timeout_s")


def _path_within(candidate: str, root: str) -> bool:
    candidate_path = PurePosixPath(_repo_path(candidate, "candidate_path"))
    root_path = PurePosixPath(_repo_path(root, "root_path"))
    return root_path == PurePosixPath(".") or candidate_path == root_path or root_path in candidate_path.parents


def _validate_narrowed_scope(request: EffectExecutionRequest, lease: EffectLease) -> None:
    granted_effects = set(lease.requested_effects)
    requested_effects = set(request.requested_effects)
    if not requested_effects <= granted_effects:
        raise EffectLeaseScopeError(
            "execution requested effects outside lease: "
            + ", ".join(sorted(requested_effects - granted_effects))
        )
    scope = lease.effect_scope
    for candidate in request.writable_paths:
        if not any(_path_within(candidate, root) for root in scope.writable_paths):
            raise EffectLeaseScopeError(
                f"writable path {candidate!r} is outside the leased roots"
            )
    if not set(request.egress_endpoints) <= set(scope.egress_endpoints):
        raise EffectLeaseScopeError("execution requested an unleased egress endpoint")
    if not set(request.tools) <= set(scope.tools):
        raise EffectLeaseScopeError("execution requested an unleased tool")
    if not set(request.secret_refs) <= set(scope.secret_refs):
        raise EffectLeaseScopeError("execution requested an unleased secret")
    if scope.max_cost_microusd is None:
        if request.max_cost_microusd:
            raise EffectLeaseScopeError("execution requested spend from a no-spend lease")
    elif request.max_cost_microusd > scope.max_cost_microusd:
        raise EffectLeaseScopeError("execution requested cost above the leased ceiling")
    if request.kill_switch_ref != scope.kill_switch_ref:
        raise EffectLeaseScopeError("execution kill_switch_ref does not match the lease")
    if request.kill_switch_generation != lease.kill_switch_generation:
        raise EffectLeaseScopeError("execution kill-switch generation is stale")

    write_effects = {Effect.FILESYSTEM_WRITE.value, Effect.REPOSITORY_MUTATION.value}
    network_effects = {Effect.NETWORK_EGRESS.value, Effect.LISTEN_SOCKET.value}
    process_effects = {Effect.PROCESS_SPAWN.value, Effect.PROCESS_CONTROL.value}
    if request.writable_paths and not requested_effects & write_effects:
        raise EffectLeaseScopeError("writable_paths supplied without a write effect")
    if requested_effects & write_effects and not request.writable_paths:
        raise EffectLeaseScopeError("write execution must name its exact writable paths")
    if request.egress_endpoints and not requested_effects & network_effects:
        raise EffectLeaseScopeError("egress_endpoints supplied without a network effect")
    if requested_effects & network_effects and not request.egress_endpoints:
        raise EffectLeaseScopeError("network execution must name its exact endpoint")
    if request.tools and not requested_effects & process_effects:
        raise EffectLeaseScopeError("tools supplied without a process effect")
    if requested_effects & process_effects and not request.tools:
        raise EffectLeaseScopeError("process execution must name its exact tool")
    if request.secret_refs and Effect.SECRETS.value not in requested_effects:
        raise EffectLeaseScopeError("secret_refs supplied without the secrets effect")
    if Effect.SECRETS.value in requested_effects and not request.secret_refs:
        raise EffectLeaseScopeError("secret execution must name its exact secret refs")
    if request.max_cost_microusd and Effect.SPEND.value not in requested_effects:
        raise EffectLeaseScopeError("cost supplied without the spend effect")


def issue_effect_lease(
    request: EffectLeaseRequest,
    policy_decision: PolicyDecision,
    *,
    lease_id: str,
    issuer_key_id: str,
    issued_at: datetime,
    expires_at: datetime,
    secret: bytes | str,
    registry: Mapping[str, EntrypointSpec] | Sequence[EntrypointSpec] = REGISTRY_BY_ID,
) -> EffectLease:
    """Create a signed lease only for an already-central entrypoint."""

    registry_map = _registry_map(registry)
    spec = registry_map.get(request.entrypoint_id)
    if spec is None or spec.id != request.entrypoint_id:
        raise EffectLeaseBindingMismatch("effect lease request names an unknown entrypoint")
    if spec.wiring is not Wiring.CENTRAL:
        raise EffectLeaseBindingMismatch(
            f"{spec.id} is {spec.wiring.value}, not central; migration is required first"
        )
    try:
        wanted = tuple(sorted({Effect(value).value for value in request.requested_effects}))
    except ValueError as exc:
        raise EffectLeaseBindingMismatch("effect lease request contains an unknown effect") from exc
    undeclared = sorted(set(wanted) - {effect.value for effect in spec.effects})
    if undeclared:
        raise EffectLeaseBindingMismatch(
            "entrypoint did not declare requested effects: " + ", ".join(undeclared)
        )
    _scope_requirements(wanted, request.effect_scope)

    if policy_decision.verdict != "allow":
        raise EffectLeaseBindingMismatch("deny policy decisions cannot issue leases")
    if policy_decision.subject_id != request.request_id:
        raise EffectLeaseBindingMismatch("policy subject_id does not match lease request")
    if policy_decision.subject_sha256 != request.digest:
        raise EffectLeaseBindingMismatch("policy subject digest does not match lease request")
    if policy_decision.effect_scope != request.effect_scope:
        raise EffectLeaseBindingMismatch("policy scope does not exactly match lease request")
    if policy_decision.provenance.source_revision != request.provenance.source_revision:
        raise EffectLeaseBindingMismatch("policy and lease request use different revisions")
    if spec.runtime_id:
        if request.runtime_manifest_sha256 is None:
            raise EffectLeaseBindingMismatch(
                "runtime entrypoints require manifest and conformance digests"
            )
    elif request.runtime_manifest_sha256 is not None:
        raise EffectLeaseBindingMismatch(
            "non-runtime entrypoints cannot attach runtime conformance"
        )

    issued = _as_utc(issued_at, "issued_at")
    expires = _as_utc(expires_at, "expires_at")
    if expires <= issued:
        raise ValueError("effect lease expires_at must be after issued_at")
    if expires - issued > _MAX_LEASE_TTL:
        raise ValueError("effect lease TTL exceeds the 24-hour Gate-0 maximum")
    reg_sha = registry_sha256(tuple(registry_map.values()))
    provenance = ContractProvenance(
        origin="kernel.effect-lease",
        source_revision=request.provenance.source_revision,
        created_at=_timestamp(issued),
        input_digests=tuple(
            sorted(
                {
                    request.digest,
                    policy_decision.digest,
                    reg_sha,
                    *(
                        [request.runtime_manifest_sha256, request.runtime_conformance_sha256]
                        if request.runtime_manifest_sha256 is not None
                        else []
                    ),
                }
            )
        ),
        trace_id=request.provenance.trace_id,
    )
    placeholder = EffectLease(
        lease_id=lease_id,
        request_id=request.request_id,
        request_sha256=request.digest,
        policy_decision_id=policy_decision.decision_id,
        policy_decision_sha256=policy_decision.digest,
        registry_sha256=reg_sha,
        entrypoint_id=request.entrypoint_id,
        requested_effects=wanted,
        effect_scope=request.effect_scope,
        idempotency_namespace=request.idempotency_namespace,
        kill_switch_generation=request.kill_switch_generation,
        runtime_id=spec.runtime_id,
        runtime_manifest_sha256=request.runtime_manifest_sha256,
        runtime_conformance_sha256=request.runtime_conformance_sha256,
        issuer_key_id=issuer_key_id,
        issued_at=_timestamp(issued),
        expires_at=_timestamp(expires),
        signature_sha256="0" * 64,
        provenance=provenance,
    )
    return dataclasses.replace(
        placeholder,
        signature_sha256=_signature(placeholder.signing_digest, secret),
    )


def verify_effect_lease(
    lease: EffectLease,
    *,
    request: EffectLeaseRequest,
    policy_decision: PolicyDecision,
    keyring: Mapping[str, bytes | str],
    current_kill_switch_generation: int,
    now: datetime | None = None,
    registry: Mapping[str, EntrypointSpec] | Sequence[EntrypointSpec] = REGISTRY_BY_ID,
) -> None:
    secret = keyring.get(lease.issuer_key_id)
    if secret is None:
        raise EffectLeaseSignatureError("effect lease issuer key is unknown")
    expected_signature = _signature(lease.signing_digest, secret)
    if not hmac.compare_digest(lease.signature_sha256, expected_signature):
        raise EffectLeaseSignatureError("effect lease signature mismatch")
    instant = (
        _as_utc(now, "now") if now is not None else _utc_now()
    )
    issued = _parse_utc(lease.issued_at, "lease.issued_at")
    expires = _parse_utc(lease.expires_at, "lease.expires_at")
    if instant < issued:
        raise EffectLeaseExpired("effect lease is not valid yet")
    if instant >= expires:
        raise EffectLeaseExpired("effect lease has expired")
    if current_kill_switch_generation != lease.kill_switch_generation:
        raise EffectLeaseBindingMismatch("effect lease kill-switch generation is stale")
    _scope_requirements(lease.requested_effects, lease.effect_scope)

    registry_map = _registry_map(registry)
    spec = registry_map.get(lease.entrypoint_id)
    if spec is None or spec.wiring is not Wiring.CENTRAL:
        raise EffectLeaseBindingMismatch("leased entrypoint is not currently central")
    if registry_sha256(tuple(registry_map.values())) != lease.registry_sha256:
        raise EffectLeaseBindingMismatch("entrypoint registry changed after lease issuance")
    comparisons = {
        "request_id": (lease.request_id, request.request_id),
        "request_sha256": (lease.request_sha256, request.digest),
        "policy_decision_id": (lease.policy_decision_id, policy_decision.decision_id),
        "policy_decision_sha256": (lease.policy_decision_sha256, policy_decision.digest),
        "entrypoint_id": (lease.entrypoint_id, request.entrypoint_id),
        "requested_effects": (lease.requested_effects, request.requested_effects),
        "effect_scope": (lease.effect_scope, request.effect_scope),
        "idempotency_namespace": (
            lease.idempotency_namespace,
            request.idempotency_namespace,
        ),
        "kill_switch_generation": (
            lease.kill_switch_generation,
            request.kill_switch_generation,
        ),
        "runtime_manifest_sha256": (
            lease.runtime_manifest_sha256,
            request.runtime_manifest_sha256,
        ),
        "runtime_conformance_sha256": (
            lease.runtime_conformance_sha256,
            request.runtime_conformance_sha256,
        ),
        "runtime_id": (lease.runtime_id, spec.runtime_id),
        "policy_subject_id": (policy_decision.subject_id, request.request_id),
        "policy_subject_sha256": (policy_decision.subject_sha256, request.digest),
        "policy_verdict": (policy_decision.verdict, "allow"),
        "policy_effect_scope": (policy_decision.effect_scope, request.effect_scope),
        "lease_source_revision": (
            lease.provenance.source_revision,
            request.provenance.source_revision,
        ),
        "policy_source_revision": (
            policy_decision.provenance.source_revision,
            request.provenance.source_revision,
        ),
    }
    mismatches = sorted(
        name for name, (actual, expected) in comparisons.items() if actual != expected
    )
    if mismatches:
        raise EffectLeaseBindingMismatch(
            "effect lease binding mismatch: " + ", ".join(mismatches)
        )


class EffectLeaseLedger:
    """SQLite authority for grants, starts, replay, revocation and terminals."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), isolation_level=None, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS effect_leases (
                    lease_sha256 TEXT PRIMARY KEY,
                    lease_id TEXT NOT NULL UNIQUE,
                    request_sha256 TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    policy_decision_sha256 TEXT NOT NULL,
                    policy_decision_json TEXT NOT NULL,
                    registry_sha256 TEXT NOT NULL,
                    entrypoint_id TEXT NOT NULL,
                    lease_json TEXT NOT NULL,
                    issued_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT,
                    revocation_reason TEXT
                )
                """
            )
            # Revision-safe additive migration for Gate-0 databases created by
            # the first lease packet.  Old rows remain readable as historical
            # evidence but cannot be reconstructed until an authenticated,
            # byte-identical `grant()` supplies the missing contracts.
            lease_columns = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(effect_leases)")
            }
            if "request_json" not in lease_columns:
                conn.execute("ALTER TABLE effect_leases ADD COLUMN request_json TEXT")
            if "policy_decision_json" not in lease_columns:
                conn.execute(
                    "ALTER TABLE effect_leases ADD COLUMN policy_decision_json TEXT"
                )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS effect_executions (
                    execution_id TEXT PRIMARY KEY,
                    lease_sha256 TEXT NOT NULL REFERENCES effect_leases(lease_sha256),
                    idempotency_key TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    start_receipt_sha256 TEXT NOT NULL UNIQUE,
                    start_receipt_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    terminal_receipt_sha256 TEXT UNIQUE,
                    terminal_receipt_json TEXT,
                    UNIQUE(lease_sha256, idempotency_key)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_effect_executions_active "
                "ON effect_executions(lease_sha256, state)"
            )

    def grant(
        self,
        lease: EffectLease,
        *,
        request: EffectLeaseRequest,
        policy_decision: PolicyDecision,
        keyring: Mapping[str, bytes | str],
        current_kill_switch_generation: int,
        granted_at: datetime | None = None,
        registry: Mapping[str, EntrypointSpec] | Sequence[EntrypointSpec] = REGISTRY_BY_ID,
    ) -> None:
        verify_effect_lease(
            lease,
            request=request,
            policy_decision=policy_decision,
            keyring=keyring,
            current_kill_switch_generation=current_kill_switch_generation,
            now=granted_at or _utc_now(),
            registry=registry,
        )
        payload = lease.to_json()
        request_payload = request.to_json()
        policy_payload = policy_decision.to_json()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT lease_json, request_json, policy_decision_json
                FROM effect_leases WHERE lease_sha256=? OR lease_id=?
                """,
                (lease.digest, lease.lease_id),
            ).fetchone()
            if row is not None:
                if row["lease_json"] != payload:
                    raise EffectLeaseReplay(
                        "lease identity was already used for different content"
                    )
                if row["request_json"] not in (None, request_payload):
                    raise EffectLeaseReplay(
                        "persisted lease request bytes do not match the authenticated grant"
                    )
                if row["policy_decision_json"] not in (None, policy_payload):
                    raise EffectLeaseReplay(
                        "persisted policy bytes do not match the authenticated grant"
                    )
                # Backfill only after full lease verification above.  This is
                # the one safe migration for a pre-recovery row: the supplied
                # request and policy are the exact contracts bound by the
                # authenticated lease.
                conn.execute(
                    """
                    UPDATE effect_leases
                    SET request_json=COALESCE(request_json, ?),
                        policy_decision_json=COALESCE(policy_decision_json, ?)
                    WHERE lease_sha256=?
                    """,
                    (request_payload, policy_payload, lease.digest),
                )
                conn.execute("COMMIT")
                return
            conn.execute(
                """
                INSERT INTO effect_leases (
                    lease_sha256, lease_id, request_sha256, request_json,
                    policy_decision_sha256, policy_decision_json,
                    registry_sha256, entrypoint_id,
                    lease_json, issued_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lease.digest,
                    lease.lease_id,
                    lease.request_sha256,
                    request_payload,
                    lease.policy_decision_sha256,
                    policy_payload,
                    lease.registry_sha256,
                    lease.entrypoint_id,
                    payload,
                    lease.issued_at,
                    lease.expires_at,
                ),
            )
            conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise EffectLeaseReplay("effect lease grant conflicts with persisted identity") from exc
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

    def load_grant(
        self,
        lease_sha256: str,
        *,
        keyring: Mapping[str, bytes | str],
        current_kill_switch_generation: int,
        now: datetime | None = None,
        registry: Mapping[str, EntrypointSpec] | Sequence[EntrypointSpec] = REGISTRY_BY_ID,
    ) -> PersistedEffectGrant:
        """Reload and re-authenticate the exact contracts behind one grant.

        This is the restart seam.  Key material is supplied by the composition
        root and is never recovered from SQLite.  Expired or stale-generation
        grants are intentionally refused here; their historical executions
        remain inspectable through :meth:`execution_record`.
        """

        digest = _sha256(lease_sha256, "lease_sha256")
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT lease_json, request_json, policy_decision_json,
                       request_sha256, policy_decision_sha256,
                       revoked_at, revocation_reason
                FROM effect_leases WHERE lease_sha256=?
                """,
                (digest,),
            ).fetchone()
        if row is None:
            raise EffectLeaseStateError("unknown persisted effect lease")
        if row["request_json"] is None or row["policy_decision_json"] is None:
            raise EffectLeaseStateError(
                "persisted effect lease predates recoverable request/policy metadata"
            )

        try:
            lease_payload = json.loads(row["lease_json"])
            request_payload = json.loads(row["request_json"])
            policy_payload = json.loads(row["policy_decision_json"])
            if not all(
                isinstance(value, dict)
                for value in (lease_payload, request_payload, policy_payload)
            ):
                raise ValueError("persisted contract JSON must contain objects")
            lease = EffectLease.from_dict(lease_payload)
            request = EffectLeaseRequest.from_dict(request_payload)
            policy = PolicyDecision.from_dict(policy_payload)
        except (
            TypeError,
            ValueError,
            KeyError,
            json.JSONDecodeError,
            EffectLeaseBindingMismatch,
        ) as exc:
            raise EffectLeaseStateError(
                "persisted effect grant contains invalid contract bytes"
            ) from exc

        canonical_mismatches = []
        if lease.to_json() != row["lease_json"] or lease.digest != digest:
            canonical_mismatches.append("lease")
        if (
            request.to_json() != row["request_json"]
            or request.digest != row["request_sha256"]
        ):
            canonical_mismatches.append("request")
        if (
            policy.to_json() != row["policy_decision_json"]
            or policy.digest != row["policy_decision_sha256"]
        ):
            canonical_mismatches.append("policy")
        if canonical_mismatches:
            raise EffectLeaseStateError(
                "persisted effect grant failed canonical identity checks: "
                + ", ".join(canonical_mismatches)
            )

        verify_effect_lease(
            lease,
            request=request,
            policy_decision=policy,
            keyring=keyring,
            current_kill_switch_generation=current_kill_switch_generation,
            now=now or _utc_now(),
            registry=registry,
        )
        return PersistedEffectGrant(
            lease=lease,
            request=request,
            policy_decision=policy,
            revoked_at=row["revoked_at"],
            revocation_reason=row["revocation_reason"],
        )

    def revoke(self, lease_sha256: str, *, reason: str, revoked_at: datetime | None = None) -> None:
        digest = _sha256(lease_sha256, "lease_sha256")
        if not reason.strip() or len(reason) > 1000:
            raise ValueError("revocation reason must be non-empty and bounded")
        timestamp = _timestamp(revoked_at or _utc_now())
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT revoked_at FROM effect_leases WHERE lease_sha256=?", (digest,)
            ).fetchone()
            if row is None:
                raise EffectLeaseStateError("cannot revoke an unknown lease")
            if row["revoked_at"] is not None:
                raise EffectLeaseStateError("effect lease is already revoked")
            conn.execute(
                "UPDATE effect_leases SET revoked_at=?, revocation_reason=? WHERE lease_sha256=?",
                (timestamp, reason, digest),
            )
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

    def begin(
        self,
        lease: EffectLease,
        execution: EffectExecutionRequest,
        *,
        request: EffectLeaseRequest,
        policy_decision: PolicyDecision,
        keyring: Mapping[str, bytes | str],
        guard_decisions: Iterable[GuardDecision],
        current_kill_switch_generation: int,
        started_at: datetime | None = None,
        registry: Mapping[str, EntrypointSpec] | Sequence[EntrypointSpec] = REGISTRY_BY_ID,
    ) -> EffectStartResult:
        verification_instant = _as_utc(started_at, "started_at") if started_at is not None else _utc_now()
        verify_effect_lease(
            lease,
            request=request,
            policy_decision=policy_decision,
            keyring=keyring,
            current_kill_switch_generation=current_kill_switch_generation,
            now=verification_instant,
            registry=registry,
        )
        _validate_narrowed_scope(execution, lease)
        registry_map = _registry_map(registry)
        boundary = begin_effect(
            lease.entrypoint_id,
            execution.requested_effects,
            guard_decisions,
            registry=registry_map,
        )
        request_json = canonical_json(execution.to_dict())

        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            lease_row = conn.execute(
                "SELECT lease_json, expires_at, revoked_at FROM effect_leases WHERE lease_sha256=?",
                (lease.digest,),
            ).fetchone()
            if lease_row is None:
                raise EffectLeaseStateError("effect lease was not persisted before start")
            if lease_row["lease_json"] != lease.to_json():
                raise EffectLeaseStateError("persisted lease bytes do not match supplied lease")
            if lease_row["revoked_at"] is not None:
                raise EffectLeaseStateError("effect lease is revoked")
            persistence_instant = (
                verification_instant if started_at is not None else _utc_now()
            )
            if persistence_instant >= _parse_utc(
                lease_row["expires_at"], "persisted lease expiry"
            ):
                raise EffectLeaseExpired("persisted effect lease expired before start")
            existing = conn.execute(
                """
                SELECT lease_sha256, idempotency_key, request_sha256, start_receipt_json
                FROM effect_executions
                WHERE execution_id=? OR (lease_sha256=? AND idempotency_key=?)
                """,
                (execution.execution_id, lease.digest, execution.idempotency_key),
            ).fetchone()
            if existing is not None:
                if (
                    existing["lease_sha256"] != lease.digest
                    or existing["idempotency_key"] != execution.idempotency_key
                    or existing["request_sha256"] != execution.digest
                ):
                    raise EffectLeaseReplay(
                        "execution identity or idempotency key was reused across a different lease or scope"
                    )
                stored = json.loads(existing["start_receipt_json"])
                replay_receipt = LeasedEffectStartReceipt(**stored)
                conn.execute("COMMIT")
                return EffectStartResult(receipt=replay_receipt, execute=False)
            active = conn.execute(
                "SELECT COUNT(*) FROM effect_executions WHERE lease_sha256=? AND state='STARTED'",
                (lease.digest,),
            ).fetchone()[0]
            if active >= lease.effect_scope.max_concurrency:
                raise EffectLeaseConcurrencyError("effect lease concurrency ceiling reached")
            payload = {
                "lease_sha256": lease.digest,
                "execution_id": execution.execution_id,
                "idempotency_key": execution.idempotency_key,
                "execution_request_sha256": execution.digest,
                "boundary_receipt_sha256": boundary.receipt_sha256,
                "started_at": _timestamp(persistence_instant),
            }
            receipt = LeasedEffectStartReceipt(
                receipt_sha256=canonical_sha(payload), **payload
            )
            receipt_json = canonical_json(receipt.to_dict())
            conn.execute(
                """
                INSERT INTO effect_executions (
                    execution_id, lease_sha256, idempotency_key,
                    request_sha256, request_json, start_receipt_sha256,
                    start_receipt_json, state, started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'STARTED', ?)
                """,
                (
                    execution.execution_id,
                    lease.digest,
                    execution.idempotency_key,
                    execution.digest,
                    request_json,
                    receipt.receipt_sha256,
                    receipt_json,
                    receipt.started_at,
                ),
            )
            conn.execute("COMMIT")
            return EffectStartResult(receipt=receipt, execute=True)
        except sqlite3.IntegrityError as exc:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise EffectLeaseReplay("effect execution identity was already consumed") from exc
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

    def finish(
        self,
        start_receipt: LeasedEffectStartReceipt,
        *,
        outcome: str,
        output_digests: Iterable[str] = (),
        detail_sha256: str | None = None,
        finished_at: datetime | None = None,
    ) -> EffectTerminalReceipt:
        normalized_outcome = str(outcome).upper()
        if normalized_outcome not in _TERMINAL_STATES:
            raise ValueError("outcome must be completed, failed, or cancelled")
        outputs = tuple(
            sorted({_sha256(value, "output_digest") for value in output_digests})
        )
        detail = _sha256(detail_sha256, "detail_sha256") if detail_sha256 is not None else None
        timestamp = _timestamp(finished_at or _utc_now())
        payload = {
            "lease_sha256": start_receipt.lease_sha256,
            "execution_id": start_receipt.execution_id,
            "start_receipt_sha256": start_receipt.receipt_sha256,
            "outcome": normalized_outcome,
            "output_digests": list(outputs),
            "detail_sha256": detail,
            "finished_at": timestamp,
        }
        receipt = EffectTerminalReceipt(
            lease_sha256=start_receipt.lease_sha256,
            execution_id=start_receipt.execution_id,
            start_receipt_sha256=start_receipt.receipt_sha256,
            outcome=normalized_outcome,
            output_digests=outputs,
            detail_sha256=detail,
            finished_at=timestamp,
            receipt_sha256=canonical_sha(payload),
        )
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT state, start_receipt_sha256
                FROM effect_executions WHERE execution_id=? AND lease_sha256=?
                """,
                (start_receipt.execution_id, start_receipt.lease_sha256),
            ).fetchone()
            if row is None:
                raise EffectLeaseStateError("unknown effect execution")
            if row["start_receipt_sha256"] != start_receipt.receipt_sha256:
                raise EffectLeaseStateError("start receipt does not match persisted execution")
            if row["state"] != "STARTED":
                raise EffectLeaseStateError("effect execution is already terminal")
            conn.execute(
                """
                UPDATE effect_executions
                SET state=?, finished_at=?, terminal_receipt_sha256=?, terminal_receipt_json=?
                WHERE execution_id=?
                """,
                (
                    normalized_outcome,
                    timestamp,
                    receipt.receipt_sha256,
                    canonical_json(receipt.to_dict()),
                    start_receipt.execution_id,
                ),
            )
            conn.execute("COMMIT")
            return receipt
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

    def execution_state(self, execution_id: str) -> str | None:
        value = _identifier(execution_id, "execution_id")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state FROM effect_executions WHERE execution_id=?", (value,)
            ).fetchone()
        return None if row is None else str(row["state"])

    def execution_record(
        self, execution_id: str
    ) -> PersistedEffectExecution | None:
        """Load one execution with canonical-byte and receipt validation.

        Unlike :meth:`load_grant`, this historical/reconciliation read does not
        require a currently valid lease.  It performs no effect and never turns
        a ``STARTED`` row into permission to call the provider again.
        """

        value = _identifier(execution_id, "execution_id")
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT lease_sha256, idempotency_key, request_sha256,
                       request_json, start_receipt_sha256,
                       start_receipt_json, state, started_at, finished_at,
                       terminal_receipt_sha256, terminal_receipt_json
                FROM effect_executions WHERE execution_id=?
                """,
                (value,),
            ).fetchone()
        if row is None:
            return None

        try:
            request_payload = json.loads(row["request_json"])
            start_payload = json.loads(row["start_receipt_json"])
            if not isinstance(request_payload, dict) or not isinstance(
                start_payload, dict
            ):
                raise ValueError("execution JSON must contain objects")
            request = EffectExecutionRequest(**request_payload)
            start = LeasedEffectStartReceipt(**start_payload)
        except (
            TypeError,
            ValueError,
            KeyError,
            json.JSONDecodeError,
            EffectLeaseBindingMismatch,
        ) as exc:
            raise EffectLeaseStateError(
                "persisted effect execution contains invalid start bytes"
            ) from exc

        start_body = start.to_dict()
        start_digest = start_body.pop("receipt_sha256")
        start_mismatches = []
        if canonical_json(request.to_dict()) != row["request_json"]:
            start_mismatches.append("request_json")
        if request.digest != row["request_sha256"]:
            start_mismatches.append("request_sha256")
        if canonical_json(start.to_dict()) != row["start_receipt_json"]:
            start_mismatches.append("start_receipt_json")
        if start.receipt_sha256 != row["start_receipt_sha256"]:
            start_mismatches.append("start_receipt_sha256")
        if canonical_sha(start_body) != start_digest:
            start_mismatches.append("start_receipt_digest")
        if start.lease_sha256 != row["lease_sha256"]:
            start_mismatches.append("lease_sha256")
        if start.execution_id != value or request.execution_id != value:
            start_mismatches.append("execution_id")
        if start.idempotency_key != row["idempotency_key"]:
            start_mismatches.append("idempotency_key")
        if start.idempotency_key != request.idempotency_key:
            start_mismatches.append("request_idempotency_key")
        if start.execution_request_sha256 != request.digest:
            start_mismatches.append("execution_request_binding")
        if start.started_at != row["started_at"]:
            start_mismatches.append("started_at")
        if start_mismatches:
            raise EffectLeaseStateError(
                "persisted effect execution failed start identity checks: "
                + ", ".join(sorted(set(start_mismatches)))
            )

        state = str(row["state"])
        terminal: EffectTerminalReceipt | None = None
        if state == "STARTED":
            if any(
                row[name] is not None
                for name in (
                    "finished_at",
                    "terminal_receipt_sha256",
                    "terminal_receipt_json",
                )
            ):
                raise EffectLeaseStateError(
                    "STARTED execution unexpectedly carries terminal fields"
                )
        elif state in _TERMINAL_STATES:
            if any(
                row[name] is None
                for name in (
                    "finished_at",
                    "terminal_receipt_sha256",
                    "terminal_receipt_json",
                )
            ):
                raise EffectLeaseStateError(
                    "terminal execution is missing terminal receipt fields"
                )
            try:
                terminal_payload = json.loads(row["terminal_receipt_json"])
                if not isinstance(terminal_payload, dict):
                    raise ValueError("terminal receipt JSON must contain an object")
                terminal_payload["output_digests"] = tuple(
                    terminal_payload["output_digests"]
                )
                terminal = EffectTerminalReceipt(**terminal_payload)
            except (
                TypeError,
                ValueError,
                KeyError,
                json.JSONDecodeError,
                EffectLeaseBindingMismatch,
            ) as exc:
                raise EffectLeaseStateError(
                    "persisted effect execution contains invalid terminal bytes"
                ) from exc
            terminal_body = terminal.to_dict()
            terminal_digest = terminal_body.pop("receipt_sha256")
            terminal_mismatches = []
            if canonical_json(terminal.to_dict()) != row["terminal_receipt_json"]:
                terminal_mismatches.append("terminal_receipt_json")
            if terminal.receipt_sha256 != row["terminal_receipt_sha256"]:
                terminal_mismatches.append("terminal_receipt_sha256")
            if canonical_sha(terminal_body) != terminal_digest:
                terminal_mismatches.append("terminal_receipt_digest")
            if terminal.lease_sha256 != start.lease_sha256:
                terminal_mismatches.append("terminal_lease_binding")
            if terminal.execution_id != value:
                terminal_mismatches.append("terminal_execution_binding")
            if terminal.start_receipt_sha256 != start.receipt_sha256:
                terminal_mismatches.append("terminal_start_binding")
            if terminal.outcome != state:
                terminal_mismatches.append("terminal_state")
            if terminal.finished_at != row["finished_at"]:
                terminal_mismatches.append("finished_at")
            if terminal_mismatches:
                raise EffectLeaseStateError(
                    "persisted effect execution failed terminal identity checks: "
                    + ", ".join(sorted(set(terminal_mismatches)))
                )
        else:
            raise EffectLeaseStateError(
                f"persisted effect execution has unknown state {state!r}"
            )

        return PersistedEffectExecution(
            request=request,
            start_receipt=start,
            state=state,
            terminal_receipt=terminal,
        )


@dataclass(frozen=True)
class LeasedEffectAuthorization:
    """One explicit, persisted capability for a single effectful call path.

    The bundle carries every authority needed by :class:`EffectLeaseLedger`
    without teaching production entrypoints how to mint leases or discover
    secrets from ambient configuration.  Entry points may *consume* this
    capability; they cannot construct a valid one without the signed lease,
    exact policy decision, issuer keyring, and persisted ledger grant.
    """

    lease: EffectLease
    request: EffectLeaseRequest
    policy_decision: PolicyDecision
    ledger: "EffectLeaseLedger"
    keyring: Mapping[str, bytes | str] = field(repr=False)
    guard_decisions: tuple[GuardDecision, ...]
    current_kill_switch_generation: int
    registry: Mapping[str, EntrypointSpec] | Sequence[EntrypointSpec] = field(
        default=REGISTRY_BY_ID, repr=False
    )

    def __post_init__(self) -> None:
        if self.lease.entrypoint_id != self.request.entrypoint_id:
            raise EffectLeaseBindingMismatch(
                "authorization lease and request name different entrypoints"
            )
        if not self.guard_decisions:
            raise EffectLeaseBindingMismatch(
                "authorization requires concrete guard decisions"
            )
        object.__setattr__(self, "guard_decisions", tuple(self.guard_decisions))
        object.__setattr__(self, "keyring", dict(self.keyring))

    def begin_effect(
        self,
        execution: EffectExecutionRequest,
        *,
        started_at: datetime | None = None,
    ) -> EffectStartResult:
        """Persist and verify the start before the entrypoint performs work."""

        return self.ledger.begin(
            self.lease,
            execution,
            request=self.request,
            policy_decision=self.policy_decision,
            keyring=self.keyring,
            guard_decisions=self.guard_decisions,
            current_kill_switch_generation=self.current_kill_switch_generation,
            started_at=started_at,
            registry=self.registry,
        )

    def finish_effect(
        self,
        start_receipt: LeasedEffectStartReceipt,
        *,
        outcome: str,
        output_digests: Iterable[str] = (),
        detail_sha256: str | None = None,
        finished_at: datetime | None = None,
    ) -> EffectTerminalReceipt:
        """Persist the terminal outcome against the exact start receipt."""

        return self.ledger.finish(
            start_receipt,
            outcome=outcome,
            output_digests=output_digests,
            detail_sha256=detail_sha256,
            finished_at=finished_at,
        )
