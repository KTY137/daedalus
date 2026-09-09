"""Authenticated, one-use owner seals for a frozen Gate-3 baseline harness.

Plan §11 Gate 3 opens with a freeze obligation and continues "Only after that
baseline harness is sealed".  `G3-BASE-01` §F4 recorded that sealing had no
mechanism, so ``RunManifest.sealed`` was hard-wired ``False`` -- correct, and
terminal: an eternally-false flag means no Gate-3 evidence can ever exist.

This module is that mechanism, and it is deliberately NOT a second operation
tag on :class:`~daedalus.kernel.contracts.OwnerApproval`.  A seal authorizes
nothing.  It cannot promote a candidate, merge a branch, widen a write root,
admit egress or mint a lease; it is a pure attestation that one exact frozen
harness is the one that counts.  Sharing the promotion contract's type, ledger
and keyring with a much cheaper-to-obtain artifact would make the record that
guards Invariant 5 polymorphic, and
``docs/GATE0_PROMOTION_TRUST_ROOT_FINDING.md`` already documents two
constructed attacks against that trust root.

Three separations keep the two artifacts non-interchangeable:

1. **Type.**  ``signing_dict()`` includes ``contract_type``, so a seal
   signature is not a signature over any ``daedalus.owner-approval`` body.
   This holds before anything else in this module.
2. **Domain.**  Seals sign ``SEAL_SIGNING_DOMAIN + signing_digest`` rather than
   the bare digest.  Belt and braces over (1), at zero cost.
3. **Ledger.**  Seals consume against ``baseline_harness_seal_consumptions_v1``,
   a table :class:`~daedalus.kernel.approvals.ApprovalLedger` never reads or
   writes.  A consumed seal cannot retire a promotion nonce and a consumed
   promotion cannot retire a seal nonce -- even in one SQLite file.

The primitives (canonical serialization, digests, the 32-byte secret floor,
HMAC-SHA256, the WAL/``synchronous=FULL``/``busy_timeout`` connection
discipline, the 24-hour TTL cap) are reused from the approval path unchanged.
"""
from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping

from daedalus.kernel.contracts.security import SEAL_OPERATION, BaselineHarnessSeal
from daedalus.kernel.contracts.base import (
    ContractProvenance,
    _identifier,
    _revision,
    _sha256,
    _utc_timestamp,
)
from daedalus.spine.envelope import canonical_json, canonical_sha

#: Signature domain separator.  A seal signs this prefix plus the canonical
#: signing digest, so a seal signature can never be replayed as a signature
#: over any other artifact even if a future contract accidentally produced an
#: identical signing digest.
SEAL_SIGNING_DOMAIN = "daedalus.baseline-harness-seal.v1:"

#: Matches the Gate-0 approval maximum.  Recorded in `G3-SEAL-02` §8 as an
#: expected friction point: an owner sealing a harness a day after the run
#: must re-issue.  Lengthening it is an owner decision with its own evidence,
#: not a convenience edit here.
_MAX_SEAL_TTL = timedelta(hours=24)


class SealError(RuntimeError):
    """Base class for fail-closed baseline-harness-seal rejection."""


class SealSignatureError(SealError):
    pass


class SealExpired(SealError):
    pass


class SealBindingMismatch(SealError):
    pass


class SealReplay(SealError):
    pass


class SealStateError(SealError):
    pass


@dataclass(frozen=True)
class SealExpectation:
    """What the caller independently believes it is sealing.

    Verification refuses unless the expectation and the signed seal agree field
    by field, so a seal issued for one harness cannot be pointed at another.
    The caller derives these from the live ``RunManifest`` it holds; it never
    copies them out of the seal.
    """

    operation: str
    manifest_sha256: str
    task_set_sha256: str
    evaluator_sha256: str
    budget_sha256: str
    environment_sha256: str
    seed_policy_sha256: str
    base_revision: str
    plan_digest: str

    def __post_init__(self) -> None:
        if self.operation != SEAL_OPERATION:
            raise ValueError(f"seal expectation operation must be {SEAL_OPERATION}")
        for name in (
            "manifest_sha256",
            "task_set_sha256",
            "evaluator_sha256",
            "budget_sha256",
            "environment_sha256",
            "seed_policy_sha256",
            "plan_digest",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(
            self, "base_revision", _revision(self.base_revision, "base_revision")
        )

    def to_dict(self) -> dict[str, str]:
        return dataclasses.asdict(self)

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class VerifiedBaselineSeal:
    """The authenticated result of one signed seal.

    ``__post_init__`` recomputes nothing it was told; it validates every field
    and refuses a ``seal_sha256`` that is not a digest.  The class is
    constructible in practice only by :func:`verify_baseline_seal`, because a
    caller inventing one still has to produce a signature the ledger will
    re-authenticate before it can be consumed, and ``RunManifest.sealed``
    additionally re-compares every bound digest against the live manifest.
    """

    seal_sha256: str
    seal_id: str
    owner_id: str
    key_id: str
    operation: str
    manifest_sha256: str
    task_set_sha256: str
    evaluator_sha256: str
    budget_sha256: str
    environment_sha256: str
    seed_policy_sha256: str
    base_revision: str
    plan_digest: str
    nonce: str
    issued_at: str
    expires_at: str
    signature_sha256: str

    def __post_init__(self) -> None:
        for name in ("seal_id", "owner_id", "key_id", "nonce"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        if self.operation != SEAL_OPERATION:
            raise ValueError(f"verified seal operation must be {SEAL_OPERATION}")
        for name in (
            "seal_sha256",
            "manifest_sha256",
            "task_set_sha256",
            "evaluator_sha256",
            "budget_sha256",
            "environment_sha256",
            "seed_policy_sha256",
            "plan_digest",
            "signature_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(
            self, "base_revision", _revision(self.base_revision, "base_revision")
        )
        object.__setattr__(self, "issued_at", _utc_timestamp(self.issued_at, "issued_at"))
        object.__setattr__(
            self, "expires_at", _utc_timestamp(self.expires_at, "expires_at")
        )
        if self.expires_at <= self.issued_at:
            raise ValueError("verified seal expires_at must be after issued_at")

    def to_dict(self) -> dict[str, str]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "VerifiedBaselineSeal":
        if not isinstance(payload, Mapping):
            raise ValueError("verified baseline seal must be an object")
        expected = {field.name for field in dataclasses.fields(cls)}
        actual = set(payload)
        if actual != expected:
            raise ValueError(
                "verified baseline seal fields mismatch: "
                f"missing={sorted(expected - actual)} extra={sorted(actual - expected)}"
            )
        return cls(**{key: str(payload[key]) for key in expected})

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class ConsumedBaselineSeal:
    """Persisted, binding-complete evidence of one atomic seal consumption."""

    verified: VerifiedBaselineSeal
    expectation_sha256: str
    seal_use_id: str
    consumed_at: str
    consumption_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.verified, VerifiedBaselineSeal):
            raise ValueError("consumed seal requires a verified baseline seal")
        object.__setattr__(
            self,
            "expectation_sha256",
            _sha256(self.expectation_sha256, "expectation_sha256"),
        )
        object.__setattr__(
            self, "seal_use_id", _identifier(self.seal_use_id, "seal_use_id")
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
            raise ValueError("seal cannot be consumed before it was issued")
        if self.consumed_at >= self.verified.expires_at:
            raise ValueError("seal cannot be consumed at or after expiry")
        if self.consumption_sha256 != canonical_sha(self.payload_dict()):
            raise ValueError("seal consumption digest mismatch")

    def payload_dict(self) -> dict[str, object]:
        return {
            "verified": self.verified.to_dict(),
            "expectation_sha256": self.expectation_sha256,
            "seal_use_id": self.seal_use_id,
            "consumed_at": self.consumed_at,
        }

    def to_dict(self) -> dict[str, object]:
        payload = self.payload_dict()
        payload["consumption_sha256"] = self.consumption_sha256
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "ConsumedBaselineSeal":
        if not isinstance(payload, Mapping):
            raise ValueError("consumed baseline seal must be an object")
        body = dict(payload)
        verified = body.get("verified")
        if not isinstance(verified, Mapping):
            raise ValueError("consumed baseline seal requires a verified object")
        return cls(
            verified=VerifiedBaselineSeal.from_dict(verified),
            expectation_sha256=str(body.get("expectation_sha256", "")),
            seal_use_id=str(body.get("seal_use_id", "")),
            consumed_at=str(body.get("consumed_at", "")),
            consumption_sha256=str(body.get("consumption_sha256", "")),
        )

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{label} must be a datetime")
    if value.tzinfo is None:
        raise ValueError(f"{label} must be timezone aware")
    return value.astimezone(timezone.utc)


def _parse_utc(value: str, label: str) -> datetime:
    """Accept both wire forms of a UTC instant.

    ``_utc_timestamp`` (the canonical validator every contract field runs
    through) normalizes to ``...+00:00``, while callers commonly hand in the
    ``...Z`` form. Accepting only one of them would make a contract unable to
    re-parse its own normalized field, so both are parsed and anything without
    a timezone is refused.
    """

    text = str(value)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must be a timezone-aware UTC timestamp")
    return parsed.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    """Emit the canonical normalized form, so a digest computed over it here
    equals the digest recomputed after ``_utc_timestamp`` validation."""

    return _as_utc(value, "timestamp").isoformat(timespec="microseconds")


def _secret_bytes(secret: bytes | str) -> bytes:
    value = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
    if len(value) < 32:
        raise ValueError("baseline harness seal secret must contain at least 32 bytes")
    return value


def _seal_signature(signing_digest: str, secret: bytes | str) -> str:
    """HMAC over the DOMAIN-PREFIXED digest.

    Signing the bare digest would still be safe today (``contract_type`` is
    inside the signed body), but the prefix makes the separation independent of
    that invariant surviving future edits to the canonical serializer.
    """

    message = f"{SEAL_SIGNING_DOMAIN}{signing_digest}".encode("ascii")
    return hmac.new(_secret_bytes(secret), message, hashlib.sha256).hexdigest()


def issue_baseline_seal(
    *,
    seal_id: str,
    owner_id: str,
    key_id: str,
    manifest_sha256: str,
    task_set_sha256: str,
    evaluator_sha256: str,
    budget_sha256: str,
    environment_sha256: str,
    seed_policy_sha256: str,
    base_revision: str,
    plan_digest: str,
    nonce: str,
    issued_at: str,
    expires_at: str,
    provenance: ContractProvenance,
    secret: bytes | str,
) -> BaselineHarnessSeal:
    """Create a signed seal without persisting or consuming it."""

    placeholder = BaselineHarnessSeal(
        seal_id=seal_id,
        owner_id=owner_id,
        key_id=key_id,
        operation=SEAL_OPERATION,
        manifest_sha256=manifest_sha256,
        task_set_sha256=task_set_sha256,
        evaluator_sha256=evaluator_sha256,
        budget_sha256=budget_sha256,
        environment_sha256=environment_sha256,
        seed_policy_sha256=seed_policy_sha256,
        base_revision=base_revision,
        plan_digest=plan_digest,
        nonce=nonce,
        issued_at=issued_at,
        expires_at=expires_at,
        signature_sha256="0" * 64,
        provenance=provenance,
    )
    issued = _parse_utc(placeholder.issued_at, "seal.issued_at")
    expires = _parse_utc(placeholder.expires_at, "seal.expires_at")
    if expires - issued > _MAX_SEAL_TTL:
        raise ValueError("baseline harness seal TTL exceeds the 24-hour maximum")
    return dataclasses.replace(
        placeholder,
        signature_sha256=_seal_signature(placeholder.signing_digest, secret),
    )


def verify_baseline_seal(
    seal: BaselineHarnessSeal,
    *,
    keyring: Mapping[tuple[str, str], bytes | str],
    expectation: SealExpectation,
    now: datetime | None = None,
) -> VerifiedBaselineSeal:
    """Authenticate and validate every bound dimension of one seal."""

    if not isinstance(seal, BaselineHarnessSeal):
        raise TypeError("verification requires a signed BaselineHarnessSeal")
    if not isinstance(expectation, SealExpectation):
        raise TypeError("verification requires a SealExpectation")
    secret = keyring.get((seal.owner_id, seal.key_id))
    if secret is None:
        raise SealSignatureError("baseline harness seal key is unknown")
    expected_signature = _seal_signature(seal.signing_digest, secret)
    if not hmac.compare_digest(seal.signature_sha256, expected_signature):
        raise SealSignatureError("baseline harness seal signature mismatch")

    instant = _as_utc(now, "now") if now is not None else _utc_now()
    issued = _parse_utc(seal.issued_at, "seal.issued_at")
    expires = _parse_utc(seal.expires_at, "seal.expires_at")
    if expires - issued > _MAX_SEAL_TTL:
        raise SealExpired("baseline harness seal TTL exceeds the maximum")
    if instant < issued:
        raise SealExpired("baseline harness seal is not valid yet")
    if instant >= expires:
        raise SealExpired("baseline harness seal has expired")

    comparisons = {
        "operation": (seal.operation, expectation.operation),
        "manifest_sha256": (seal.manifest_sha256, expectation.manifest_sha256),
        "task_set_sha256": (seal.task_set_sha256, expectation.task_set_sha256),
        "evaluator_sha256": (seal.evaluator_sha256, expectation.evaluator_sha256),
        "budget_sha256": (seal.budget_sha256, expectation.budget_sha256),
        "environment_sha256": (
            seal.environment_sha256,
            expectation.environment_sha256,
        ),
        "seed_policy_sha256": (
            seal.seed_policy_sha256,
            expectation.seed_policy_sha256,
        ),
        "base_revision": (seal.base_revision, expectation.base_revision),
        "plan_digest": (seal.plan_digest, expectation.plan_digest),
    }
    mismatches = sorted(
        name for name, (actual, expected) in comparisons.items() if actual != expected
    )
    if mismatches:
        raise SealBindingMismatch(
            "baseline harness seal binding mismatch: " + ", ".join(mismatches)
        )

    return VerifiedBaselineSeal(
        seal_sha256=seal.digest,
        seal_id=seal.seal_id,
        owner_id=seal.owner_id,
        key_id=seal.key_id,
        operation=seal.operation,
        manifest_sha256=seal.manifest_sha256,
        task_set_sha256=seal.task_set_sha256,
        evaluator_sha256=seal.evaluator_sha256,
        budget_sha256=seal.budget_sha256,
        environment_sha256=seal.environment_sha256,
        seed_policy_sha256=seal.seed_policy_sha256,
        base_revision=seal.base_revision,
        plan_digest=seal.plan_digest,
        nonce=seal.nonce,
        issued_at=seal.issued_at,
        expires_at=seal.expires_at,
        signature_sha256=seal.signature_sha256,
    )


_SEAL_TABLE = "baseline_harness_seal_consumptions_v1"


class SealLedger:
    """SQLite authority for authenticated, atomic seal consumption.

    Its table is disjoint from ``owner_approval_consumptions_v2``.  The two may
    share one file; neither reads the other's rows, so consuming a seal cannot
    retire a promotion nonce and vice versa.  That non-interference is asserted
    directly in ``tests/kernel/test_baseline_harness_seal.py``.
    """

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
        return _as_utc(self._clock(), "seal ledger clock")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), isolation_level=None, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {_SEAL_TABLE} (
                    seal_sha256 TEXT PRIMARY KEY,
                    seal_id TEXT NOT NULL UNIQUE,
                    owner_id TEXT NOT NULL,
                    key_id TEXT NOT NULL,
                    nonce TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    manifest_sha256 TEXT NOT NULL,
                    task_set_sha256 TEXT NOT NULL,
                    evaluator_sha256 TEXT NOT NULL,
                    budget_sha256 TEXT NOT NULL,
                    environment_sha256 TEXT NOT NULL,
                    seed_policy_sha256 TEXT NOT NULL,
                    base_revision TEXT NOT NULL,
                    plan_digest TEXT NOT NULL,
                    issued_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    signature_sha256 TEXT NOT NULL,
                    expectation_sha256 TEXT NOT NULL,
                    seal_use_id TEXT NOT NULL UNIQUE,
                    consumed_at TEXT NOT NULL,
                    consumption_sha256 TEXT NOT NULL UNIQUE,
                    seal_json TEXT NOT NULL,
                    expectation_json TEXT NOT NULL,
                    consumption_json TEXT NOT NULL,
                    UNIQUE(owner_id, key_id, nonce)
                )
                """
            )
        finally:
            connection.close()

    def consume(
        self,
        seal: BaselineHarnessSeal,
        *,
        keyring: Mapping[tuple[str, str], bytes | str],
        expectation: SealExpectation,
        seal_use_id: str,
    ) -> ConsumedBaselineSeal:
        """Authenticate and consume one signed seal inside one transaction."""

        if not isinstance(seal, BaselineHarnessSeal):
            raise TypeError("consumption requires the signed BaselineHarnessSeal")
        normalized_use_id = _identifier(seal_use_id, "seal_use_id")
        now = self._now()
        verified = verify_baseline_seal(
            seal, keyring=keyring, expectation=expectation, now=now
        )
        consumed_at = _timestamp(now)
        payload = {
            "verified": verified.to_dict(),
            "expectation_sha256": expectation.digest,
            "seal_use_id": normalized_use_id,
            "consumed_at": consumed_at,
        }
        receipt = ConsumedBaselineSeal(
            verified=verified,
            expectation_sha256=expectation.digest,
            seal_use_id=normalized_use_id,
            consumed_at=consumed_at,
            consumption_sha256=canonical_sha(payload),
        )

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    f"""
                    INSERT INTO {_SEAL_TABLE} (
                        seal_sha256, seal_id, owner_id, key_id, nonce, operation,
                        manifest_sha256, task_set_sha256, evaluator_sha256,
                        budget_sha256, environment_sha256, seed_policy_sha256,
                        base_revision, plan_digest, issued_at, expires_at,
                        signature_sha256, expectation_sha256, seal_use_id,
                        consumed_at, consumption_sha256, seal_json,
                        expectation_json, consumption_json
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        verified.seal_sha256,
                        verified.seal_id,
                        verified.owner_id,
                        verified.key_id,
                        verified.nonce,
                        verified.operation,
                        verified.manifest_sha256,
                        verified.task_set_sha256,
                        verified.evaluator_sha256,
                        verified.budget_sha256,
                        verified.environment_sha256,
                        verified.seed_policy_sha256,
                        verified.base_revision,
                        verified.plan_digest,
                        verified.issued_at,
                        verified.expires_at,
                        verified.signature_sha256,
                        receipt.expectation_sha256,
                        receipt.seal_use_id,
                        receipt.consumed_at,
                        receipt.consumption_sha256,
                        canonical_json(seal.to_dict()),
                        canonical_json(expectation.to_dict()),
                        canonical_json(receipt.to_dict()),
                    ),
                )
            except sqlite3.IntegrityError as error:
                connection.execute("ROLLBACK")
                raise SealReplay(
                    "baseline harness seal was already consumed"
                ) from error
            connection.execute("COMMIT")
        finally:
            connection.close()
        return receipt

    def consumed(self, seal_sha256: str) -> bool:
        """True when this exact seal digest has already been consumed."""

        digest = _sha256(seal_sha256, "seal_sha256")
        connection = self._connect()
        try:
            row = connection.execute(
                f"SELECT 1 FROM {_SEAL_TABLE} WHERE seal_sha256 = ?", (digest,)
            ).fetchone()
        finally:
            connection.close()
        return row is not None

    def verify_consumption(self, receipt: ConsumedBaselineSeal) -> ConsumedBaselineSeal:
        """Re-read one persisted consumption and refuse any drift."""

        if not isinstance(receipt, ConsumedBaselineSeal):
            raise TypeError("verification requires a ConsumedBaselineSeal")
        connection = self._connect()
        try:
            row = connection.execute(
                f"SELECT consumption_json FROM {_SEAL_TABLE} "
                "WHERE consumption_sha256 = ?",
                (receipt.consumption_sha256,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise SealStateError("baseline harness seal consumption is not recorded")
        stored = ConsumedBaselineSeal.from_dict(json.loads(row["consumption_json"]))
        if stored.consumption_sha256 != receipt.consumption_sha256:
            raise SealStateError("baseline harness seal consumption digest drifted")
        return stored


__all__ = [
    "SEAL_SIGNING_DOMAIN",
    "BaselineHarnessSeal",
    "ConsumedBaselineSeal",
    "SealBindingMismatch",
    "SealError",
    "SealExpectation",
    "SealExpired",
    "SealLedger",
    "SealReplay",
    "SealSignatureError",
    "SealStateError",
    "VerifiedBaselineSeal",
    "issue_baseline_seal",
    "verify_baseline_seal",
]
