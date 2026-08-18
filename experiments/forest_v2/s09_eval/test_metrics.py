"""Tests for the scoring rules, including the ones that are easy to fudge."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from s09_eval import metrics  # noqa: E402

CUTOFFS = (1, 5, 10, 20)


def test_score_case_counts_hits_per_cutoff():
    ranking = ["a", "b", "c", "d", "e", "f"]
    score = metrics.score_case("c00", ranking, ["c", "f"], CUTOFFS)
    assert score.hits_at == {1: 0, 5: 1, 10: 2, 20: 2}
    assert score.first_hit_rank == 3
    assert score.reciprocal_rank == 1 / 3
    assert score.recall_at(10) == 1.0


def test_a_miss_scores_zero_not_a_tail_value():
    score = metrics.score_case("c00", ["x", "y"], ["z"], CUTOFFS)
    assert score.first_hit_rank is None
    assert score.reciprocal_rank == 0.0
    assert score.hits_at == {1: 0, 5: 0, 10: 0, 20: 0}


def test_reciprocal_rank_is_bounded_by_the_measured_window():
    """A hit past max_k was never actually looked at; it must not score."""
    ranking = [f"f{i}" for i in range(30)]
    score = metrics.score_case("c00", ranking, ["f25"], CUTOFFS)
    assert score.first_hit_rank == 26
    assert score.reciprocal_rank == 0.0


def test_macro_and_micro_recall_differ_when_cases_differ_in_size():
    """The whole reason both are reported: they disagree, and the gap matters."""
    big = metrics.score_case("big", ["a"], ["a", "b", "c", "d"], CUTOFFS)
    small = metrics.score_case("small", ["z"], ["z"], CUTOFFS)
    agg = metrics.aggregate("t", "raw", [big, small], CUTOFFS)

    assert agg.gold_total == 5
    assert agg.hits_at[20] == 2
    # macro: (0.25 + 1.0) / 2
    assert abs(agg.macro_recall_at[20] - 0.625) < 1e-9
    # micro: 2 of 5 pooled gold paths
    assert abs(agg.micro_recall_at[20] - 0.4) < 1e-9
    assert agg.macro_recall_at[20] != agg.micro_recall_at[20]


def test_aggregate_reports_hit_cases_and_median_rank():
    scores = [
        metrics.score_case("c0", ["a"], ["a"], CUTOFFS),
        metrics.score_case("c1", ["x", "y", "b"], ["b"], CUTOFFS),
        metrics.score_case("c2", ["n"], ["gone"], CUTOFFS),
    ]
    agg = metrics.aggregate("t", "raw", scores, CUTOFFS)
    assert agg.cases == 3
    assert agg.cases_with_any_hit == 2
    assert agg.median_first_hit_rank == 2  # ranks 1 and 3, missing case excluded
    assert abs(agg.mrr - (1.0 + 1 / 3 + 0.0) / 3) < 1e-9


def test_empty_aggregate_does_not_divide_by_zero():
    agg = metrics.aggregate("t", "raw", [], CUTOFFS)
    assert agg.mrr == 0.0 and agg.macro_recall_at[1] == 0.0
    assert agg.median_first_hit_rank is None


def test_raw_table_shows_counts_before_ratios():
    agg = metrics.aggregate(
        "t", "raw", [metrics.score_case("c0", ["a"], ["a"], CUTOFFS)], CUTOFFS
    )
    table = metrics.raw_table([agg], CUTOFFS)
    assert "hits/gold" in table
    assert "1/1" in table
    assert table.count("\n") == 2  # header, rule, one row
