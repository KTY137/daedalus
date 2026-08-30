from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOPOLOGY = ROOT / "docs" / "recovery" / "GARDENER_BRANCH_TOPOLOGY_20260830.json"
ALLOWED = {
    "active_candidate",
    "required_dependency",
    "contained_evidence",
    "historical_evidence",
    "experiment",
    "superseded",
    "unknown",
}
FORBIDDEN_ACTIONS = {
    "merge",
    "rebase",
    "force-update",
    "branch deletion",
    "PR closure",
    "OwnerApproval issuance",
    "promotion",
    "Gate transition",
}


def _load() -> dict:
    value = json.loads(TOPOLOGY.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_checkpoint_is_revision_bound_and_non_authorizing() -> None:
    report = _load()
    authority = report["authority"]
    assert report["schema"] == "daedalus-gardener-branch-topology/1"
    assert report["observed_date_europe_berlin"] == "2026-08-30"
    assert authority["master_plan_revision"] == 8
    assert authority["master_plan_version"] == "1.3.0"
    assert authority["main_head"] == "24c2f1ecbaac0244a121b08f13d0f4ba623f7bf2"
    assert report["scope"]["local_worktrees"]["classification"] == "unknown"
    assert set(report["actions_not_performed"]) == FORBIDDEN_ACTIONS


def test_each_observed_pr_has_one_allowed_classification_and_unique_number() -> None:
    report = _load()
    observations = report["observations"]
    numbers = [row["pr"] for row in observations]
    assert len(numbers) == len(set(numbers))
    for row in observations:
        assert row["classification"] in ALLOWED
        assert row["branch"]
        assert row["head"]
        assert row["reason"]


def test_measured_git_relations_are_complete_and_non_negative() -> None:
    report = _load()
    measured = 0
    for row in report["observations"]:
        for key in ("git_vs_main", "git_vs_pr229_head", "split_stack_observation"):
            relation = row.get(key)
            if not relation:
                continue
            measured += 1
            assert relation["status"] in {"ahead", "behind", "diverged", "identical"}
            assert type(relation["ahead"]) is int and relation["ahead"] >= 0
            assert type(relation["behind"]) is int and relation["behind"] >= 0
            assert len(relation["merge_base"]) == 40
    assert measured >= 8


def test_each_inspected_delivery_area_has_one_serialized_plan() -> None:
    report = _load()
    lines = report["proposed_canonical_lines"]
    areas = [row["area"] for row in lines]
    assert len(areas) == len(set(areas))
    assert {
        "loop-safety",
        "fourfold-production",
        "tensor-research",
        "tier2-evaluation",
        "benchmark-authority",
        "ikarus-runtime",
        "gardener-operations",
    } == set(areas)
    for row in lines:
        assert row["order"]
        assert row["action"]
        assert row["reason"]


def test_parallel_same_surface_repairs_are_explicitly_serialized() -> None:
    report = _load()
    lines = {row["area"]: row for row in report["proposed_canonical_lines"]}
    assert lines["loop-safety"]["order"] == ["main", "PR#258", "issue#250-follow-up"]
    assert lines["tier2-evaluation"]["order"] == ["main", "PR#260", "issue#268-follow-up"]
    assert lines["ikarus-runtime"]["order"] == [
        "main",
        "PR#257",
        "PR#259",
        "PR#263",
        "selective-port(PR#264)",
        "PR#266",
    ]


def test_experiments_are_not_promoted_into_production_line_by_the_report() -> None:
    report = _load()
    observations = {row["pr"]: row for row in report["observations"]}
    assert observations[255]["classification"] == "experiment"
    assert observations[262]["classification"] == "experiment"
    tensor = next(
        row for row in report["proposed_canonical_lines"] if row["area"] == "tensor-research"
    )
    assert tensor["action"] == "retain-isolated-evidence"


def _run_direct() -> None:
    tests = [
        test_checkpoint_is_revision_bound_and_non_authorizing,
        test_each_observed_pr_has_one_allowed_classification_and_unique_number,
        test_measured_git_relations_are_complete_and_non_negative,
        test_each_inspected_delivery_area_has_one_serialized_plan,
        test_parallel_same_surface_repairs_are_explicitly_serialized,
        test_experiments_are_not_promoted_into_production_line_by_the_report,
    ]
    for test in tests:
        test()
    print(f"{len(tests)} topology checks passed")


if __name__ == "__main__":
    _run_direct()
