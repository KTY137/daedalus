from __future__ import annotations

import dataclasses
import json

import pytest

from daedalus.twin.ablations import AblationResult, FourPlaneAblationError, FourPlaneAblationReport

VARIANTS = (
    "code-only",
    "four-separate-indices",
    "full-four-plane",
    "without-code",
    "without-data",
    "without-knowledge",
    "without-type",
)


def report(*, full_score: float = 0.80, full_cost: float = 10.0, without_data: float = 0.70):
    scores = {
        "code-only": 0.70,
        "four-separate-indices": 0.72,
        "full-four-plane": full_score,
        "without-code": 0.68,
        "without-data": without_data,
        "without-knowledge": 0.69,
        "without-type": 0.71,
    }
    costs = {variant: 10.0 for variant in VARIANTS}
    costs["full-four-plane"] = full_cost
    return FourPlaneAblationReport(
        schema="daedalus-four-plane-ablation-report/1",
        project_twin_manifest_sha256="1" * 64,
        evaluator_contract_sha256="2" * 64,
        task_set_sha256="3" * 64,
        budget_contract_sha256="4" * 64,
        seed_policy_sha256="5" * 64,
        metric_id="held-out-retrieval-success",
        minimum_margin=0.05,
        results=tuple(
            AblationResult(
                variant=variant,
                quality_score=scores[variant],
                cost_units=costs[variant],
                successful_tasks=int(scores[variant] * 100),
                total_tasks=100,
                evidence_sha256=hex(index + 6)[2:] * 64,
            )
            for index, variant in enumerate(VARIANTS)
        ),
    )


def test_complete_budget_equal_positive_ablation_round_trips() -> None:
    value = report()
    assert value.closed_for_gate2
    assert value.blockers == ()
    assert FourPlaneAblationReport.from_json_bytes(value.to_json_bytes()) == value


def test_full_representation_must_beat_simpler_controls_by_margin() -> None:
    value = report(full_score=0.75)
    assert value.blockers == ("full-representation-does-not-beat-simpler-control",)


def test_full_representation_must_not_exceed_control_budget() -> None:
    value = report(full_cost=10.1)
    assert value.blockers == ("full-representation-exceeds-control-budget",)


def test_each_plane_must_have_positive_marginal_contribution() -> None:
    value = report(without_data=0.80)
    assert value.blockers == ("plane-data-has-no-positive-marginal-contribution",)


def test_missing_reordered_or_mismatched_task_variants_refuse() -> None:
    value = report()
    with pytest.raises(FourPlaneAblationError, match="every required variant"):
        dataclasses.replace(value, results=value.results[:-1])
    with pytest.raises(FourPlaneAblationError, match="canonical order"):
        dataclasses.replace(value, results=tuple(reversed(value.results)))
    changed = dataclasses.replace(value.results[0], total_tasks=99)
    with pytest.raises(FourPlaneAblationError, match="same task count"):
        dataclasses.replace(value, results=(changed,) + value.results[1:])


def test_nonfinite_out_of_range_and_fabricated_blockers_refuse() -> None:
    with pytest.raises(FourPlaneAblationError, match="finite"):
        dataclasses.replace(report().results[0], quality_score=float("nan"))
    with pytest.raises(FourPlaneAblationError, match="between zero and one"):
        dataclasses.replace(report().results[0], quality_score=1.1)
    payload = report().to_dict()
    payload["blockers"] = ["fabricated"]
    with pytest.raises(FourPlaneAblationError, match="mechanically derived"):
        FourPlaneAblationReport.from_dict(payload)


def test_noncanonical_json_refuses() -> None:
    value = report()
    pretty = (json.dumps(value.to_dict(), indent=2, sort_keys=True) + "\n").encode()
    with pytest.raises(FourPlaneAblationError, match="canonical JSON"):
        FourPlaneAblationReport.from_json_bytes(pretty)
