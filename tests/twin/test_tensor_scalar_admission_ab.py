from __future__ import annotations

import math

import pytest

from daedalus.twin.semiring import EvidenceValue
from experiments.tensor_gpu import scalar_admission_ab as ab


@pytest.mark.parametrize(
    ("semiring", "values"),
    (
        ("boolean", (True, True)),
        ("natural", (1, 2, 3)),
        ("tropical", (1, -0.0, 2.5)),
        (
            "evidence-dag",
            (EvidenceValue.atom("a" * 64), EvidenceValue.atom("b" * 64)),
        ),
    ),
)
def test_candidate_matches_current_admission_values(
    semiring: str,
    values: tuple[object, ...],
) -> None:
    assert ab.semantic_parity(values, semiring)
    current = ab._current_stored_values(values, semiring)
    candidate = ab._candidate_stored_values(values, semiring)
    assert candidate == current
    if semiring != "tropical":
        assert candidate is values
    else:
        assert math.copysign(1.0, candidate[1]) == 1.0


@pytest.mark.parametrize(
    ("semiring", "values"),
    (
        ("boolean", (True, False, "bad")),
        ("boolean", (True, 1)),
        ("natural", (1, 0, "bad")),
        ("natural", (1, -1)),
        ("natural", (1, 1 << 4096)),
        ("tropical", (1.0, float("inf"))),
        ("tropical", (1.0, -1.0)),
        ("evidence-dag", (EvidenceValue.atom("a" * 64), "bad")),
        ("unknown", (True,)),
    ),
)
def test_candidate_matches_current_first_error(
    semiring: str,
    values: tuple[object, ...],
) -> None:
    assert ab.semantic_parity(values, semiring)


def test_candidate_matches_current_list_materialization() -> None:
    values = [True, True, True]
    current = ab._current_stored_values(values, "boolean")
    candidate = ab._candidate_stored_values(values, "boolean")

    assert candidate == current == (True, True, True)
    assert type(candidate) is tuple


def test_paired_boolean_probe_uses_exact_packed_fixture_and_mints_no_claim() -> None:
    case = ab.ProbeCase(
        size=8,
        density=0.25,
        repeats=3,
        warmup=1,
        max_device_mib=64,
    )
    report = ab.run_probe((case,))

    assert report["schema"] == "daedalus-tensor-scalar-admission-ab/2"
    assert report["status"] == "completed"
    assert report["authority"] == "diagnostic-only"
    assert report["claim"] == "none"
    assert report["gpu22_semantic_evidence"]["experiment_head"] == ab.GPU22_EXPERIMENT_HEAD
    assert report["gpu22_semantic_evidence"]["candidate_blob"] == ab.GPU22_EXPERIMENT_BLOB
    assert "paired alternating AB/BA" in report["measurement_contract"]
    assert "No product code" in report["measurement_contract"]

    result = report["cases"][0]
    assert result["status"] == "verified"
    assert result["claim"] == "none"
    assert result["case"]["size"] == 8
    assert result["case"]["density"] == 0.25
    assert result["entries"] > 0
    assert result["control"]["timing_ms"]["samples"] == 3
    assert result["candidate"]["timing_ms"]["samples"] == 3
    assert result["control"]["timing_ms"]["median"] >= 0.0
    assert result["candidate"]["timing_ms"]["median"] >= 0.0
    ratio = result["candidate_to_control_ratio"]
    assert ratio is None or ratio >= 0.0
    assert "paired AB/BA microstage" in result["interpretation"]
    assert "not a constructor-wide" in result["interpretation"]


def test_paired_measurement_returns_identical_sample_counts() -> None:
    values = (True,) * 32
    control, candidate = ab._measure_paired(
        lambda: ab._current_stored_values(values, "boolean"),
        lambda: ab._candidate_stored_values(values, "boolean"),
        repeats=4,
        warmup=2,
    )

    assert control["samples"] == candidate["samples"] == 4
    assert control["median"] >= 0.0
    assert candidate["median"] >= 0.0


@pytest.mark.parametrize(
    ("repeats", "warmup"),
    (
        (0, 0),
        (ab.MAX_REPEATS + 1, 0),
        (True, 0),
        (1, -1),
        (1, ab.MAX_WARMUP + 1),
        (1, True),
    ),
)
def test_timing_bounds_are_strict(repeats: int, warmup: int) -> None:
    with pytest.raises(ValueError):
        ab._validate_timing_bounds(repeats, warmup)


def test_probe_bounds_case_collection() -> None:
    case = ab.ProbeCase(
        size=8,
        density=0.25,
        repeats=1,
        warmup=0,
        max_device_mib=64,
    )
    for cases in ((), (case,) * (ab.MAX_CASES + 1)):
        with pytest.raises(ValueError, match="cases must contain"):
            ab.run_probe(cases)
