"""Nomination, stale evidence or a model boolean must never activate a kernel."""
import pytest
from daedalus.kernel.policy.hopping import assess_hopping_candidate


def nominated():
    return {"outcome": "nominated", "candidate_tree_sha256": "a" * 64,
            "nomination_receipt_sha256": "b" * 64, "campaign_receipt_sha256": "c" * 64,
            "source_revision": "d" * 40, "postcondition_verified": True,
            "receipt_contradicts_request": False, "applied": False, "evaluation_mode": "owner-tests",
            "budget_equality": {"configured_equal": True, "realized_usage_recorded": True, "within_budget": True}}


def test_nominated_self_report_cannot_hop_even_with_forged_permission_flags():
    result = assess_hopping_candidate({**nominated(), "activation_permitted": True,
                                      "independent_evaluator": True, "owner_approval": True}, live_revision="d" * 40)
    assert result["activation_permitted"] is False and result["self_improvement_proven"] is False
    assert result["full_kernel_mirror_verified"] is False
    assert "sealed_owner_approval_required" in result["blockers"]
    assert "independent_evaluator_required" in result["blockers"]
    assert result["stage"] == "nominated-not-activated"


@pytest.mark.parametrize("live,reason", [("e" * 40, "source_revision_changed"),
                                         (None, "live_source_revision_unverified"),
                                         ("", "live_source_revision_unverified")])
def test_stale_or_missing_head_refuses(live, reason):
    assert reason in assess_hopping_candidate(nominated(), live_revision=live)["blockers"]


@pytest.mark.parametrize("field,value,reason", [
    ("candidate_tree_sha256", "bad", "missing_candidate_tree_sha256"),
    ("postcondition_verified", "true", "campaign_postcondition_unverified"),
    ("receipt_contradicts_request", None, "campaign_request_binding_unverified"),
    ("budget_equality", {}, "budget_equality_unverified"),
    ("evaluation_mode", "exact-match", "exact_match_is_not_behavioral_evaluation"),
    ("outcome", "failed", "candidate_not_nominated"),
])
def test_missing_or_weak_evidence_is_explicit(field, value, reason):
    result = assess_hopping_candidate({**nominated(), field: value}, live_revision="d" * 40)
    assert result["activation_permitted"] is False and reason in result["blockers"]
