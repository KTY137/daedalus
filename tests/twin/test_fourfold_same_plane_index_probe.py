from __future__ import annotations

import json
import os
import sys
import warnings

import pytest

from experiments.tensor_gpu.fourfold_same_plane_index_probe import (
    ProjectionCase,
    run_probe,
)


def test_same_plane_probe_preserves_canonical_projection_and_error_surface() -> None:
    designated = sys.version_info[:2] == (3, 12) and os.environ.get("PYTHONHASHSEED") == "0"
    cases = (
        tuple(
            ProjectionCase(size, float(density), 11, 3)
            for size in (64, 128, 256)
            for density in (0.01, 0.05)
        )
        if designated
        else (ProjectionCase(size=8, density=0.25, pairs=1, warmup=0),)
    )
    result = run_probe(cases)

    assert result["status"] == "completed"
    assert result["claim"] == "none"
    assert result["semantic_case_count"] == 6
    assert result["semantic_mismatches"] == 0
    assert all(case["status"] == "verified" for case in result["cases"])
    assert all(case["candidate_to_baseline_ratio"] > 0.0 for case in result["cases"])

    if designated:
        evidence = {
            "runtime": result["runtime"],
            "semantic_case_count": result["semantic_case_count"],
            "semantic_mismatches": result["semantic_mismatches"],
            "semantic_cases": [
                {
                    "name": case["name"],
                    "outcome": case["outcome"],
                    "message": case["message"],
                }
                for case in result["semantic_cases"]
            ],
            "cases": [
                {
                    "size": case["case"]["size"],
                    "density": case["case"]["requested_density"],
                    "edges": case["case"]["edge_count"],
                    "baseline_median_ms": case["baseline_ms"]["median"],
                    "candidate_median_ms": case["candidate_ms"]["median"],
                    "ratio": case["candidate_to_baseline_ratio"],
                }
                for case in result["cases"]
            ],
        }
        warnings.warn(
            "GPU35_EVIDENCE=" + json.dumps(evidence, sort_keys=True, allow_nan=False),
            RuntimeWarning,
            stacklevel=1,
        )


def test_same_plane_probe_rejects_unbounded_or_empty_case_sets() -> None:
    with pytest.raises(ValueError, match="non-empty bounded sequence"):
        run_probe(())
    with pytest.raises(ValueError, match="at most 8"):
        run_probe(tuple(ProjectionCase(2, 0.5, 1, 0) for _ in range(9)))


@pytest.mark.parametrize(
    "kwargs",
    (
        {"size": 1, "density": 0.5, "pairs": 1, "warmup": 0},
        {"size": 8, "density": 0.0, "pairs": 1, "warmup": 0},
        {"size": 8, "density": 0.5, "pairs": 0, "warmup": 0},
        {"size": 8, "density": 0.5, "pairs": 1, "warmup": 8},
    ),
)
def test_same_plane_probe_bounds_are_fail_closed(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        ProjectionCase(**kwargs)  # type: ignore[arg-type]
