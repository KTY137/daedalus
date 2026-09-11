"""Advisory hopping admission for current canonical campaign projections.

A nomination is not an activation permit. This module grants no authority,
performs no I/O and cannot replace the sealed promotion path. Its current
fail-closed result documents precisely why a candidate cannot switch runtimes.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _digest(value: object, size: int = 64) -> bool:
    return type(value) is str and len(value) == size and all(c in "0123456789abcdef" for c in value)


def assess_hopping_candidate(result: Mapping[str, Any], *, live_revision: str | None) -> dict[str, Any]:
    """Do not let a green/self-reported test, stale receipt or nomination hop.

    The adapter supplies the current HEAD separately, never a value proposed by
    the candidate. Even valid nomination evidence is NOT evidence of a running
    replacement, state migration, healthy rollback or independent verification.
    """
    blockers: list[str] = []
    nominated = result.get("outcome") == "nominated"
    if not nominated:
        blockers.append("candidate_not_nominated")
    for field in ("candidate_tree_sha256", "nomination_receipt_sha256", "campaign_receipt_sha256"):
        if not _digest(result.get(field)):
            blockers.append("missing_" + field)
    revision = result.get("source_revision")
    if not _digest(revision, 40) or not _digest(live_revision, 40):
        blockers.append("live_source_revision_unverified")
    elif revision != live_revision:
        blockers.append("source_revision_changed")
    if result.get("postcondition_verified") is not True:
        blockers.append("campaign_postcondition_unverified")
    if result.get("receipt_contradicts_request") is not False:
        blockers.append("campaign_request_binding_unverified")
    equality = result.get("budget_equality")
    if not isinstance(equality, Mapping) or any(equality.get(k) is not True for k in
                                               ("configured_equal", "realized_usage_recorded", "within_budget")):
        blockers.append("budget_equality_unverified")
    if result.get("evaluation_mode") != "owner-tests":
        blockers.append("exact_match_is_not_behavioral_evaluation")
    # Current evaluator boundaries, not caller-controlled permission flags.
    blockers.extend(("independent_evaluator_required", "candidate_network_fence_required",
                     "sealed_owner_approval_required", "full_kernel_mirror_unverified",
                     "runtime_health_and_rollback_unverified"))
    return {
        "schema": "daedalus-hopping-admission/1",
        "stage": "nominated-not-activated" if nominated else "no-nominated-candidate",
        "activation_permitted": False,
        "self_improvement_proven": False,
        "candidate_applied": result.get("applied") is True,
        "full_kernel_mirror_verified": False,
        "blockers": blockers,
        "next_action": "independent verification and sealed promotion; never overwrite the live kernel",
    }
