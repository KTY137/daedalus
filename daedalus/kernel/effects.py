# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

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
        # Validate names against the canonical Effect enum without changing
        # their deterministic sorted representation.
        for value in self.requested_effects:
            try:
                Effect(value)
            except ValueError as exc:
                raise ValueError(f"unknown requested effect {value!r}") from exc

    def to_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)

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

    def to_dict(self) -> dict[str, object]:
        return {
            **dataclasses.asdict(self),
            "output_digests": list(self.output_digests),
        }


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
                    policy_decision_sha256 TEXT NOT NULL,
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
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT lease_json FROM effect_leases WHERE lease_sha256=? OR lease_id=?",
                (lease.digest, lease.lease_id),
            ).fetchone()
            if row is not None:
                if row["lease_json"] == payload:
                    conn.execute("COMMIT")
                    return
                raise EffectLeaseReplay("lease identity was already used for different content")
            conn.execute(
                """
                INSERT INTO effect_leases (
                    lease_sha256, lease_id, request_sha256,
                    policy_decision_sha256, registry_sha256, entrypoint_id,
                    lease_json, issued_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lease.digest,
                    lease.lease_id,
                    lease.request_sha256,
                    lease.policy_decision_sha256,
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
