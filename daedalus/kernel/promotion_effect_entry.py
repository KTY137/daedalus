"""Strangler entry preparation for the sealed promotion effect.

This module decides what the live promotion boundary may do *before* it can
reach any repository mutation.  It handles an as-yet unpersisted Effect Lease,
exact start races, pending restart state, deterministic terminal
reconciliation, and retained replay without accepting a promotion callback.

Only the caller that durably creates the exact Effect-Lease start receives the
``execute_promotion`` action.  Every restarted or racing caller receives a
non-executing action.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from daedalus.kernel.effects import LeasedEffectStartReceipt
from daedalus.kernel.promotion_effect_reconcile import (
    PromotionEffectReconciliationResult,
    reconcile_promotion_effect_terminal,
)
from daedalus.kernel.promotion_effect_replay import (
    PromotionEffectReplayDecision,
    PromotionEffectReplayMismatch,
    inspect_promotion_effect_replay,
)
from daedalus.kernel.promotion_effects import PromotionEffectCapability
from daedalus.kernel.promotion_execution import PromotionExecutionLedger
from daedalus.kernel.promotion_replay import inspect_promotion_execution
from daedalus.spine.ledger import _uri_path


_ENTRY_ACTIONS = frozenset(
    {
        "execute_promotion",
        "pending_reconciliation",
        "replay_promotion_report",
        "replay_effect_terminal_without_report",
    }
)


class PromotionEffectEntryMismatch(RuntimeError):
    """Persisted entry state is absent, malformed, racing or contradictory."""


@dataclass(frozen=True)
class PromotionEffectEntryResult:
    """One inert entry action; only ``execute_promotion`` permits the caller on."""

    action: str
    decision: PromotionEffectReplayDecision
    start_receipt: LeasedEffectStartReceipt | None = None
    reconciliation: PromotionEffectReconciliationResult | None = None

    def __post_init__(self) -> None:
        if self.action not in _ENTRY_ACTIONS:
            raise ValueError("unknown promotion effect entry action")
        if self.action == "execute_promotion":
            if self.start_receipt is None:
                raise ValueError("execute action requires exact Effect-Lease start")
            if self.reconciliation is not None:
                raise ValueError("execute action cannot contain reconciliation")
            if self.decision.action != "pending_reconciliation":
                raise ValueError("execute action requires post-start pending decision")
            if self.decision.promotion is not None:
                raise ValueError("execute action cannot race an existing promotion start")
            if (
                self.decision.effect is None
                or self.decision.effect.start_receipt != self.start_receipt
            ):
                raise ValueError("execute action start does not match persisted effect")
            return

        if self.start_receipt is not None:
            raise ValueError("non-execute entry action cannot carry a fresh start")
        if self.action == "pending_reconciliation":
            if self.decision.action != "pending_reconciliation":
                raise ValueError("pending entry action has the wrong decision")
            if self.reconciliation is not None:
                raise ValueError("pending entry action cannot contain reconciliation")
        elif self.action == "replay_promotion_report":
            if self.decision.action != "replay_promotion_report":
                raise ValueError("report replay action has the wrong decision")
            if (
                self.reconciliation is not None
                and self.reconciliation.decision != self.decision
            ):
                raise ValueError("reconciliation result does not match replay decision")
        elif self.action == "replay_effect_terminal_without_report":
            if self.decision.action != "replay_effect_terminal_without_report":
                raise ValueError("terminal replay action has the wrong decision")
            if self.reconciliation is not None:
                raise ValueError("terminal-only replay cannot contain reconciliation")

    @property
    def permits_promotion_execution(self) -> bool:
        return self.action == "execute_promotion"


def _exact_lease_is_persisted(capability: PromotionEffectCapability) -> bool:
    """Check only presence/collision; strict lease authentication happens later."""

    ledger = capability.authorization.effect_ledger
    path = ledger.path.resolve()
    if not path.exists():
        return False
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            f"file:{_uri_path(path)}?mode=ro",
            uri=True,
            timeout=30.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA query_only=ON")
        rows = connection.execute(
            """
            SELECT lease_sha256, lease_id
            FROM effect_leases
            WHERE lease_sha256=? OR lease_id=?
            """,
            (
                capability.authorization.lease.digest,
                capability.authorization.lease.lease_id,
            ),
        ).fetchall()
    except sqlite3.DatabaseError as exc:
        raise PromotionEffectEntryMismatch(
            "cannot inspect exact Effect-Lease presence"
        ) from exc
    finally:
        if connection is not None:
            connection.close()
    if not rows:
        return False
    if len(rows) != 1:
        raise PromotionEffectEntryMismatch(
            "Effect-Lease identity resolves to multiple persisted rows"
        )
    row = rows[0]
    if (
        str(row["lease_sha256"]) != capability.authorization.lease.digest
        or str(row["lease_id"]) != capability.authorization.lease.lease_id
    ):
        raise PromotionEffectEntryMismatch(
            "persisted Effect-Lease identity collides with another authority"
        )
    return True


def _route_nonexecuting(
    capability: PromotionEffectCapability,
    promotion_ledger: PromotionExecutionLedger,
    decision: PromotionEffectReplayDecision,
) -> PromotionEffectEntryResult:
    if decision.action == "pending_reconciliation":
        return PromotionEffectEntryResult(
            action="pending_reconciliation",
            decision=decision,
        )
    if decision.action == "reconcile_effect_terminal":
        reconciliation = reconcile_promotion_effect_terminal(
            capability,
            promotion_ledger,
        )
        return PromotionEffectEntryResult(
            action="replay_promotion_report",
            decision=reconciliation.decision,
            reconciliation=reconciliation,
        )
    if decision.action == "replay_promotion_report":
        return PromotionEffectEntryResult(
            action="replay_promotion_report",
            decision=decision,
        )
    if decision.action == "replay_effect_terminal_without_report":
        return PromotionEffectEntryResult(
            action="replay_effect_terminal_without_report",
            decision=decision,
        )
    raise PromotionEffectEntryMismatch(
        f"cannot route unexpected promotion entry decision {decision.action!r}"
    )


def prepare_promotion_effect_entry(
    capability: PromotionEffectCapability,
    promotion_ledger: PromotionExecutionLedger,
) -> PromotionEffectEntryResult:
    """Persist a fresh exact start or return a non-executing restart action.

    The function accepts no callback, report, time, path or outcome.  It never
    invokes promotion.  ``execute_promotion`` is returned only when this call's
    canonical ``begin`` result has ``execute=True`` and a strict post-start
    cross-ledger inspection shows the exact effect start with no promotion start.
    """

    if not isinstance(capability, PromotionEffectCapability):
        raise TypeError("promotion effect entry requires PromotionEffectCapability")
    if not isinstance(promotion_ledger, PromotionExecutionLedger):
        raise TypeError("promotion effect entry requires PromotionExecutionLedger")

    if _exact_lease_is_persisted(capability):
        decision = inspect_promotion_effect_replay(capability, promotion_ledger)
        if decision.action != "fresh":
            return _route_nonexecuting(capability, promotion_ledger, decision)
    else:
        retained_promotion = inspect_promotion_execution(
            promotion_ledger,
            capability.promotion,
        )
        if retained_promotion is not None:
            raise PromotionEffectEntryMismatch(
                "promotion execution exists before exact Effect-Lease persistence"
            )

    capability.grant()
    begun = capability.begin()
    try:
        after = inspect_promotion_effect_replay(capability, promotion_ledger)
    except PromotionEffectReplayMismatch as exc:
        raise PromotionEffectEntryMismatch(
            "post-start promotion effect state is contradictory"
        ) from exc

    if not begun.execute:
        return _route_nonexecuting(capability, promotion_ledger, after)
    if (
        after.action != "pending_reconciliation"
        or after.promotion is not None
        or after.effect is None
        or after.effect.start_receipt != begun.receipt
    ):
        raise PromotionEffectEntryMismatch(
            "fresh Effect-Lease start did not produce isolated executable state"
        )
    return PromotionEffectEntryResult(
        action="execute_promotion",
        decision=after,
        start_receipt=begun.receipt,
    )


__all__ = [
    "PromotionEffectEntryMismatch",
    "PromotionEffectEntryResult",
    "prepare_promotion_effect_entry",
]
