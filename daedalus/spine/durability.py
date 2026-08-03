"""Gate-0 durability profile for the canonical :class:`SpineLedger`.

This module does not introduce another ledger or another state authority. It
hardens the exact existing writable ``SpineLedger`` connection and reads the
settings back from SQLite. Gate-0 writers must pass through this profile before
claiming power-loss-aware intent durability; ordinary legacy callers remain
honestly outside that claim until migrated.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from .ledger import DEFAULT_BUSY_TIMEOUT_MS, SpineLedger


_REQUIRED_SYNCHRONOUS = 2  # SQLite FULL
_REQUIRED_FOREIGN_KEYS = 1
_REQUIRED_JOURNAL_MODE = "wal"


class Gate0DurabilityError(RuntimeError):
    """The canonical Event Store cannot satisfy the Gate-0 writer profile."""


@dataclass(frozen=True)
class Gate0DurabilityStatus:
    """Machine-readable readback of one hardened Event-Store connection."""

    schema: str
    journal_mode: str
    synchronous: int
    busy_timeout_ms: int
    foreign_keys: int
    satisfied: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "journal_mode": self.journal_mode,
            "synchronous": self.synchronous,
            "busy_timeout_ms": self.busy_timeout_ms,
            "foreign_keys": self.foreign_keys,
            "satisfied": self.satisfied,
        }


def _status(
    *,
    journal_mode: object,
    synchronous: object,
    busy_timeout: object,
    foreign_keys: object,
) -> Gate0DurabilityStatus:
    try:
        journal = str(journal_mode or "").lower()
        sync_value = int(synchronous)
        timeout_value = int(busy_timeout)
        foreign_value = int(foreign_keys)
    except (TypeError, ValueError) as exc:
        raise Gate0DurabilityError(
            "canonical Event Store returned malformed durability values"
        ) from exc
    satisfied = (
        journal == _REQUIRED_JOURNAL_MODE
        and sync_value == _REQUIRED_SYNCHRONOUS
        and timeout_value >= DEFAULT_BUSY_TIMEOUT_MS
        and foreign_value == _REQUIRED_FOREIGN_KEYS
    )
    return Gate0DurabilityStatus(
        schema="daedalus-gate0-spine-durability/1",
        journal_mode=journal,
        synchronous=sync_value,
        busy_timeout_ms=timeout_value,
        foreign_keys=foreign_value,
        satisfied=satisfied,
    )


def _read_connection_status(connection: sqlite3.Connection) -> Gate0DurabilityStatus:
    try:
        return _status(
            journal_mode=connection.execute("PRAGMA journal_mode").fetchone()[0],
            synchronous=connection.execute("PRAGMA synchronous").fetchone()[0],
            busy_timeout=connection.execute("PRAGMA busy_timeout").fetchone()[0],
            foreign_keys=connection.execute("PRAGMA foreign_keys").fetchone()[0],
        )
    except (sqlite3.Error, IndexError, TypeError) as exc:
        raise Gate0DurabilityError(
            "canonical Event Store did not return a complete durability readback"
        ) from exc


def inspect_gate0_durability(ledger: SpineLedger) -> Gate0DurabilityStatus:
    """Read the active connection's durability posture without changing it."""
    if not isinstance(ledger, SpineLedger):
        raise Gate0DurabilityError("Gate-0 durability requires SpineLedger")
    try:
        values = ledger.pragmas()
        return _status(
            journal_mode=values["journal_mode"],
            synchronous=values["synchronous"],
            busy_timeout=values["busy_timeout"],
            foreign_keys=values["foreign_keys"],
        )
    except Gate0DurabilityError:
        raise
    except (KeyError, TypeError, sqlite3.Error) as exc:
        raise Gate0DurabilityError(
            "canonical Event Store did not return a complete durability readback"
        ) from exc


def enforce_gate0_durability(ledger: SpineLedger) -> Gate0DurabilityStatus:
    """Harden and verify the exact existing writable Event-Store connection.

    ``journal_mode`` is intentionally not changed here: it is persistent file
    state and the canonical ``SpineLedger`` constructor already owns that
    transition. This profile refuses a non-WAL file instead of silently
    rewriting it. Apply and readback happen atomically under the ledger's exact
    connection lock; no nested public-lock call or replacement connection is
    used.
    """
    if not isinstance(ledger, SpineLedger):
        raise Gate0DurabilityError("Gate-0 durability requires SpineLedger")
    if ledger.read_only:
        raise Gate0DurabilityError(
            "read-only Event Store cannot be used as a Gate-0 writer"
        )
    try:
        connection = ledger._conn
        lock = ledger._lock
    except AttributeError as exc:
        raise Gate0DurabilityError(
            "SpineLedger does not expose the required canonical connection seam"
        ) from exc
    if not isinstance(connection, sqlite3.Connection):
        raise Gate0DurabilityError(
            "SpineLedger canonical connection seam has an unexpected type"
        )

    try:
        with lock:
            before = _read_connection_status(connection)
            if before.journal_mode != _REQUIRED_JOURNAL_MODE:
                raise Gate0DurabilityError(
                    "Gate-0 Event Store requires existing WAL journal mode"
                )
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute(
                f"PRAGMA busy_timeout={max(DEFAULT_BUSY_TIMEOUT_MS, ledger.busy_timeout_ms)}"
            )
            connection.execute("PRAGMA foreign_keys=ON")
            status = _read_connection_status(connection)
    except Gate0DurabilityError:
        raise
    except (sqlite3.Error, TypeError, AttributeError) as exc:
        raise Gate0DurabilityError(
            "Gate-0 Event Store durability profile could not be applied"
        ) from exc

    if not status.satisfied:
        raise Gate0DurabilityError(
            "Gate-0 Event Store durability readback is weaker than required"
        )
    return status


__all__ = [
    "Gate0DurabilityError",
    "Gate0DurabilityStatus",
    "enforce_gate0_durability",
    "inspect_gate0_durability",
]
