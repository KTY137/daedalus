"""Authenticated, exact-head, one-use Gate-2 closure boundary.

The closure detail is not self-authorizing.  The existing canonical OwnerApproval
contract signs its digest and every report/evidence/head dimension.  This module
verifies that approval through the Gate-0 authority and atomically records the
single Gate-2 closure in a FULL-synchronous SQLite ledger.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from daedalus.kernel.approvals import (
    ApprovalExpectation,
    ApprovalReplay,
    VerifiedOwnerApproval,
    verify_owner_approval,
)
from daedalus.kernel.contracts import OwnerApproval
from daedalus.schemas import _revision, _sha256
from daedalus.twin.gate2_report import Gate2Report

_NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_REQUIRED_WORKFLOWS = ("Gate 2 Corpus Pilot", "Gate 2 Project Twin", "Iron Plan")
_OPERATION = "close-gate-2"
_TARGET_REF = "gate/2"
_TARGET_STATE = "gate-2-closed"


class Gate2ClosureError(ValueError):
    """Raised when closure evidence is stale, unauthenticated, or replayed."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _parse_utc(value: str, field: str) -> dt.datetime:
    if not isinstance(value, str) or not _TIME_RE.fullmatch(value):
        raise Gate2ClosureError(f"{field} must be canonical UTC seconds")
    return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


@dataclasses.dataclass(frozen=True, slots=True)
class Gate2ClosureApproval:
    """Unsigned closure detail whose digest must be signed by OwnerApproval."""

    head_sha: str
    iron_plan_sha256: str
    report_sha256: str
    evidence_packet_sha256: str
    corpus_manifest_sha256: str
    capability_matrix_sha256: str
    motif_provenance_sha256s: tuple[str, ...]
    workflow_run_ids: tuple[tuple[str, int], ...]
    target_state: str
    issued_at: str
    expires_at: str
    nonce: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "head_sha", _revision(self.head_sha, "head_sha"))
        for field in (
            "iron_plan_sha256",
            "report_sha256",
            "evidence_packet_sha256",
            "corpus_manifest_sha256",
            "capability_matrix_sha256",
        ):
            object.__setattr__(self, field, _sha256(getattr(self, field), field))
        motifs = tuple(_sha256(value, "motif_provenance_sha256") for value in self.motif_provenance_sha256s)
        if not motifs or motifs != tuple(sorted(set(motifs))):
            raise Gate2ClosureError("motif_provenance_sha256s must be non-empty, unique and sorted")
        names = tuple(name for name, _ in self.workflow_run_ids)
        if names != _REQUIRED_WORKFLOWS:
            raise Gate2ClosureError("workflow_run_ids must contain every required workflow in canonical order")
        if any(isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0 for _, run_id in self.workflow_run_ids):
            raise Gate2ClosureError("workflow run IDs must be positive integers")
        if self.target_state != _TARGET_STATE:
            raise Gate2ClosureError("target_state must be gate-2-closed")
        issued = _parse_utc(self.issued_at, "issued_at")
        expires = _parse_utc(self.expires_at, "expires_at")
        if expires <= issued:
            raise Gate2ClosureError("expires_at must be later than issued_at")
        if not isinstance(self.nonce, str) or not _NONCE_RE.fullmatch(self.nonce):
            raise Gate2ClosureError("nonce must be a canonical high-entropy identifier")

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.to_json_bytes()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "daedalus-gate2-closure-approval/1",
            "head_sha": self.head_sha,
            "iron_plan_sha256": self.iron_plan_sha256,
            "report_sha256": self.report_sha256,
            "evidence_packet_sha256": self.evidence_packet_sha256,
            "corpus_manifest_sha256": self.corpus_manifest_sha256,
            "capability_matrix_sha256": self.capability_matrix_sha256,
            "motif_provenance_sha256s": list(self.motif_provenance_sha256s),
            "workflow_run_ids": [
                {"workflow_name": name, "run_id": run_id}
                for name, run_id in self.workflow_run_ids
            ],
            "target_state": self.target_state,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "nonce": self.nonce,
        }

    def to_json_bytes(self) -> bytes:
        return _canonical_json(self.to_dict()) + b"\n"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Gate2ClosureApproval":
        expected = {
            "schema", "head_sha", "iron_plan_sha256", "report_sha256",
            "evidence_packet_sha256", "corpus_manifest_sha256",
            "capability_matrix_sha256", "motif_provenance_sha256s",
            "workflow_run_ids", "target_state", "issued_at", "expires_at", "nonce",
        }
        if set(payload) != expected or payload.get("schema") != "daedalus-gate2-closure-approval/1":
            raise Gate2ClosureError("closure approval fields or schema are not canonical")
        motifs = payload["motif_provenance_sha256s"]
        runs = payload["workflow_run_ids"]
        if not isinstance(motifs, list) or not isinstance(runs, list):
            raise Gate2ClosureError("motif and workflow fields must be arrays")
        normalized_runs: list[tuple[str, int]] = []
        for item in runs:
            if not isinstance(item, Mapping) or set(item) != {"workflow_name", "run_id"}:
                raise Gate2ClosureError("workflow run record is not canonical")
            normalized_runs.append((item["workflow_name"], item["run_id"]))
        return cls(
            head_sha=payload["head_sha"],
            iron_plan_sha256=payload["iron_plan_sha256"],
            report_sha256=payload["report_sha256"],
            evidence_packet_sha256=payload["evidence_packet_sha256"],
            corpus_manifest_sha256=payload["corpus_manifest_sha256"],
            capability_matrix_sha256=payload["capability_matrix_sha256"],
            motif_provenance_sha256s=tuple(motifs),
            workflow_run_ids=tuple(normalized_runs),
            target_state=payload["target_state"],
            issued_at=payload["issued_at"],
            expires_at=payload["expires_at"],
            nonce=payload["nonce"],
        )

    @classmethod
    def from_json_bytes(cls, payload: bytes) -> "Gate2ClosureApproval":
        try:
            decoded = json.loads(payload.decode("ascii"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Gate2ClosureError("closure approval must be canonical JSON") from exc
        if not isinstance(decoded, Mapping):
            raise Gate2ClosureError("closure approval root must be an object")
        approval = cls.from_dict(decoded)
        if payload != approval.to_json_bytes():
            raise Gate2ClosureError("closure approval bytes must be canonical JSON plus one newline")
        return approval


@dataclasses.dataclass(frozen=True, slots=True)
class Gate2ClosureReceipt:
    owner_approval_sha256: str
    closure_approval_sha256: str
    report_sha256: str
    head_sha: str
    owner_id: str
    key_id: str
    nonce: str
    consumed_at: str
    consumption_sha256: str

    def __post_init__(self) -> None:
        for field in (
            "owner_approval_sha256",
            "closure_approval_sha256",
            "report_sha256",
            "consumption_sha256",
        ):
            object.__setattr__(self, field, _sha256(getattr(self, field), field))
        object.__setattr__(self, "head_sha", _revision(self.head_sha, "head_sha"))
        _parse_utc(self.consumed_at, "consumed_at")

    def to_dict(self) -> dict[str, str]:
        return dataclasses.asdict(self)

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical_json(self.to_dict())).hexdigest()


def owner_approval_expectation(
    *,
    closure: Gate2ClosureApproval,
    report: Gate2Report,
) -> ApprovalExpectation:
    return ApprovalExpectation(
        operation=_OPERATION,
        nomination_receipt_sha256=report.digest,
        candidate_artifact_sha256=closure.digest,
        evidence_packet_sha256=closure.evidence_packet_sha256,
        base_revision=report.head_sha,
        target_ref=_TARGET_REF,
        current_target_revision=report.head_sha,
    )


def verify_gate2_closure_approval(
    *,
    closure: Gate2ClosureApproval,
    owner_approval: OwnerApproval,
    keyring: Mapping[tuple[str, str], bytes | str],
    report: Gate2Report,
    evidence_packet_sha256: str,
    corpus_manifest_sha256: str,
    capability_matrix_sha256: str,
    now: str,
) -> VerifiedOwnerApproval:
    """Verify deterministic closure details and canonical owner authentication."""
    if not report.closed:
        raise Gate2ClosureError("an open Gate-2 report cannot be approved for closure")
    expected_runs = tuple((item.workflow_name, item.run_id) for item in report.workflow_evidence)
    mismatches: list[str] = []
    if closure.head_sha != report.head_sha:
        mismatches.append("head_sha")
    if closure.iron_plan_sha256 != report.iron_plan_sha256:
        mismatches.append("iron_plan")
    if closure.report_sha256 != report.digest:
        mismatches.append("report")
    if closure.evidence_packet_sha256 != _sha256(evidence_packet_sha256, "evidence_packet_sha256"):
        mismatches.append("evidence_packet")
    if closure.corpus_manifest_sha256 != _sha256(corpus_manifest_sha256, "corpus_manifest_sha256"):
        mismatches.append("corpus_manifest")
    if closure.capability_matrix_sha256 != _sha256(capability_matrix_sha256, "capability_matrix_sha256"):
        mismatches.append("capability_matrix")
    if closure.motif_provenance_sha256s != report.motif_provenance_sha256s:
        mismatches.append("motif_provenance")
    if closure.workflow_run_ids != expected_runs:
        mismatches.append("workflow_runs")
    current = _parse_utc(now, "now")
    if current < _parse_utc(closure.issued_at, "issued_at"):
        mismatches.append("not_yet_valid")
    if current >= _parse_utc(closure.expires_at, "expires_at"):
        mismatches.append("expired")
    if mismatches:
        raise Gate2ClosureError("closure approval mismatch: " + ", ".join(sorted(mismatches)))

    verified = verify_owner_approval(
        owner_approval,
        keyring=keyring,
        expectation=owner_approval_expectation(closure=closure, report=report),
        now=current,
    )
    owner_mismatches: list[str] = []
    if verified.nonce != closure.nonce:
        owner_mismatches.append("nonce")
    if verified.issued_at != closure.issued_at:
        owner_mismatches.append("issued_at")
    if verified.expires_at != closure.expires_at:
        owner_mismatches.append("expires_at")
    if owner_mismatches:
        raise Gate2ClosureError(
            "owner approval does not bind closure detail: " + ", ".join(owner_mismatches)
        )
    return verified


class Gate2ClosureLedger:
    """SQLite-backed atomic final closure consumption."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), isolation_level=None, timeout=30)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS gate2_closure_consumptions (
                    owner_approval_sha256 TEXT PRIMARY KEY,
                    closure_approval_sha256 TEXT NOT NULL UNIQUE,
                    report_sha256 TEXT NOT NULL UNIQUE,
                    head_sha TEXT NOT NULL UNIQUE,
                    owner_id TEXT NOT NULL,
                    key_id TEXT NOT NULL,
                    nonce TEXT NOT NULL,
                    target_state TEXT NOT NULL UNIQUE,
                    consumed_at TEXT NOT NULL,
                    consumption_sha256 TEXT NOT NULL UNIQUE,
                    UNIQUE(owner_id, key_id, nonce)
                )
                """
            )

    def consume(
        self,
        *,
        closure: Gate2ClosureApproval,
        owner_approval: OwnerApproval,
        keyring: Mapping[tuple[str, str], bytes | str],
        report: Gate2Report,
        evidence_packet_sha256: str,
        corpus_manifest_sha256: str,
        capability_matrix_sha256: str,
        now: str,
    ) -> Gate2ClosureReceipt:
        verified = verify_gate2_closure_approval(
            closure=closure,
            owner_approval=owner_approval,
            keyring=keyring,
            report=report,
            evidence_packet_sha256=evidence_packet_sha256,
            corpus_manifest_sha256=corpus_manifest_sha256,
            capability_matrix_sha256=capability_matrix_sha256,
            now=now,
        )
        record = {
            "schema": "daedalus-gate2-closure-consumption/1",
            "owner_approval_sha256": verified.approval_sha256,
            "closure_approval_sha256": closure.digest,
            "report_sha256": report.digest,
            "head_sha": report.head_sha,
            "owner_id": verified.owner_id,
            "key_id": verified.key_id,
            "nonce": verified.nonce,
            "target_state": _TARGET_STATE,
            "consumed_at": now,
        }
        consumption_sha256 = hashlib.sha256(_canonical_json(record)).hexdigest()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO gate2_closure_consumptions (
                    owner_approval_sha256, closure_approval_sha256, report_sha256,
                    head_sha, owner_id, key_id, nonce, target_state, consumed_at,
                    consumption_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    verified.approval_sha256,
                    closure.digest,
                    report.digest,
                    report.head_sha,
                    verified.owner_id,
                    verified.key_id,
                    verified.nonce,
                    _TARGET_STATE,
                    now,
                    consumption_sha256,
                ),
            )
            connection.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise ApprovalReplay("Gate-2 closure approval, report, head, or nonce was already consumed") from exc
        except Exception:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            connection.close()
        return Gate2ClosureReceipt(
            owner_approval_sha256=verified.approval_sha256,
            closure_approval_sha256=closure.digest,
            report_sha256=report.digest,
            head_sha=report.head_sha,
            owner_id=verified.owner_id,
            key_id=verified.key_id,
            nonce=verified.nonce,
            consumed_at=now,
            consumption_sha256=consumption_sha256,
        )

    def closed(self, report_sha256: str) -> bool:
        digest = _sha256(report_sha256, "report_sha256")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM gate2_closure_consumptions WHERE report_sha256=?",
                (digest,),
            ).fetchone()
        return row is not None


__all__ = [
    "Gate2ClosureApproval",
    "Gate2ClosureError",
    "Gate2ClosureLedger",
    "Gate2ClosureReceipt",
    "owner_approval_expectation",
    "verify_gate2_closure_approval",
]
