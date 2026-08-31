"""Strict read-only projection over persisted Effect-Lease execution rows.

The generic Effect-Lease authority intentionally returns ``execute=False`` on
an exact start replay. That prevents a second external effect, but the returned
start receipt alone does not distinguish a still-pending execution from a
retained terminal outcome. Restart composition therefore needs a separate
reader that cannot create or transition ledger state.

This module opens the selected Effect-Lease SQLite file with ``mode=ro`` and
``query_only=ON``, authenticates the signed lease at the retained start instant,
and strictly validates the exact persisted request, start receipt, state and
optional terminal receipt. It neither grants nor starts a lease and exposes no
re-execution authority.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from daedalus.kernel.authorization import NonRuntimeEffectAuthorization
from daedalus.kernel.contracts import EffectLease, EffectLeaseRequest
from daedalus.kernel.effects import (
    EffectExecutionRequest,
    EffectLeaseBindingMismatch,
    EffectLeaseError,
    EffectLeaseLedger,
    EffectLeaseStateError,
    EffectTerminalReceipt,
    LeasedEffectStartReceipt,
    _parse_utc,
    verify_effect_lease,
)
from daedalus.schemas import PolicyDecision, _identifier, _sha256
from daedalus.spine.effect_boundary import REGISTRY_BY_ID, EntrypointSpec
from daedalus.spine.envelope import canonical_json, canonical_sha
from daedalus.spine.ledger import _uri_path


_TERMINAL_STATES = frozenset({"COMPLETED", "FAILED", "CANCELLED"})
_START_FIELDS = frozenset(
    {
        "lease_sha256",
        "execution_id",
        "idempotency_key",
        "execution_request_sha256",
        "boundary_receipt_sha256",
        "started_at",
        "receipt_sha256",
    }
)
_TERMINAL_FIELDS = frozenset(
    {
        "lease_sha256",
        "execution_id",
        "start_receipt_sha256",
        "outcome",
        "output_digests",
        "detail_sha256",
        "finished_at",
        "receipt_sha256",
    }
)


class EffectReplayProjectionError(EffectLeaseStateError):
    """Persisted effect replay material is absent, malformed or contradictory."""


@dataclass(frozen=True)
class EffectExecutionReplaySnapshot:
    """One exact persisted execution state with no authority to execute again."""

    start_receipt: LeasedEffectStartReceipt
    state: str
    terminal_receipt: EffectTerminalReceipt | None

    def __post_init__(self) -> None:
        if self.state != "STARTED" and self.state not in _TERMINAL_STATES:
            raise ValueError("unknown effect replay state")
        if (self.state == "STARTED") != (self.terminal_receipt is None):
            raise ValueError("effect replay state and terminal receipt disagree")

    @property
    def pending_reconciliation(self) -> bool:
        return self.state == "STARTED"


def _strict_object(raw: object, label: str) -> dict[str, Any]:
    if not isinstance(raw, str):
        raise EffectReplayProjectionError(f"{label} must be persisted text")

    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise EffectReplayProjectionError(
                    f"{label} contains duplicate JSON key {key!r}"
                )
            result[key] = value
        return result

    try:
        parsed = json.loads(raw, object_pairs_hook=pairs)
    except EffectReplayProjectionError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise EffectReplayProjectionError(f"{label} is malformed JSON") from exc
    if not isinstance(parsed, dict):
        raise EffectReplayProjectionError(f"{label} must be a JSON object")
    if canonical_json(parsed) != raw:
        raise EffectReplayProjectionError(f"{label} is noncanonical")
    return parsed


def _canonical_time(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise EffectReplayProjectionError(f"{label} must be a string")
    try:
        parsed = _parse_utc(value, label)
    except EffectLeaseBindingMismatch as exc:
        raise EffectReplayProjectionError(f"{label} is malformed") from exc
    canonical = parsed.isoformat(timespec="microseconds")
    if canonical != value:
        raise EffectReplayProjectionError(f"{label} is noncanonical")
    return canonical


def _start_receipt(
    raw: object,
    *,
    lease_sha256: str,
    execution: EffectExecutionRequest,
) -> LeasedEffectStartReceipt:
    parsed = _strict_object(raw, "persisted effect start receipt")
    if set(parsed) != _START_FIELDS:
        raise EffectReplayProjectionError(
            "persisted effect start receipt has the wrong fields"
        )
    try:
        receipt = LeasedEffectStartReceipt(
            lease_sha256=_sha256(parsed["lease_sha256"], "lease_sha256"),
            execution_id=_identifier(parsed["execution_id"], "execution_id"),
            idempotency_key=_identifier(
                parsed["idempotency_key"], "idempotency_key"
            ),
            execution_request_sha256=_sha256(
                parsed["execution_request_sha256"],
                "execution_request_sha256",
            ),
            boundary_receipt_sha256=_sha256(
                parsed["boundary_receipt_sha256"],
                "boundary_receipt_sha256",
            ),
            started_at=_canonical_time(parsed["started_at"], "started_at"),
            receipt_sha256=_sha256(
                parsed["receipt_sha256"], "receipt_sha256"
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise EffectReplayProjectionError(
            "persisted effect start receipt is malformed"
        ) from exc
    expected_subject = {
        "lease_sha256": lease_sha256,
        "execution_id": execution.execution_id,
        "idempotency_key": execution.idempotency_key,
        "execution_request_sha256": execution.digest,
    }
    actual_subject = {
        "lease_sha256": receipt.lease_sha256,
        "execution_id": receipt.execution_id,
        "idempotency_key": receipt.idempotency_key,
        "execution_request_sha256": receipt.execution_request_sha256,
    }
    mismatches = sorted(
        name
        for name, expected in expected_subject.items()
        if actual_subject[name] != expected
    )
    if mismatches:
        raise EffectReplayProjectionError(
            "persisted effect start contradicts requested execution: "
            + ", ".join(mismatches)
        )
    digest_payload = {
        "lease_sha256": receipt.lease_sha256,
        "execution_id": receipt.execution_id,
        "idempotency_key": receipt.idempotency_key,
        "execution_request_sha256": receipt.execution_request_sha256,
        "boundary_receipt_sha256": receipt.boundary_receipt_sha256,
        "started_at": receipt.started_at,
    }
    if canonical_sha(digest_payload) != receipt.receipt_sha256:
        raise EffectReplayProjectionError(
            "persisted effect start receipt digest is invalid"
        )
    if canonical_json(receipt.to_dict()) != raw:
        raise EffectReplayProjectionError(
            "persisted effect start receipt does not round-trip canonically"
        )
    return receipt


def _terminal_receipt(
    raw: object,
    *,
    start: LeasedEffectStartReceipt,
    row_state: str,
) -> EffectTerminalReceipt:
    parsed = _strict_object(raw, "persisted effect terminal receipt")
    if set(parsed) != _TERMINAL_FIELDS:
        raise EffectReplayProjectionError(
            "persisted effect terminal receipt has the wrong fields"
        )
    outputs_raw = parsed.get("output_digests")
    if not isinstance(outputs_raw, list):
        raise EffectReplayProjectionError(
            "persisted effect terminal outputs must be an array"
        )
    try:
        outputs = tuple(
            _sha256(value, f"output_digests[{index}]")
            for index, value in enumerate(outputs_raw)
        )
        if tuple(sorted(set(outputs))) != outputs:
            raise EffectReplayProjectionError(
                "persisted effect terminal outputs are not sorted and unique"
            )
        detail_raw = parsed.get("detail_sha256")
        detail = (
            None
            if detail_raw is None
            else _sha256(detail_raw, "detail_sha256")
        )
        outcome_raw = parsed["outcome"]
        if not isinstance(outcome_raw, str) or outcome_raw not in _TERMINAL_STATES:
            raise EffectReplayProjectionError(
                "persisted effect terminal outcome is invalid"
            )
        receipt = EffectTerminalReceipt(
            lease_sha256=_sha256(parsed["lease_sha256"], "lease_sha256"),
            execution_id=_identifier(parsed["execution_id"], "execution_id"),
            start_receipt_sha256=_sha256(
                parsed["start_receipt_sha256"],
                "start_receipt_sha256",
            ),
            outcome=outcome_raw,
            output_digests=outputs,
            detail_sha256=detail,
            finished_at=_canonical_time(parsed["finished_at"], "finished_at"),
            receipt_sha256=_sha256(
                parsed["receipt_sha256"], "receipt_sha256"
            ),
        )
    except EffectReplayProjectionError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise EffectReplayProjectionError(
            "persisted effect terminal receipt is malformed"
        ) from exc
    comparisons = {
        "lease_sha256": (receipt.lease_sha256, start.lease_sha256),
        "execution_id": (receipt.execution_id, start.execution_id),
        "start_receipt_sha256": (
            receipt.start_receipt_sha256,
            start.receipt_sha256,
        ),
        "outcome": (receipt.outcome, row_state),
    }
    mismatches = sorted(
        name for name, (actual, expected) in comparisons.items() if actual != expected
    )
    if mismatches:
        raise EffectReplayProjectionError(
            "persisted effect terminal contradicts its start or row: "
            + ", ".join(mismatches)
        )
    if _parse_utc(receipt.finished_at, "finished_at") < _parse_utc(
        start.started_at,
        "started_at",
    ):
        raise EffectReplayProjectionError(
            "persisted effect terminal precedes its start"
        )
    digest_payload = {
        "lease_sha256": receipt.lease_sha256,
        "execution_id": receipt.execution_id,
        "start_receipt_sha256": receipt.start_receipt_sha256,
        "outcome": receipt.outcome,
        "output_digests": list(receipt.output_digests),
        "detail_sha256": receipt.detail_sha256,
        "finished_at": receipt.finished_at,
    }
    if canonical_sha(digest_payload) != receipt.receipt_sha256:
        raise EffectReplayProjectionError(
            "persisted effect terminal receipt digest is invalid"
        )
    if canonical_json(receipt.to_dict()) != raw:
        raise EffectReplayProjectionError(
            "persisted effect terminal receipt does not round-trip canonically"
        )
    return receipt


@dataclass(frozen=True)
class PersistedEffectLeaseSubject:
    """The exact lease subject one read-only replay projection reads.

    This is deliberately *not* a capability. It carries no guard decisions, no
    kill-switch authority and no grant/begin/finish methods, so holding one can
    never authorize an effect. Both the non-runtime and the runtime-bound
    projections describe their subject with it; a runtime-bearing lease is
    therefore never downgraded through a non-runtime capability facade to be
    read.
    """

    lease: EffectLease
    request: EffectLeaseRequest
    policy_decision: PolicyDecision
    effect_ledger: EffectLeaseLedger
    lease_keyring: Mapping[str, bytes | str] = field(repr=False)
    registry: Mapping[str, EntrypointSpec] | Sequence[EntrypointSpec] = field(
        default_factory=lambda: REGISTRY_BY_ID,
        repr=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.lease, EffectLease):
            raise TypeError("effect replay subject requires an EffectLease")
        if not isinstance(self.effect_ledger, EffectLeaseLedger):
            raise TypeError("effect replay inspection requires EffectLeaseLedger")
        if self.lease.request_sha256 != self.request.digest:
            raise EffectLeaseBindingMismatch(
                "effect replay subject request does not match its lease"
            )
        if self.lease.policy_decision_sha256 != self.policy_decision.digest:
            raise EffectLeaseBindingMismatch(
                "effect replay subject policy does not match its lease"
            )
        object.__setattr__(
            self,
            "lease_keyring",
            MappingProxyType(dict(self.lease_keyring)),
        )


def _project_persisted_execution(
    authorization: PersistedEffectLeaseSubject,
    execution: EffectExecutionRequest,
) -> EffectExecutionReplaySnapshot | None:
    """Read one persisted execution for one exact signed lease subject.

    Shared read-only reader behind every replay projection. It opens the ledger
    read-only, never writes, and grants no execute authority; each public
    projection remains responsible for its own capability-class verification.
    """

    ledger = authorization.effect_ledger

    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            f"file:{_uri_path(ledger.path.resolve())}?mode=ro",
            uri=True,
            timeout=30.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA query_only=ON")

        lease_rows = connection.execute(
            """
            SELECT lease_sha256, lease_id, request_sha256,
                   policy_decision_sha256, registry_sha256, entrypoint_id,
                   lease_json, issued_at, expires_at
            FROM effect_leases
            WHERE lease_sha256=? OR lease_id=?
            """,
            (authorization.lease.digest, authorization.lease.lease_id),
        ).fetchall()
        if len(lease_rows) != 1:
            raise EffectReplayProjectionError(
                "exact effect lease is not uniquely persisted"
            )
        persisted_lease = lease_rows[0]
        lease_comparisons = {
            "lease_sha256": (
                str(persisted_lease["lease_sha256"]),
                authorization.lease.digest,
            ),
            "lease_id": (
                str(persisted_lease["lease_id"]),
                authorization.lease.lease_id,
            ),
            "request_sha256": (
                str(persisted_lease["request_sha256"]),
                authorization.request.digest,
            ),
            "policy_decision_sha256": (
                str(persisted_lease["policy_decision_sha256"]),
                authorization.policy_decision.digest,
            ),
            "registry_sha256": (
                str(persisted_lease["registry_sha256"]),
                authorization.lease.registry_sha256,
            ),
            "entrypoint_id": (
                str(persisted_lease["entrypoint_id"]),
                authorization.lease.entrypoint_id,
            ),
            "lease_json": (
                str(persisted_lease["lease_json"]),
                authorization.lease.to_json(),
            ),
            "issued_at": (
                str(persisted_lease["issued_at"]),
                authorization.lease.issued_at,
            ),
            "expires_at": (
                str(persisted_lease["expires_at"]),
                authorization.lease.expires_at,
            ),
        }
        lease_mismatches = sorted(
            name
            for name, (actual, expected) in lease_comparisons.items()
            if actual != expected
        )
        if lease_mismatches:
            raise EffectReplayProjectionError(
                "persisted effect lease contradicts supplied authorization: "
                + ", ".join(lease_mismatches)
            )

        rows = connection.execute(
            """
            SELECT execution_id, lease_sha256, idempotency_key,
                   request_sha256, request_json, start_receipt_sha256,
                   start_receipt_json, state, started_at, finished_at,
                   terminal_receipt_sha256, terminal_receipt_json
            FROM effect_executions
            WHERE execution_id=? OR (lease_sha256=? AND idempotency_key=?)
            """,
            (
                execution.execution_id,
                authorization.lease.digest,
                execution.idempotency_key,
            ),
        ).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise EffectReplayProjectionError(
                "effect execution identity resolves to multiple rows"
            )
        row = rows[0]
        row_comparisons = {
            "execution_id": (str(row["execution_id"]), execution.execution_id),
            "lease_sha256": (
                str(row["lease_sha256"]),
                authorization.lease.digest,
            ),
            "idempotency_key": (
                str(row["idempotency_key"]),
                execution.idempotency_key,
            ),
            "request_sha256": (
                str(row["request_sha256"]),
                execution.digest,
            ),
            "request_json": (
                str(row["request_json"]),
                canonical_json(execution.to_dict()),
            ),
        }
        row_mismatches = sorted(
            name
            for name, (actual, expected) in row_comparisons.items()
            if actual != expected
        )
        if row_mismatches:
            raise EffectReplayProjectionError(
                "persisted effect row contradicts requested execution: "
                + ", ".join(row_mismatches)
            )

        start = _start_receipt(
            row["start_receipt_json"],
            lease_sha256=authorization.lease.digest,
            execution=execution,
        )
        if str(row["start_receipt_sha256"]) != start.receipt_sha256:
            raise EffectReplayProjectionError(
                "effect row start digest does not bind persisted start receipt"
            )
        if str(row["started_at"]) != start.started_at:
            raise EffectReplayProjectionError(
                "effect row start time does not bind persisted start receipt"
            )

        verify_effect_lease(
            authorization.lease,
            request=authorization.request,
            policy_decision=authorization.policy_decision,
            keyring=authorization.lease_keyring,
            current_kill_switch_generation=authorization.lease.kill_switch_generation,
            now=_parse_utc(start.started_at, "started_at"),
            registry=authorization.registry,
        )

        state = str(row["state"])
        if state == "STARTED":
            if any(
                row[name] is not None
                for name in (
                    "finished_at",
                    "terminal_receipt_sha256",
                    "terminal_receipt_json",
                )
            ):
                raise EffectReplayProjectionError(
                    "started effect row contains terminal material"
                )
            return EffectExecutionReplaySnapshot(
                start_receipt=start,
                state=state,
                terminal_receipt=None,
            )
        if state not in _TERMINAL_STATES:
            raise EffectReplayProjectionError(
                f"persisted effect row has unknown state {state!r}"
            )
        if any(
            row[name] is None
            for name in (
                "finished_at",
                "terminal_receipt_sha256",
                "terminal_receipt_json",
            )
        ):
            raise EffectReplayProjectionError(
                "terminal effect row is missing terminal material"
            )
        terminal = _terminal_receipt(
            row["terminal_receipt_json"],
            start=start,
            row_state=state,
        )
        if str(row["terminal_receipt_sha256"]) != terminal.receipt_sha256:
            raise EffectReplayProjectionError(
                "effect row terminal digest does not bind persisted terminal receipt"
            )
        if str(row["finished_at"]) != terminal.finished_at:
            raise EffectReplayProjectionError(
                "effect row terminal time does not bind persisted terminal receipt"
            )
        return EffectExecutionReplaySnapshot(
            start_receipt=start,
            state=state,
            terminal_receipt=terminal,
        )
    except EffectReplayProjectionError:
        raise
    except (EffectLeaseError, sqlite3.DatabaseError) as exc:
        raise EffectReplayProjectionError(
            "cannot authenticate or read persisted effect execution"
        ) from exc
    finally:
        if connection is not None:
            connection.close()


def inspect_effect_execution(
    authorization: NonRuntimeEffectAuthorization,
    execution: EffectExecutionRequest,
) -> EffectExecutionReplaySnapshot | None:
    """Project one exact persisted effect execution without changing its state.

    ``None`` means the signed lease is persisted but the exact execution has no
    start. A returned snapshot is either ``STARTED`` and pending reconciliation
    or contains one strictly validated terminal receipt. Historical signature
    and scope verification is evaluated at the retained start instant; no stale
    lease or kill switch can thereby regain authority to execute.
    """

    if not isinstance(authorization, NonRuntimeEffectAuthorization):
        raise TypeError(
            "effect replay inspection requires NonRuntimeEffectAuthorization"
        )
    if not isinstance(execution, EffectExecutionRequest):
        raise TypeError("effect replay inspection requires EffectExecutionRequest")
    return _project_persisted_execution(
        PersistedEffectLeaseSubject(
            lease=authorization.lease,
            request=authorization.request,
            policy_decision=authorization.policy_decision,
            effect_ledger=authorization.effect_ledger,
            lease_keyring=authorization.lease_keyring,
            registry=authorization.registry,
        ),
        execution,
    )


__all__ = [
    "EffectExecutionReplaySnapshot",
    "EffectReplayProjectionError",
    "inspect_effect_execution",
]
