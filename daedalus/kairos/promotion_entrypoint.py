"""Public capability-bearing promotion entrypoint.

This module is the strangler-facing production surface for repository promotion.
It accepts the complete persisted Effect-Lease capability and delegates exactly
once to the restart-safe lifecycle adapter.  The historical
``daedalus.kairos.gated_writes.promote_candidates`` callable remains available
only as a compatibility implementation while callers are migrated in small
reviewable packets.
"""
from __future__ import annotations

from typing import Any, Mapping

from daedalus.kernel.promotion_effects import PromotionEffectCapability
from daedalus.kernel.promotion_execution import PromotionExecutionLedger

from .promotion_effect_lifecycle import promote_candidates_with_effect_lifecycle


def promote_candidates(
    repo_root: str,
    candidates: list[Any],
    *,
    project: str | None,
    availability: dict,
    consumed_approval: Any,
    evidence_packet: Any,
    target_ref: str,
    promotion_effect_capability: PromotionEffectCapability,
    approval_ledger: Any,
    owner_keyring: Mapping[tuple[str, str], bytes | str],
    promotion_execution_ledger: PromotionExecutionLedger,
    ledger_path: Any = None,
    lock_timeout_s: float = 120.0,
    gate_timeout_s: float = 900.0,
    cancel: Any = None,
) -> dict[str, Any]:
    """Run or replay one manually authorized promotion under an Effect Lease.

    No callback or lower-level implementation is accepted from the caller.  The
    lifecycle adapter owns preauthorization, persisted start ordering, restart
    classification and evidence-derived terminal accounting.
    """

    return promote_candidates_with_effect_lifecycle(
        repo_root,
        candidates,
        project=project,
        availability=availability,
        consumed_approval=consumed_approval,
        evidence_packet=evidence_packet,
        target_ref=target_ref,
        promotion_effect_capability=promotion_effect_capability,
        approval_ledger=approval_ledger,
        owner_keyring=owner_keyring,
        promotion_execution_ledger=promotion_execution_ledger,
        ledger_path=ledger_path,
        lock_timeout_s=lock_timeout_s,
        gate_timeout_s=gate_timeout_s,
        cancel=cancel,
    )


__all__ = ["promote_candidates"]
