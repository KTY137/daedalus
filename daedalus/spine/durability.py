"""Gate-0 durability profile for the canonical :class:`SpineLedger`.

This module does not introduce another ledger or another state authority.  It
hardens the exact existing writable ``SpineLedger`` connection and reads the
settings back from SQLite.  Gate-0 writers must pass through this profile before
claiming power-loss-aware intent durability; ordinary legacy callers remain
honestly outside that claim until migrated.
"""
from __future__ import annotations

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


def inspect_gate0_durability(ledger: SpineLedger) -> Gate0DurabilityStatus:
    """Read the active connection's durability posture without changing it."""
    if not isinstance(ledger, SpineLedger):
        raise Gate0DurabilityError("Gate-0 durability requires SpineLedger")
    try:
        values = ledger.pragmas()
        journal = str(values["journal_mode"] or "").lower()
        synchronous = int(values["synchronous"])
        busy_timeout = int(values["busy_timeout"])
        foreign_keys = int(values["foreign_keys"])
    except (KeyError, TypeError, ValueError) as exc:
        raise Gate0DurabilityError(
            "canonical Event Store did not return a complete durability readback"
        ) from exc
    satisfied = (
        journal == _REQUIRED_JOURNAL_MODE
        and synchronous == _REQUIRED_SYNCHRONOUS
        and busy_timeout >= DEFAULT_BUSY_TIMEOUT_MS
        and foreign_keys == _REQUIRED_FOREIGN_KEYS
    )
    return Gate0DurabilityStatus(
        schema="daedalus-gate0-spine-durability/1",
        journal_mode=journal,
        synchronous=synchronous,
        busy_timeout_ms=busy_timeout,
        foreign_keys=foreign_keys,
        satisfied=satisfied,
    )


def enforce_gate0_durability(ledger: SpineLedger) -> Gate0DurabilityStatus:
    """Harden and verify the exact existing writable Event-Store connection.

    ``journal_mode`` is intentionally not changed here: it is persistent file
    state and the canonical ``SpineLedger`` constructor already owns that
    transition.  This profile refuses a non-WAL file instead of silently
    rewriting it.  The remaining settings are connection-local and are applied
    under the ledger's own connection lock.
    """
    if not isinstance(ledger, SpineLedger):
        raise Gate0DurabilityError("Gate-0 durability requires SpineLedger")
    if ledger.read_only:
        raise Gate0DurabilityError(
            "read-only Event Store cannot be used as a Gate-0 writer"
        )

    with ledger._lock:
        before = ledger.pragmas()
        if str(before["journal_mode"] or "").lower() != _REQUIRED_JOURNAL_MODE:
            raise Gate0DurabilityError(
                "Gate-0 Event Store requires existing WAL journal mode"
            )
        ledger._conn.execute("PRAGMA synchronous=FULL")
        ledger._conn.execute(
            f"PRAGMA busy_timeout={max(DEFAULT_BUSY_TIMEOUT_MS, ledger.busy_timeout_ms)}"
        )
        ledger._conn.execute("PRAGMA foreign_keys=ON")

    status = inspect_gate0_durability(ledger)
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
