"""Read-only replay projection for one promotion Effect-Lease execution.

The projection binds retained start/terminal bytes to an already-validated
``PromotionEffectCapability``.  It opens the existing lease database with
``mode=ro`` and never calls the writer connection factory, grants a lease,
starts or finishes an effect, invokes Git, or executes promotion.
"""
from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from daedalus.kernel.effects import (
    EffectTerminalReceipt,
    LeasedEffectStartReceipt,
)
from daedalus.kernel.promotion_effects import PromotionEffectCapability
from daedalus.schemas import _identifier, _sha256
from daedalus.spine.envelope import canonical_json, canonical_sha

_MAX_ROW_BYTES = 4 * 1024 * 1024
_TERMINAL_STATES = frozenset({"COMPLETED", "FAILED", "CANCELLED"})


class PromotionEffectReplayError(RuntimeError):
    """Persisted Effect-Lease material is malformed or belongs elsewhere."""


@dataclass(frozen=True)
class PromotionEffectReplayResult:
    """Strict retained state for one exact promotion effect execution."""

    start: LeasedEffectStartReceipt
    state: str
    terminal: EffectTerminalReceipt | None

    def __post_init__(self) -> None:
        if not isinstance(self.start, LeasedEffectStartReceipt):
            raise ValueError("promotion effect replay requires a start receipt")
        if self.state not in {"STARTED", *_TERMINAL_STATES}:
            raise ValueError("promotion effect replay state is invalid")
        if (self.state == "STARTED") != (self.terminal is None):
            raise ValueError("promotion effect replay terminal/state mismatch")

    @property
    def pending_reconciliation(self) -> bool:
        return self.state == "STARTED"


def _strict_object(raw: Any, label: str) -> dict[str, Any]:
    if not isinstance(raw, str):
        raise PromotionEffectReplayError(f"{label} must be retained JSON text")
    if len(raw.encode("utf-8")) > _MAX_ROW_BYTES:
        raise PromotionEffectReplayError(f"{label} exceeds {_MAX_ROW_BYTES} bytes")

    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise PromotionEffectReplayError(
                    f"{label} contains duplicate key {key!r}"
                )
            result[key] = value
        return result

    try:
        value = json.loads(
            raw,
            object_pairs_hook=pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(
                PromotionEffectReplayError(
                    f"{label} contains non-finite constant {token}"
                )
            ),
        )
    except PromotionEffectReplayError:
        raise
    except (json.JSONDecodeError, UnicodeError, TypeError, ValueError) as exc:
        raise PromotionEffectReplayError(f"{label} is malformed JSON") from exc
    if not isinstance(value, dict):
        raise PromotionEffectReplayError(f"{label} must be a JSON object")
    _validate_json(value, label)
    if canonical_json(value) != raw:
        raise PromotionEffectReplayError(f"{label} is not canonical JSON")
    return value


def _validate_json(value: Any, label: str) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PromotionEffectReplayError(f"{label} contains non-finite float")
        return
    if isinstance(value, list):
        for item in value:
            _validate_json(item, label)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise PromotionEffectReplayError(
                    f"{label} contains a non-string object key"
                )
            _validate_json(item, label)
        return
    raise PromotionEffectReplayError(
        f"{label} contains unsupported {type(value).__name__}"
    )


def _timestamp(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise PromotionEffectReplayError(f"{label} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PromotionEffectReplayError(f"{label} is not ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PromotionEffectReplayError(f"{label} is not timezone-aware")
    canonical = parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")
    if value != canonical:
        raise PromotionEffectReplayError(f"{label} is not canonical UTC time")
    return canonical


def _readonly(path: Path) -> sqlite3.Connection:
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise PromotionEffectReplayError(
            "effect replay database is unavailable"
        ) from exc
    if path.is_symlink() or not resolved.is_file():
        raise PromotionEffectReplayError(
            "effect replay database must be a regular non-symlink file"
        )
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(
            resolved.as_uri() + "?mode=ro",
            uri=True,
            isolation_level=None,
            timeout=30,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        if int(conn.execute("PRAGMA query_only").fetchone()[0]) != 1:
            raise PromotionEffectReplayError(
                "effect replay connection did not enter query-only mode"
            )
        return conn
    except Exception:
        if conn is not None:
            conn.close()
        raise


def _decode_start(
    row: sqlite3.Row,
    capability: PromotionEffectCapability,
) -> LeasedEffectStartReceipt:
    payload = _strict_object(row["start_receipt_json"], "effect start receipt")
    fields = {
        "lease_sha256",
        "execution_id",
        "idempotency_key",
        "execution_request_sha256",
        "boundary_receipt_sha256",
        "started_at",
        "receipt_sha256",
    }
    if set(payload) != fields:
        raise PromotionEffectReplayError(
            "effect start receipt has an unexpected field set"
        )
    body = {key: payload[key] for key in fields - {"receipt_sha256"}}
    declared = _sha256(payload["receipt_sha256"], "receipt_sha256")
    if canonical_sha(body) != declared:
        raise PromotionEffectReplayError("effect start receipt digest mismatch")
    receipt = LeasedEffectStartReceipt(
        lease_sha256=_sha256(payload["lease_sha256"], "lease_sha256"),
        execution_id=_identifier(payload["execution_id"], "execution_id"),
        idempotency_key=_identifier(payload["idempotency_key"], "idempotency_key"),
        execution_request_sha256=_sha256(
            payload["execution_request_sha256"], "execution_request_sha256"
        ),
        boundary_receipt_sha256=_sha256(
            payload["boundary_receipt_sha256"], "boundary_receipt_sha256"
        ),
        started_at=_timestamp(payload["started_at"], "started_at"),
        receipt_sha256=declared,
    )
    execution = capability.execution
    expected = {
        "lease_sha256": capability.authorization.lease.digest,
        "execution_id": execution.execution_id,
        "idempotency_key": execution.idempotency_key,
        "execution_request_sha256": execution.digest,
    }
    actual = {
        "lease_sha256": receipt.lease_sha256,
        "execution_id": receipt.execution_id,
        "idempotency_key": receipt.idempotency_key,
        "execution_request_sha256": receipt.execution_request_sha256,
    }
    row_expected = {
        "lease_sha256": expected["lease_sha256"],
        "execution_id": expected["execution_id"],
        "idempotency_key": expected["idempotency_key"],
        "request_sha256": execution.digest,
        "request_json": canonical_json(execution.to_dict()),
        "start_receipt_sha256": receipt.receipt_sha256,
        "started_at": receipt.started_at,
    }
    mismatches = sorted(
        name for name, wanted in expected.items() if actual[name] != wanted
    )
    mismatches += sorted(
        f"row.{name}"
        for name, wanted in row_expected.items()
        if row[name] != wanted
    )
    if mismatches:
        raise PromotionEffectReplayError(
            "persisted effect start mismatch: " + ", ".join(mismatches)
        )
    return receipt


def _decode_terminal(
    row: sqlite3.Row,
    start: LeasedEffectStartReceipt,
) -> EffectTerminalReceipt:
    payload = _strict_object(
        row["terminal_receipt_json"], "effect terminal receipt"
    )
    fields = {
        "lease_sha256",
        "execution_id",
        "start_receipt_sha256",
        "outcome",
        "output_digests",
        "detail_sha256",
        "finished_at",
        "receipt_sha256",
    }
    if set(payload) != fields:
        raise PromotionEffectReplayError(
            "effect terminal receipt has an unexpected field set"
        )
    outcome = payload["outcome"]
    if not isinstance(outcome, str) or outcome not in _TERMINAL_STATES:
        raise PromotionEffectReplayError("effect terminal outcome is invalid")
    raw_outputs = payload["output_digests"]
    if not isinstance(raw_outputs, list):
        raise PromotionEffectReplayError("effect outputs must be an array")
    outputs = tuple(_sha256(value, "output_digest") for value in raw_outputs)
    if outputs != tuple(sorted(set(outputs))):
        raise PromotionEffectReplayError("effect outputs are not canonical")
    detail = (
        None
        if payload["detail_sha256"] is None
        else _sha256(payload["detail_sha256"], "detail_sha256")
    )
    body = {key: payload[key] for key in fields - {"receipt_sha256"}}
    declared = _sha256(payload["receipt_sha256"], "receipt_sha256")
    if canonical_sha(body) != declared:
        raise PromotionEffectReplayError("effect terminal receipt digest mismatch")
    receipt = EffectTerminalReceipt(
        lease_sha256=_sha256(payload["lease_sha256"], "lease_sha256"),
        execution_id=_identifier(payload["execution_id"], "execution_id"),
        start_receipt_sha256=_sha256(
            payload["start_receipt_sha256"], "start_receipt_sha256"
        ),
        outcome=outcome,
        output_digests=outputs,
        detail_sha256=detail,
        finished_at=_timestamp(payload["finished_at"], "finished_at"),
        receipt_sha256=declared,
    )
    expected = {
        "lease_sha256": start.lease_sha256,
        "execution_id": start.execution_id,
        "start_receipt_sha256": start.receipt_sha256,
        "state": receipt.outcome,
        "finished_at": receipt.finished_at,
        "terminal_receipt_sha256": receipt.receipt_sha256,
    }
    actual = {
        "lease_sha256": receipt.lease_sha256,
        "execution_id": receipt.execution_id,
        "start_receipt_sha256": receipt.start_receipt_sha256,
        "state": row["state"],
        "finished_at": row["finished_at"],
        "terminal_receipt_sha256": row["terminal_receipt_sha256"],
    }
    mismatches = sorted(
        name for name, wanted in expected.items() if actual[name] != wanted
    )
    if mismatches:
        raise PromotionEffectReplayError(
            "persisted effect terminal mismatch: " + ", ".join(mismatches)
        )
    return receipt


def inspect_promotion_effect_execution(
    capability: PromotionEffectCapability,
) -> PromotionEffectReplayResult | None:
    """Return exact retained state without creating or changing a row."""

    if not isinstance(capability, PromotionEffectCapability):
        raise TypeError(
            "promotion effect replay requires PromotionEffectCapability"
        )
    path = getattr(capability.authorization.effect_ledger, "path", None)
    if not isinstance(path, Path):
        raise PromotionEffectReplayError(
            "promotion effect ledger does not expose a canonical path"
        )
    conn = _readonly(path)
    try:
        lease = capability.authorization.lease
        lease_rows = conn.execute(
            """
            SELECT * FROM effect_leases
            WHERE lease_sha256=? OR lease_id=?
            """,
            (lease.digest, lease.lease_id),
        ).fetchall()
        if not lease_rows:
            return None
        if len(lease_rows) != 1:
            raise PromotionEffectReplayError("effect lease identity is ambiguous")
        lease_row = lease_rows[0]
        lease_expected = {
            "lease_sha256": lease.digest,
            "lease_id": lease.lease_id,
            "request_sha256": capability.authorization.request.digest,
            "policy_decision_sha256": (
                capability.authorization.policy_decision.digest
            ),
            "registry_sha256": lease.registry_sha256,
            "entrypoint_id": lease.entrypoint_id,
            "lease_json": lease.to_json(),
            "issued_at": lease.issued_at,
            "expires_at": lease.expires_at,
        }
        lease_mismatches = sorted(
            name for name, wanted in lease_expected.items()
            if lease_row[name] != wanted
        )
        if lease_mismatches:
            raise PromotionEffectReplayError(
                "persisted effect lease mismatch: "
                + ", ".join(lease_mismatches)
            )

        execution = capability.execution
        rows = conn.execute(
            """
            SELECT * FROM effect_executions
            WHERE execution_id=?
               OR (lease_sha256=? AND idempotency_key=?)
            """,
            (
                execution.execution_id,
                lease.digest,
                execution.idempotency_key,
            ),
        ).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise PromotionEffectReplayError(
                "effect execution identity is ambiguous"
            )
        row = rows[0]
        start = _decode_start(row, capability)
        state = str(row["state"])
        terminal_columns = (
            "finished_at",
            "terminal_receipt_sha256",
            "terminal_receipt_json",
        )
        if state == "STARTED":
            if any(row[name] is not None for name in terminal_columns):
                raise PromotionEffectReplayError(
                    "pending effect retains terminal material"
                )
            return PromotionEffectReplayResult(start, state, None)
        if state not in _TERMINAL_STATES:
            raise PromotionEffectReplayError("effect has an unknown state")
        if any(row[name] is None for name in terminal_columns):
            raise PromotionEffectReplayError(
                "terminal effect is missing receipt material"
            )
        return PromotionEffectReplayResult(
            start,
            state,
            _decode_terminal(row, start),
        )
    except sqlite3.Error as exc:
        raise PromotionEffectReplayError("effect replay query failed") from exc
    finally:
        conn.close()


__all__ = [
    "PromotionEffectReplayError",
    "PromotionEffectReplayResult",
    "inspect_promotion_effect_execution",
]
