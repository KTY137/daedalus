"""Authenticated closure of indeterminate Gate-0 effect executions.

Reconciliation grants no permission to start or repeat an effect.  It accepts
one terminal receipt that was frozen at the live boundary, authenticates the
exact historical lease grant and start identity, verifies a short-lived
operator decision, and atomically consumes that decision's nonce while closing
the existing ``STARTED`` or exclusively claimed ``EXECUTING`` row in
:class:`EffectLeaseLedger`.
"""
from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar, Mapping

from daedalus.kernel.contracts import EffectLease, EffectLeaseRequest
from daedalus.kernel.effects import (
    EffectExecutionClaimReceipt,
    EffectExecutionRequest,
    EffectLeaseBindingMismatch,
    EffectLeaseError,
    EffectLeaseLedger,
    EffectLeaseStateError,
    EffectTerminalReceipt,
    LeasedEffectStartReceipt,
    _TERMINAL_STATES,
    _authenticate_effect_lease_contracts,
    _authenticate_persisted_grant,
    _authenticated_replay_start,
    _load_persisted_execution_claim,
    _validate_narrowed_scope,
)
from daedalus.schemas import (
    CanonicalContract,
    ContractProvenance,
    PolicyDecision,
    _identifier,
    _require_provenance_inputs,
    _sha256,
    _utc_timestamp,
)
from daedalus.spine.envelope import canonical_json, canonical_sha


_MAX_DECISION_TTL = timedelta(hours=24)


class EffectReconciliationError(EffectLeaseError):
    """Base class for fail-closed reconciliation failures."""


class EffectReconciliationSignatureError(EffectReconciliationError):
    pass


class EffectReconciliationExpired(EffectReconciliationError):
    pass


class EffectReconciliationBindingError(EffectReconciliationError):
    pass


class EffectReconciliationReplay(EffectReconciliationError):
    pass


class EffectReconciliationConflict(EffectReconciliationError):
    pass


def _parse_utc(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EffectReconciliationBindingError(
            f"{label} is not ISO-8601"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EffectReconciliationBindingError(
            f"{label} must be timezone-aware"
        )
    return parsed.astimezone(timezone.utc)


def _as_utc(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _secret_bytes(secret: bytes | str) -> bytes:
    value = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
    if len(value) < 32:
        raise ValueError(
            "effect reconciliation operator secret must contain at least 32 bytes"
        )
    return value


def _signature(signing_digest: str, secret: bytes | str) -> str:
    return hmac.new(
        _secret_bytes(secret), signing_digest.encode("ascii"), hashlib.sha256
    ).hexdigest()


@dataclass(frozen=True)
class EffectReconciliationDecision(CanonicalContract):
    """Inert, bounded operator authority to record one exact terminal claim."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.effect-reconciliation-decision"

    decision_id: str
    operator_id: str
    key_id: str
    operation: str
    execution_id: str
    lease_sha256: str
    execution_request_sha256: str
    start_receipt_sha256: str
    terminal_receipt_sha256: str
    evidence_sha256: str
    nonce: str
    issued_at: str
    expires_at: str
    signature_sha256: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        for name in (
            "decision_id",
            "operator_id",
            "key_id",
            "execution_id",
            "nonce",
        ):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        if self.operation != "reconcile-effect-terminal":
            raise ValueError(
                "effect reconciliation operation must be reconcile-effect-terminal"
            )
        for name in (
            "lease_sha256",
            "execution_request_sha256",
            "start_receipt_sha256",
            "terminal_receipt_sha256",
            "evidence_sha256",
            "signature_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(
            self, "issued_at", _utc_timestamp(self.issued_at, "issued_at")
        )
        object.__setattr__(
            self, "expires_at", _utc_timestamp(self.expires_at, "expires_at")
        )
        issued = _parse_utc(self.issued_at, "issued_at")
        expires = _parse_utc(self.expires_at, "expires_at")
        if expires <= issued:
            raise ValueError(
                "effect reconciliation expires_at must be after issued_at"
            )
        if expires - issued > _MAX_DECISION_TTL:
            raise ValueError(
                "effect reconciliation TTL exceeds the 24-hour Gate-0 maximum"
            )
        _require_provenance_inputs(
            self.provenance,
            (
                self.lease_sha256,
                self.execution_request_sha256,
                self.start_receipt_sha256,
                self.terminal_receipt_sha256,
                self.evidence_sha256,
            ),
            "effect reconciliation decision",
        )

    def signing_dict(self) -> dict[str, Any]:
        body = self.to_dict()
        body.pop("signature_sha256")
        return body

    @property
    def signing_digest(self) -> str:
        return canonical_sha(self.signing_dict())

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any]
    ) -> "EffectReconciliationDecision":
        body = cls._contract_payload(payload)
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class EffectReconciliationResult:
    """Receipt and nonce-consumption evidence returned by reconciliation."""

    terminal_receipt: EffectTerminalReceipt
    decision_sha256: str
    applied: bool
    nonce_consumed: bool
    reconciled_at: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.terminal_receipt, EffectTerminalReceipt):
            raise TypeError("terminal_receipt must be an EffectTerminalReceipt")
        if not isinstance(self.applied, bool) or not isinstance(
            self.nonce_consumed, bool
        ):
            raise TypeError("reconciliation result flags must be booleans")
        object.__setattr__(
            self,
            "decision_sha256",
            _sha256(self.decision_sha256, "decision_sha256"),
        )
        if self.reconciled_at is not None:
            object.__setattr__(
                self,
                "reconciled_at",
                _utc_timestamp(self.reconciled_at, "reconciled_at"),
            )
        if self.applied and not self.nonce_consumed:
            raise ValueError("an applied reconciliation must consume its nonce")
        if self.nonce_consumed != (self.reconciled_at is not None):
            raise ValueError(
                "nonce_consumed must exactly match durable reconciliation time"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "terminal_receipt": self.terminal_receipt.to_dict(),
            "decision_sha256": self.decision_sha256,
            "applied": self.applied,
            "nonce_consumed": self.nonce_consumed,
            "reconciled_at": self.reconciled_at,
        }


def issue_effect_reconciliation_decision(
    pending_terminal_receipt: EffectTerminalReceipt,
    *,
    execution_request_sha256: str,
    evidence_sha256: str,
    decision_id: str,
    operator_id: str,
    key_id: str,
    nonce: str,
    issued_at: str,
    expires_at: str,
    provenance: ContractProvenance,
    secret: bytes | str,
) -> EffectReconciliationDecision:
    """Sign a decision that is already bound to one frozen terminal receipt."""

    if not isinstance(pending_terminal_receipt, EffectTerminalReceipt):
        raise TypeError(
            "pending_terminal_receipt must be an EffectTerminalReceipt"
        )
    placeholder = EffectReconciliationDecision(
        decision_id=decision_id,
        operator_id=operator_id,
        key_id=key_id,
        operation="reconcile-effect-terminal",
        execution_id=pending_terminal_receipt.execution_id,
        lease_sha256=pending_terminal_receipt.lease_sha256,
        execution_request_sha256=execution_request_sha256,
        start_receipt_sha256=pending_terminal_receipt.start_receipt_sha256,
        terminal_receipt_sha256=pending_terminal_receipt.receipt_sha256,
        evidence_sha256=evidence_sha256,
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


def _authenticate_effect_reconciliation_decision(
    decision: EffectReconciliationDecision,
    *,
    pending_terminal_receipt: EffectTerminalReceipt,
    execution_request_sha256: str,
    source_revision: str,
    keyring: Mapping[tuple[str, str], bytes | str],
) -> None:
    if not isinstance(decision, EffectReconciliationDecision):
        raise TypeError("decision must be an EffectReconciliationDecision")
    if not isinstance(pending_terminal_receipt, EffectTerminalReceipt):
        raise TypeError(
            "pending_terminal_receipt must be an EffectTerminalReceipt"
        )
    secret = keyring.get((decision.operator_id, decision.key_id))
    if secret is None:
        raise EffectReconciliationSignatureError(
            "effect reconciliation operator key is unknown"
        )
    expected_signature = _signature(decision.signing_digest, secret)
    if not hmac.compare_digest(decision.signature_sha256, expected_signature):
        raise EffectReconciliationSignatureError(
            "effect reconciliation signature mismatch"
        )

    request_digest = _sha256(
        execution_request_sha256, "execution_request_sha256"
    )
    comparisons = {
        "operation": (decision.operation, "reconcile-effect-terminal"),
        "execution_id": (
            decision.execution_id,
            pending_terminal_receipt.execution_id,
        ),
        "lease_sha256": (
            decision.lease_sha256,
            pending_terminal_receipt.lease_sha256,
        ),
        "execution_request_sha256": (
            decision.execution_request_sha256,
            request_digest,
        ),
        "start_receipt_sha256": (
            decision.start_receipt_sha256,
            pending_terminal_receipt.start_receipt_sha256,
        ),
        "terminal_receipt_sha256": (
            decision.terminal_receipt_sha256,
            pending_terminal_receipt.receipt_sha256,
        ),
        "source_revision": (
            decision.provenance.source_revision,
            source_revision,
        ),
    }
    mismatches = sorted(
        name for name, (actual, expected) in comparisons.items() if actual != expected
    )
    if mismatches:
        raise EffectReconciliationBindingError(
            "effect reconciliation binding mismatch: " + ", ".join(mismatches)
        )


def verify_effect_reconciliation_decision(
    decision: EffectReconciliationDecision,
    *,
    pending_terminal_receipt: EffectTerminalReceipt,
    execution_request_sha256: str,
    source_revision: str,
    keyring: Mapping[tuple[str, str], bytes | str],
    now: datetime | None = None,
) -> None:
    """Authenticate the operator and every current terminal binding."""

    _authenticate_effect_reconciliation_decision(
        decision,
        pending_terminal_receipt=pending_terminal_receipt,
        execution_request_sha256=execution_request_sha256,
        source_revision=source_revision,
        keyring=keyring,
    )
    instant = _as_utc(now, "now") if now is not None else datetime.now(timezone.utc)
    issued = _parse_utc(decision.issued_at, "decision.issued_at")
    expires = _parse_utc(decision.expires_at, "decision.expires_at")
    if instant < issued:
        raise EffectReconciliationExpired(
            "effect reconciliation decision is not valid yet"
        )
    if instant >= expires:
        raise EffectReconciliationExpired(
            "effect reconciliation decision has expired"
        )


def _load_authenticated_grant(
    row: sqlite3.Row,
    *,
    historical_keyring: Mapping[str, bytes | str],
) -> tuple[EffectLease, EffectLeaseRequest, PolicyDecision]:
    if row["request_json"] is None or row["policy_decision_json"] is None:
        raise EffectLeaseStateError(
            "persisted effect lease predates recoverable request/policy metadata"
        )
    try:
        lease_payload = json.loads(row["lease_json"])
        request_payload = json.loads(row["request_json"])
        policy_payload = json.loads(row["policy_decision_json"])
        if not all(
            isinstance(value, dict)
            for value in (lease_payload, request_payload, policy_payload)
        ):
            raise ValueError("persisted contract JSON must contain objects")
        lease = EffectLease.from_dict(lease_payload)
        request = EffectLeaseRequest.from_dict(request_payload)
        policy = PolicyDecision.from_dict(policy_payload)
    except (
        TypeError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
        EffectLeaseBindingMismatch,
    ) as exc:
        raise EffectLeaseStateError(
            "persisted effect grant contains invalid contract bytes"
        ) from exc

    _authenticate_effect_lease_contracts(
        lease,
        request=request,
        policy_decision=policy,
        keyring=historical_keyring,
    )
    _authenticate_persisted_grant(
        row,
        lease=lease,
        request=request,
        policy_decision=policy,
    )
    return lease, request, policy


def _load_authenticated_start(
    row: sqlite3.Row,
    *,
    lease: EffectLease,
    historical_keyring: Mapping[str, bytes | str],
) -> tuple[EffectExecutionRequest, LeasedEffectStartReceipt]:
    try:
        request_payload = json.loads(row["request_json"])
        if not isinstance(request_payload, dict):
            raise ValueError("execution request JSON must contain an object")
        execution = EffectExecutionRequest(**request_payload)
    except (
        TypeError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
        EffectLeaseBindingMismatch,
    ) as exc:
        raise EffectLeaseStateError(
            "persisted effect execution contains invalid request bytes"
        ) from exc
    _validate_narrowed_scope(execution, lease)
    start = _authenticated_replay_start(
        row,
        lease=lease,
        execution=execution,
        request_json=canonical_json(execution.to_dict()),
        keyring=historical_keyring,
    ).receipt
    return execution, start


def _verify_causal_ordering(
    *,
    start: LeasedEffectStartReceipt,
    claim: EffectExecutionClaimReceipt | None,
    terminal: EffectTerminalReceipt,
    decision: EffectReconciliationDecision,
    reconciled_at: datetime,
) -> None:
    started = _parse_utc(start.started_at, "start.started_at")
    claimed = (
        _parse_utc(claim.claimed_at, "claim.claimed_at")
        if claim is not None
        else started
    )
    finished = _parse_utc(terminal.finished_at, "terminal.finished_at")
    issued = _parse_utc(decision.issued_at, "decision.issued_at")
    expires = _parse_utc(decision.expires_at, "decision.expires_at")
    if not started <= claimed <= finished <= issued <= reconciled_at < expires:
        raise EffectReconciliationBindingError(
            "effect reconciliation violates "
            "start <= claim <= terminal <= decision <= reconciliation < expiry "
            "ordering"
        )


def _load_terminal(
    row: sqlite3.Row, start: LeasedEffectStartReceipt
) -> EffectTerminalReceipt:
    try:
        payload = json.loads(row["terminal_receipt_json"])
        if not isinstance(payload, dict):
            raise ValueError("terminal receipt JSON must contain an object")
        payload["output_digests"] = tuple(payload["output_digests"])
        receipt = EffectTerminalReceipt(**payload)
    except (
        TypeError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
        EffectLeaseBindingMismatch,
    ) as exc:
        raise EffectLeaseStateError(
            "persisted effect execution contains invalid terminal bytes"
        ) from exc
    mismatches = sorted(
        name
        for name, actual, expected in (
            (
                "terminal_receipt_json",
                row["terminal_receipt_json"],
                canonical_json(receipt.to_dict()),
            ),
            (
                "terminal_receipt_sha256",
                row["terminal_receipt_sha256"],
                receipt.receipt_sha256,
            ),
            ("terminal_state", row["state"], receipt.outcome),
            ("finished_at", row["finished_at"], receipt.finished_at),
            ("terminal_lease", receipt.lease_sha256, start.lease_sha256),
            ("terminal_execution", receipt.execution_id, start.execution_id),
            (
                "terminal_start",
                receipt.start_receipt_sha256,
                start.receipt_sha256,
            ),
        )
        if actual != expected
    )
    if mismatches:
        raise EffectLeaseStateError(
            "persisted effect execution failed terminal identity checks: "
            + ", ".join(mismatches)
        )
    return receipt


def reconcile_effect_terminal(
    ledger: EffectLeaseLedger,
    pending_terminal_receipt: EffectTerminalReceipt,
    decision: EffectReconciliationDecision,
    *,
    historical_keyring: Mapping[str, bytes | str],
    operator_keyring: Mapping[tuple[str, str], bytes | str],
    now: datetime | None = None,
) -> EffectReconciliationResult:
    """Atomically close one indeterminate ``STARTED`` or ``EXECUTING`` row.

    Lease expiry, revocation, current kill-switch generation, guard state and
    registry drift are intentionally absent: they govern a *new start*, while
    this function can only record the already-frozen outcome of a historical
    start.  HMAC authentication of the historical grant remains mandatory.
    """

    if not isinstance(ledger, EffectLeaseLedger):
        raise TypeError("ledger must be an EffectLeaseLedger")
    if not isinstance(pending_terminal_receipt, EffectTerminalReceipt):
        raise TypeError(
            "pending_terminal_receipt must be an EffectTerminalReceipt"
        )
    if not isinstance(decision, EffectReconciliationDecision):
        raise TypeError("decision must be an EffectReconciliationDecision")
    instant = _as_utc(now, "now") if now is not None else datetime.now(timezone.utc)
    reconciled_at = instant.isoformat(timespec="microseconds")

    conn = ledger._connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        execution_row = conn.execute(
            """
            SELECT execution_id, lease_sha256, idempotency_key,
                   request_sha256, request_json, start_receipt_sha256,
                   start_receipt_json, state, started_at, claimed_at,
                   claim_receipt_sha256, claim_receipt_json, finished_at,
                   terminal_receipt_sha256, terminal_receipt_json
            FROM effect_executions WHERE execution_id=?
            """,
            (decision.execution_id,),
        ).fetchone()
        if execution_row is None:
            raise EffectLeaseStateError("unknown effect execution")
        grant_row = conn.execute(
            """
            SELECT lease_sha256, lease_id, request_sha256, request_json,
                   policy_decision_sha256, policy_decision_json,
                   registry_sha256, entrypoint_id, lease_json,
                   issued_at, expires_at, revoked_at, revocation_reason
            FROM effect_leases WHERE lease_sha256=?
            """,
            (execution_row["lease_sha256"],),
        ).fetchone()
        if grant_row is None:
            raise EffectLeaseStateError(
                "effect execution is missing its historical grant"
            )

        lease, _request, _policy = _load_authenticated_grant(
            grant_row, historical_keyring=historical_keyring
        )
        execution, start = _load_authenticated_start(
            execution_row,
            lease=lease,
            historical_keyring=historical_keyring,
        )
        claim = _load_persisted_execution_claim(
            execution_row,
            execution=execution,
            start_receipt=start,
            lease=lease,
            historical_keyring=historical_keyring,
        )
        historical_mismatches = sorted(
            name
            for name, actual, expected in (
                (
                    "terminal_lease",
                    pending_terminal_receipt.lease_sha256,
                    start.lease_sha256,
                ),
                (
                    "terminal_execution",
                    pending_terminal_receipt.execution_id,
                    start.execution_id,
                ),
                (
                    "terminal_start",
                    pending_terminal_receipt.start_receipt_sha256,
                    start.receipt_sha256,
                ),
            )
            if actual != expected
        )
        if historical_mismatches:
            raise EffectReconciliationBindingError(
                "effect reconciliation historical start mismatch: "
                + ", ".join(historical_mismatches)
            )
        existing = conn.execute(
            """
            SELECT decision_sha256, decision_id, nonce, execution_id,
                   operator_id, operator_key_id, decision_json,
                   terminal_receipt_sha256, reconciled_at
            FROM effect_reconciliations
            WHERE decision_id=? OR nonce=? OR execution_id=?
            """,
            (decision.decision_id, decision.nonce, decision.execution_id),
        ).fetchone()
        exact_existing = existing is not None and all(
            (
                existing["decision_sha256"] == decision.digest,
                existing["decision_id"] == decision.decision_id,
                existing["nonce"] == decision.nonce,
                existing["execution_id"] == decision.execution_id,
                existing["operator_id"] == decision.operator_id,
                existing["operator_key_id"] == decision.key_id,
                existing["decision_json"] == decision.to_json(),
                existing["terminal_receipt_sha256"]
                == pending_terminal_receipt.receipt_sha256,
            )
        )
        if exact_existing:
            # A timed-out caller may retry after the decision itself expires.
            # Authenticate the exact historical capability and prove that the
            # ledger consumed it while it was valid; do not turn expiry into a
            # false conflict after the terminal CAS already committed.
            _authenticate_effect_reconciliation_decision(
                decision,
                pending_terminal_receipt=pending_terminal_receipt,
                execution_request_sha256=execution.digest,
                source_revision=lease.provenance.source_revision,
                keyring=operator_keyring,
            )
            stored_reconciled_at = str(existing["reconciled_at"])
            try:
                canonical_reconciled_at = _utc_timestamp(
                    stored_reconciled_at, "reconciled_at"
                )
            except ValueError as exc:
                raise EffectLeaseStateError(
                    "persisted reconciliation time is invalid"
                ) from exc
            consumed = _parse_utc(canonical_reconciled_at, "reconciled_at")
            if canonical_reconciled_at != stored_reconciled_at:
                raise EffectLeaseStateError(
                    "persisted reconciliation time is not canonical"
                )
            _verify_causal_ordering(
                start=start,
                claim=claim,
                terminal=pending_terminal_receipt,
                decision=decision,
                reconciled_at=consumed,
            )
        else:
            verify_effect_reconciliation_decision(
                decision,
                pending_terminal_receipt=pending_terminal_receipt,
                execution_request_sha256=execution.digest,
                source_revision=lease.provenance.source_revision,
                keyring=operator_keyring,
                now=instant,
            )
            _verify_causal_ordering(
                start=start,
                claim=claim,
                terminal=pending_terminal_receipt,
                decision=decision,
                reconciled_at=instant,
            )
            if existing is not None:
                raise EffectReconciliationReplay(
                    "effect reconciliation decision, nonce, or execution was already consumed"
                )

        state = str(execution_row["state"])
        if state in _TERMINAL_STATES:
            if any(
                execution_row[name] is None
                for name in (
                    "finished_at",
                    "terminal_receipt_sha256",
                    "terminal_receipt_json",
                )
            ):
                raise EffectLeaseStateError(
                    "terminal execution is missing terminal receipt fields"
                )
            terminal = _load_terminal(execution_row, start)
            if terminal != pending_terminal_receipt:
                raise EffectReconciliationConflict(
                    "effect execution already has a different terminal receipt"
                )
            conn.execute("COMMIT")
            return EffectReconciliationResult(
                terminal_receipt=terminal,
                decision_sha256=decision.digest,
                applied=False,
                nonce_consumed=existing is not None,
                reconciled_at=(
                    str(existing["reconciled_at"])
                    if existing is not None
                    else None
                ),
            )

        if state not in {"STARTED", "EXECUTING"}:
            raise EffectLeaseStateError(
                "effect reconciliation requires STARTED or EXECUTING, "
                f"got {state!r}"
            )
        if existing is not None:
            raise EffectLeaseStateError(
                "consumed reconciliation decision points to an indeterminate "
                "execution"
            )
        if state == "STARTED" and claim is not None:
            raise EffectLeaseStateError(
                "STARTED reconciliation row unexpectedly carries claim fields"
            )
        if state == "EXECUTING" and claim is None:
            raise EffectLeaseStateError(
                "EXECUTING reconciliation row is missing its authenticated claim"
            )
        if any(
            execution_row[name] is not None
            for name in (
                "finished_at",
                "terminal_receipt_sha256",
                "terminal_receipt_json",
            )
        ):
            raise EffectLeaseStateError(
                "STARTED execution unexpectedly carries terminal fields"
            )

        conn.execute(
            """
            INSERT INTO effect_reconciliations (
                decision_sha256, decision_id, nonce, execution_id,
                operator_id, operator_key_id, decision_json,
                terminal_receipt_sha256, reconciled_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision.digest,
                decision.decision_id,
                decision.nonce,
                decision.execution_id,
                decision.operator_id,
                decision.key_id,
                decision.to_json(),
                pending_terminal_receipt.receipt_sha256,
                reconciled_at,
            ),
        )
        terminal_values = (
            pending_terminal_receipt.outcome,
            pending_terminal_receipt.finished_at,
            pending_terminal_receipt.receipt_sha256,
            canonical_json(pending_terminal_receipt.to_dict()),
            pending_terminal_receipt.execution_id,
            pending_terminal_receipt.lease_sha256,
            execution.digest,
            pending_terminal_receipt.start_receipt_sha256,
        )
        if claim is None:
            updated = conn.execute(
                """
                UPDATE effect_executions
                SET state=?, finished_at=?, terminal_receipt_sha256=?,
                    terminal_receipt_json=?
                WHERE execution_id=? AND lease_sha256=? AND state='STARTED'
                  AND request_sha256=? AND start_receipt_sha256=?
                  AND claimed_at IS NULL AND claim_receipt_sha256 IS NULL
                  AND claim_receipt_json IS NULL
                """,
                terminal_values,
            )
        else:
            updated = conn.execute(
                """
                UPDATE effect_executions
                SET state=?, finished_at=?, terminal_receipt_sha256=?,
                    terminal_receipt_json=?
                WHERE execution_id=? AND lease_sha256=? AND state='EXECUTING'
                  AND request_sha256=? AND start_receipt_sha256=?
                  AND claimed_at=? AND claim_receipt_sha256=?
                  AND claim_receipt_json=?
                """,
                terminal_values
                + (
                    claim.claimed_at,
                    claim.receipt_sha256,
                    canonical_json(claim.to_dict()),
                ),
            )
        if updated.rowcount != 1:
            raise EffectReconciliationConflict(
                "effect execution changed while reconciliation held the ledger lock"
            )
        conn.execute("COMMIT")
        return EffectReconciliationResult(
            terminal_receipt=pending_terminal_receipt,
            decision_sha256=decision.digest,
            applied=True,
            nonce_consumed=True,
            reconciled_at=reconciled_at,
        )
    except sqlite3.IntegrityError as exc:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise EffectReconciliationReplay(
            "effect reconciliation decision, nonce, or execution was already consumed"
        ) from exc
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()


__all__ = [
    "EffectReconciliationBindingError",
    "EffectReconciliationConflict",
    "EffectReconciliationDecision",
    "EffectReconciliationError",
    "EffectReconciliationExpired",
    "EffectReconciliationReplay",
    "EffectReconciliationResult",
    "EffectReconciliationSignatureError",
    "issue_effect_reconciliation_decision",
    "reconcile_effect_terminal",
    "verify_effect_reconciliation_decision",
]
