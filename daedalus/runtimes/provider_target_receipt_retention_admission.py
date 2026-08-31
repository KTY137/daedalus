"""Read-only persisted-lease and topology admission for receipt retention.

This packet stops before the durable effect start and before receipt retention.
It replays the signed retention preflight, authenticates the exact persisted
non-runtime Effect Lease through the query-only replay projection, and proves
that all protected filesystem targets remain concrete and disjoint.

The returned receipt is admission evidence, not execution authority. A retained
``STARTED`` execution is reported as ``started`` and never authorizes automatic
re-execution, retention, completion, promotion, or a Gate transition.
"""
from __future__ import annotations

import os
import re
import sqlite3
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping

from daedalus.kernel.authorization import NonRuntimeEffectAuthorization
from daedalus.kernel.contracts import EffectLease, EffectLeaseRequest
from daedalus.kernel.effect_replay import (
    EffectExecutionReplaySnapshot,
    EffectReplayProjectionError,
    inspect_effect_execution,
)
from daedalus.kernel.effects import (
    EffectExecutionRequest,
    EffectLeaseError,
    EffectLeaseLedger,
)
from daedalus.kernel.source_trees import SourceTreeStore
from daedalus.runtimes.contracts.ports import (
    RepositoryHeadReceiptVerifier,
    RetentionInventoryScanner,
)
from daedalus.runtimes.provider_target_receipt_ledger import (
    ProviderTargetReceiptLedger,
)
from daedalus.runtimes.provider_target_receipt_retention_contract import (
    RETENTION_ENTRYPOINT,
    RETENTION_GUARD_CONTRACT,
)
from daedalus.runtimes.provider_target_receipt_retention_preflight import (
    ProviderTargetReceiptRetentionPreflightError,
    ProviderTargetReceiptRetentionPreflightReceipt,
    verify_provider_target_receipt_retention_preflight,
)
from daedalus.schemas import PolicyDecision, _repo_path, _revision, _sha256
from daedalus.spine.effect_boundary import GuardDecision
from daedalus.spine.envelope import canonical_sha
from daedalus.spine.ledger import SpineLedger

_EXECUTION_STATES = frozenset(
    {"not_started", "started", "COMPLETED", "FAILED", "CANCELLED"}
)
_TERMINAL_STATES = frozenset({"COMPLETED", "FAILED", "CANCELLED"})
_REVISION_40 = re.compile(r"^[0-9a-f]{40}$")
_GUARD_EVIDENCE = re.compile(
    r"^authority_sha256=[0-9a-f]{64};subject_sha256=[0-9a-f]{64}$"
)
_DIGEST_FIELDS = (
    "preflight_sha256",
    "provider_target_receipt_sha256",
    "retention_inventory_sha256",
    "retention_authority_sha256",
    "retention_execution_request_sha256",
    "retention_effect_lease_sha256",
    "retention_effect_lease_request_sha256",
    "retention_policy_decision_sha256",
)
_OPTIONAL_DIGEST_FIELDS = ("start_receipt_sha256", "terminal_receipt_sha256")
_PATH_FIELDS = (
    "primary_checkout_path",
    "retention_root_path",
    "event_store_path",
    "receipt_cas_path",
    "effect_lease_store_path",
)
_FALSE_CLAIMS = (
    "retention_write_performed",
    "automatic_reexecution_allowed",
    "canonical_entrypoint_registered",
    "gate_transition_authorized",
    "closed",
)


class ProviderTargetReceiptRetentionAdmissionError(RuntimeError):
    """Base class for fail-closed retention admission refusal."""


class ProviderTargetReceiptRetentionAdmissionShapeError(
    ProviderTargetReceiptRetentionAdmissionError
):
    """A caller supplied a malformed or non-exact admission subject."""


class ProviderTargetReceiptRetentionAdmissionBindingError(
    ProviderTargetReceiptRetentionAdmissionError
):
    """Persisted authority, topology, preflight, or replay state disagrees."""


_Identity = tuple[Path, int, int]


@dataclass(frozen=True)
class _TopologySnapshot:
    primary: _Identity
    retention_root: _Identity
    event_store: _Identity
    receipt_cas: _Identity
    receipt_cas_objects: _Identity
    effect_store: _Identity
    sqlite_companions: tuple[_Identity, ...]

    def __iter__(self) -> Iterator[Path]:
        yield self.primary[0]
        yield self.retention_root[0]
        yield self.event_store[0]
        yield self.receipt_cas[0]
        yield self.effect_store[0]


def _strict_scope_path(value: Any, label: str) -> str:
    if type(value) is not str:
        raise ProviderTargetReceiptRetentionAdmissionShapeError(
            f"{label} must be an exact string"
        )
    try:
        normalized = _repo_path(value, label)
    except (TypeError, ValueError) as exc:
        raise ProviderTargetReceiptRetentionAdmissionShapeError(
            f"{label} is malformed"
        ) from exc
    if normalized == "." or normalized != value:
        raise ProviderTargetReceiptRetentionAdmissionShapeError(
            f"{label} must be canonical non-root repository-relative POSIX"
        )
    return normalized


def _contains_symlink(path: Path) -> bool:
    current = Path(path.anchor) if path.is_absolute() else Path()
    for part in path.parts:
        if part == path.anchor:
            continue
        current = current / part
        if current.is_symlink():
            return True
    return False


def _identity(path: Path, label: str, *, directory: bool) -> _Identity:
    try:
        absolute = Path(os.path.abspath(os.fspath(path)))
        if _contains_symlink(absolute):
            raise ProviderTargetReceiptRetentionAdmissionBindingError(
                f"{label} path must not contain symlinks"
            )
        resolved = absolute.resolve(strict=True)
        info = resolved.stat()
    except ProviderTargetReceiptRetentionAdmissionError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            f"{label} cannot be resolved"
        ) from exc
    if directory:
        if not stat.S_ISDIR(info.st_mode):
            raise ProviderTargetReceiptRetentionAdmissionBindingError(
                f"{label} must be a real directory"
            )
    else:
        if not stat.S_ISREG(info.st_mode):
            raise ProviderTargetReceiptRetentionAdmissionBindingError(
                f"{label} must be a real regular file"
            )
        if info.st_nlink != 1:
            raise ProviderTargetReceiptRetentionAdmissionBindingError(
                f"{label} must have one filesystem identity"
            )
    return resolved, int(info.st_dev), int(info.st_ino)


def _same_identity(left: _Identity, right: _Identity) -> bool:
    return left[1:] == right[1:]


def _overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _sqlite_companion_paths(path: Path) -> tuple[Path, ...]:
    values: list[Path] = []
    for suffix in ("-wal", "-shm", "-journal"):
        candidate = Path(f"{path}{suffix}")
        if candidate.exists() or candidate.is_symlink():
            values.append(candidate)
    return tuple(values)


def _path_attribute(value: Any, label: str) -> Path:
    if not isinstance(value, Path):
        raise ProviderTargetReceiptRetentionAdmissionShapeError(
            f"{label} must be pathlib.Path"
        )
    return value


def _spine_database_identity(spine: SpineLedger) -> _Identity:
    connection = getattr(spine, "_conn", None)
    lock = getattr(spine, "_lock", None)
    if type(connection) is not sqlite3.Connection:
        raise ProviderTargetReceiptRetentionAdmissionShapeError(
            "retention_ledger.spine must retain one exact SQLite connection"
        )
    if lock is None or not hasattr(lock, "__enter__") or not hasattr(
        lock,
        "__exit__",
    ):
        raise ProviderTargetReceiptRetentionAdmissionShapeError(
            "retention_ledger.spine lock is malformed"
        )
    try:
        with lock:
            rows = connection.execute("PRAGMA database_list").fetchall()
    except (sqlite3.Error, RuntimeError, TypeError) as exc:
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "retention_ledger.spine connection cannot be inspected"
        ) from exc
    main_rows = [row for row in rows if len(row) >= 3 and row[1] == "main"]
    if len(main_rows) != 1 or type(main_rows[0][2]) is not str or not main_rows[0][2]:
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "retention_ledger.spine connection has no concrete main database"
        )
    return _identity(
        Path(main_rows[0][2]),
        "connected canonical Event Store",
        directory=False,
    )


def _verify_topology(
    *,
    repository_root: Path,
    retention_root: Path,
    retention_ledger: ProviderTargetReceiptLedger,
    effect_store_path: Path,
    event_store_scope_path: str,
    receipt_cas_scope_path: str,
) -> _TopologySnapshot:
    try:
        spine = retention_ledger.spine
        source_store = retention_ledger.source_store
        ledger_checkout = _path_attribute(
            retention_ledger.primary_checkout,
            "retention_ledger.primary_checkout",
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise ProviderTargetReceiptRetentionAdmissionShapeError(
            "retention_ledger topology is malformed"
        ) from exc
    if type(spine) is not SpineLedger:
        raise ProviderTargetReceiptRetentionAdmissionShapeError(
            "retention_ledger.spine must be exact SpineLedger"
        )
    if type(source_store) is not SourceTreeStore:
        raise ProviderTargetReceiptRetentionAdmissionShapeError(
            "retention_ledger.source_store must be exact SourceTreeStore"
        )
    if type(getattr(spine, "read_only", None)) is not bool or spine.read_only:
        raise ProviderTargetReceiptRetentionAdmissionShapeError(
            "retention_ledger.spine must be writable"
        )
    event_path = _path_attribute(
        getattr(spine, "path", None),
        "retention_ledger.spine.path",
    )
    cas_path = _path_attribute(
        getattr(source_store, "root", None),
        "retention_ledger.source_store.root",
    )
    objects_path = _path_attribute(
        getattr(source_store, "objects", None),
        "retention_ledger.source_store.objects",
    )

    primary = _identity(repository_root, "repository_root", directory=True)
    ledger_primary = _identity(
        ledger_checkout,
        "retention ledger primary checkout",
        directory=True,
    )
    if not _same_identity(primary, ledger_primary):
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "retention ledger is bound to a different Primary Checkout"
        )

    root = _identity(retention_root, "retention_root", directory=True)
    event = _identity(event_path, "canonical Event Store", directory=False)
    connected_event = _spine_database_identity(spine)
    if not _same_identity(event, connected_event):
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "SpineLedger.path is detached from its live SQLite connection"
        )
    cas = _identity(cas_path, "receipt CAS", directory=True)
    objects = _identity(objects_path, "receipt CAS objects", directory=True)
    effect = _identity(effect_store_path, "Effect-Lease store", directory=False)

    event_scope = _strict_scope_path(
        event_store_scope_path,
        "event_store_scope_path",
    )
    cas_scope = _strict_scope_path(
        receipt_cas_scope_path,
        "receipt_cas_scope_path",
    )
    expected_event = _identity(
        retention_root / Path(*event_scope.split("/")),
        "scoped canonical Event Store",
        directory=False,
    )
    expected_cas = _identity(
        retention_root / Path(*cas_scope.split("/")),
        "scoped receipt CAS",
        directory=True,
    )
    expected_objects = _identity(
        expected_cas[0] / "objects",
        "scoped receipt CAS objects",
        directory=True,
    )
    if not _same_identity(event, expected_event):
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "event_store_scope_path does not bind the concrete Event Store"
        )
    if not _same_identity(cas, expected_cas):
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "receipt_cas_scope_path does not bind the concrete receipt CAS"
        )
    if not _same_identity(objects, expected_objects):
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "receipt CAS objects are detached from the concrete receipt CAS"
        )
    if objects[0].parent != cas[0]:
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "receipt CAS objects must be the direct canonical child of receipt CAS"
        )
    if _overlap(primary[0], root[0]):
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "retention_root must be outside the Primary Checkout"
        )
    if root[0] not in event[0].parents:
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "canonical Event Store is outside retention_root"
        )
    if root[0] not in cas[0].parents:
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "receipt CAS is outside retention_root"
        )

    protected = (primary, event, cas, effect)
    for index, left in enumerate(protected):
        for right in protected[index + 1 :]:
            if _overlap(left[0], right[0]) or _same_identity(left, right):
                raise ProviderTargetReceiptRetentionAdmissionBindingError(
                    "Primary Checkout and retention stores must be pairwise disjoint"
                )
    for protected_row in (primary, event, effect):
        if _overlap(objects[0], protected_row[0]) or _same_identity(
            objects,
            protected_row,
        ):
            raise ProviderTargetReceiptRetentionAdmissionBindingError(
                "receipt CAS objects overlap another protected store"
            )

    companions: list[_Identity] = []
    known_identities = {(row[1], row[2]) for row in (*protected, objects)}
    known_paths = [row[0] for row in (*protected, objects)]
    for label, store in (
        ("canonical Event Store", event[0]),
        ("Effect-Lease store", effect[0]),
    ):
        for companion_path in _sqlite_companion_paths(store):
            companion = _identity(
                companion_path,
                f"{label} companion",
                directory=False,
            )
            identity_key = (companion[1], companion[2])
            if identity_key in known_identities or any(
                _overlap(companion[0], path) for path in known_paths
            ):
                raise ProviderTargetReceiptRetentionAdmissionBindingError(
                    f"{label} companion aliases or overlaps a protected path"
                )
            known_identities.add(identity_key)
            known_paths.append(companion[0])
            companions.append(companion)

    return _TopologySnapshot(
        primary=primary,
        retention_root=root,
        event_store=event,
        receipt_cas=cas,
        receipt_cas_objects=objects,
        effect_store=effect,
        sqlite_companions=tuple(companions),
    )


def _exact_guard(
    authorization: NonRuntimeEffectAuthorization,
    preflight: ProviderTargetReceiptRetentionPreflightReceipt,
) -> GuardDecision:
    expected = GuardDecision(
        contract=RETENTION_GUARD_CONTRACT,
        allowed=True,
        evidence=preflight.guard_evidence,
    )
    guards = authorization.guard_decisions
    if (
        type(guards) is not tuple
        or len(guards) != 1
        or type(guards[0]) is not GuardDecision
    ):
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "retention authorization must carry one exact guard decision"
        )
    if guards[0] != expected:
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "retention authorization guard is detached from the signed preflight"
        )
    return expected


def _verify_authorization_shape(
    authorization: NonRuntimeEffectAuthorization,
) -> None:
    exact = (
        (authorization.lease, EffectLease, "authorization.lease"),
        (authorization.request, EffectLeaseRequest, "authorization.request"),
        (
            authorization.policy_decision,
            PolicyDecision,
            "authorization.policy_decision",
        ),
        (
            authorization.effect_ledger,
            EffectLeaseLedger,
            "authorization.effect_ledger",
        ),
    )
    for value, expected, label in exact:
        if type(value) is not expected:
            raise ProviderTargetReceiptRetentionAdmissionShapeError(
                f"{label} must be exact {expected.__name__}"
            )
    if not isinstance(getattr(authorization.effect_ledger, "path", None), Path):
        raise ProviderTargetReceiptRetentionAdmissionShapeError(
            "authorization.effect_ledger.path must be pathlib.Path"
        )

    lease = authorization.lease
    request = authorization.request
    policy = authorization.policy_decision
    if request.entrypoint_id != RETENTION_ENTRYPOINT:
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "persisted Effect-Lease request names the wrong retention entrypoint"
        )
    if lease.entrypoint_id != RETENTION_ENTRYPOINT:
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "persisted Effect Lease names the wrong retention entrypoint"
        )
    if (
        lease.request_id != request.request_id
        or lease.request_sha256 != request.digest
        or lease.policy_decision_id != policy.decision_id
        or lease.policy_decision_sha256 != policy.digest
        or policy.subject_id != request.request_id
        or policy.subject_sha256 != request.digest
        or policy.verdict != "allow"
        or lease.requested_effects != request.requested_effects
        or lease.effect_scope != request.effect_scope
        or policy.effect_scope != request.effect_scope
        or lease.idempotency_namespace != request.idempotency_namespace
        or lease.kill_switch_generation != request.kill_switch_generation
        or lease.runtime_manifest_sha256 != request.runtime_manifest_sha256
        or lease.runtime_conformance_sha256 != request.runtime_conformance_sha256
    ):
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "persisted Effect-Lease authority components are detached"
        )


def _inspect_persisted_execution(
    authorization: NonRuntimeEffectAuthorization,
    execution: EffectExecutionRequest,
) -> EffectExecutionReplaySnapshot | None:
    try:
        replay = inspect_effect_execution(authorization, execution)
    except EffectReplayProjectionError as exc:
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "persisted retention Effect Lease or execution did not authenticate"
        ) from exc
    if replay is not None and type(replay) is not EffectExecutionReplaySnapshot:
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "effect replay returned a non-exact snapshot"
        )
    return replay


def _verify_live_unstarted_authority(
    authorization: NonRuntimeEffectAuthorization,
) -> None:
    try:
        authorization.verify()
    except (EffectLeaseError, TypeError, ValueError) as exc:
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "unstarted retention Effect Lease is not live and authentic"
        ) from exc


@dataclass(frozen=True)
class ProviderTargetReceiptRetentionAdmissionReceipt:
    """Canonical non-executing admission receipt for one retention execution."""

    source_revision: str
    preflight_sha256: str
    provider_target_receipt_sha256: str
    retention_inventory_sha256: str
    retention_authority_sha256: str
    retention_execution_request_sha256: str
    retention_effect_lease_sha256: str
    retention_effect_lease_request_sha256: str
    retention_policy_decision_sha256: str
    guard_contract: str
    guard_evidence: str
    execution_state: str
    start_receipt_sha256: str | None
    terminal_receipt_sha256: str | None
    primary_checkout_path: str
    retention_root_path: str
    event_store_path: str
    receipt_cas_path: str
    effect_lease_store_path: str

    def __post_init__(self) -> None:
        try:
            revision = _revision(self.source_revision, "source_revision")
            if _REVISION_40.fullmatch(revision) is None:
                raise ValueError("source_revision must be exact 40-hex commit")
            object.__setattr__(self, "source_revision", revision)
            for field in _DIGEST_FIELDS:
                object.__setattr__(
                    self,
                    field,
                    _sha256(getattr(self, field), field),
                )
            for field in _OPTIONAL_DIGEST_FIELDS:
                value = getattr(self, field)
                if value is not None:
                    object.__setattr__(self, field, _sha256(value, field))
        except (TypeError, ValueError) as exc:
            raise ProviderTargetReceiptRetentionAdmissionShapeError(
                "retention admission receipt is malformed"
            ) from exc

        if type(self.execution_state) is not str or (
            self.execution_state not in _EXECUTION_STATES
        ):
            raise ProviderTargetReceiptRetentionAdmissionShapeError(
                "retention admission execution_state is unknown"
            )
        if self.guard_contract != RETENTION_GUARD_CONTRACT:
            raise ProviderTargetReceiptRetentionAdmissionShapeError(
                "retention admission guard_contract is wrong"
            )
        if type(self.guard_evidence) is not str or (
            _GUARD_EVIDENCE.fullmatch(self.guard_evidence) is None
        ):
            raise ProviderTargetReceiptRetentionAdmissionShapeError(
                "retention admission guard_evidence is malformed"
            )
        if self.execution_state == "not_started":
            valid_receipts = (
                self.start_receipt_sha256 is None
                and self.terminal_receipt_sha256 is None
            )
        elif self.execution_state == "started":
            valid_receipts = (
                self.start_receipt_sha256 is not None
                and self.terminal_receipt_sha256 is None
            )
        else:
            valid_receipts = (
                self.start_receipt_sha256 is not None
                and self.terminal_receipt_sha256 is not None
            )
        if not valid_receipts:
            raise ProviderTargetReceiptRetentionAdmissionShapeError(
                "retention admission state and execution receipts disagree"
            )
        for field in _PATH_FIELDS:
            value = getattr(self, field)
            if (
                type(value) is not str
                or not value
                or len(value) > 4096
                or "\x00" in value
                or "\r" in value
                or "\n" in value
            ):
                raise ProviderTargetReceiptRetentionAdmissionShapeError(
                    f"{field} must be a bounded exact path string"
                )

    def to_dict(self) -> dict[str, Any]:
        terminal = self.execution_state in _TERMINAL_STATES
        return {
            "schema": "daedalus-provider-target-receipt-retention-admission/1",
            "source_revision": self.source_revision,
            "preflight_sha256": self.preflight_sha256,
            "provider_target_receipt_sha256": self.provider_target_receipt_sha256,
            "retention_inventory_sha256": self.retention_inventory_sha256,
            "retention_authority_sha256": self.retention_authority_sha256,
            "retention_execution_request_sha256": (
                self.retention_execution_request_sha256
            ),
            "retention_effect_lease_sha256": self.retention_effect_lease_sha256,
            "retention_effect_lease_request_sha256": (
                self.retention_effect_lease_request_sha256
            ),
            "retention_policy_decision_sha256": (
                self.retention_policy_decision_sha256
            ),
            "guard_contract": self.guard_contract,
            "guard_evidence": self.guard_evidence,
            "execution_state": self.execution_state,
            "start_receipt_sha256": self.start_receipt_sha256,
            "terminal_receipt_sha256": self.terminal_receipt_sha256,
            "primary_checkout_path": self.primary_checkout_path,
            "retention_root_path": self.retention_root_path,
            "event_store_path": self.event_store_path,
            "receipt_cas_path": self.receipt_cas_path,
            "effect_lease_store_path": self.effect_lease_store_path,
            "persisted_effect_lease_verified": True,
            "primary_checkout_disjointness_verified": True,
            "retention_effect_started": self.execution_state != "not_started",
            "retention_effect_terminal": terminal,
            "retention_write_performed": False,
            "automatic_reexecution_allowed": False,
            "canonical_entrypoint_registered": False,
            "gate_transition_authorized": False,
            "closed": False,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "ProviderTargetReceiptRetentionAdmissionReceipt":
        fields = {
            "source_revision",
            *_DIGEST_FIELDS,
            *_OPTIONAL_DIGEST_FIELDS,
            "guard_contract",
            "guard_evidence",
            "execution_state",
            *_PATH_FIELDS,
        }
        claims = {
            "persisted_effect_lease_verified",
            "primary_checkout_disjointness_verified",
            "retention_effect_started",
            "retention_effect_terminal",
            *_FALSE_CLAIMS,
        }
        if not isinstance(payload, Mapping) or set(payload) != {
            "schema",
            *fields,
            *claims,
        }:
            raise ProviderTargetReceiptRetentionAdmissionShapeError(
                "retention admission receipt fields are not exact"
            )
        if (
            payload["schema"]
            != "daedalus-provider-target-receipt-retention-admission/1"
        ):
            raise ProviderTargetReceiptRetentionAdmissionShapeError(
                "retention admission receipt schema is wrong"
            )
        state = payload["execution_state"]
        if type(state) is not str or state not in _EXECUTION_STATES:
            raise ProviderTargetReceiptRetentionAdmissionShapeError(
                "retention admission execution_state is unknown"
            )
        expected_claims = {
            "persisted_effect_lease_verified": True,
            "primary_checkout_disjointness_verified": True,
            "retention_effect_started": state != "not_started",
            "retention_effect_terminal": state in _TERMINAL_STATES,
            **{field: False for field in _FALSE_CLAIMS},
        }
        for field, expected in expected_claims.items():
            if payload[field] is not expected:
                raise ProviderTargetReceiptRetentionAdmissionShapeError(
                    f"retention admission receipt contains unsupported claim: {field}"
                )
        try:
            return cls(**{field: payload[field] for field in fields})
        except ProviderTargetReceiptRetentionAdmissionError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProviderTargetReceiptRetentionAdmissionShapeError(
                "retention admission receipt is malformed"
            ) from exc

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def _replay_preflight(
    *,
    repository_root: Path,
    repository_head_receipt: Any,
    receipt: Any,
    inventory: Any,
    authority: Any,
    execution: EffectExecutionRequest,
    effect_lease: EffectLease,
    expected_authority_id: str,
    authority_keyring: Mapping[str, bytes | str],
    event_store_scope_path: str,
    receipt_cas_scope_path: str,
    at: Any,
    repository_head_verifier: RepositoryHeadReceiptVerifier,
    retention_inventory_scanner: RetentionInventoryScanner,
) -> ProviderTargetReceiptRetentionPreflightReceipt:
    try:
        preflight = verify_provider_target_receipt_retention_preflight(
            repository_root,
            repository_head_receipt,
            receipt,
            inventory,
            authority,
            execution,
            effect_lease,
            expected_authority_id=expected_authority_id,
            authority_keyring=authority_keyring,
            event_store_scope_path=event_store_scope_path,
            receipt_cas_scope_path=receipt_cas_scope_path,
            at=at,
            repository_head_verifier=repository_head_verifier,
            retention_inventory_scanner=retention_inventory_scanner,
        )
    except ProviderTargetReceiptRetentionPreflightError as exc:
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "retention preflight did not reverify"
        ) from exc
    if type(preflight) is not ProviderTargetReceiptRetentionPreflightReceipt:
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "retention preflight returned a non-exact receipt"
        )
    if (
        preflight.retention_execution_request_sha256 != execution.digest
        or preflight.retention_effect_lease_sha256 != effect_lease.digest
        or preflight.provider_target_receipt_sha256 != receipt.digest
        or preflight.retention_inventory_sha256 != inventory.digest
        or preflight.retention_authority_sha256 != authority.digest
    ):
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "retention preflight is detached from admission subjects"
        )
    return preflight


def verify_provider_target_receipt_retention_admission(
    repository_root: Path,
    retention_root: Path,
    repository_head_receipt: Any,
    receipt: Any,
    inventory: Any,
    authority: Any,
    execution: EffectExecutionRequest,
    authorization: NonRuntimeEffectAuthorization,
    retention_ledger: ProviderTargetReceiptLedger,
    *,
    expected_authority_id: str,
    authority_keyring: Mapping[str, bytes | str],
    event_store_scope_path: str,
    receipt_cas_scope_path: str,
    at: Any,
    repository_head_verifier: RepositoryHeadReceiptVerifier,
    retention_inventory_scanner: RetentionInventoryScanner,
) -> ProviderTargetReceiptRetentionAdmissionReceipt:
    """Verify one non-executing central-admission candidate.

    Signed preflight, concrete topology, and persisted replay state are each
    fenced on both sides of the read-only admission. No lease or retention state
    is mutated. An unstarted lease is additionally reverified at facade-owned
    live time and kill-switch generation on both sides of the second replay.
    """

    if not isinstance(repository_root, Path) or not isinstance(
        retention_root,
        Path,
    ):
        raise ProviderTargetReceiptRetentionAdmissionShapeError(
            "repository_root and retention_root must be pathlib.Path"
        )
    exact = (
        (execution, EffectExecutionRequest, "execution"),
        (authorization, NonRuntimeEffectAuthorization, "authorization"),
        (retention_ledger, ProviderTargetReceiptLedger, "retention_ledger"),
    )
    for value, expected, label in exact:
        if type(value) is not expected:
            raise ProviderTargetReceiptRetentionAdmissionShapeError(
                f"{label} must be exact {expected.__name__}"
            )
    _verify_authorization_shape(authorization)

    execution_digest = execution.digest
    lease_digest = authorization.lease.digest
    request_digest = authorization.request.digest
    policy_digest = authorization.policy_decision.digest

    preflight = _replay_preflight(
        repository_root=repository_root,
        repository_head_receipt=repository_head_receipt,
        receipt=receipt,
        inventory=inventory,
        authority=authority,
        execution=execution,
        effect_lease=authorization.lease,
        expected_authority_id=expected_authority_id,
        authority_keyring=authority_keyring,
        event_store_scope_path=event_store_scope_path,
        receipt_cas_scope_path=receipt_cas_scope_path,
        at=at,
        repository_head_verifier=repository_head_verifier,
        retention_inventory_scanner=retention_inventory_scanner,
    )
    guard = _exact_guard(authorization, preflight)
    topology = _verify_topology(
        repository_root=repository_root,
        retention_root=retention_root,
        retention_ledger=retention_ledger,
        effect_store_path=authorization.effect_ledger.path,
        event_store_scope_path=event_store_scope_path,
        receipt_cas_scope_path=receipt_cas_scope_path,
    )
    replay = _inspect_persisted_execution(authorization, execution)
    if replay is None:
        _verify_live_unstarted_authority(authorization)

    final_topology = _verify_topology(
        repository_root=repository_root,
        retention_root=retention_root,
        retention_ledger=retention_ledger,
        effect_store_path=authorization.effect_ledger.path,
        event_store_scope_path=event_store_scope_path,
        receipt_cas_scope_path=receipt_cas_scope_path,
    )
    if final_topology != topology:
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "retention topology identity changed during persisted replay"
        )
    final_preflight = _replay_preflight(
        repository_root=repository_root,
        repository_head_receipt=repository_head_receipt,
        receipt=receipt,
        inventory=inventory,
        authority=authority,
        execution=execution,
        effect_lease=authorization.lease,
        expected_authority_id=expected_authority_id,
        authority_keyring=authority_keyring,
        event_store_scope_path=event_store_scope_path,
        receipt_cas_scope_path=receipt_cas_scope_path,
        at=at,
        repository_head_verifier=repository_head_verifier,
        retention_inventory_scanner=retention_inventory_scanner,
    )
    if final_preflight.digest != preflight.digest:
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "retention preflight changed during persisted replay"
        )
    if _exact_guard(authorization, final_preflight) != guard:
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "retention guard changed during persisted replay"
        )

    final_replay = _inspect_persisted_execution(authorization, execution)
    if final_replay != replay:
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "persisted retention execution changed during admission"
        )
    if final_replay is None:
        _verify_live_unstarted_authority(authorization)

    state = "not_started"
    start_digest = None
    terminal_digest = None
    if final_replay is not None:
        state = "started" if final_replay.state == "STARTED" else final_replay.state
        start_digest = final_replay.start_receipt.receipt_sha256
        terminal_digest = (
            None
            if final_replay.terminal_receipt is None
            else final_replay.terminal_receipt.receipt_sha256
        )

    primary, root, event, cas, effect_store = final_topology
    result = ProviderTargetReceiptRetentionAdmissionReceipt(
        source_revision=final_preflight.source_revision,
        preflight_sha256=final_preflight.digest,
        provider_target_receipt_sha256=(
            final_preflight.provider_target_receipt_sha256
        ),
        retention_inventory_sha256=final_preflight.retention_inventory_sha256,
        retention_authority_sha256=final_preflight.retention_authority_sha256,
        retention_execution_request_sha256=execution_digest,
        retention_effect_lease_sha256=lease_digest,
        retention_effect_lease_request_sha256=request_digest,
        retention_policy_decision_sha256=policy_digest,
        guard_contract=guard.contract,
        guard_evidence=guard.evidence,
        execution_state=state,
        start_receipt_sha256=start_digest,
        terminal_receipt_sha256=terminal_digest,
        primary_checkout_path=os.fspath(primary),
        retention_root_path=os.fspath(root),
        event_store_path=os.fspath(event),
        receipt_cas_path=os.fspath(cas),
        effect_lease_store_path=os.fspath(effect_store),
    )

    if (
        execution.digest != execution_digest
        or authorization.lease.digest != lease_digest
        or authorization.request.digest != request_digest
        or authorization.policy_decision.digest != policy_digest
        or receipt.digest != result.provider_target_receipt_sha256
        or inventory.digest != result.retention_inventory_sha256
        or authority.digest != result.retention_authority_sha256
        or result.preflight_sha256 != final_preflight.digest
    ):
        raise ProviderTargetReceiptRetentionAdmissionBindingError(
            "retention admission subject changed during verification"
        )
    return result


__all__ = [
    "ProviderTargetReceiptRetentionAdmissionBindingError",
    "ProviderTargetReceiptRetentionAdmissionError",
    "ProviderTargetReceiptRetentionAdmissionReceipt",
    "ProviderTargetReceiptRetentionAdmissionShapeError",
    "verify_provider_target_receipt_retention_admission",
]
