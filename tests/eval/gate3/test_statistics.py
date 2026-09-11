"""Tests for the Gate-3 statistical-reporting freeze obligation (packet
G3-BASE-01, measure D6: ``test_variance_reported_with_interval``).

Deterministic, offline, no network, no model calls. ``TrialResult`` fixtures
are built directly, matching the fixture style already used by
``tests/eval/gate3/test_arm_bm25.py``.
"""
from __future__ import annotations

import dataclasses
import math

import pytest

from daedalus.eval.gate3.contracts import FreezeError, TrialResult
from daedalus.eval.gate3.statistics import (
    ArmComparison,
    SummaryStats,
    compare_arms,
    summarize,
    variance_across_seeds,
)


def _trial(arm: str, task_id: str, seed: int, score: float | None = None,
           error: str | None = None) -> TrialResult:
    if error is not None:
        return TrialResult(
            arm=arm, task_id=task_id, seed=seed, wall_seconds=0.01,
            tokens_used=0, calls=0, error=error,
        )
    return TrialResult(
        arm=arm, task_id=task_id, seed=seed, wall_seconds=0.01,
        tokens_used=10, calls=1, success=True, score=score,
    )


# --------------------------------------------------------------------------- #
# summarize(): known-answer test                                              #
# --------------------------------------------------------------------------- #
def test_summarize_known_answer() -> None:
    """Classic textbook example (Wikipedia "Standard deviation"):
    values = [2, 4, 4, 4, 5, 5, 7, 9], n=8, mean=5,
    sample variance (ddof=1) = 32/7, sample stdev = sqrt(32/7).
    """
    values = [2, 4, 4, 4, 5, 5, 7, 9]
    result = summarize(values)

    assert result.n == 8
    assert result.mean == pytest.approx(5.0)
    assert result.stdev == pytest.approx(math.sqrt(32 / 7), rel=1e-9)

    # df=7 -> exact t-table lookup, t_{0.025,7} = 2.365
    expected_half_width = 2.365 * result.stdev / math.sqrt(8)
    assert result.ci_high - result.mean == pytest.approx(expected_half_width, rel=1e-6)
    assert result.mean - result.ci_low == pytest.approx(expected_half_width, rel=1e-6)
    assert "exact table" in result.interval_method
    assert "df=7" in result.interval_method
    assert result.confidence == 0.95


def test_summarize_zero_variance_is_a_real_zero_width_interval() -> None:
    """All-identical values -> stdev=0 -> a genuine zero-width interval. This
    is different from the n=1 refusal: here variance really was measured and
    really is zero."""
    result = summarize([3.0, 3.0, 3.0, 3.0])
    assert result.stdev == 0.0
    assert result.ci_low == result.ci_high == pytest.approx(3.0)


# --------------------------------------------------------------------------- #
# THE refusal: n=1 must never silently become 0.0                            #
# --------------------------------------------------------------------------- #
def test_summarize_refuses_single_sample() -> None:
    with pytest.raises(FreezeError, match="n=1"):
        summarize([0.7])


def test_summarize_refuses_single_sample_never_returns_zero() -> None:
    """Explicit negative assertion: whatever summarize() does on n=1, it must
    not be possible to read off a SummaryStats with stdev/interval == 0.0 as
    if it were a measured result."""
    with pytest.raises(FreezeError):
        result = summarize([42.0])
        # unreachable, but pin the intent: if this line ever runs, the
        # refusal above was removed and this test must still fail loudly.
        assert result.stdev != 0.0  # pragma: no cover


def test_summarize_refuses_empty_sample() -> None:
    with pytest.raises(FreezeError):
        summarize([])


def test_summarize_refuses_non_finite_values() -> None:
    with pytest.raises(FreezeError):
        summarize([1.0, float("nan"), 2.0])
    with pytest.raises(FreezeError):
        summarize([1.0, float("inf"), 2.0])


# --------------------------------------------------------------------------- #
# interval widens as n shrinks                                                #
# --------------------------------------------------------------------------- #
def test_interval_widens_as_n_shrinks() -> None:
    """Same underlying pattern repeated fewer times -> fewer seeds -> a wider
    (or at least not narrower) 95% interval. Uses n=10 vs n=5 to sit inside
    plan §14's 5-10 seed regime, where every df here hits the exact t-table."""
    base = [1.0, 2.0, 3.0, 4.0, 5.0]
    small = summarize(base)               # n=5
    large = summarize(base + base)        # n=10, same generating pattern

    assert small.n == 5
    assert large.n == 10
    assert small.half_width > large.half_width, (
        "a 95% interval built from fewer seeds must not be narrower than "
        "one built from more seeds of the same underlying spread")


def test_interval_widens_monotonically_across_several_sizes() -> None:
    pattern = [10.0, 12.0, 9.0, 11.0, 10.0]
    widths = []
    for repeats in (1, 2, 3, 4):
        values = pattern * repeats
        widths.append(summarize(values).half_width)
    for narrower, wider in zip(widths[1:], widths[:-1]):
        assert narrower <= wider


# --------------------------------------------------------------------------- #
# variance_across_seeds(): D6                                                 #
# --------------------------------------------------------------------------- #
def test_variance_reported_with_interval() -> None:
    """D6. One arm, one task, five seeds (plan §14 floor) -> a per-task
    SummaryStats with a real interval, not a placeholder."""
    trials = [
        _trial("arm-x", "task-1", seed, score=score)
        for seed, score in enumerate([0.6, 0.8, 0.7, 0.9, 0.5])
    ]
    report = variance_across_seeds(trials)

    assert report.arm == "arm-x"
    assert report.n_tasks == 1
    assert report.n_tasks_with_interval == 1
    assert report.n_tasks_insufficient == 0

    row = report.per_task[0]
    assert row.task_id == "task-1"
    assert row.n_seeds_measured == 5
    assert row.n_seeds_errored == 0
    assert isinstance(row.stats, SummaryStats)
    assert row.stats.n == 5
    assert row.stats.ci_low < row.stats.mean < row.stats.ci_high


def test_variance_across_seeds_groups_multiple_tasks_independently() -> None:
    trials = (
        [_trial("arm-x", "task-1", s, score=v)
         for s, v in enumerate([0.1, 0.2, 0.3, 0.2, 0.1])]
        + [_trial("arm-x", "task-2", s, score=v)
           for s, v in enumerate([0.9, 0.9, 0.9, 0.9, 0.9])]
    )
    report = variance_across_seeds(trials)
    assert report.n_tasks == 2
    by_id = {row.task_id: row for row in report.per_task}
    assert by_id["task-1"].stats.mean == pytest.approx(0.18)
    assert by_id["task-2"].stats.stdev == 0.0  # real, measured zero variance


def test_variance_across_seeds_refuses_mixed_arms() -> None:
    trials = [
        _trial("arm-x", "task-1", 0, score=0.5),
        _trial("arm-y", "task-1", 1, score=0.6),
    ]
    with pytest.raises(FreezeError, match="multiple arms"):
        variance_across_seeds(trials)


def test_variance_across_seeds_refuses_no_trials() -> None:
    with pytest.raises(FreezeError):
        variance_across_seeds([])


# --------------------------------------------------------------------------- #
# errored trials: excluded from stats, count still reported                   #
# --------------------------------------------------------------------------- #
def test_errored_trials_excluded_but_counted() -> None:
    trials = [
        _trial("arm-x", "task-1", 0, score=0.5),
        _trial("arm-x", "task-1", 1, score=0.7),
        _trial("arm-x", "task-1", 2, score=0.6),
        _trial("arm-x", "task-1", 3, error="RuntimeError: boom"),
        _trial("arm-x", "task-1", 4, error="TimeoutError: exceeded budget"),
    ]
    report = variance_across_seeds(trials)
    row = report.per_task[0]

    assert row.n_seeds_measured == 3
    assert row.n_seeds_errored == 2
    assert row.stats is not None
    assert row.stats.n == 3
    # the errored trials must not silently become a 0.0 that would drag the
    # mean down or otherwise appear in the statistic
    assert row.stats.mean == pytest.approx((0.5 + 0.7 + 0.6) / 3)


def test_task_with_fewer_than_two_scored_seeds_is_explicitly_undefined() -> None:
    """A task with only one measured-with-score seed gets an explicit
    ``stats=None`` + reason, never a fabricated zero-width interval."""
    trials = [
        _trial("arm-x", "task-1", 0, score=0.5),
        _trial("arm-x", "task-1", 1, error="RuntimeError: boom"),
    ]
    report = variance_across_seeds(trials)
    row = report.per_task[0]

    assert row.n_seeds_measured == 1
    assert row.n_seeds_errored == 1
    assert row.stats is None
    assert row.insufficient_reason is not None
    assert report.n_tasks_insufficient == 1
    assert report.n_tasks_with_interval == 0


def test_task_with_zero_scored_seeds_is_explicitly_undefined_not_dropped() -> None:
    trials = [
        _trial("arm-x", "task-1", 0, error="RuntimeError: a"),
        _trial("arm-x", "task-1", 1, error="RuntimeError: b"),
    ]
    report = variance_across_seeds(trials)
    assert report.n_tasks == 1  # the task is still reported, not dropped
    row = report.per_task[0]
    assert row.n_seeds_measured == 0
    assert row.n_seeds_errored == 2
    assert row.stats is None


# --------------------------------------------------------------------------- #
# compare_arms(): difference + interval, never a p-value/"significant"        #
# --------------------------------------------------------------------------- #
def test_compare_arms_never_emits_pvalue_or_significance_language() -> None:
    trials_a = [_trial("arm-a", "t", s, score=v)
                for s, v in enumerate([0.9, 0.85, 0.95, 0.9, 0.88])]
    trials_b = [_trial("arm-b", "t", s, score=v)
                for s, v in enumerate([0.2, 0.25, 0.15, 0.22, 0.18])]

    result = compare_arms(trials_a, trials_b)

    field_names = {f.name for f in dataclasses.fields(result)}
    assert "p_value" not in field_names
    assert "pvalue" not in field_names
    assert not any("signif" in name.lower() for name in field_names)

    rendered = " ".join(str(getattr(result, f.name)) for f in dataclasses.fields(result))
    assert "significant" not in rendered.lower()
    assert "p_value" not in rendered.lower()


def test_compare_arms_separable_when_intervals_clearly_apart() -> None:
    trials_a = [_trial("arm-a", "t", s, score=v)
                for s, v in enumerate([0.95, 0.94, 0.96, 0.95, 0.93])]
    trials_b = [_trial("arm-b", "t", s, score=v)
                for s, v in enumerate([0.10, 0.12, 0.09, 0.11, 0.13])]

    result = compare_arms(trials_a, trials_b)

    assert isinstance(result, ArmComparison)
    assert result.separable is True
    assert result.diff == pytest.approx(result.mean_a - result.mean_b)
    assert result.diff_ci_low > 0.0  # whole difference interval is positive


def test_compare_arms_not_separable_when_intervals_overlap() -> None:
    trials_a = [_trial("arm-a", "t", s, score=v)
                for s, v in enumerate([0.50, 0.52, 0.48, 0.51, 0.49])]
    trials_b = [_trial("arm-b", "t", s, score=v)
                for s, v in enumerate([0.51, 0.49, 0.53, 0.50, 0.52])]

    result = compare_arms(trials_a, trials_b)

    assert result.separable is False
    assert result.diff_ci_low <= 0.0 <= result.diff_ci_high


def test_compare_arms_refuses_single_sample_side() -> None:
    trials_a = [_trial("arm-a", "t", 0, score=0.9)]
    trials_b = [_trial("arm-b", "t", s, score=v)
                for s, v in enumerate([0.1, 0.2, 0.15, 0.18, 0.12])]
    with pytest.raises(FreezeError):
        compare_arms(trials_a, trials_b)


def test_compare_arms_refuses_same_arm_both_sides() -> None:
    trials_a = [_trial("arm-a", "t", s, score=v)
                for s, v in enumerate([0.5, 0.6, 0.55, 0.58, 0.52])]
    trials_b = [_trial("arm-a", "t2", s, score=v)
                for s, v in enumerate([0.4, 0.45, 0.42, 0.48, 0.41])]
    with pytest.raises(FreezeError, match="same arm"):
        compare_arms(trials_a, trials_b)


def test_compare_arms_refuses_mixed_arm_on_one_side() -> None:
    trials_a = [
        _trial("arm-a", "t", 0, score=0.5),
        _trial("arm-a2", "t", 1, score=0.6),
    ]
    trials_b = [_trial("arm-b", "t", s, score=v)
                for s, v in enumerate([0.1, 0.2, 0.15, 0.18, 0.12])]
    with pytest.raises(FreezeError, match="multiple arms"):
        compare_arms(trials_a, trials_b)
