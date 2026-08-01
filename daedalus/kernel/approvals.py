"""Authenticated, one-use owner approval capabilities.

This module deliberately stops before promotion. It authenticates an approval,
binds it to exact candidate/evidence/base/target identities, and atomically
consumes the nonce. The later promotion Work Packet must re-check the live
Target HEAD immediately before applying a candidate and must retain the
returned capability as evidence.
"""
from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from daedalus.schemas import ContractProvenance
from daedalus.kernel.contracts import OwnerApproval
from daedalus.spine.envelope import canonical_sha


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


@dataclass(frozen=True)
class ApprovalExpectation:
    operation: str
    nomination_receipt_sha256: str
    candidate_artifact_sha256: str
    evidence_packet_sha256: str
    base_revision: str
    target_ref: str
    current_target_revision: str


@dataclass(frozen=True)
class VerifiedOwnerApproval:
    approval_sha256: str
    approval_id: str
    owner_id: str
    key_id: str
    operation: str
    nonce: str
    target_ref: str
    expected_target_revision: str
    issued_at: str
    expires_at: str

    def to_dict(self) -> dict[str, str]:
        return dataclasses.asdict(self)

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class ConsumedOwnerApproval:
    """Atomic replay-ledger evidence required by the promotion boundary."""

    verified: VerifiedOwnerApproval
    promotion_id: str
    consumed_at: str
    consumption_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "verified": self.verified.to_dict(),
            "promotion_id": self.promotion_id,
            "consumed_at": self.consumed_at,
            "consumption_sha256": self.consumption_sha256,
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ApprovalBindingMismatch("approval timestamp is not timezone-aware")
    return parsed.astimezone(timezone.utc)


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

    secret = keyring.get((approval.owner_id, approval.key_id))
    if secret is None:
        raise ApprovalSignatureError("owner approval key is unknown")
    expected_signature = _signature(approval.signing_digest, secret)
    if not hmac.compare_digest(approval.signature_sha256, expected_signature):
        raise ApprovalSignatureError("owner approval signature mismatch")

    instant = (now or _utc_now()).astimezone(timezone.utc)
    issued = _parse_utc(approval.issued_at)
    expires = _parse_utc(approval.expires_at)
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
    mismatches = [name for name, (actual, expected) in comparisons.items() if actual != expected]
    if mismatches:
        raise ApprovalBindingMismatch(
            "owner approval binding mismatch: " + ", ".join(sorted(mismatches))
        )

    return VerifiedOwnerApproval(
        approval_sha256=approval.digest,
        approval_id=approval.approval_id,
        owner_id=approval.owner_id,
        key_id=approval.key_id,
        operation=approval.operation,
        nonce=approval.nonce,
        target_ref=approval.target_ref,
        expected_target_revision=approval.expected_target_revision,
        issued_at=approval.issued_at,
        expires_at=approval.expires_at,
    )


class ApprovalLedger:
    """SQLite-backed atomic nonce consumption and replay refusal."""

    def __init__(self, path: str | Path):
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
                CREATE TABLE IF NOT EXISTS owner_approval_consumptions (
                    approval_sha256 TEXT PRIMARY KEY,
                    approval_id TEXT NOT NULL UNIQUE,
                    owner_id TEXT NOT NULL,
                    key_id TEXT NOT NULL,
                    nonce TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    target_ref TEXT NOT NULL,
                    target_revision TEXT NOT NULL,
                    promotion_id TEXT NOT NULL UNIQUE,
                    consumed_at TEXT NOT NULL,
                    capability_sha256 TEXT NOT NULL,
                    consumption_sha256 TEXT NOT NULL UNIQUE,
                    UNIQUE(owner_id, key_id, nonce)
                )
                """
            )

    def consume(
        self,
        verified: VerifiedOwnerApproval,
        *,
        promotion_id: str,
        consumed_at: datetime | None = None,
    ) -> ConsumedOwnerApproval:
        """Consume an authenticated approval exactly once.

        The returned object is the only capability shape the later promotion
        boundary should accept. The target HEAD is retained but must still be
        compared to the live target immediately before mutation.
        """

        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", promotion_id):
            raise ValueError("promotion_id must be a bounded identifier")
        consumed_instant = (consumed_at or _utc_now()).astimezone(timezone.utc)
        if consumed_instant < _parse_utc(verified.issued_at):
            raise ApprovalExpired("owner approval is not valid yet at consumption")
        if consumed_instant >= _parse_utc(verified.expires_at):
            raise ApprovalExpired("owner approval expired before consumption")
        timestamp = consumed_instant.isoformat(timespec="microseconds")
        record = {
            **verified.to_dict(),
            "promotion_id": promotion_id,
            "consumed_at": timestamp,
        }
        record_sha256 = canonical_sha(record)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO owner_approval_consumptions (
                    approval_sha256, approval_id, owner_id, key_id, nonce,
                    operation, target_ref, target_revision, promotion_id,
                    consumed_at, capability_sha256, consumption_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    verified.approval_sha256,
                    verified.approval_id,
                    verified.owner_id,
                    verified.key_id,
                    verified.nonce,
                    verified.operation,
                    verified.target_ref,
                    verified.expected_target_revision,
                    promotion_id,
                    timestamp,
                    verified.digest,
                    record_sha256,
                ),
            )
            connection.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise ApprovalReplay("owner approval or nonce was already consumed") from exc
        except Exception:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            connection.close()
        return ConsumedOwnerApproval(
            verified=verified,
            promotion_id=promotion_id,
            consumed_at=timestamp,
            consumption_sha256=record_sha256,
        )

    def consumed(self, approval_sha256: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM owner_approval_consumptions WHERE approval_sha256=?",
                (approval_sha256,),
            ).fetchone()
        return row is not None


def _cli_issue(input_path: Path, secret_env: str) -> int:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("owner approval request must be an object")
    secret = os.environ.get(secret_env)
    if secret is None:
        raise ValueError(f"missing owner approval secret environment variable {secret_env}")
    provenance = ContractProvenance.from_dict(payload.pop("provenance"))
    payload.pop("contract_type", None)
    payload.pop("contract_version", None)
    payload.pop("signature_sha256", None)
    approval = issue_owner_approval(**payload, provenance=provenance, secret=secret)
    print(json.dumps(approval.to_dict(), indent=2, sort_keys=True))
    return 0


def _cli_verify(input_path: Path, expectation_path: Path, secret_env: str) -> int:
    approval_payload = json.loads(input_path.read_text(encoding="utf-8"))
    expectation_payload = json.loads(expectation_path.read_text(encoding="utf-8"))
    if not isinstance(approval_payload, dict) or not isinstance(expectation_payload, dict):
        raise ValueError("approval and expectation must be objects")
    secret = os.environ.get(secret_env)
    if secret is None:
        raise ValueError(f"missing owner approval secret environment variable {secret_env}")
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

    parser = argparse.ArgumentParser(prog="python -m daedalus.kernel.approvals")
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
        return _cli_verify(args.input, args.expectation, args.secret_env)
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
