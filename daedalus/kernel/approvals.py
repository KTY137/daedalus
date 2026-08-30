# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Authenticated, one-use owner approval capabilities.

The signed approval remains inert until :class:`ApprovalLedger` authenticates
it again and atomically persists a binding-complete consumption receipt.  The
receipt is still not a promotion authority by itself: the later promotion
boundary must verify it against this ledger and re-check the live target HEAD
immediately before repository mutation.
"""
from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping

from daedalus.kernel.contracts import OwnerApproval
from daedalus.schemas import (
    ContractProvenance,
    _identifier,
    _revision,
    _sha256,
    _utc_timestamp,
)
from daedalus.spine.envelope import canonical_json, canonical_sha

_MAX_APPROVAL_TTL = timedelta(hours=24)


class ApprovalError(RuntimeError):
    """Base class for fail-closed approval rejection."""


class ApprovalSignatureError(ApprovalError):
    pass


class ApprovalExpired(ApprovalError):
    pass


class ApprovalBindingMismatch(ApprovalError):
    pass


class ApprovalReplay(ApprovalError):
    pass


class ApprovalStateError(ApprovalError):
    pass


@dataclass(frozen=True)
class ApprovalExpectation:
    operation: str
    nomination_receipt_sha256: str
    candidate_artifact_sha256: str
    evidence_packet_sha256: str
    base_revision: str
    target_ref: str
    current_target_revision: str

    def __post_init__(self) -> None:
        if self.operation != "promote-candidate":
            raise ValueError("approval expectation operation must be promote-candidate")
        for name in (
            "nomination_receipt_sha256",
            "candidate_artifact_sha256",
            "evidence_packet_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(
            self, "base_revision", _revision(self.base_revision, "base_revision")
        )
        object.__setattr__(
            self,
            "target_ref",
            _identifier(self.target_ref, "target_ref"),
        )
        object.__setattr__(
            self,
            "current_target_revision",
            _revision(self.current_target_revision, "current_target_revision"),
        )

    def to_dict(self) -> dict[str, str]:
        return dataclasses.asdict(self)

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class VerifiedOwnerApproval:
    """A fully bound result of authenticating one signed approval."""

    approval_sha256: str
    approval_id: str
    owner_id: str
    key_id: str
    operation: str
    nomination_receipt_sha256: str
    candidate_artifact_sha256: str
    evidence_packet_sha256: str
    base_revision: str
    nonce: str
    target_ref: str
    expected_target_revision: str
    issued_at: str
    expires_at: str
    signature_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "approval_sha256", _sha256(self.approval_sha256, "approval_sha256")
        )
        for name in ("approval_id", "owner_id", "key_id", "nonce"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        if self.operation != "promote-candidate":
            raise ValueError("verified approval operation must be promote-candidate")
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
            self, "target_ref", _identifier(self.target_ref, "target_ref")
        )
        object.__setattr__(
            self,
            "expected_target_revision",
            _revision(self.expected_target_revision, "expected_target_revision"),
        )
        object.__setattr__(
            self, "issued_at", _utc_timestamp(self.issued_at, "issued_at")
        )
        object.__setattr__(
            self, "expires_at", _utc_timestamp(self.expires_at, "expires_at")
        )
        if self.expires_at <= self.issued_at:
            raise ValueError("verified approval expires_at must be after issued_at")

    def to_dict(self) -> dict[str, str]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "VerifiedOwnerApproval":
        if not isinstance(payload, Mapping):
            raise ValueError("verified owner approval must be an object")
        expected = {field.name for field in dataclasses.fields(cls)}
        actual = set(payload)
        if actual != expected:
            raise ValueError(
                "verified owner approval fields mismatch: "
                f"missing={sorted(expected - actual)} extra={sorted(actual - expected)}"
            )
        return cls(**{key: str(payload[key]) for key in expected})

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class ConsumedOwnerApproval:
    """Persisted, binding-complete evidence of atomic approval consumption."""

    verified: VerifiedOwnerApproval
    expectation_sha256: str
    promotion_id: str
    consumed_at: str
    consumption_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.verified, VerifiedOwnerApproval):
            raise ValueError("consumed approval requires a verified approval")
        object.__setattr__(
            self,
            "expectation_sha256",
            _sha256(self.expectation_sha256, "expectation_sha256"),
        )
        object.__setattr__(
            self, "promotion_id", _identifier(self.promotion_id, "promotion_id")
        )
        object.__setattr__(
            self, "consumed_at", _utc_timestamp(self.consumed_at, "consumed_at")
        )
        object.__setattr__(
            self,
            "consumption_sha256",
            _sha256(self.consumption_sha256, "consumption_sha256"),
        )
        if self.consumed_at < self.verified.issued_at:
            raise ValueError("approval cannot be consumed before it was issued")
        if self.consumed_at >= self.verified.expires_at:
            raise ValueError("approval cannot be consumed at or after expiry")
        if self.consumption_sha256 != canonical_sha(self.payload_dict()):
            raise ValueError("approval consumption digest mismatch")

    def payload_dict(self) -> dict[str, object]:
        return {
            "verified": self.verified.to_dict(),
            "expectation_sha256": self.expectation_sha256,
            "promotion_id": self.promotion_id,
            "consumed_at": self.consumed_at,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.payload_dict(),
            "consumption_sha256": self.consumption_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "ConsumedOwnerApproval":
        if not isinstance(payload, Mapping):
            raise ValueError("consumed owner approval must be an object")
        expected = {
            "verified",
            "expectation_sha256",
            "promotion_id",
            "consumed_at",
            "consumption_sha256",
        }
        actual = set(payload)
        if actual != expected:
            raise ValueError(
                "consumed owner approval fields mismatch: "
                f"missing={sorted(expected - actual)} extra={sorted(actual - expected)}"
            )
        verified_payload = payload["verified"]
        if not isinstance(verified_payload, Mapping):
            raise ValueError("consumed approval verified field must be an object")
        return cls(
            verified=VerifiedOwnerApproval.from_dict(verified_payload),
            expectation_sha256=str(payload["expectation_sha256"]),
            promotion_id=str(payload["promotion_id"]),
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


def _parse_utc(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApprovalBindingMismatch(f"{label} is not ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ApprovalBindingMismatch(f"{label} is not timezone-aware")
    return parsed.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return _as_utc(value, "timestamp").isoformat(timespec="microseconds")


def _secret_bytes(secret: bytes | str) -> bytes:
    value = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
    if len(value) < 32:
        raise ValueError("owner approval secret must contain at least 32 bytes")
    return value


def _signature(signing_digest: str, secret: bytes | str) -> str:
    return hmac.new(
        _secret_bytes(secret), signing_digest.encode("ascii"), hashlib.sha256
    ).hexdigest()


def issue_owner_approval(
    *,
    approval_id: str,
    owner_id: str,
    key_id: str,
    operation: str,
    nomination_receipt_sha256: str,
    candidate_artifact_sha256: str,
    evidence_packet_sha256: str,
    base_revision: str,
    target_ref: str,
    expected_target_revision: str,
    nonce: str,
    issued_at: str,
    expires_at: str,
    provenance: ContractProvenance,
    secret: bytes | str,
) -> OwnerApproval:
    """Create a signed approval without persisting or consuming it."""

    placeholder = OwnerApproval(
        approval_id=approval_id,
        owner_id=owner_id,
        key_id=key_id,
        operation=operation,
        nomination_receipt_sha256=nomination_receipt_sha256,
        candidate_artifact_sha256=candidate_artifact_sha256,
        evidence_packet_sha256=evidence_packet_sha256,
        base_revision=base_revision,
        target_ref=target_ref,
        expected_target_revision=expected_target_revision,
        nonce=nonce,
        issued_at=issued_at,
        expires_at=expires_at,
        signature_sha256="0" * 64,
        provenance=provenance,
    )
    issued = _parse_utc(placeholder.issued_at, "approval.issued_at")
    expires = _parse_utc(placeholder.expires_at, "approval.expires_at")
    if expires - issued > _MAX_APPROVAL_TTL:
        raise ValueError("owner approval TTL exceeds the 24-hour Gate-0 maximum")
    return dataclasses.replace(
        placeholder,
        signature_sha256=_signature(placeholder.signing_digest, secret),
    )


def verify_owner_approval(
    approval: OwnerApproval,
    *,
    keyring: Mapping[tuple[str, str], bytes | str],
    expectation: ApprovalExpectation,
    now: datetime | None = None,
) -> VerifiedOwnerApproval:
    """Authenticate and validate every bounded approval dimension."""

    if not isinstance(approval, OwnerApproval):
        raise TypeError("verification requires a signed OwnerApproval")
    if not isinstance(expectation, ApprovalExpectation):
        raise TypeError("verification requires an ApprovalExpectation")
    secret = keyring.get((approval.owner_id, approval.key_id))
    if secret is None:
        raise ApprovalSignatureError("owner approval key is unknown")
    expected_signature = _signature(approval.signing_digest, secret)
    if not hmac.compare_digest(approval.signature_sha256, expected_signature):
        raise ApprovalSignatureError("owner approval signature mismatch")

    instant = _as_utc(now, "now") if now is not None else _utc_now()
    issued = _parse_utc(approval.issued_at, "approval.issued_at")
    expires = _parse_utc(approval.expires_at, "approval.expires_at")
    if expires - issued > _MAX_APPROVAL_TTL:
        raise ApprovalExpired("owner approval TTL exceeds the Gate-0 maximum")
    if instant < issued:
        raise ApprovalExpired("owner approval is not valid yet")
    if instant >= expires:
        raise ApprovalExpired("owner approval has expired")

    comparisons = {
        "operation": (approval.operation, expectation.operation),
        "nomination_receipt_sha256": (
            approval.nomination_receipt_sha256,
            expectation.nomination_receipt_sha256,
        ),
        "candidate_artifact_sha256": (
            approval.candidate_artifact_sha256,
            expectation.candidate_artifact_sha256,
        ),
        "evidence_packet_sha256": (
            approval.evidence_packet_sha256,
            expectation.evidence_packet_sha256,
        ),
        "base_revision": (approval.base_revision, expectation.base_revision),
        "target_ref": (approval.target_ref, expectation.target_ref),
        "expected_target_revision": (
            approval.expected_target_revision,
            expectation.current_target_revision,
        ),
    }
    mismatches = sorted(
        name
        for name, (actual, expected) in comparisons.items()
        if actual != expected
    )
    if mismatches:
        raise ApprovalBindingMismatch(
            "owner approval binding mismatch: " + ", ".join(mismatches)
        )

    return VerifiedOwnerApproval(
        approval_sha256=approval.digest,
        approval_id=approval.approval_id,
        owner_id=approval.owner_id,
        key_id=approval.key_id,
        operation=approval.operation,
        nomination_receipt_sha256=approval.nomination_receipt_sha256,
        candidate_artifact_sha256=approval.candidate_artifact_sha256,
        evidence_packet_sha256=approval.evidence_packet_sha256,
        base_revision=approval.base_revision,
        nonce=approval.nonce,
        target_ref=approval.target_ref,
        expected_target_revision=approval.expected_target_revision,
        issued_at=approval.issued_at,
        expires_at=approval.expires_at,
        signature_sha256=approval.signature_sha256,
    )


class ApprovalLedger:
    """SQLite authority for authenticated, atomic approval consumption."""

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
        return _as_utc(self._clock(), "approval ledger clock")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.path), isolation_level=None, timeout=30
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
                CREATE TABLE IF NOT EXISTS owner_approval_consumptions_v2 (
                    approval_sha256 TEXT PRIMARY KEY,
                    approval_id TEXT NOT NULL UNIQUE,
                    owner_id TEXT NOT NULL,
                    key_id TEXT NOT NULL,
                    nonce TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    nomination_receipt_sha256 TEXT NOT NULL,
                    candidate_artifact_sha256 TEXT NOT NULL,
                    evidence_packet_sha256 TEXT NOT NULL,
                    base_revision TEXT NOT NULL,
                    target_ref TEXT NOT NULL,
                    target_revision TEXT NOT NULL,
                    issued_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    signature_sha256 TEXT NOT NULL,
                    expectation_sha256 TEXT NOT NULL,
                    promotion_id TEXT NOT NULL UNIQUE,
                    consumed_at TEXT NOT NULL,
                    capability_sha256 TEXT NOT NULL,
                    consumption_sha256 TEXT NOT NULL UNIQUE,
                    approval_json TEXT NOT NULL,
                    expectation_json TEXT NOT NULL,
                    consumption_json TEXT NOT NULL,
                    UNIQUE(owner_id, key_id, nonce)
                )
                """
            )
            legacy = connection.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name='owner_approval_consumptions'"
            ).fetchone()
            if legacy is not None:
                legacy_count = connection.execute(
                    "SELECT COUNT(*) FROM owner_approval_consumptions"
                ).fetchone()[0]
                if legacy_count:
                    raise ApprovalStateError(
                        "legacy approval consumptions require explicit migration"
                    )

    def consume(
        self,
        approval: OwnerApproval,
        *,
        keyring: Mapping[tuple[str, str], bytes | str],
        expectation: ApprovalExpectation,
        promotion_id: str,
    ) -> ConsumedOwnerApproval:
        """Authenticate and consume one signed approval inside one transaction."""

        if not isinstance(approval, OwnerApproval):
            raise TypeError("consumption requires the signed OwnerApproval")
        normalized_promotion_id = _identifier(promotion_id, "promotion_id")
        preflight_at = self._now()
        preflight = verify_owner_approval(
            approval,
            keyring=keyring,
            expectation=expectation,
            now=preflight_at,
        )
        approval_json = canonical_json(approval.to_dict())
        expectation_json = canonical_json(expectation.to_dict())

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            transaction_at = self._now()
            if transaction_at < preflight_at:
                raise ApprovalStateError(
                    "approval ledger clock moved backwards before consumption"
                )
            verified = verify_owner_approval(
                approval,
                keyring=keyring,
                expectation=expectation,
                now=transaction_at,
            )
            if verified != preflight:
                raise ApprovalStateError(
                    "approval verification changed before consumption"
                )
            persistence_at = self._now()
            if persistence_at < transaction_at:
                raise ApprovalStateError(
                    "approval ledger clock moved backwards during consumption"
                )
            consumed_at = _timestamp(persistence_at)
            if consumed_at < verified.issued_at:
                raise ApprovalExpired(
                    "owner approval is not valid yet at consumption"
                )
            if consumed_at >= verified.expires_at:
                raise ApprovalExpired(
                    "owner approval expired before consumption persistence"
                )
            payload = {
                "verified": verified.to_dict(),
                "expectation_sha256": expectation.digest,
                "promotion_id": normalized_promotion_id,
                "consumed_at": consumed_at,
            }
            receipt = ConsumedOwnerApproval(
                verified=verified,
                expectation_sha256=expectation.digest,
                promotion_id=normalized_promotion_id,
                consumed_at=consumed_at,
                consumption_sha256=canonical_sha(payload),
            )
            consumption_json = canonical_json(receipt.to_dict())
            connection.execute(
                """
                INSERT INTO owner_approval_consumptions_v2 (
                    approval_sha256, approval_id, owner_id, key_id, nonce,
                    operation, nomination_receipt_sha256,
                    candidate_artifact_sha256, evidence_packet_sha256,
                    base_revision, target_ref, target_revision,
                    issued_at, expires_at, signature_sha256,
                    expectation_sha256, promotion_id, consumed_at,
                    capability_sha256, consumption_sha256,
                    approval_json, expectation_json, consumption_json
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?
                )
                """,
                (
                    verified.approval_sha256,
                    verified.approval_id,
                    verified.owner_id,
                    verified.key_id,
                    verified.nonce,
                    verified.operation,
                    verified.nomination_receipt_sha256,
                    verified.candidate_artifact_sha256,
                    verified.evidence_packet_sha256,
                    verified.base_revision,
                    verified.target_ref,
                    verified.expected_target_revision,
                    verified.issued_at,
                    verified.expires_at,
                    verified.signature_sha256,
                    expectation.digest,
                    normalized_promotion_id,
                    consumed_at,
                    verified.digest,
                    receipt.consumption_sha256,
                    approval_json,
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
            raise ApprovalReplay(
                "owner approval, nonce, or promotion identity was already consumed"
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
        receipt: ConsumedOwnerApproval,
        *,
        keyring: Mapping[tuple[str, str], bytes | str],
    ) -> ConsumedOwnerApproval:
        """Re-authenticate and require exact persisted receipt equality."""

        if not isinstance(receipt, ConsumedOwnerApproval):
            raise TypeError("verification requires a ConsumedOwnerApproval")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT approval_sha256, expectation_sha256, promotion_id,
                       capability_sha256, approval_json, expectation_json,
                       consumption_json
                FROM owner_approval_consumptions_v2
                WHERE consumption_sha256=?
                """,
                (receipt.consumption_sha256,),
            ).fetchone()
        if row is None:
            raise ApprovalStateError("approval consumption is not persisted")
        try:
            consumption_payload = json.loads(row["consumption_json"])
            approval_payload = json.loads(row["approval_json"])
            expectation_payload = json.loads(row["expectation_json"])
            if not isinstance(consumption_payload, dict):
                raise ValueError("consumption JSON must be an object")
            if not isinstance(approval_payload, dict):
                raise ValueError("approval JSON must be an object")
            if not isinstance(expectation_payload, dict):
                raise ValueError("expectation JSON must be an object")
            persisted = ConsumedOwnerApproval.from_dict(consumption_payload)
            stored_approval = OwnerApproval.from_dict(approval_payload)
            stored_expectation = ApprovalExpectation(**expectation_payload)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ApprovalStateError(
                "persisted approval consumption is corrupt"
            ) from exc
        secret = keyring.get(
            (stored_approval.owner_id, stored_approval.key_id)
        )
        if secret is None:
            raise ApprovalSignatureError(
                "persisted owner approval key is unknown"
            )
        if not hmac.compare_digest(
            stored_approval.signature_sha256,
            _signature(stored_approval.signing_digest, secret),
        ):
            raise ApprovalSignatureError(
                "persisted owner approval signature mismatch"
            )
        stored_verified = VerifiedOwnerApproval(
            approval_sha256=stored_approval.digest,
            approval_id=stored_approval.approval_id,
            owner_id=stored_approval.owner_id,
            key_id=stored_approval.key_id,
            operation=stored_approval.operation,
            nomination_receipt_sha256=stored_approval.nomination_receipt_sha256,
            candidate_artifact_sha256=stored_approval.candidate_artifact_sha256,
            evidence_packet_sha256=stored_approval.evidence_packet_sha256,
            base_revision=stored_approval.base_revision,
            nonce=stored_approval.nonce,
            target_ref=stored_approval.target_ref,
            expected_target_revision=stored_approval.expected_target_revision,
            issued_at=stored_approval.issued_at,
            expires_at=stored_approval.expires_at,
            signature_sha256=stored_approval.signature_sha256,
        )
        if (
            persisted != receipt
            or canonical_json(receipt.to_dict()) != row["consumption_json"]
            or canonical_json(stored_approval.to_dict()) != row["approval_json"]
            or canonical_json(stored_expectation.to_dict())
            != row["expectation_json"]
            or stored_verified != receipt.verified
            or stored_expectation.digest != receipt.expectation_sha256
            or row["approval_sha256"] != receipt.verified.approval_sha256
            or row["expectation_sha256"] != receipt.expectation_sha256
            or row["promotion_id"] != receipt.promotion_id
            or row["capability_sha256"] != receipt.verified.digest
        ):
            raise ApprovalStateError(
                "approval consumption does not match its persisted authority"
            )
        return persisted

    def consumed(self, approval_sha256: str) -> bool:
        digest = _sha256(approval_sha256, "approval_sha256")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM owner_approval_consumptions_v2 "
                "WHERE approval_sha256=?",
                (digest,),
            ).fetchone()
        return row is not None


def _cli_issue(input_path: Path, secret_env: str) -> int:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("owner approval request must be an object")
    secret = os.environ.get(secret_env)
    if secret is None:
        raise ValueError(
            f"missing owner approval secret environment variable {secret_env}"
        )
    if "signature_sha256" in payload:
        raise ValueError("owner approval issue input must not supply a signature")
    contract_type = payload.pop("contract_type", None)
    contract_version = payload.pop("contract_version", None)
    if contract_type not in (None, OwnerApproval.CONTRACT_TYPE):
        raise ValueError("owner approval issue input has wrong contract_type")
    if contract_version not in (None, OwnerApproval.CONTRACT_VERSION):
        raise ValueError("owner approval issue input has wrong contract_version")
    provenance_payload = payload.pop("provenance", None)
    if not isinstance(provenance_payload, Mapping):
        raise ValueError("owner approval issue input requires provenance")
    provenance = ContractProvenance.from_dict(provenance_payload)
    approval = issue_owner_approval(
        **payload, provenance=provenance, secret=secret
    )
    print(json.dumps(approval.to_dict(), indent=2, sort_keys=True))
    return 0


def _cli_verify(
    input_path: Path, expectation_path: Path, secret_env: str
) -> int:
    approval_payload = json.loads(input_path.read_text(encoding="utf-8"))
    expectation_payload = json.loads(
        expectation_path.read_text(encoding="utf-8")
    )
    if not isinstance(approval_payload, dict) or not isinstance(
        expectation_payload, dict
    ):
        raise ValueError("approval and expectation must be objects")
    secret = os.environ.get(secret_env)
    if secret is None:
        raise ValueError(
            f"missing owner approval secret environment variable {secret_env}"
        )
    approval = OwnerApproval.from_dict(approval_payload)
    expectation = ApprovalExpectation(**expectation_payload)
    verified = verify_owner_approval(
        approval,
        keyring={(approval.owner_id, approval.key_id): secret},
        expectation=expectation,
    )
    print(json.dumps(verified.to_dict(), indent=2, sort_keys=True))
    return 0


def main() -> int:
    import argparse

    # THE BOUNDARY COMES FIRST -- above parse_args, the c67fd116 shape. This
    # tail is the console door that MINTS owner approvals, the capability
    # invariant 5 makes promotion depend on, and it had no row: the one door
    # in the tree where forgetting the boundary costs trust rather than money.
    #
    # It writes nothing and spawns nothing; its only effect is SECRETS,
    # because the signing key enters THIS process from the environment inside
    # _cli_issue/_cli_verify and is used to compute or check the HMAC. That is
    # cli.doctor's rule (the value crosses into this process), not inheritance
    # from a child that authenticates itself.
    #
    # budget.process_guard is the only decision actually taken here, and it
    # guards spend rather than key custody -- an honest Gate-0 gap recorded in
    # the row note, not a claim that the key is protected. No
    # promotion.owner_approval decision is presented because this door ISSUES
    # approvals; requiring the contract it implements would be circular.
    from daedalus.budget import process_guard_boundary_decision
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "cli.approvals",
        REGISTRY_BY_ID["cli.approvals"].effects,
        (process_guard_boundary_decision(),),
    )

    parser = argparse.ArgumentParser(
        prog="python -m daedalus.kernel.approvals"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    issue = sub.add_parser("issue")
    issue.add_argument("--input", type=Path, required=True)
    issue.add_argument("--secret-env", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--input", type=Path, required=True)
    verify.add_argument("--expectation", type=Path, required=True)
    verify.add_argument("--secret-env", required=True)
    args = parser.parse_args()
    if args.command == "issue":
        return _cli_issue(args.input, args.secret_env)
    if args.command == "verify":
        return _cli_verify(
            args.input, args.expectation, args.secret_env
        )
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
