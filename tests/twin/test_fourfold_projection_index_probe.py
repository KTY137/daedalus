from __future__ import annotations

import pytest

from experiments.tensor_gpu.fourfold_projection_index_probe import (
    ProjectionCase,
    run_case,
    run_probe,
)


def test_probe_preserves_canonical_projection_on_small_valid_fixture() -> None:
    result = run_case(ProjectionCase(size=8, density=0.25, pairs=1, warmup=0))

    assert result["status"] == "verified"
    assert result["claim"] == "none"
    assert result["case"]["binding_count"] == 16
    assert result["candidate_to_baseline_ratio"] > 0.0


def test_probe_rejects_unbounded_or_empty_case_sets() -> None:
    with pytest.raises(ValueError, match="non-empty bounded sequence"):
        run_probe(())
    with pytest.raises(ValueError, match="at most 8"):
        run_probe(tuple(ProjectionCase(2, 0.5, 1, 0) for _ in range(9)))


@pytest.mark.parametrize(
    "kwargs",
    (
        {"size": 0, "density": 0.5, "pairs": 1, "warmup": 0},
        {"size": 8, "density": 0.0, "pairs": 1, "warmup": 0},
        {"size": 8, "density": 0.5, "pairs": 0, "warmup": 0},
        {"size": 8, "density": 0.5, "pairs": 1, "warmup": 8},
    ),
)
def test_probe_bounds_are_fail_closed(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        ProjectionCase(**kwargs)  # type: ignore[arg-type]
