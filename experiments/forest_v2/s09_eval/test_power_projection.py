"""Pin the supply ceiling, so nobody re-derives it or quietly contradicts it.

These are cheap structural assertions over retained artifacts, not a re-run of
the harness. They exist because
``docs/GATE2_CROSS_PLANE_SUPPLY_CEILING_20260909.md`` makes a load-bearing
claim -- that Gate 2's two reachable criteria are undecidable on this
repository by two orders of magnitude -- and a claim that large should fail
loudly when its inputs move.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from experiments.forest_v2.s09_eval import power_projection as subject

TASKSET = json.loads(subject.DEFAULT_TASKSET.read_text(encoding="utf-8"))
KILL_INPUT = json.loads(subject.DEFAULT_INPUT.read_text(encoding="utf-8"))


def test_cross_plane_supply_is_exhausted():
    """The whole argument rests on this: there is nothing left to sample."""
    supply = TASKSET["census"]["supply"]
    assert supply["cross_plane_admissible"] == 58
    assert supply["cross_plane_accepted"] == 58
    assert supply["cross_plane_unused"] == 0


def test_the_unsampled_remainder_holds_no_cross_plane_case():
    """678 commits are admissible and unsampled -- every one single-plane.

    If a future rule change moves cross-plane cases into that pool, the ceiling
    argument is wrong and this test is where that should surface.
    """
    census = TASKSET["census"]
    assert census["commits_admissible_but_not_sampled"] == 678
    not_sampled = census["not_sampled"]
    assert set(not_sampled) == {
        "single_plane_below_control_min_gold",
        "single_plane_beyond_control_quota",
    }
    assert sum(v["count"] for v in not_sampled.values()) == 678


def test_the_census_arithmetic_closes():
    census = TASKSET["census"]
    assert census["buckets_sum_to_considered"] is True
    assert (
        census["commits_accepted"]
        + census["commits_admissible_but_not_sampled"]
        + census["commits_rejected_by_rule"]
        == census["commits_considered"]
    )
    assert census["commits_considered"] == 1457
    assert census["commits_admissible"] == 766


@pytest.mark.parametrize(
    "criterion, subject_arm, reference_arm, low, high",
    [
        ("14.1", "fusion_rrf/raw#full", "code_only_bm25/raw#code_only", 0.010, 0.014),
        ("14.1", "fusion_rrf/raw#full", "bm25/raw", 0.008, 0.012),
        (
            "14.3",
            "fusion_rrf/raw#fusion",
            "separate_indices_bm25/raw#separate_indices",
            0.009,
            0.013,
        ),
    ],
)
def test_every_projected_effect_is_smaller_than_the_equivalence_margin(
    criterion, subject_arm, reference_arm, low, high
):
    """The effects are ~0.01 against a +/-0.02 margin.

    Bounded rather than pinned to four decimals: the point estimate is a plain
    mean over retained per-case scores, so it is exact, but pinning it exactly
    would make this test about float formatting instead of about the finding.
    """
    s = subject._scores(KILL_INPUT, subject_arm)
    r = subject._scores(KILL_INPUT, reference_arm)
    cases = KILL_INPUT["cases"]
    point = sum(s[c] - r[c] for c in cases) / len(cases)
    assert low < point < high, (criterion, point)
    assert point < 0.02, "an effect above the margin would change the argument"


def test_fusion_loses_more_cases_than_it_wins():
    """The mean is positive; the case count is not. Keep both visible."""
    cases = KILL_INPUT["cases"]
    s = subject._scores(KILL_INPUT, "fusion_rrf/raw#full")
    r = subject._scores(KILL_INPUT, "code_only_bm25/raw#code_only")
    wins = sum(1 for c in cases if s[c] > r[c])
    losses = sum(1 for c in cases if s[c] < r[c])
    assert (wins, losses) == (29, 38)


def test_decisive_n_is_two_orders_of_magnitude_above_supply():
    """The headline, computed rather than asserted."""
    n0 = len(KILL_INPUT["cases"])
    assert n0 == 88
    # a half-width of ~0.094 against an effect of ~0.012
    n_needed = subject._n_for_halfwidth(n0, 0.0938, 0.0118)
    assert 5_000 < n_needed < 6_500
    assert n_needed / TASKSET["census"]["supply"]["cross_plane_admissible"] > 80


def test_the_type_plane_carries_no_gold_label():
    """Why 14.4 is NOT_EVALUABLE, and why that one is NOT a sample-size problem."""
    composition = TASKSET["plane_composition"]
    by_combination = composition["cases_by_plane_combination"]
    assert not any("type" in key for key in by_combination), by_combination
