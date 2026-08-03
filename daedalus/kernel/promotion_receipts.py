"""Persisted, replay-safe receipts for sealed promotion attempts.

The ledger writes an exact authorization/start record before any repository
mutation, then accepts one immutable terminal outcome. It never creates
worktrees, applies candidates, merges branches, or issues owner approval.
"""
from __future__ import annotations

import dataclasses
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, ClassVar, Mapping

from daedalus.kernel.promotion import PromotionAuthorization
from daedalus.schemas import (
    CanonicalContract,
    ContractProvenance,
    _freeze_json,
    _identifier,
    _require_provenance_inputs,
    _revision,
    _sha256,
    _utc_timestamp,
)
from daedalus.spine.envelope import canonical_json, canonical_sha


class PromotionReceiptError(RuntimeError):
    """Base class for fail-closed promotion-receipt rejection."""


class PromotionReceiptBindingMismatch(PromotionReceiptError):
    pass


class PromotionReceiptReplay(PromotionReceiptError):
    pass


class PromotionReceiptStateError(PromotionReceiptError):
    pass


@dataclass(frozen=True)
class PromotionStartRecord:
    """Persisted intent written before any promotion-side repository effect."""

    start_id: str
    promotion_id: str
    authorization_sha256: str
    approval_consumption_sha256: str
    candidate_artifact_sha256: str
    evidence_packet_sha256: str
    source_revision: str
    target_ref: str
    authorized_target_revision: str
    primary_checkout_before_sha256: str
    started_at: str
    start_sha256: str

    def __post_init__(self) -> None:
        for name in ("start_id", "promotion_id", "target_ref"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        for name in (
            "authorization_sha256",
            "approval_consumption_sha256",
            "candidate_artifact_sha256",
            "evidence_packet_sha256",
            "primary_checkout_before_sha256",
            "start_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(
            self, "source_revision", _revision(self.source_revision, "source_revision")
        )
        object.__setattr__(
            self,
            "authorized_target_revision",
            _revision(self.authorized_target_revision, "authorized_target_revision"),
        )
        object.__setattr__(self, "started_at", _utc_timestamp(self.started_at, "started_at"))
        if self.start_sha256 != canonical_sha(self.payload_dict()):
            raise ValueError("promotion start digest mismatch")

    def payload_dict(self) -> dict[str, str]:
        return {
            field.name: getattr(self, field.name)
            for field in dataclasses.fields(self)
            if field.name != "start_sha256"
        }

    def to_dict(self) -> dict[str, str]:
        return {**self.payload_dict(), "start_sha256": self.start_sha256}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "PromotionStartRecord":
        if not isinstance(payload, Mapping):
            raise ValueError("promotion start record must be an object")
        expected = {field.name for field in dataclasses.fields(cls)}
        actual = set(payload)
        if actual != expected:
            raise ValueError(
                "promotion start fields mismatch: "
                f"missing={sorted(expected - actual)} extra={sorted(actual - expected)}"
            )
        return cls(**{name: str(payload[name]) for name in expected})


@dataclass(frozen=True)
class PromotionReceipt(CanonicalContract):
    """One immutable terminal account of a sealed promotion attempt."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.promotion-receipt"

    receipt_id: str
    promotion_id: str
    start_sha256: str
    authorization_sha256: str
    approval_consumption_sha256: str
    candidate_artifact_sha256: str
    evidence_packet_sha256: str
    source_revision: str
    target_ref: str
    authorized_target_revision: str
    outcome: str
    integration_branch: str | None
    integration_revision: str | None
    report_sha256: str
    primary_checkout_before_sha256: str
    primary_checkout_after_sha256: str
    started_at: str
    completed_at: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        for name in ("receipt_id", "promotion_id", "target_ref"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        for name in (
            "start_sha256",
            "authorization_sha256",
            "approval_consumption_sha256",
            "candidate_artifact_sha256",
            "evidence_packet_sha256",
            "report_sha256",
            "primary_checkout_before_sha256",
            "primary_checkout_after_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(
            self, "source_revision", _revision(self.source_revision, "source_revision")
        )
        object.__setattr__(
            self,
            "authorized_target_revision",
            _revision(self.authorized_target_revision, "authorized_target_revision"),
        )
        if self.integration_branch is not None:
            object.__setattr__(
                self,
                "integration_branch",
                _identifier(self.integration_branch, "integration_branch"),
            )
        if self.integration_revision is not None:
            object.__setattr__(
                self,
                "integration_revision",
                _revision(self.integration_revision, "integration_revision"),
            )
        if self.integration_revision is not None and self.integration_branch is None:
            raise ValueError("integration_revision requires integration_branch")
        if self.outcome not in {"succeeded", "refused", "faulted"}:
            raise ValueError("promotion receipt outcome must be succeeded, refused, or faulted")
        if self.outcome == "succeeded" and (
            self.integration_branch is None or self.integration_revision is None
        ):
            raise ValueError(
                "successful promotion receipt requires integration branch and revision"
            )
        if (
            self.primary_checkout_before_sha256
            != self.primary_checkout_after_sha256
            and self.outcome != "faulted"
        ):
            raise ValueError(
                "primary checkout identity changed; terminal outcome must be faulted"
            )
        object.__setattr__(self, "started_at", _utc_timestamp(self.started_at, "started_at"))
        object.__setattr__(
            self, "completed_at", _utc_timestamp(self.completed_at, "completed_at")
        )
        if _parse_utc(self.completed_at, "completed_at") < _parse_utc(
            self.started_at, "started_at"
        ):
            raise ValueError("promotion receipt completed_at precedes started_at")
        if self.provenance.source_revision != self.source_revision:
            raise ValueError(
                "promotion receipt source_revision must match provenance.source_revision"
            )
        _require_provenance_inputs(
            self.provenance,
            (
                self.start_sha256,
                self.authorization_sha256,
                self.approval_consumption_sha256,
                self.candidate_artifact_sha256,
                self.evidence_packet_sha256,
                self.report_sha256,
                self.primary_checkout_before_sha256,
                self.primary_checkout_after_sha256,
            ),
            "promotion receipt",
        )

    @property
    def primary_checkout_unchanged(self) -> bool:
        return self.primary_checkout_before_sha256 == self.primary_checkout_after_sha256

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "PromotionReceipt":
        body = cls._contract_payload(payload)
        provenance = body.get("provenance")
        if not isinstance(provenance, Mapping):
            raise ValueError("promotion receipt provenance must be an object")
        body["provenance"] = ContractProvenance.from_dict(provenance)
        return cls(**body)


@dataclass(frozen=True)
class PromotionCompletion:
    receipt: PromotionReceipt
    report: Mapping[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.receipt, PromotionReceipt):
            raise ValueError("promotion completion requires PromotionReceipt")
        frozen = _freeze_json(self.report, "promotion completion report")
        if not isinstance(frozen, Mapping):
            raise ValueError("promotion completion report must be an object")
        object.__setattr__(self, "report", frozen)

    def report_dict(self) -> dict[str, object]:
        return json.loads(canonical_json(self.report))


@dataclass(frozen=True)
class PromotionBeginResult:
    """Atomic replay decision for one exact promotion authorization."""

    start: PromotionStartRecord
    execute: bool
    completion: PromotionCompletion | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.start, PromotionStartRecord):
            raise ValueError("promotion begin result requires PromotionStartRecord")
        if not isinstance(self.execute, bool):
            raise ValueError("promotion begin execute must be boolean")
        if self.execute and self.completion is not None:
            raise ValueError("new promotion start cannot already have a completion")
        if self.completion is not None:
            if self.completion.receipt.promotion_id != self.start.promotion_id:
                raise ValueError("promotion begin completion is bound to another promotion")
            if self.completion.receipt.start_sha256 != self.start.start_sha256:
                raise ValueError("promotion begin completion is bound to another start")

    @property
    def pending_reconciliation(self) -> bool:
        return not self.execute and self.completion is None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{label} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return _as_utc(value, "timestamp").isoformat(timespec="microseconds")


def _parse_utc(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _authorization_start_fields(
    authorization: PromotionAuthorization,
    *,
    start_id: str,
    primary_checkout_before_sha256: str,
) -> dict[str, str]:
    if not isinstance(authorization, PromotionAuthorization):
        raise TypeError("promotion start requires PromotionAuthorization")
    authorization_body = {
        "promotion_id": _identifier(authorization.promotion_id, "promotion_id"),
        "candidate_artifact_sha256": _sha256(
            authorization.candidate_artifact_sha256, "candidate_artifact_sha256"
        ),
        "evidence_packet_sha256": _sha256(
            authorization.evidence_packet_sha256, "evidence_packet_sha256"
        ),
        "source_revision": _revision(authorization.source_revision, "source_revision"),
        "target_ref": _identifier(authorization.target_ref, "target_ref"),
        "live_target_revision": _revision(
            authorization.live_target_revision, "live_target_revision"
        ),
        "approval_consumption_sha256": _sha256(
            authorization.approval_consumption_sha256,
            "approval_consumption_sha256",
        ),
    }
    authorization_sha256 = _sha256(
        authorization.authorization_sha256, "authorization_sha256"
    )
    if authorization_sha256 != canonical_sha(authorization_body):
        raise PromotionReceiptBindingMismatch(
            "promotion authorization digest does not bind its fields"
        )
    return {
        "start_id": _identifier(start_id, "start_id"),
        "promotion_id": authorization_body["promotion_id"],
        "authorization_sha256": authorization_sha256,
        "approval_consumption_sha256": authorization_body[
            "approval_consumption_sha256"
        ],
        "candidate_artifact_sha256": authorization_body[
            "candidate_artifact_sha256"
        ],
        "evidence_packet_sha256": authorization_body["evidence_packet_sha256"],
        "source_revision": authorization_body["source_revision"],
        "target_ref": authorization_body["target_ref"],
        "authorized_target_revision": authorization_body["live_target_revision"],
        "primary_checkout_before_sha256": _sha256(
            primary_checkout_before_sha256, "primary_checkout_before_sha256"
        ),
    }


def _new_start(fields: Mapping[str, str], started_at: datetime) -> PromotionStartRecord:
    body = {**dict(fields), "started_at": _timestamp(started_at)}
    return PromotionStartRecord(**body, start_sha256=canonical_sha(body))


def _start_matches_fields(
    record: PromotionStartRecord, fields: Mapping[str, str]
) -> bool:
    return all(getattr(record, name) == value for name, value in fields.items())


def _canonical_report(report: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(report, Mapping):
        raise ValueError("promotion report must be an object")
    payload = json.loads(canonical_json(report))
    if not isinstance(payload, dict):
        raise ValueError("promotion report must canonicalize to an object")
    return payload


def _validate_terminal_report(
    *,
    outcome: str,
    report: Mapping[str, object],
    integration_branch: str | None,
    primary_unchanged: bool,
) -> None:
    promoted = report.get("promoted", [])
    refused = report.get("refused", [])
    not_gated = report.get("not_gated", [])
    if not isinstance(promoted, list) or not isinstance(refused, list) or not isinstance(
        not_gated, list
    ):
        raise ValueError("promotion report outcome collections must be arrays")
    report_branch = report.get("integration_branch")
    if report_branch is not None and report_branch != integration_branch:
        raise ValueError("promotion report integration branch mismatch")
    if outcome == "succeeded":
        if len(promoted) != 1 or refused or not_gated:
            raise ValueError("successful receipt requires exactly one promoted result")
        row = promoted[0]
        if not isinstance(row, Mapping) or row.get("promoted") is not True:
            raise ValueError("successful receipt promoted result is malformed")
        if report.get("cleanup_error") is not None:
            raise ValueError("successful receipt cannot retain a cleanup error")
    elif outcome == "refused":
        if promoted or not (refused or not_gated):
            raise ValueError("refused receipt requires no promotion and a refusal")
    elif outcome == "faulted":
        if primary_unchanged and not report.get("fault") and not report.get("cleanup_error"):
            raise ValueError(
                "faulted receipt with unchanged primary requires explicit fault evidence"
            )


class PromotionLedger:
    """SQLite authority for one started and one terminal record per promotion."""

    def __init__(
        self,
        path: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock or _utc_now
        self._initialize()

    def _now(self) -> datetime:
        return _as_utc(self._clock(), "promotion ledger clock")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), isolation_level=None, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize(self) -> None:
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS promotion_starts_v1 (
                        promotion_id TEXT PRIMARY KEY,
                        start_id TEXT NOT NULL UNIQUE,
                        start_sha256 TEXT NOT NULL UNIQUE,
                        authorization_sha256 TEXT NOT NULL UNIQUE,
                        approval_consumption_sha256 TEXT NOT NULL UNIQUE,
                        candidate_artifact_sha256 TEXT NOT NULL,
                        evidence_packet_sha256 TEXT NOT NULL,
                        source_revision TEXT NOT NULL,
                        target_ref TEXT NOT NULL,
                        authorized_target_revision TEXT NOT NULL,
                        primary_checkout_before_sha256 TEXT NOT NULL,
                        started_at TEXT NOT NULL,
                        start_json TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS promotion_receipts_v1 (
                        promotion_id TEXT PRIMARY KEY,
                        receipt_id TEXT NOT NULL UNIQUE,
                        receipt_sha256 TEXT NOT NULL UNIQUE,
                        start_sha256 TEXT NOT NULL UNIQUE,
                        outcome TEXT NOT NULL,
                        report_sha256 TEXT NOT NULL,
                        completed_at TEXT NOT NULL,
                        receipt_json TEXT NOT NULL,
                        report_json TEXT NOT NULL,
                        FOREIGN KEY(promotion_id)
                            REFERENCES promotion_starts_v1(promotion_id)
                    )
                    """
                )
        except sqlite3.DatabaseError as exc:
            raise PromotionReceiptStateError("cannot initialize promotion ledger") from exc

    @staticmethod
    def _start_from_row(row: sqlite3.Row) -> PromotionStartRecord:
        try:
            raw = str(row["start_json"])
            record = PromotionStartRecord.from_dict(json.loads(raw))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise PromotionReceiptStateError("persisted promotion start is corrupt") from exc
        if raw != canonical_json(record.to_dict()):
            raise PromotionReceiptStateError("promotion start JSON is not canonical")
        columns = {
            "promotion_id": row["promotion_id"],
            "start_id": row["start_id"],
            "start_sha256": row["start_sha256"],
            "authorization_sha256": row["authorization_sha256"],
            "approval_consumption_sha256": row["approval_consumption_sha256"],
            "candidate_artifact_sha256": row["candidate_artifact_sha256"],
            "evidence_packet_sha256": row["evidence_packet_sha256"],
            "source_revision": row["source_revision"],
            "target_ref": row["target_ref"],
            "authorized_target_revision": row["authorized_target_revision"],
            "primary_checkout_before_sha256": row[
                "primary_checkout_before_sha256"
            ],
            "started_at": row["started_at"],
        }
        for name, value in columns.items():
            if getattr(record, name) != str(value):
                raise PromotionReceiptStateError(
                    f"promotion start column/json mismatch: {name}"
                )
        return record

    @staticmethod
    def _completion_from_row(row: sqlite3.Row) -> PromotionCompletion:
        try:
            receipt_raw = str(row["receipt_json"])
            report_raw = str(row["report_json"])
            receipt = PromotionReceipt.from_dict(json.loads(receipt_raw))
            report_payload = json.loads(report_raw)
            if not isinstance(report_payload, Mapping):
                raise ValueError("report must be an object")
            _validate_terminal_report(
                outcome=receipt.outcome,
                report=report_payload,
                integration_branch=receipt.integration_branch,
                primary_unchanged=receipt.primary_checkout_unchanged,
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise PromotionReceiptStateError("persisted promotion receipt is corrupt") from exc
        if receipt_raw != receipt.to_json():
            raise PromotionReceiptStateError("promotion receipt JSON is not canonical")
        if report_raw != canonical_json(report_payload):
            raise PromotionReceiptStateError("promotion report JSON is not canonical")
        columns = {
            "promotion_id": row["promotion_id"],
            "receipt_id": row["receipt_id"],
            "start_sha256": row["start_sha256"],
            "outcome": row["outcome"],
            "report_sha256": row["report_sha256"],
            "completed_at": row["completed_at"],
        }
        for name, value in columns.items():
            if getattr(receipt, name) != str(value):
                raise PromotionReceiptStateError(
                    f"promotion receipt column/json mismatch: {name}"
                )
        if receipt.digest != str(row["receipt_sha256"]):
            raise PromotionReceiptStateError("persisted promotion receipt digest mismatch")
        if canonical_sha(report_payload) != receipt.report_sha256:
            raise PromotionReceiptStateError("persisted promotion report digest mismatch")
        return PromotionCompletion(receipt=receipt, report=report_payload)

    def begin(
        self,
        authorization: PromotionAuthorization,
        *,
        start_id: str,
        primary_checkout_before_sha256: str,
        started_at: datetime | None = None,
    ) -> PromotionBeginResult:
        fields = _authorization_start_fields(
            authorization,
            start_id=start_id,
            primary_checkout_before_sha256=primary_checkout_before_sha256,
        )
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                rows = connection.execute(
                    """
                    SELECT * FROM promotion_starts_v1
                    WHERE promotion_id=? OR start_id=?
                       OR authorization_sha256=? OR approval_consumption_sha256=?
                    """,
                    (
                        fields["promotion_id"],
                        fields["start_id"],
                        fields["authorization_sha256"],
                        fields["approval_consumption_sha256"],
                    ),
                ).fetchall()
                if rows:
                    existing = [self._start_from_row(row) for row in rows]
                    if len(existing) != 1 or not _start_matches_fields(
                        existing[0], fields
                    ):
                        raise PromotionReceiptReplay(
                            "promotion start identity or authorization was already used"
                        )
                    receipt_row = connection.execute(
                        "SELECT * FROM promotion_receipts_v1 WHERE promotion_id=?",
                        (fields["promotion_id"],),
                    ).fetchone()
                    completion = (
                        None
                        if receipt_row is None
                        else self._completion_from_row(receipt_row)
                    )
                    connection.execute("COMMIT")
                    return PromotionBeginResult(
                        start=existing[0], execute=False, completion=completion
                    )
                record = _new_start(fields, started_at or self._now())
                connection.execute(
                    """
                    INSERT INTO promotion_starts_v1 (
                        promotion_id, start_id, start_sha256,
                        authorization_sha256, approval_consumption_sha256,
                        candidate_artifact_sha256, evidence_packet_sha256,
                        source_revision, target_ref, authorized_target_revision,
                        primary_checkout_before_sha256, started_at, start_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.promotion_id,
                        record.start_id,
                        record.start_sha256,
                        record.authorization_sha256,
                        record.approval_consumption_sha256,
                        record.candidate_artifact_sha256,
                        record.evidence_packet_sha256,
                        record.source_revision,
                        record.target_ref,
                        record.authorized_target_revision,
                        record.primary_checkout_before_sha256,
                        record.started_at,
                        canonical_json(record.to_dict()),
                    ),
                )
                connection.execute("COMMIT")
                return PromotionBeginResult(start=record, execute=True)
        except PromotionReceiptError:
            raise
        except sqlite3.IntegrityError as exc:
            raise PromotionReceiptReplay("promotion start uniqueness collision") from exc
        except sqlite3.DatabaseError as exc:
            raise PromotionReceiptStateError("promotion start persistence failed") from exc

    def complete(
        self,
        start: PromotionStartRecord,
        *,
        receipt_id: str,
        outcome: str,
        report: Mapping[str, object],
        primary_checkout_after_sha256: str,
        integration_branch: str | None = None,
        integration_revision: str | None = None,
        completed_at: datetime | None = None,
    ) -> PromotionCompletion:
        if not isinstance(start, PromotionStartRecord):
            raise TypeError("promotion completion requires PromotionStartRecord")
        report_payload = _canonical_report(report)
        report_sha256 = canonical_sha(report_payload)
        completed = completed_at or self._now()
        primary_after = _sha256(
            primary_checkout_after_sha256, "primary_checkout_after_sha256"
        )
        primary_unchanged = start.primary_checkout_before_sha256 == primary_after
        _validate_terminal_report(
            outcome=outcome,
            report=report_payload,
            integration_branch=integration_branch,
            primary_unchanged=primary_unchanged,
        )
        inputs = tuple(
            sorted(
                {
                    start.start_sha256,
                    start.authorization_sha256,
                    start.approval_consumption_sha256,
                    start.candidate_artifact_sha256,
                    start.evidence_packet_sha256,
                    report_sha256,
                    start.primary_checkout_before_sha256,
                    primary_after,
                }
            )
        )
        provenance = ContractProvenance(
            origin="kernel.promotion-receipt-ledger",
            source_revision=start.source_revision,
            created_at=_timestamp(completed),
            input_digests=inputs,
            trace_id=start.promotion_id,
        )
        receipt = PromotionReceipt(
            receipt_id=receipt_id,
            promotion_id=start.promotion_id,
            start_sha256=start.start_sha256,
            authorization_sha256=start.authorization_sha256,
            approval_consumption_sha256=start.approval_consumption_sha256,
            candidate_artifact_sha256=start.candidate_artifact_sha256,
            evidence_packet_sha256=start.evidence_packet_sha256,
            source_revision=start.source_revision,
            target_ref=start.target_ref,
            authorized_target_revision=start.authorized_target_revision,
            outcome=outcome,
            integration_branch=integration_branch,
            integration_revision=integration_revision,
            report_sha256=report_sha256,
            primary_checkout_before_sha256=start.primary_checkout_before_sha256,
            primary_checkout_after_sha256=primary_after,
            started_at=start.started_at,
            completed_at=_timestamp(completed),
            provenance=provenance,
        )
        completion = PromotionCompletion(receipt=receipt, report=report_payload)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                start_row = connection.execute(
                    "SELECT * FROM promotion_starts_v1 WHERE promotion_id=?",
                    (start.promotion_id,),
                ).fetchone()
                if start_row is None or self._start_from_row(start_row) != start:
                    raise PromotionReceiptBindingMismatch(
                        "promotion completion is not bound to the persisted start"
                    )
                rows = connection.execute(
                    """
                    SELECT * FROM promotion_receipts_v1
                    WHERE promotion_id=? OR receipt_id=? OR receipt_sha256=?
                       OR start_sha256=?
                    """,
                    (
                        receipt.promotion_id,
                        receipt.receipt_id,
                        receipt.digest,
                        receipt.start_sha256,
                    ),
                ).fetchall()
                if rows:
                    existing = [self._completion_from_row(row) for row in rows]
                    if len(existing) == 1 and existing[0] == completion:
                        connection.execute("COMMIT")
                        return existing[0]
                    raise PromotionReceiptReplay(
                        "promotion already has a different terminal receipt"
                    )
                connection.execute(
                    """
                    INSERT INTO promotion_receipts_v1 (
                        promotion_id, receipt_id, receipt_sha256, start_sha256,
                        outcome, report_sha256, completed_at,
                        receipt_json, report_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        receipt.promotion_id,
                        receipt.receipt_id,
                        receipt.digest,
                        receipt.start_sha256,
                        receipt.outcome,
                        receipt.report_sha256,
                        receipt.completed_at,
                        receipt.to_json(),
                        canonical_json(report_payload),
                    ),
                )
                connection.execute("COMMIT")
                return completion
        except PromotionReceiptError:
            raise
        except sqlite3.IntegrityError as exc:
            raise PromotionReceiptReplay("promotion receipt uniqueness collision") from exc
        except sqlite3.DatabaseError as exc:
            raise PromotionReceiptStateError("promotion receipt persistence failed") from exc

    def pending(self) -> tuple[PromotionStartRecord, ...]:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT s.* FROM promotion_starts_v1 AS s
                    LEFT JOIN promotion_receipts_v1 AS r
                      ON r.promotion_id = s.promotion_id
                    WHERE r.promotion_id IS NULL
                    ORDER BY s.started_at, s.promotion_id
                    """
                ).fetchall()
                return tuple(self._start_from_row(row) for row in rows)
        except PromotionReceiptError:
            raise
        except sqlite3.DatabaseError as exc:
            raise PromotionReceiptStateError("cannot read pending promotions") from exc

    def get_receipt(self, promotion_id: str) -> PromotionCompletion | None:
        promotion = _identifier(promotion_id, "promotion_id")
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM promotion_receipts_v1 WHERE promotion_id=?",
                    (promotion,),
                ).fetchone()
                return None if row is None else self._completion_from_row(row)
        except PromotionReceiptError:
            raise
        except sqlite3.DatabaseError as exc:
            raise PromotionReceiptStateError("cannot read promotion receipt") from exc

    def verify_receipt(self, completion: PromotionCompletion) -> PromotionCompletion:
        if not isinstance(completion, PromotionCompletion):
            raise TypeError("receipt verification requires PromotionCompletion")
        persisted = self.get_receipt(completion.receipt.promotion_id)
        if persisted is None or persisted != completion:
            raise PromotionReceiptBindingMismatch(
                "promotion receipt is not the exact persisted terminal record"
            )
        return persisted


__all__ = [
    "PromotionBeginResult",
    "PromotionCompletion",
    "PromotionLedger",
    "PromotionReceipt",
    "PromotionReceiptBindingMismatch",
    "PromotionReceiptError",
    "PromotionReceiptReplay",
    "PromotionReceiptStateError",
    "PromotionStartRecord",
]
