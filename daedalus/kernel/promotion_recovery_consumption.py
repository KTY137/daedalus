"""Durable one-use consumption of authenticated promotion recovery decisions.

The ledger records that one externally supplied owner decision was authenticated
against the current strict effect-only recovery state and consumed exactly once.
It does not cancel or terminalize an Effect Lease, invoke Git, mutate a worktree,
or perform promotion.  A later writer must verify this persisted receipt and
reproject current cross-ledger state again immediately before its own effect.
"""
from __future__ import annotations

import hmac
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from daedalus.schemas import _identifier, _sha256, _utc_timestamp
from daedalus.spine.envelope import canonical_json, canonical_sha

from .promotion_effects import PromotionEffectCapability
from .promotion_execution import PromotionExecutionLedger
from .promotion_recovery_decision import (
    PromotionRecoveryDecision,
    PromotionRecoveryDecisionExpired,
    PromotionRecoveryDecisionSignatureError,
    PromotionRecoveryExpectation,
    VerifiedPromotionRecoveryDecision,
    _MAX_RECOVERY_DECISION_TTL,
    _signature,
    verify_promotion_recovery_decision,
)


class PromotionRecoveryConsumptionError(RuntimeError):
    """Base class for fail-closed recovery-decision consumption failures."""


class PromotionRecoveryConsumptionReplay(PromotionRecoveryConsumptionError):
    pass


class PromotionRecoveryConsumptionStateError(PromotionRecoveryConsumptionError):
    pass


@dataclass(frozen=True)
class ConsumedPromotionRecoveryDecision:
    """Binding-complete receipt for one durable owner-decision consumption."""

    verified: VerifiedPromotionRecoveryDecision
    expectation: PromotionRecoveryExpectation
    consumed_at: str
    consumption_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.verified, VerifiedPromotionRecoveryDecision):
            raise ValueError(
                "recovery consumption requires VerifiedPromotionRecoveryDecision"
            )
        if not isinstance(self.expectation, PromotionRecoveryExpectation):
            raise ValueError(
                "recovery consumption requires PromotionRecoveryExpectation"
            )
        object.__setattr__(
            self,
            "consumed_at",
            _utc_timestamp(self.consumed_at, "consumed_at"),
        )
        object.__setattr__(
            self,
            "consumption_sha256",
            _sha256(self.consumption_sha256, "consumption_sha256"),
        )
        comparisons = {
            "promotion_authorization_sha256": (
                self.verified.promotion_authorization_sha256,
                self.expectation.promotion_authorization_sha256,
            ),
            "recovery_plan_sha256": (
                self.verified.recovery_plan_sha256,
                self.expectation.recovery_plan_sha256,
            ),
            "effect_start_receipt_sha256": (
                self.verified.effect_start_receipt_sha256,
                self.expectation.effect_start_receipt_sha256,
            ),
            "source_revision": (
                self.verified.source_revision,
                self.expectation.source_revision,
            ),
        }
        mismatches = sorted(
            name
            for name, (actual, expected) in comparisons.items()
            if actual != expected
        )
        if mismatches:
            raise ValueError(
                "recovery consumption expectation mismatch: "
                + ", ".join(mismatches)
            )
        if self.consumed_at < self.verified.issued_at:
            raise ValueError("recovery decision cannot be consumed before issue")
        if self.consumed_at >= self.verified.expires_at:
            raise ValueError("recovery decision cannot be consumed at or after expiry")
        if self.consumption_sha256 != canonical_sha(self.payload_dict()):
            raise ValueError("recovery consumption digest mismatch")

    def payload_dict(self) -> dict[str, object]:
        return {
            "verified": self.verified.to_dict(),
            "expectation": self.expectation.to_dict(),
            "consumed_at": self.consumed_at,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.payload_dict(),
            "consumption_sha256": self.consumption_sha256,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> "ConsumedPromotionRecoveryDecision":
        if not isinstance(payload, Mapping):
            raise ValueError("recovery consumption must be an object")
        expected = {
            "verified",
            "expectation",
            "consumed_at",
            "consumption_sha256",
        }
        actual = set(payload)
        if actual != expected:
            raise ValueError(
                "recovery consumption fields mismatch: "
                f"missing={sorted(expected - actual)} "
                f"extra={sorted(actual - expected)}"
            )
        verified_payload = payload["verified"]
        expectation_payload = payload["expectation"]
        if not isinstance(verified_payload, Mapping):
            raise ValueError("recovery consumption verified field must be an object")
        if not isinstance(expectation_payload, Mapping):
            raise ValueError(
                "recovery consumption expectation field must be an object"
            )
        verified_fields = {
            "decision_sha256",
            "decision_id",
            "owner_id",
            "key_id",
            "operation",
            "promotion_authorization_sha256",
            "recovery_plan_sha256",
            "effect_start_receipt_sha256",
            "source_revision",
            "nonce",
            "issued_at",
            "expires_at",
            "signature_sha256",
        }
        if set(verified_payload) != verified_fields:
            raise ValueError("verified recovery decision fields mismatch")
        expectation_fields = {
            "promotion_authorization_sha256",
            "recovery_plan_sha256",
            "effect_start_receipt_sha256",
            "source_revision",
        }
        if set(expectation_payload) != expectation_fields:
            raise ValueError("recovery expectation fields mismatch")
        return cls(
            verified=VerifiedPromotionRecoveryDecision(
                **{
                    key: str(verified_payload[key])
                    for key in verified_fields
                }
            ),
            expectation=PromotionRecoveryExpectation(
                **{
                    key: str(expectation_payload[key])
                    for key in expectation_fields
                }
            ),
            consumed_at=str(payload["consumed_at"]),
            consumption_sha256=str(payload["consumption_sha256"]),
        )

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


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


def _expectation_from_verified(
    verified: VerifiedPromotionRecoveryDecision,
) -> PromotionRecoveryExpectation:
    return PromotionRecoveryExpectation(
        promotion_authorization_sha256=(
            verified.promotion_authorization_sha256
        ),
        recovery_plan_sha256=verified.recovery_plan_sha256,
        effect_start_receipt_sha256=(
            verified.effect_start_receipt_sha256
        ),
        source_revision=verified.source_revision,
    )


class PromotionRecoveryConsumptionLedger:
    """SQLite authority for atomic one-use recovery-decision consumption."""

    def __init__(
        self,
        path: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock or _utc_now
        self._initialize()

    def _now(self) -> datetime:
        return _as_utc(self._clock(), "recovery consumption ledger clock")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.path),
            isolation_level=None,
            timeout=30,
        )
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
                CREATE TABLE IF NOT EXISTS promotion_recovery_consumptions_v1 (
                    decision_sha256 TEXT PRIMARY KEY,
                    decision_id TEXT NOT NULL UNIQUE,
                    owner_id TEXT NOT NULL,
                    key_id TEXT NOT NULL,
                    nonce TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    promotion_authorization_sha256 TEXT NOT NULL UNIQUE,
                    recovery_plan_sha256 TEXT NOT NULL UNIQUE,
                    effect_start_receipt_sha256 TEXT NOT NULL UNIQUE,
                    source_revision TEXT NOT NULL,
                    issued_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    signature_sha256 TEXT NOT NULL,
                    expectation_sha256 TEXT NOT NULL UNIQUE,
                    verified_sha256 TEXT NOT NULL UNIQUE,
                    consumed_at TEXT NOT NULL,
                    consumption_sha256 TEXT NOT NULL UNIQUE,
                    decision_json TEXT NOT NULL,
                    expectation_json TEXT NOT NULL,
                    consumption_json TEXT NOT NULL,
                    UNIQUE(owner_id, key_id, nonce)
                )
                """
            )

    def consume(
        self,
        decision: PromotionRecoveryDecision,
        *,
        keyring: Mapping[tuple[str, str], bytes | str],
        capability: PromotionEffectCapability,
        promotion_ledger: PromotionExecutionLedger,
    ) -> ConsumedPromotionRecoveryDecision:
        """Authenticate and atomically consume one current owner decision."""

        if not isinstance(decision, PromotionRecoveryDecision):
            raise TypeError("consumption requires PromotionRecoveryDecision")
        preflight_at = self._now()
        preflight = verify_promotion_recovery_decision(
            decision,
            keyring=keyring,
            capability=capability,
            promotion_ledger=promotion_ledger,
            now=preflight_at,
        )
        preflight_expectation = _expectation_from_verified(preflight)
        decision_json = canonical_json(decision.to_dict())

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            transaction_at = self._now()
            if transaction_at < preflight_at:
                raise PromotionRecoveryConsumptionStateError(
                    "recovery consumption clock moved backwards before transaction"
                )
            verified = verify_promotion_recovery_decision(
                decision,
                keyring=keyring,
                capability=capability,
                promotion_ledger=promotion_ledger,
                now=transaction_at,
            )
            expectation = _expectation_from_verified(verified)
            if verified != preflight or expectation != preflight_expectation:
                raise PromotionRecoveryConsumptionStateError(
                    "recovery decision authority changed before persistence"
                )

            persistence_at = self._now()
            if persistence_at < transaction_at:
                raise PromotionRecoveryConsumptionStateError(
                    "recovery consumption clock moved backwards during transaction"
                )
            consumed_at = _timestamp(persistence_at)
            if consumed_at >= verified.expires_at:
                raise PromotionRecoveryDecisionExpired(
                    "owner recovery decision expired before consumption persistence"
                )
            payload = {
                "verified": verified.to_dict(),
                "expectation": expectation.to_dict(),
                "consumed_at": consumed_at,
            }
            receipt = ConsumedPromotionRecoveryDecision(
                verified=verified,
                expectation=expectation,
                consumed_at=consumed_at,
                consumption_sha256=canonical_sha(payload),
            )
            expectation_json = canonical_json(expectation.to_dict())
            consumption_json = canonical_json(receipt.to_dict())
            connection.execute(
                """
                INSERT INTO promotion_recovery_consumptions_v1 (
                    decision_sha256, decision_id, owner_id, key_id, nonce,
                    operation, promotion_authorization_sha256,
                    recovery_plan_sha256, effect_start_receipt_sha256,
                    source_revision, issued_at, expires_at, signature_sha256,
                    expectation_sha256, verified_sha256, consumed_at,
                    consumption_sha256, decision_json, expectation_json,
                    consumption_json
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    verified.decision_sha256,
                    verified.decision_id,
                    verified.owner_id,
                    verified.key_id,
                    verified.nonce,
                    verified.operation,
                    verified.promotion_authorization_sha256,
                    verified.recovery_plan_sha256,
                    verified.effect_start_receipt_sha256,
                    verified.source_revision,
                    verified.issued_at,
                    verified.expires_at,
                    verified.signature_sha256,
                    expectation.digest,
                    verified.digest,
                    consumed_at,
                    receipt.consumption_sha256,
                    decision_json,
                    expectation_json,
                    consumption_json,
                ),
            )
            connection.execute("COMMIT")
            return receipt
        except sqlite3.IntegrityError as exc:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise PromotionRecoveryConsumptionReplay(
                "recovery decision, nonce, or promotion subject was already consumed"
            ) from exc
        except Exception:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            connection.close()

    def verify_consumption(
        self,
        receipt: ConsumedPromotionRecoveryDecision,
        *,
        keyring: Mapping[tuple[str, str], bytes | str],
    ) -> ConsumedPromotionRecoveryDecision:
        """Re-authenticate and require exact persisted receipt equality."""

        if not isinstance(receipt, ConsumedPromotionRecoveryDecision):
            raise TypeError(
                "verification requires ConsumedPromotionRecoveryDecision"
            )
        if not isinstance(keyring, Mapping):
            raise TypeError("verification requires an owner keyring mapping")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT decision_sha256, promotion_authorization_sha256,
                       recovery_plan_sha256, effect_start_receipt_sha256,
                       source_revision, expectation_sha256, verified_sha256,
                       decision_json, expectation_json, consumption_json
                FROM promotion_recovery_consumptions_v1
                WHERE consumption_sha256=?
                """,
                (receipt.consumption_sha256,),
            ).fetchone()
        if row is None:
            raise PromotionRecoveryConsumptionStateError(
                "recovery decision consumption is not persisted"
            )
        try:
            decision_payload = json.loads(row["decision_json"])
            expectation_payload = json.loads(row["expectation_json"])
            consumption_payload = json.loads(row["consumption_json"])
            if not isinstance(decision_payload, dict):
                raise ValueError("decision JSON must be an object")
            if not isinstance(expectation_payload, dict):
                raise ValueError("expectation JSON must be an object")
            if not isinstance(consumption_payload, dict):
                raise ValueError("consumption JSON must be an object")
            stored_decision = PromotionRecoveryDecision.from_dict(decision_payload)
            stored_expectation = PromotionRecoveryExpectation(
                **{
                    key: str(value)
                    for key, value in expectation_payload.items()
                }
            )
            persisted = ConsumedPromotionRecoveryDecision.from_dict(
                consumption_payload
            )
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise PromotionRecoveryConsumptionStateError(
                "persisted recovery decision consumption is corrupt"
            ) from exc

        secret = keyring.get(
            (stored_decision.owner_id, stored_decision.key_id)
        )
        if secret is None:
            raise PromotionRecoveryDecisionSignatureError(
                "persisted owner recovery decision key is unknown"
            )
        if not hmac.compare_digest(
            stored_decision.signature_sha256,
            _signature(stored_decision.signing_digest, secret),
        ):
            raise PromotionRecoveryDecisionSignatureError(
                "persisted owner recovery decision signature mismatch"
            )
        issued = datetime.fromisoformat(
            stored_decision.issued_at.replace("Z", "+00:00")
        )
        expires = datetime.fromisoformat(
            stored_decision.expires_at.replace("Z", "+00:00")
        )
        if expires - issued > _MAX_RECOVERY_DECISION_TTL:
            raise PromotionRecoveryConsumptionStateError(
                "persisted recovery decision exceeds maximum TTL"
            )
        stored_verified = VerifiedPromotionRecoveryDecision(
            decision_sha256=stored_decision.digest,
            decision_id=stored_decision.decision_id,
            owner_id=stored_decision.owner_id,
            key_id=stored_decision.key_id,
            operation=stored_decision.operation,
            promotion_authorization_sha256=(
                stored_decision.promotion_authorization_sha256
            ),
            recovery_plan_sha256=stored_decision.recovery_plan_sha256,
            effect_start_receipt_sha256=(
                stored_decision.effect_start_receipt_sha256
            ),
            source_revision=stored_decision.provenance.source_revision,
            nonce=stored_decision.nonce,
            issued_at=stored_decision.issued_at,
            expires_at=stored_decision.expires_at,
            signature_sha256=stored_decision.signature_sha256,
        )
        if (
            persisted != receipt
            or canonical_json(receipt.to_dict()) != row["consumption_json"]
            or canonical_json(stored_decision.to_dict()) != row["decision_json"]
            or canonical_json(stored_expectation.to_dict())
            != row["expectation_json"]
            or stored_verified != receipt.verified
            or stored_expectation != receipt.expectation
            or row["decision_sha256"] != stored_decision.digest
            or row["promotion_authorization_sha256"]
            != stored_expectation.promotion_authorization_sha256
            or row["recovery_plan_sha256"]
            != stored_expectation.recovery_plan_sha256
            or row["effect_start_receipt_sha256"]
            != stored_expectation.effect_start_receipt_sha256
            or row["source_revision"] != stored_expectation.source_revision
            or row["expectation_sha256"] != stored_expectation.digest
            or row["verified_sha256"] != stored_verified.digest
        ):
            raise PromotionRecoveryConsumptionStateError(
                "recovery consumption does not match persisted authority"
            )
        return persisted

    def consumed(self, decision_sha256: str) -> bool:
        digest = _sha256(decision_sha256, "decision_sha256")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM promotion_recovery_consumptions_v1 "
                "WHERE decision_sha256=?",
                (digest,),
            ).fetchone()
        return row is not None


__all__ = [
    "ConsumedPromotionRecoveryDecision",
    "PromotionRecoveryConsumptionError",
    "PromotionRecoveryConsumptionLedger",
    "PromotionRecoveryConsumptionReplay",
    "PromotionRecoveryConsumptionStateError",
]
