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
    # Both halves, matching ``approvals._as_utc``. Checking only ``tzinfo is
    # None`` lets a tzinfo whose ``utcoffset()`` returns None through, and
    # ``astimezone`` then silently reinterprets the value in LOCAL time -- an
    # hours-wide shift that looks like a correct timestamp.
    if value.tzinfo is None or value.utcoffset() is None:
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
        #: True when a caller injected a clock. The seam itself is identical to
        #: ``ApprovalLedger``'s and is accepted; what was missing is the
        #: downstream refusal, because a rewound clock consumes an expired seal
        #: and the persisted row then attests a consumption that never happened
        #: at that instant. ``SealAuthority`` refuses such a receipt by default.
        self.clock_seam_used = clock is not None
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

        # Three clock samples, not one. ``BEGIN IMMEDIATE`` can block for up to
        # ``busy_timeout`` (30 s) behind another writer, so a single pre-lock
        # sample let an ALREADY EXPIRED seal be persisted with a pre-expiry
        # ``consumed_at`` -- which the receipt's own
        # ``consumed_at >= expires_at`` guard then could not see. Measured on a
        # real lock-contention repro. ``ApprovalLedger.consume`` has carried
        # this discipline all along; this module claimed to reuse the approval
        # primitives and had reused only the connection pragmas.
        preflight_at = self._now()
        preflight = verify_baseline_seal(
            seal, keyring=keyring, expectation=expectation, now=preflight_at
        )
        seal_json = canonical_json(seal.to_dict())
        expectation_json = canonical_json(expectation.to_dict())

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            transaction_at = self._now()
            if transaction_at < preflight_at:
                raise SealStateError("seal ledger clock moved backwards before consumption")
            verified = verify_baseline_seal(
                seal, keyring=keyring, expectation=expectation, now=transaction_at
            )
            if verified != preflight:
                raise SealStateError("seal verification changed before consumption")
            persistence_at = self._now()
            if persistence_at < transaction_at:
                raise SealStateError("seal ledger clock moved backwards during consumption")
            consumed_at = _timestamp(persistence_at)
            if consumed_at < verified.issued_at:
                raise SealExpired("baseline harness seal is not valid yet at consumption")
            if consumed_at >= verified.expires_at:
                raise SealExpired(
                    "baseline harness seal expired before consumption persistence"
                )
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
                        seal_json,
                        expectation_json,
                        canonical_json(receipt.to_dict()),
                    ),
                )
            connection.execute("COMMIT")
            return receipt
        except sqlite3.IntegrityError as error:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise SealReplay(
                "baseline harness seal, nonce, or use identity was already consumed"
            ) from error
        except Exception:
            # Any other fault must also release the write lock. Without this
            # branch a raised SealExpired/SealStateError left the transaction
            # open until close(); the row was never committed, but the failure
            # mode deserves an explicit rollback rather than a happy accident.
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            connection.close()

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

    def verify_consumption(
        self,
        receipt: ConsumedBaselineSeal,
        *,
        keyring: Mapping[tuple[str, str], bytes | str],
    ) -> ConsumedBaselineSeal:
        """Re-authenticate against the persisted seal and refuse any drift.

        The earlier version read one column and compared a self-consistent
        digest to itself, which authenticates nothing: a hand-edited row whose
        ``consumption_sha256`` matches its own payload passed. This re-reads
        the SIGNED seal, re-runs the HMAC against the caller's keyring, and
        cross-checks every persisted column, exactly as
        ``ApprovalLedger.verify_consumption`` does.

        The signature is re-checked at the RECORDED consumption instant, not
        at ``now``: a legitimately consumed seal is expected to be expired by
        the time anyone reads its receipt back, and treating that as a failure
        would make every historical receipt unverifiable.
        """

        if not isinstance(receipt, ConsumedBaselineSeal):
            raise TypeError("verification requires a ConsumedBaselineSeal")
        connection = self._connect()
        try:
            row = connection.execute(
                f"SELECT * FROM {_SEAL_TABLE} WHERE consumption_sha256 = ?",
                (receipt.consumption_sha256,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise SealStateError("baseline harness seal consumption is not persisted")
        try:
            consumption_payload = json.loads(row["consumption_json"])
            seal_payload = json.loads(row["seal_json"])
            expectation_payload = json.loads(row["expectation_json"])
            if not isinstance(consumption_payload, dict):
                raise ValueError("consumption JSON must be an object")
            if not isinstance(seal_payload, dict):
                raise ValueError("seal JSON must be an object")
            if not isinstance(expectation_payload, dict):
                raise ValueError("expectation JSON must be an object")
            persisted = ConsumedBaselineSeal.from_dict(consumption_payload)
            stored_seal = BaselineHarnessSeal.from_dict(seal_payload)
            stored_expectation = SealExpectation(**expectation_payload)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise SealStateError("persisted baseline harness seal is corrupt") from exc

        secret = keyring.get((stored_seal.owner_id, stored_seal.key_id))
        if secret is None:
            raise SealSignatureError("persisted baseline harness seal key is unknown")
        if not hmac.compare_digest(
            stored_seal.signature_sha256,
            _seal_signature(stored_seal.signing_digest, secret),
        ):
            raise SealSignatureError("persisted baseline harness seal signature mismatch")

        stored_verified = verify_baseline_seal(
            stored_seal,
            keyring=keyring,
            expectation=stored_expectation,
            now=_parse_utc(persisted.consumed_at, "persisted.consumed_at"),
        )
        # Every denormalized column is cross-checked against the SIGNED seal,
        # not just the four an index needs. The narrower version passed an
        # in-place `UPDATE ... SET owner_id='attacker'`: the columns are a
        # queryable projection of `seal_json`, so any column that disagrees
        # with it means the row was edited outside this API. Enumerated rather
        # than looped so a future column addition fails this comparison loudly
        # instead of being silently unchecked.
        column_expectations = {
            "seal_sha256": stored_verified.seal_sha256,
            "seal_id": stored_seal.seal_id,
            "owner_id": stored_seal.owner_id,
            "key_id": stored_seal.key_id,
            "nonce": stored_seal.nonce,
            "operation": stored_seal.operation,
            "manifest_sha256": stored_seal.manifest_sha256,
            "task_set_sha256": stored_seal.task_set_sha256,
            "evaluator_sha256": stored_seal.evaluator_sha256,
            "budget_sha256": stored_seal.budget_sha256,
            "environment_sha256": stored_seal.environment_sha256,
            "seed_policy_sha256": stored_seal.seed_policy_sha256,
            "base_revision": stored_seal.base_revision,
            "plan_digest": stored_seal.plan_digest,
            "issued_at": stored_seal.issued_at,
            "expires_at": stored_seal.expires_at,
            "signature_sha256": stored_seal.signature_sha256,
            "expectation_sha256": receipt.expectation_sha256,
            "seal_use_id": receipt.seal_use_id,
            "consumed_at": receipt.consumed_at,
            "consumption_sha256": receipt.consumption_sha256,
            "seal_json": canonical_json(stored_seal.to_dict()),
            "expectation_json": canonical_json(stored_expectation.to_dict()),
            "consumption_json": canonical_json(receipt.to_dict()),
        }
        unchecked = sorted(set(row.keys()) - set(column_expectations))
        if unchecked:
            raise SealStateError(
                f"seal ledger columns are not cross-checked: {unchecked}"
            )
        drifted = sorted(
            name for name, expected in column_expectations.items() if row[name] != expected
        )
        if (
            drifted
            or persisted != receipt
            or stored_verified != receipt.verified
            or stored_expectation.digest != receipt.expectation_sha256
        ):
            raise SealStateError(
                "baseline harness seal consumption does not match its persisted "
                f"authority (drifted columns: {drifted})"
            )
        return persisted


@dataclass(frozen=True)
class SealAuthority:
    """The only thing that can answer "is this harness sealed?".

    A :class:`VerifiedBaselineSeal` is a VALUE, not a capability -- it is a
    frozen dataclass anyone can construct, deserialize from JSON, subclass,
    pickle or deepcopy, and every digest it carries is publicly computable from
    the manifest it describes.  An adversarial reviewer built one with
    ``owner_id="attacker"`` and ``signature_sha256="0"*64`` and sealed a run
    with it.  Holding the value therefore proves nothing; only re-reading the
    ledger and re-running the HMAC does.

    This object is that re-check, and it is what ``RunManifest`` requires.  It
    also refuses a ledger built on a test clock seam, mirroring
    ``promotion.authorize_persisted_promotion``'s refusal of a decision whose
    ``seams_used`` is non-empty: a rewound clock can consume an expired seal,
    so a seam-built receipt must not be able to seal anything by default.
    """

    ledger: SealLedger
    keyring: Mapping[tuple[str, str], bytes | str]
    allow_clock_seam: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.ledger, SealLedger):
            raise TypeError("seal authority requires a SealLedger")
        if not isinstance(self.keyring, Mapping) or not self.keyring:
            raise ValueError("seal authority requires a non-empty keyring")

    def reauthenticate(self, receipt: ConsumedBaselineSeal) -> VerifiedBaselineSeal:
        """Return the persisted verified seal, or raise. Never returns a bool."""

        if not isinstance(receipt, ConsumedBaselineSeal):
            raise TypeError("seal authority requires a ConsumedBaselineSeal")
        if self.ledger.clock_seam_used and not self.allow_clock_seam:
            raise SealStateError(
                "a seal consumed through a ledger clock seam is not a sealing "
                "authority; pass allow_clock_seam=True to accept it in a test"
            )
        return self.ledger.verify_consumption(receipt, keyring=self.keyring).verified


__all__ = [
    "SEAL_SIGNING_DOMAIN",
    "BaselineHarnessSeal",
    "ConsumedBaselineSeal",
    "SealAuthority",
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
