"""Persisted quarantine state for externally trusted runtime evidence.

The external trusted-envelope set remains the root of authority. This module
never upgrades a locally constructed conformance envelope into trusted evidence.
It verifies one exact live envelope and then persists only its exact runtime,
manifest, probe, receipt, revision, observation time and expiry bindings.
Every stored row is authenticated with an external ledger-integrity key; a
canonical digest alone is not treated as authentication. Rotation and expiry
are monotonic: older evidence cannot replace newer evidence, and a quarantined
record cannot be silently reactivated.
"""
from __future__ import annotations

import hashlib
import hmac
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from daedalus.schemas import _identifier, _non_empty, _revision, _sha256, _utc_timestamp
from daedalus.spine.envelope import canonical_sha

from .profiles import RuntimeConformanceEnvelope, RuntimeProbeIdentity
from .trust import verify_production_runtime_envelope

_MAX_RECEIPT_AGE = timedelta(days=7)
_ACTIVE = "ACTIVE"
_QUARANTINED = "QUARANTINED"


class RuntimeTrustStoreError(RuntimeError):
    """Base class for persisted runtime-trust failures."""


class RuntimeTrustNotFound(RuntimeTrustStoreError):
    pass


class RuntimeTrustBindingMismatch(RuntimeTrustStoreError):
    pass


class RuntimeTrustExpired(RuntimeTrustStoreError):
    pass


class RuntimeTrustQuarantined(RuntimeTrustStoreError):
    pass


class RuntimeTrustCorrupt(RuntimeTrustStoreError):
    pass


def _as_utc(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _parse_timestamp(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise RuntimeTrustBindingMismatch(f"{label} must be ISO-8601") from exc
    return _as_utc(parsed, label)


def _timestamp(value: datetime) -> str:
    return _as_utc(value, "timestamp").isoformat(timespec="microseconds")


def _secret_bytes(secret: bytes | str) -> bytes:
    value = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
    if len(value) < 32:
        raise ValueError("runtime trust ledger integrity key must contain at least 32 bytes")
    return value


def _record_hmac(record_sha256: str, key: bytes) -> str:
    return hmac.new(key, record_sha256.encode("ascii"), hashlib.sha256).hexdigest()


def _record_payload(
    *,
    runtime_id: str,
    envelope_sha256: str,
    probe_identity_sha256: str,
    conformance_receipt_sha256: str,
    runtime_manifest_sha256: str,
    source_revision: str,
    observed_at: str,
    admitted_at: str,
    expires_at: str,
    state: str,
    state_changed_at: str,
    reason: str,
) -> dict[str, str]:
    return {
        "runtime_id": runtime_id,
        "envelope_sha256": envelope_sha256,
        "probe_identity_sha256": probe_identity_sha256,
        "conformance_receipt_sha256": conformance_receipt_sha256,
        "runtime_manifest_sha256": runtime_manifest_sha256,
        "source_revision": source_revision,
        "observed_at": observed_at,
        "admitted_at": admitted_at,
        "expires_at": expires_at,
        "state": state,
        "state_changed_at": state_changed_at,
        "reason": reason,
    }


@dataclass(frozen=True)
class RuntimeTrustRecord:
    runtime_id: str
    envelope_sha256: str
    probe_identity_sha256: str
    conformance_receipt_sha256: str
    runtime_manifest_sha256: str
    source_revision: str
    observed_at: str
    admitted_at: str
    expires_at: str
    state: str
    state_changed_at: str
    reason: str
    record_sha256: str
    record_hmac_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "runtime_id", _identifier(self.runtime_id, "runtime_id"))
        for name in (
            "envelope_sha256",
            "probe_identity_sha256",
            "conformance_receipt_sha256",
            "runtime_manifest_sha256",
            "record_sha256",
            "record_hmac_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(
            self, "source_revision", _revision(self.source_revision, "source_revision")
        )
        for name in ("observed_at", "admitted_at", "expires_at", "state_changed_at"):
            object.__setattr__(self, name, _utc_timestamp(getattr(self, name), name))
        observed = _parse_timestamp(self.observed_at, "observed_at")
        admitted = _parse_timestamp(self.admitted_at, "admitted_at")
        expires = _parse_timestamp(self.expires_at, "expires_at")
        changed = _parse_timestamp(self.state_changed_at, "state_changed_at")
        if observed > admitted:
            raise RuntimeTrustCorrupt("runtime trust observation follows admission")
        if expires <= admitted:
            raise RuntimeTrustCorrupt("runtime trust expiry must follow admission")
        if expires > observed + _MAX_RECEIPT_AGE:
            raise RuntimeTrustCorrupt("runtime trust outlives its conformance receipt")
        if changed < admitted:
            raise RuntimeTrustCorrupt("runtime trust state change predates admission")
        if self.state not in {_ACTIVE, _QUARANTINED}:
            raise RuntimeTrustCorrupt("runtime trust state is unknown")
        if self.state == _ACTIVE and self.reason:
            raise RuntimeTrustCorrupt("active runtime trust record cannot carry a reason")
        if self.state == _QUARANTINED:
            object.__setattr__(
                self, "reason", _non_empty(self.reason, "reason", max_length=500)
            )
        expected = canonical_sha(self.payload())
        if self.record_sha256 != expected:
            raise RuntimeTrustCorrupt("runtime trust record digest mismatch")

    def payload(self) -> dict[str, str]:
        return _record_payload(
            runtime_id=self.runtime_id,
            envelope_sha256=self.envelope_sha256,
            probe_identity_sha256=self.probe_identity_sha256,
            conformance_receipt_sha256=self.conformance_receipt_sha256,
            runtime_manifest_sha256=self.runtime_manifest_sha256,
            source_revision=self.source_revision,
            observed_at=self.observed_at,
            admitted_at=self.admitted_at,
            expires_at=self.expires_at,
            state=self.state,
            state_changed_at=self.state_changed_at,
            reason=self.reason,
        )

    def to_dict(self) -> dict[str, str]:
        return {
            **self.payload(),
            "record_sha256": self.record_sha256,
            "record_hmac_sha256": self.record_hmac_sha256,
        }


def _make_record(
    *,
    integrity_key: bytes,
    runtime_id: str,
    envelope_sha256: str,
    probe_identity_sha256: str,
    conformance_receipt_sha256: str,
    runtime_manifest_sha256: str,
    source_revision: str,
    observed_at: str,
    admitted_at: str,
    expires_at: str,
    state: str,
    state_changed_at: str,
    reason: str,
) -> RuntimeTrustRecord:
    payload = _record_payload(
        runtime_id=runtime_id,
        envelope_sha256=envelope_sha256,
        probe_identity_sha256=probe_identity_sha256,
        conformance_receipt_sha256=conformance_receipt_sha256,
        runtime_manifest_sha256=runtime_manifest_sha256,
        source_revision=source_revision,
        observed_at=observed_at,
        admitted_at=admitted_at,
        expires_at=expires_at,
        state=state,
        state_changed_at=state_changed_at,
        reason=reason,
    )
    digest = canonical_sha(payload)
    return RuntimeTrustRecord(
        **payload,
        record_sha256=digest,
        record_hmac_sha256=_record_hmac(digest, integrity_key),
    )


class RuntimeTrustLedger:
    """SQLite-backed exact-envelope admission and monotonic quarantine ledger."""

    def __init__(self, path: str | Path, *, integrity_key: bytes | str):
        self.path = Path(path)
        self._integrity_key = _secret_bytes(integrity_key)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), isolation_level=None, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_trust_records (
                    envelope_sha256 TEXT PRIMARY KEY,
                    runtime_id TEXT NOT NULL,
                    probe_identity_sha256 TEXT NOT NULL,
                    conformance_receipt_sha256 TEXT NOT NULL,
                    runtime_manifest_sha256 TEXT NOT NULL,
                    source_revision TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    admitted_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    state TEXT NOT NULL,
                    state_changed_at TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    record_sha256 TEXT NOT NULL UNIQUE,
                    record_hmac_sha256 TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS runtime_trust_runtime_idx "
                "ON runtime_trust_records(runtime_id, state)"
            )

    def _from_row(self, row: sqlite3.Row) -> RuntimeTrustRecord:
        try:
            record = RuntimeTrustRecord(**dict(row))
        except (TypeError, ValueError, RuntimeTrustStoreError) as exc:
            raise RuntimeTrustCorrupt("persisted runtime trust row is invalid") from exc
        expected_hmac = _record_hmac(record.record_sha256, self._integrity_key)
        if not hmac.compare_digest(record.record_hmac_sha256, expected_hmac):
            raise RuntimeTrustCorrupt("persisted runtime trust authentication failed")
        return record

    @staticmethod
    def _insert(connection: sqlite3.Connection, record: RuntimeTrustRecord) -> None:
        connection.execute(
            """
            INSERT INTO runtime_trust_records (
                envelope_sha256, runtime_id, probe_identity_sha256,
                conformance_receipt_sha256, runtime_manifest_sha256,
                source_revision, observed_at, admitted_at, expires_at, state,
                state_changed_at, reason, record_sha256, record_hmac_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.envelope_sha256,
                record.runtime_id,
                record.probe_identity_sha256,
                record.conformance_receipt_sha256,
                record.runtime_manifest_sha256,
                record.source_revision,
                record.observed_at,
                record.admitted_at,
                record.expires_at,
                record.state,
                record.state_changed_at,
                record.reason,
                record.record_sha256,
                record.record_hmac_sha256,
            ),
        )

    @staticmethod
    def _replace(connection: sqlite3.Connection, record: RuntimeTrustRecord) -> None:
        result = connection.execute(
            """
            UPDATE runtime_trust_records SET
                runtime_id=?, probe_identity_sha256=?,
                conformance_receipt_sha256=?, runtime_manifest_sha256=?,
                source_revision=?, observed_at=?, admitted_at=?, expires_at=?, state=?,
                state_changed_at=?, reason=?, record_sha256=?, record_hmac_sha256=?
            WHERE envelope_sha256=?
            """,
            (
                record.runtime_id,
                record.probe_identity_sha256,
                record.conformance_receipt_sha256,
                record.runtime_manifest_sha256,
                record.source_revision,
                record.observed_at,
                record.admitted_at,
                record.expires_at,
                record.state,
                record.state_changed_at,
                record.reason,
                record.record_sha256,
                record.record_hmac_sha256,
                record.envelope_sha256,
            ),
        )
        if result.rowcount != 1:
            raise RuntimeTrustCorrupt("runtime trust state transition lost its row")

    def _quarantined(
        self, record: RuntimeTrustRecord, *, changed_at: str, reason: str
    ) -> RuntimeTrustRecord:
        return _make_record(
            integrity_key=self._integrity_key,
            runtime_id=record.runtime_id,
            envelope_sha256=record.envelope_sha256,
            probe_identity_sha256=record.probe_identity_sha256,
            conformance_receipt_sha256=record.conformance_receipt_sha256,
            runtime_manifest_sha256=record.runtime_manifest_sha256,
            source_revision=record.source_revision,
            observed_at=record.observed_at,
            admitted_at=record.admitted_at,
            expires_at=record.expires_at,
            state=_QUARANTINED,
            state_changed_at=changed_at,
            reason=reason,
        )

    def admit(
        self,
        envelope: RuntimeConformanceEnvelope,
        identity: RuntimeProbeIdentity,
        receipt,
        manifest,
        *,
        trusted_envelope_sha256s: Iterable[str],
        admitted_at: datetime,
        expires_at: datetime,
    ) -> RuntimeTrustRecord:
        """Verify external trust and atomically rotate one runtime's active record."""

        admitted = _as_utc(admitted_at, "admitted_at")
        expires = _as_utc(expires_at, "expires_at")
        observed = _parse_timestamp(receipt.finished_at, "receipt.finished_at")
        if observed > admitted:
            raise RuntimeTrustBindingMismatch(
                "runtime conformance receipt finishes after trust admission"
            )
        if expires <= admitted:
            raise ValueError("runtime trust expires_at must follow admitted_at")
        if expires > observed + _MAX_RECEIPT_AGE:
            raise ValueError("runtime trust expiry exceeds receipt freshness window")
        verify_production_runtime_envelope(
            envelope,
            identity,
            receipt,
            manifest,
            trusted_envelope_sha256s=trusted_envelope_sha256s,
            now=admitted,
        )
        comparisons = {
            "runtime_id": (envelope.runtime_id, manifest.runtime_id),
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
        }
        mismatches = sorted(
            name for name, (actual, expected) in comparisons.items() if actual != expected
        )
        if mismatches:
            raise RuntimeTrustBindingMismatch(
                "runtime trust admission binding mismatch: " + ", ".join(mismatches)
            )
        admitted_text = _timestamp(admitted)
        observed_text = _timestamp(observed)
        record = _make_record(
            integrity_key=self._integrity_key,
            runtime_id=manifest.runtime_id,
            envelope_sha256=envelope.digest,
            probe_identity_sha256=identity.digest,
            conformance_receipt_sha256=receipt.digest,
            runtime_manifest_sha256=manifest.digest,
            source_revision=manifest.source_revision,
            observed_at=observed_text,
            admitted_at=admitted_text,
            expires_at=_timestamp(expires),
            state=_ACTIVE,
            state_changed_at=admitted_text,
            reason="",
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM runtime_trust_records WHERE envelope_sha256=?",
                (record.envelope_sha256,),
            ).fetchone()
            if row is not None:
                existing = self._from_row(row)
                if existing == record:
                    connection.execute("COMMIT")
                    return existing
                connection.execute("ROLLBACK")
                raise RuntimeTrustBindingMismatch(
                    "runtime trust envelope replay changed persisted bindings"
                )
            active_rows = connection.execute(
                "SELECT * FROM runtime_trust_records WHERE runtime_id=? AND state=?",
                (record.runtime_id, _ACTIVE),
            ).fetchall()
            for active_row in active_rows:
                active = self._from_row(active_row)
                if observed <= _parse_timestamp(active.observed_at, "active.observed_at"):
                    connection.execute("ROLLBACK")
                    raise RuntimeTrustBindingMismatch(
                        "runtime trust evidence is not newer than the active observation"
                    )
                rotated = self._quarantined(
                    active,
                    changed_at=admitted_text,
                    reason=f"superseded-by:{record.envelope_sha256}",
                )
                self._replace(connection, rotated)
            self._insert(connection, record)
            connection.execute("COMMIT")
        return record

    def require_active(
        self,
        *,
        runtime_id: str,
        envelope_sha256: str,
        runtime_manifest_sha256: str,
        conformance_receipt_sha256: str,
        source_revision: str,
        now: datetime,
    ) -> RuntimeTrustRecord:
        """Return only the exact current, authenticated and unexpired record."""

        runtime = _identifier(runtime_id, "runtime_id")
        envelope_digest = _sha256(envelope_sha256, "envelope_sha256")
        manifest_digest = _sha256(
            runtime_manifest_sha256, "runtime_manifest_sha256"
        )
        receipt_digest = _sha256(
            conformance_receipt_sha256, "conformance_receipt_sha256"
        )
        revision = _revision(source_revision, "source_revision")
        instant = _as_utc(now, "now")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM runtime_trust_records "
                "WHERE runtime_id=? AND envelope_sha256=?",
                (runtime, envelope_digest),
            ).fetchone()
            if row is None:
                connection.execute("ROLLBACK")
                raise RuntimeTrustNotFound("runtime envelope is not admitted")
            record = self._from_row(row)
            if record.state != _ACTIVE:
                connection.execute("ROLLBACK")
                raise RuntimeTrustQuarantined(
                    f"runtime envelope is quarantined: {record.reason}"
                )
            expires = _parse_timestamp(record.expires_at, "expires_at")
            if instant >= expires:
                expired = self._quarantined(
                    record,
                    changed_at=_timestamp(instant),
                    reason="expired",
                )
                self._replace(connection, expired)
                connection.execute("COMMIT")
                raise RuntimeTrustExpired("runtime trust record has expired")
            comparisons = {
                "runtime_manifest_sha256": (
                    record.runtime_manifest_sha256,
                    manifest_digest,
                ),
                "conformance_receipt_sha256": (
                    record.conformance_receipt_sha256,
                    receipt_digest,
                ),
                "source_revision": (record.source_revision, revision),
            }
            mismatches = sorted(
                name
                for name, (actual, expected) in comparisons.items()
                if actual != expected
            )
            if mismatches:
                connection.execute("ROLLBACK")
                raise RuntimeTrustBindingMismatch(
                    "runtime trust lookup binding mismatch: " + ", ".join(mismatches)
                )
            connection.execute("COMMIT")
            return record

    def quarantine(
        self,
        *,
        runtime_id: str,
        envelope_sha256: str,
        reason: str,
        quarantined_at: datetime,
    ) -> RuntimeTrustRecord:
        """Monotonically quarantine the exact active envelope; never reactivate it."""

        runtime = _identifier(runtime_id, "runtime_id")
        envelope_digest = _sha256(envelope_sha256, "envelope_sha256")
        why = _non_empty(reason, "reason", max_length=500)
        changed = _timestamp(_as_utc(quarantined_at, "quarantined_at"))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM runtime_trust_records "
                "WHERE runtime_id=? AND envelope_sha256=?",
                (runtime, envelope_digest),
            ).fetchone()
            if row is None:
                connection.execute("ROLLBACK")
                raise RuntimeTrustNotFound("runtime envelope is not admitted")
            record = self._from_row(row)
            if record.state == _QUARANTINED:
                if record.reason != why:
                    connection.execute("ROLLBACK")
                    raise RuntimeTrustQuarantined(
                        "runtime envelope is already quarantined for another reason"
                    )
                connection.execute("COMMIT")
                return record
            if _parse_timestamp(changed, "quarantined_at") < _parse_timestamp(
                record.admitted_at, "admitted_at"
            ):
                connection.execute("ROLLBACK")
                raise ValueError("quarantine time predates runtime trust admission")
            updated = self._quarantined(record, changed_at=changed, reason=why)
            self._replace(connection, updated)
            connection.execute("COMMIT")
            return updated

    def records(self, runtime_id: str | None = None) -> tuple[RuntimeTrustRecord, ...]:
        """Return a deterministic, authenticated audit projection."""

        with self._connect() as connection:
            if runtime_id is None:
                rows = connection.execute(
                    "SELECT * FROM runtime_trust_records "
                    "ORDER BY runtime_id, observed_at, envelope_sha256"
                ).fetchall()
            else:
                runtime = _identifier(runtime_id, "runtime_id")
                rows = connection.execute(
                    "SELECT * FROM runtime_trust_records WHERE runtime_id=? "
                    "ORDER BY observed_at, envelope_sha256",
                    (runtime,),
                ).fetchall()
        return tuple(self._from_row(row) for row in rows)


__all__ = [
    "RuntimeTrustBindingMismatch",
    "RuntimeTrustCorrupt",
    "RuntimeTrustExpired",
    "RuntimeTrustLedger",
    "RuntimeTrustNotFound",
    "RuntimeTrustQuarantined",
    "RuntimeTrustRecord",
    "RuntimeTrustStoreError",
]
