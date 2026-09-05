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


def test_bounded_boolean_probe_executes_without_minting_claim() -> None:
    report = ab.run_boolean_probe(entries=256, repeats=3)

    assert report["schema"] == "daedalus-tensor-scalar-admission-ab/1"
    assert report["status"] == "verified"
    assert report["claim"] == "none"
    assert report["entries"] == 256
    assert report["repeats"] == 3
    assert report["current_ms_median"] >= 0.0
    assert report["candidate_ms_median"] >= 0.0
    ratio = report["candidate_to_current_ratio"]
    assert ratio is None or ratio >= 0.0
    assert "not a constructor-wide speedup claim" in report["interpretation"]


@pytest.mark.parametrize(
    ("entries", "repeats"),
    ((0, 1), (ab.MAX_VALUES + 1, 1), (1, 0), (1, ab.MAX_REPEATS + 1)),
)
def test_probe_bounds_are_strict(entries: int, repeats: int) -> None:
    with pytest.raises(ValueError):
        ab.run_boolean_probe(entries=entries, repeats=repeats)
