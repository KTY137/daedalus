"""Persisted restart-safe lifecycle for checkout-external isolated attempts.

The records in this module are the Gate-0 execution-lifecycle authority. They do
not invoke a provider or a runtime. A start is committed before an input source
tree is materialized, terminal replay is read-only, and a start without a
terminal receipt is an unknown outcome that cannot be executed automatically.
"""
from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Mapping

from daedalus.kernel.artifacts import ArtifactRef
from daedalus.kernel.source_trees import SourceTreeStore, StoredSourceTree
from daedalus.schemas import (
    AttemptContract,
    CanonicalContract,
    ContractProvenance,
    _identifier,
    _record_payload,
    _repo_path,
    _require_provenance_inputs,
    _revision,
    _sha256,
    _utc_timestamp,
)
from daedalus.spine.envelope import canonical_json, canonical_sha


_ATTEMPT_WORKSPACE_SCHEMA = "daedalus-attempt-workspace/1"
_TERMINAL_OUTCOMES = {"succeeded", "failed", "cancelled", "faulted"}
_MAX_REPORT_BYTES = 16 * 1024 * 1024


class AttemptLifecycleError(RuntimeError):
    """Base class for malformed, stale, replayed, or inconsistent lifecycle state."""


class AttemptBindingMismatch(AttemptLifecycleError):
    """The Attempt, input tree, workspace, or terminal material does not bind."""


class AttemptReplay(AttemptLifecycleError):
    """An identity was reused with different immutable lifecycle material."""


class AttemptStateError(AttemptLifecycleError):
    """Persisted attempt state is missing, corrupt, or transitioned illegally."""


class AttemptWorkspaceError(AttemptLifecycleError):
    """The checkout-external workspace boundary is unsafe or unavailable."""


def _artifact_ref(payload: Mapping[str, Any], label: str) -> ArtifactRef:
    if not isinstance(payload, Mapping):
        raise ValueError(f"{label} must be an object")
    return ArtifactRef(**_record_payload(ArtifactRef, payload, label))


def _path_identity(path: Path) -> str:
    normalized = os.path.normcase(str(path.resolve())).replace("\\", "/")
    return canonical_sha({"schema": _ATTEMPT_WORKSPACE_SCHEMA, "path": normalized})


def _workspace_relative_path(attempt: AttemptContract) -> str:
    return f"attempts/{attempt.attempt_id}-{attempt.digest[:16]}"


def _is_same_or_within(candidate: Path, parent: Path) -> bool:
    return candidate == parent or parent in candidate.parents


def _strict_json(payload: str, label: str) -> Mapping[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise AttemptStateError(f"{label} contains duplicate key {key!r}")
            result[key] = value
        return result

    try:
        parsed = json.loads(payload, object_pairs_hook=pairs)
    except (json.JSONDecodeError, ValueError) as exc:
        raise AttemptStateError(f"{label} is not strict JSON") from exc
    if not isinstance(parsed, Mapping):
        raise AttemptStateError(f"{label} must be a JSON object")
    return parsed


@dataclass(frozen=True)
class AttemptStartRecord(CanonicalContract):
    """Durable intent to materialize and execute one exact Attempt once."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.attempt-start"

    start_id: str
    attempt_id: str
    attempt_sha256: str
    source_revision: str
    input_tree: ArtifactRef
    workspace_parent_sha256: str
    workspace_relative_path: str
    started_at: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        for name in ("start_id", "attempt_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(
            self,
            "attempt_sha256",
            _sha256(self.attempt_sha256, "attempt_sha256"),
        )
        revision = _revision(self.source_revision, "source_revision")
        object.__setattr__(self, "source_revision", revision)
        if not isinstance(self.input_tree, ArtifactRef):
            raise ValueError("input_tree must be an ArtifactRef")
        object.__setattr__(
            self,
            "workspace_parent_sha256",
            _sha256(self.workspace_parent_sha256, "workspace_parent_sha256"),
        )
        relative = _repo_path(self.workspace_relative_path, "workspace_relative_path")
        if relative == "." or not relative.startswith("attempts/"):
            raise ValueError("workspace_relative_path must be below attempts/")
        object.__setattr__(self, "workspace_relative_path", relative)
        object.__setattr__(
            self,
            "started_at",
            _utc_timestamp(self.started_at, "started_at"),
        )
        if not isinstance(self.provenance, ContractProvenance):
            raise ValueError("start provenance must be ContractProvenance")
        if self.provenance.source_revision != revision:
            raise ValueError("start provenance must use the source revision")
        expected = tuple(
            sorted(
                {
                    self.attempt_sha256,
                    self.input_tree.sha256,
                    self.workspace_parent_sha256,
                }
            )
        )
        _require_provenance_inputs(self.provenance, expected, "attempt start")
        if tuple(self.provenance.input_digests) != expected:
            raise ValueError("attempt start provenance must bind exactly its inputs")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AttemptStartRecord":
        body = cls._contract_payload(payload)
        body["input_tree"] = _artifact_ref(body["input_tree"], "input_tree")
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)

    def same_subject(self, other: "AttemptStartRecord") -> bool:
        """Compare replay identity while retaining the first persisted timestamp."""
        return isinstance(other, AttemptStartRecord) and (
            self.start_id,
            self.attempt_id,
            self.attempt_sha256,
            self.source_revision,
            self.input_tree,
            self.workspace_parent_sha256,
            self.workspace_relative_path,
        ) == (
            other.start_id,
            other.attempt_id,
            other.attempt_sha256,
            other.source_revision,
            other.input_tree,
            other.workspace_parent_sha256,
            other.workspace_relative_path,
        )


@dataclass(frozen=True)
class AttemptTerminalReceipt(CanonicalContract):
    """One immutable terminal outcome for one exact persisted start."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.attempt-terminal"

    receipt_id: str
    start_sha256: str
    attempt_id: str
    attempt_sha256: str
    source_revision: str
    input_tree_sha256: str
    outcome: str
    report: ArtifactRef
    candidate_tree: ArtifactRef | None
    completed_at: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        for name in ("receipt_id", "attempt_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        for name in ("start_sha256", "attempt_sha256", "input_tree_sha256"):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        revision = _revision(self.source_revision, "source_revision")
        object.__setattr__(self, "source_revision", revision)
        if self.outcome not in _TERMINAL_OUTCOMES:
            raise ValueError(
                "attempt outcome must be succeeded, failed, cancelled, or faulted"
            )
        if not isinstance(self.report, ArtifactRef):
            raise ValueError("terminal report must be an ArtifactRef")
        if self.candidate_tree is not None and not isinstance(
            self.candidate_tree, ArtifactRef
        ):
            raise ValueError("candidate_tree must be an ArtifactRef or null")
        if self.outcome == "succeeded" and self.candidate_tree is None:
            raise ValueError("successful attempt must bind a candidate source tree")
        object.__setattr__(
            self,
            "completed_at",
            _utc_timestamp(self.completed_at, "completed_at"),
        )
        if not isinstance(self.provenance, ContractProvenance):
            raise ValueError("terminal provenance must be ContractProvenance")
        if self.provenance.source_revision != revision:
            raise ValueError("terminal provenance must use the source revision")
        required = {
            self.start_sha256,
            self.attempt_sha256,
            self.input_tree_sha256,
            self.report.sha256,
        }
        if self.candidate_tree is not None:
            required.add(self.candidate_tree.sha256)
        expected = tuple(sorted(required))
        _require_provenance_inputs(self.provenance, expected, "attempt terminal")
        if tuple(self.provenance.input_digests) != expected:
            raise ValueError("attempt terminal provenance must bind exactly its inputs")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AttemptTerminalReceipt":
        body = cls._contract_payload(payload)
        body["report"] = _artifact_ref(body["report"], "report")
        if body.get("candidate_tree") is not None:
            body["candidate_tree"] = _artifact_ref(
                body["candidate_tree"], "candidate_tree"
            )
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)

    def same_subject(self, other: "AttemptTerminalReceipt") -> bool:
        """Compare exact terminal material while retaining first completion time."""
        return isinstance(other, AttemptTerminalReceipt) and (
            self.receipt_id,
            self.start_sha256,
            self.attempt_id,
            self.attempt_sha256,
            self.source_revision,
            self.input_tree_sha256,
            self.outcome,
            self.report,
            self.candidate_tree,
        ) == (
            other.receipt_id,
            other.start_sha256,
            other.attempt_id,
            other.attempt_sha256,
            other.source_revision,
            other.input_tree_sha256,
            other.outcome,
            other.report,
            other.candidate_tree,
        )


@dataclass(frozen=True)
class AttemptCompletion:
    start: AttemptStartRecord
    receipt: AttemptTerminalReceipt

    def __post_init__(self) -> None:
        if not isinstance(self.start, AttemptStartRecord):
            raise ValueError("completion start must be AttemptStartRecord")
        if not isinstance(self.receipt, AttemptTerminalReceipt):
            raise ValueError("completion receipt must be AttemptTerminalReceipt")
        if self.receipt.start_sha256 != self.start.digest:
            raise ValueError("terminal receipt does not bind the start")
        if self.receipt.attempt_id != self.start.attempt_id:
            raise ValueError("terminal receipt attempt_id does not bind the start")
        if self.receipt.attempt_sha256 != self.start.attempt_sha256:
            raise ValueError("terminal receipt attempt digest does not bind the start")
        if self.receipt.input_tree_sha256 != self.start.input_tree.sha256:
            raise ValueError("terminal receipt input tree does not bind the start")


@dataclass(frozen=True)
class AttemptBeginResult:
    start: AttemptStartRecord
    execute: bool
    completion: AttemptCompletion | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.start, AttemptStartRecord):
            raise ValueError("begin start must be AttemptStartRecord")
        if not isinstance(self.execute, bool):
            raise ValueError("execute must be boolean")
        if self.execute and self.completion is not None:
            raise ValueError("fresh execution cannot already have completion")
        if self.completion is not None and self.completion.start != self.start:
            raise ValueError("completion does not bind begin start")

    @property
    def pending_reconciliation(self) -> bool:
        return not self.execute and self.completion is None


@dataclass(frozen=True)
class PreparedAttempt:
    begin: AttemptBeginResult
    workspace: Path | None

    def __post_init__(self) -> None:
        if not isinstance(self.begin, AttemptBeginResult):
            raise ValueError("prepared begin must be AttemptBeginResult")
        if self.begin.execute and self.workspace is None:
            raise ValueError("fresh prepared attempt must expose its workspace")
        if not self.begin.execute and self.workspace is not None:
            raise ValueError("replay or pending attempt must not expose a workspace")


class AttemptLedger:
    """SQLite start/terminal authority over one exact content-addressed store."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        source_store: SourceTreeStore,
    ) -> None:
        if not isinstance(source_store, SourceTreeStore):
            raise AttemptStateError("source_store must be SourceTreeStore")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.source_store = source_store
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=30.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS attempt_starts (
                    start_sha256 TEXT PRIMARY KEY,
                    start_id TEXT NOT NULL UNIQUE,
                    attempt_id TEXT NOT NULL UNIQUE,
                    attempt_sha256 TEXT NOT NULL UNIQUE,
                    input_tree_sha256 TEXT NOT NULL,
                    start_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS attempt_terminals (
                    receipt_sha256 TEXT PRIMARY KEY,
                    receipt_id TEXT NOT NULL UNIQUE,
                    start_sha256 TEXT NOT NULL UNIQUE,
                    attempt_id TEXT NOT NULL UNIQUE,
                    receipt_json TEXT NOT NULL,
                    FOREIGN KEY(start_sha256) REFERENCES attempt_starts(start_sha256)
                );
                """
            )

    @staticmethod
    def _decode_start(raw: str) -> AttemptStartRecord:
        parsed = _strict_json(raw, "persisted attempt start")
        try:
            start = AttemptStartRecord.from_dict(parsed)
        except (TypeError, ValueError, KeyError) as exc:
            raise AttemptStateError("persisted attempt start is malformed") from exc
        if start.to_json() != raw:
            raise AttemptStateError("persisted attempt start is noncanonical")
        return start

    @staticmethod
    def _decode_receipt(raw: str) -> AttemptTerminalReceipt:
        parsed = _strict_json(raw, "persisted attempt terminal")
        try:
            receipt = AttemptTerminalReceipt.from_dict(parsed)
        except (TypeError, ValueError, KeyError) as exc:
            raise AttemptStateError("persisted attempt terminal is malformed") from exc
        if receipt.to_json() != raw:
            raise AttemptStateError("persisted attempt terminal is noncanonical")
        return receipt

    def _completion_for(
        self,
        connection: sqlite3.Connection,
        start: AttemptStartRecord,
    ) -> AttemptCompletion | None:
        row = connection.execute(
            "SELECT receipt_json FROM attempt_terminals WHERE start_sha256 = ?",
            (start.digest,),
        ).fetchone()
        if row is None:
            return None
        receipt = self._decode_receipt(str(row["receipt_json"]))
        self.source_store.read_bytes(receipt.report, max_bytes=_MAX_REPORT_BYTES)
        if receipt.candidate_tree is not None:
            candidate = self.source_store.load_tree(receipt.candidate_tree)
            if candidate.source_revision != receipt.source_revision:
                raise AttemptStateError(
                    "persisted candidate tree revision differs from terminal receipt"
                )
        return AttemptCompletion(start=start, receipt=receipt)

    def begin(
        self,
        attempt: AttemptContract,
        input_tree: StoredSourceTree,
        *,
        start_id: str,
        workspace_parent_sha256: str,
        workspace_relative_path: str,
        started_at: str,
    ) -> AttemptBeginResult:
        if not isinstance(attempt, AttemptContract):
            raise AttemptBindingMismatch("attempt must be a canonical AttemptContract")
        if not isinstance(input_tree, StoredSourceTree):
            raise AttemptBindingMismatch("input_tree must be StoredSourceTree")
        loaded = self.source_store.load_tree(input_tree.ref)
        if loaded != input_tree.manifest:
            raise AttemptBindingMismatch(
                "input tree manifest differs from the ledger CAS object"
            )
        if loaded.source_revision != attempt.base_revision:
            raise AttemptBindingMismatch(
                "input source tree revision must equal attempt base revision"
            )
        parent_digest = _sha256(
            workspace_parent_sha256,
            "workspace_parent_sha256",
        )
        start = AttemptStartRecord(
            start_id=start_id,
            attempt_id=attempt.attempt_id,
            attempt_sha256=attempt.digest,
            source_revision=attempt.base_revision,
            input_tree=input_tree.ref,
            workspace_parent_sha256=parent_digest,
            workspace_relative_path=workspace_relative_path,
            started_at=started_at,
            provenance=ContractProvenance(
                origin="kernel.attempt-ledger.begin",
                source_revision=attempt.base_revision,
                created_at=started_at,
                input_digests=tuple(
                    sorted(
                        {
                            attempt.digest,
                            input_tree.ref.sha256,
                            parent_digest,
                        }
                    )
                ),
                trace_id=attempt.attempt_id,
            ),
        )
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT start_json FROM attempt_starts WHERE attempt_id = ?",
                    (attempt.attempt_id,),
                ).fetchone()
                if row is not None:
                    persisted = self._decode_start(str(row["start_json"]))
                    if not persisted.same_subject(start):
                        raise AttemptReplay(
                            "attempt_id was already started with different material"
                        )
                    completion = self._completion_for(connection, persisted)
                    connection.commit()
                    return AttemptBeginResult(
                        start=persisted,
                        execute=False,
                        completion=completion,
                    )
                collision = connection.execute(
                    """
                    SELECT start_json FROM attempt_starts
                    WHERE start_id = ? OR attempt_sha256 = ?
                    """,
                    (start.start_id, start.attempt_sha256),
                ).fetchone()
                if collision is not None:
                    raise AttemptReplay(
                        "start_id or attempt digest belongs to another attempt"
                    )
                connection.execute(
                    """
                    INSERT INTO attempt_starts (
                        start_sha256, start_id, attempt_id, attempt_sha256,
                        input_tree_sha256, start_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        start.digest,
                        start.start_id,
                        start.attempt_id,
                        start.attempt_sha256,
                        start.input_tree.sha256,
                        start.to_json(),
                    ),
                )
                connection.commit()
        except sqlite3.DatabaseError as exc:
            raise AttemptStateError("attempt start ledger transaction failed") from exc
        return AttemptBeginResult(start=start, execute=True)

    def complete(
        self,
        start: AttemptStartRecord,
        *,
        receipt_id: str,
        outcome: str,
        report: ArtifactRef,
        candidate_tree: StoredSourceTree | None,
        completed_at: str,
    ) -> AttemptCompletion:
        if not isinstance(start, AttemptStartRecord):
            raise AttemptBindingMismatch("start must be AttemptStartRecord")
        if not isinstance(report, ArtifactRef):
            raise AttemptBindingMismatch("report must be ArtifactRef")
        self.source_store.read_bytes(report, max_bytes=_MAX_REPORT_BYTES)
        candidate_ref = None
        if candidate_tree is not None:
            if not isinstance(candidate_tree, StoredSourceTree):
                raise AttemptBindingMismatch(
                    "candidate_tree must be StoredSourceTree or null"
                )
            loaded_candidate = self.source_store.load_tree(candidate_tree.ref)
            if loaded_candidate != candidate_tree.manifest:
                raise AttemptBindingMismatch(
                    "candidate tree manifest differs from the ledger CAS object"
                )
            if loaded_candidate.source_revision != start.source_revision:
                raise AttemptBindingMismatch(
                    "candidate source tree revision must equal attempt source revision"
                )
            candidate_ref = candidate_tree.ref
        receipt = AttemptTerminalReceipt(
            receipt_id=receipt_id,
            start_sha256=start.digest,
            attempt_id=start.attempt_id,
            attempt_sha256=start.attempt_sha256,
            source_revision=start.source_revision,
            input_tree_sha256=start.input_tree.sha256,
            outcome=outcome,
            report=report,
            candidate_tree=candidate_ref,
            completed_at=completed_at,
            provenance=ContractProvenance(
                origin="kernel.attempt-ledger.complete",
                source_revision=start.source_revision,
                created_at=completed_at,
                input_digests=tuple(
                    sorted(
                        {
                            start.digest,
                            start.attempt_sha256,
                            start.input_tree.sha256,
                            report.sha256,
                            *(
                                (candidate_ref.sha256,)
                                if candidate_ref is not None
                                else ()
                            ),
                        }
                    )
                ),
                trace_id=start.attempt_id,
            ),
        )
        completion = AttemptCompletion(start=start, receipt=receipt)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT start_json FROM attempt_starts WHERE start_sha256 = ?",
                    (start.digest,),
                ).fetchone()
                if row is None:
                    raise AttemptStateError("attempt start is not persisted")
                persisted_start = self._decode_start(str(row["start_json"]))
                if persisted_start != start:
                    raise AttemptBindingMismatch(
                        "submitted start differs from persisted start"
                    )
                existing = self._completion_for(connection, persisted_start)
                if existing is not None:
                    if not existing.receipt.same_subject(receipt):
                        raise AttemptReplay(
                            "attempt already has a different terminal receipt"
                        )
                    connection.commit()
                    return existing
                collision = connection.execute(
                    """
                    SELECT receipt_json FROM attempt_terminals
                    WHERE receipt_id = ? OR receipt_sha256 = ?
                    """,
                    (receipt.receipt_id, receipt.digest),
                ).fetchone()
                if collision is not None:
                    raise AttemptReplay(
                        "receipt_id or receipt digest belongs to another attempt"
                    )
                connection.execute(
                    """
                    INSERT INTO attempt_terminals (
                        receipt_sha256, receipt_id, start_sha256,
                        attempt_id, receipt_json
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        receipt.digest,
                        receipt.receipt_id,
                        start.digest,
                        start.attempt_id,
                        receipt.to_json(),
                    ),
                )
                connection.commit()
        except sqlite3.DatabaseError as exc:
            raise AttemptStateError("attempt terminal ledger transaction failed") from exc
        return completion

    def pending(self) -> tuple[AttemptStartRecord, ...]:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT s.start_json
                    FROM attempt_starts AS s
                    LEFT JOIN attempt_terminals AS t
                      ON t.start_sha256 = s.start_sha256
                    WHERE t.start_sha256 IS NULL
                    ORDER BY s.attempt_id
                    """
                ).fetchall()
        except sqlite3.DatabaseError as exc:
            raise AttemptStateError("cannot read pending attempts") from exc
        return tuple(self._decode_start(str(row["start_json"])) for row in rows)


class IsolatedAttemptCoordinator:
    """Materialize exact inputs under one checkout-external workspace parent."""

    def __init__(
        self,
        *,
        primary_checkout: str | os.PathLike[str],
        workspace_parent: str | os.PathLike[str],
        source_store: SourceTreeStore,
        ledger: AttemptLedger,
    ) -> None:
        if not isinstance(source_store, SourceTreeStore):
            raise AttemptWorkspaceError("source_store must be SourceTreeStore")
        if not isinstance(ledger, AttemptLedger):
            raise AttemptWorkspaceError("ledger must be AttemptLedger")
        if ledger.source_store is not source_store:
            raise AttemptWorkspaceError(
                "coordinator and ledger must share the exact SourceTreeStore"
            )
        primary = Path(primary_checkout)
        if primary.is_symlink():
            raise AttemptWorkspaceError("primary checkout must not be a symlink")
        primary = primary.resolve(strict=True)
        if not primary.is_dir():
            raise AttemptWorkspaceError("primary checkout must be a directory")

        raw_parent = Path(workspace_parent)
        raw_parent.mkdir(parents=True, exist_ok=True)
        if raw_parent.is_symlink():
            raise AttemptWorkspaceError("workspace parent must not be a symlink")
        parent = raw_parent.resolve()
        cas_root = source_store.root.resolve()
        for left, right, label in (
            (parent, primary, "workspace parent and primary checkout"),
            (parent, cas_root, "workspace parent and source-tree store"),
        ):
            if _is_same_or_within(left, right) or _is_same_or_within(right, left):
                raise AttemptWorkspaceError(f"{label} must be disjoint")

        self.primary_checkout = primary
        self.workspace_parent = parent
        self.workspace_parent_sha256 = _path_identity(parent)
        self.source_store = source_store
        self.ledger = ledger

    def prepare(
        self,
        attempt: AttemptContract,
        input_tree: StoredSourceTree,
        *,
        start_id: str,
        started_at: str,
    ) -> PreparedAttempt:
        if not isinstance(attempt, AttemptContract):
            raise AttemptBindingMismatch("attempt must be AttemptContract")
        if not isinstance(input_tree, StoredSourceTree):
            raise AttemptBindingMismatch("input_tree must be StoredSourceTree")
        loaded = self.source_store.load_tree(input_tree.ref)
        if loaded != input_tree.manifest:
            raise AttemptBindingMismatch(
                "input tree manifest differs from the CAS object"
            )
        if loaded.source_revision != attempt.base_revision:
            raise AttemptBindingMismatch(
                "input source tree revision must equal attempt base revision"
            )
        relative = _workspace_relative_path(attempt)
        begin = self.ledger.begin(
            attempt,
            input_tree,
            start_id=start_id,
            workspace_parent_sha256=self.workspace_parent_sha256,
            workspace_relative_path=relative,
            started_at=started_at,
        )
        if not begin.execute:
            return PreparedAttempt(begin=begin, workspace=None)
        workspace = self.workspace_parent.joinpath(*relative.split("/"))
        try:
            materialized = self.source_store.materialize_tree(
                input_tree.ref,
                workspace,
            )
            if materialized != input_tree.manifest:
                raise AttemptBindingMismatch(
                    "materialized input manifest differs from requested input"
                )
        except Exception as exc:
            report_payload = {
                "schema": "daedalus-attempt-materialization-fault/1",
                "attempt_sha256": attempt.digest,
                "input_tree_sha256": input_tree.ref.sha256,
                "error_type": type(exc).__name__,
            }
            report = self.source_store.put_bytes(
                canonical_json(report_payload).encode("ascii")
            )
            self.ledger.complete(
                begin.start,
                receipt_id=f"terminal-{attempt.attempt_id}",
                outcome="faulted",
                report=report,
                candidate_tree=None,
                completed_at=started_at,
            )
            raise AttemptWorkspaceError(
                "attempt input materialization failed and was terminalized"
            ) from exc
        return PreparedAttempt(begin=begin, workspace=workspace)


__all__ = [
    "AttemptBeginResult",
    "AttemptBindingMismatch",
    "AttemptCompletion",
    "AttemptLedger",
    "AttemptLifecycleError",
    "AttemptReplay",
    "AttemptStartRecord",
    "AttemptStateError",
    "AttemptTerminalReceipt",
    "AttemptWorkspaceError",
    "IsolatedAttemptCoordinator",
    "PreparedAttempt",
]
