"""test_regressions.py -- acceptance tests D8 and D9 (G3-BASE-01 §5d).

Offline, no model calls, no filesystem/network dependency. Builds
``TrialResult`` fixtures directly rather than running a real arm, since these
two measures (regressions, human intervention) are pure aggregators over
already-produced trial rows.
"""
from __future__ import annotations

import pytest

from daedalus.eval.gate3.contracts import FreezeError, TrialResult
from daedalus.eval.gate3.regressions import (
    TRACKED_KEY,
    human_interventions,
    regressions,
)


def _measured(arm: str, task_id: str, score: float, **kw) -> TrialResult:
    return TrialResult(arm=arm, task_id=task_id, seed=kw.pop("seed", 1),
                        wall_seconds=0.01, tokens_used=10, calls=1,
                        success=score > 0, score=score, **kw)


def _errored(arm: str, task_id: str, error: str = "boom", **kw) -> TrialResult:
    return TrialResult(arm=arm, task_id=task_id, seed=kw.pop("seed", 1),
                        wall_seconds=0.01, tokens_used=0, calls=0,
                        error=error, **kw)


# --------------------------------------------------------------------------- #
# D8 -- regressions, per task, never on a mean                                #
# --------------------------------------------------------------------------- #
def test_regressions_per_task_not_mean():
    """THE headline test: task A drops 1.0 -> 0.5 while task B rises
    0.5 -> 1.0. The mean of both tasks is unchanged (0.75 both times), but
    regressions() MUST still report exactly one regression (task A) and one
    improvement (task B) -- a verdict computed per task, never via the mean."""
    baseline = [
        _measured("arm", "task_a", 1.0),
        _measured("arm", "task_b", 0.5),
    ]
    current = [
        _measured("arm", "task_a", 0.5),
        _measured("arm", "task_b", 1.0),
    ]
    # sanity: the mean genuinely did not move
    assert sum(t.score for t in baseline) / 2 == sum(t.score for t in current) / 2

    report = regressions(baseline, current)

    assert [r.task_id for r in report.regressed] == ["task_a"]
    assert report.regressed[0].delta == pytest.approx(-0.5)
    assert [r.task_id for r in report.improved] == ["task_b"]
    assert report.improved[0].delta == pytest.approx(0.5)
    assert not report.passed


def test_regressions_unchanged_reported_as_unchanged():
    baseline = [_measured("arm", "t1", 0.5)]
    current = [_measured("arm", "t1", 0.5)]
    report = regressions(baseline, current)
    assert [r.task_id for r in report.unchanged] == ["t1"]
    assert report.regressed == ()
    assert report.passed


def test_newly_errored_task_is_a_regression_not_dropped():
    """A task that scored in baseline but ERRORS now is a distinct kind of
    regression. It must appear in newly_errored, never silently vanish and
    never get folded into the plain `regressed` bucket (that bucket implies
    a comparable score delta, which an errored trial does not have)."""
    baseline = [_measured("arm", "t1", 1.0)]
    current = [_errored("arm", "t1", error="RuntimeError: crashed")]

    report = regressions(baseline, current)

    assert report.regressed == ()
    assert len(report.newly_errored) == 1
    row = report.newly_errored[0]
    assert row.task_id == "t1"
    assert row.baseline_score == 1.0
    assert row.current_error == "RuntimeError: crashed"
    assert row.current_score is None  # absent, never coerced to 0.0
    assert not report.passed  # a newly-errored task fails the verdict


def test_missing_task_is_reported():
    """A task present in baseline but absent from the current run must be
    reported, not silently ignored -- mirrors run_gate's `missing_tasks`."""
    baseline = [_measured("arm", "t1", 1.0), _measured("arm", "gone", 0.7)]
    current = [_measured("arm", "t1", 1.0)]

    report = regressions(baseline, current)

    assert [r.task_id for r in report.missing] == ["gone"]
    assert report.missing[0].baseline_score == 0.7
    assert report.missing[0].current_score is None


def test_new_task_not_in_baseline_is_reported_not_a_regression():
    baseline = [_measured("arm", "t1", 1.0)]
    current = [_measured("arm", "t1", 1.0), _measured("arm", "brand_new", 0.2)]

    report = regressions(baseline, current)

    assert [r.task_id for r in report.new] == ["brand_new"]
    assert report.regressed == () and report.improved == ()
    assert report.passed


def test_errored_trials_excluded_from_score_comparison_but_still_counted():
    """A task that ERRORED in BOTH runs has no score to compare -- it must be
    EXCLUDED from regressed/improved/unchanged (there is nothing to diff),
    but it must still show up somewhere in the report, never dropped."""
    baseline = [_errored("arm", "t1", error="timeout")]
    current = [_errored("arm", "t1", error="timeout again")]

    report = regressions(baseline, current)

    assert report.regressed == () and report.improved == () and report.unchanged == ()
    assert report.newly_errored == ()  # not "newly" -- it errored before too
    assert len(report.still_errored) == 1
    row = report.still_errored[0]
    assert row.baseline_error == "timeout"
    assert row.current_error == "timeout again"
    assert row.baseline_score is None and row.current_score is None


def test_recovery_from_error_to_measured_is_improvement():
    baseline = [_errored("arm", "t1", error="flaked")]
    current = [_measured("arm", "t1", 0.9)]

    report = regressions(baseline, current)

    assert len(report.improved) == 1
    assert report.improved[0].baseline_error == "flaked"
    assert report.improved[0].current_score == 0.9


def test_duplicate_task_id_in_one_run_is_refused():
    """regressions() compares exactly one row per task; a caller that hands
    it multiple seeds/arms collapsed into one sequence gets a loud refusal,
    not a silently-picked winner."""
    baseline = [_measured("arm", "t1", 1.0)]
    current = [_measured("arm", "t1", 1.0, seed=1), _measured("arm", "t1", 0.5, seed=2)]
    with pytest.raises(FreezeError):
        regressions(baseline, current)


def test_regressions_never_coerces_absent_score_to_zero():
    """Absent is ABSENT (packet binding rule). An errored trial's score field
    must stay None throughout -- never silently become 0.0, which would make
    a genuinely-scored 0.0 result indistinguishable from an unmeasured one."""
    baseline = [_measured("arm", "t1", 0.0)]  # a REAL, measured zero
    current = [_errored("arm", "t1")]

    report = regressions(baseline, current)

    assert report.newly_errored[0].baseline_score == 0.0  # real zero preserved
    assert report.newly_errored[0].current_score is None  # absent, not 0.0


# --------------------------------------------------------------------------- #
# D9 -- human intervention, measured, not assumed zero                        #
# --------------------------------------------------------------------------- #
def test_human_intervention_counted():
    """Sum and per-arm breakdown, AND the zero-recorded-vs-never-recorded
    distinction plan §11 requires: an arm that explicitly tracked
    interventions and measured zero must be distinguishable from an arm that
    never declared whether it tracks them at all (the s06 structural-zero
    defect)."""
    trials = [
        _measured("arm_tracks", "t1", 1.0, human_interventions=2,
                  notes={TRACKED_KEY: True}),
        _measured("arm_tracks", "t2", 1.0, human_interventions=1,
                  notes={TRACKED_KEY: True}),
        _measured("arm_zero_measured", "t1", 1.0, human_interventions=0,
                  notes={TRACKED_KEY: True}),
        _measured("arm_never_recorded", "t1", 1.0),  # no TRACKED_KEY at all
    ]

    report = human_interventions(trials)

    assert report.total == 3  # 2 + 1 + 0 + 0

    by_arm = {s.arm: s for s in report.by_arm}
    assert by_arm["arm_tracks"].total == 3
    assert by_arm["arm_tracks"].recorded is True
    assert by_arm["arm_tracks"].per_task == {"t1": 2, "t2": 1}

    # measured zero: explicitly tracked, genuinely zero
    assert by_arm["arm_zero_measured"].total == 0
    assert by_arm["arm_zero_measured"].recorded is True

    # never recorded: same field value (0) as above, but NOT a measurement
    assert by_arm["arm_never_recorded"].total == 0
    assert by_arm["arm_never_recorded"].recorded is False

    assert report.unrecorded_arms == ("arm_never_recorded",)
    # the two zero-total arms must remain distinguishable via `recorded`,
    # not conflated just because their totals are numerically identical
    assert by_arm["arm_zero_measured"].total == by_arm["arm_never_recorded"].total
    assert by_arm["arm_zero_measured"].recorded != by_arm["arm_never_recorded"].recorded


def test_human_intervention_sums_across_errored_trials_too():
    """An intervention that happened before a trial errored still happened;
    it must be counted, not dropped because the trial ultimately errored."""
    trials = [
        _errored("arm", "t1", human_interventions=3, notes={TRACKED_KEY: True}),
        _measured("arm", "t2", 1.0, human_interventions=1, notes={TRACKED_KEY: True}),
    ]
    report = human_interventions(trials)
    assert report.total == 4
    assert report.by_arm[0].per_task == {"t1": 3, "t2": 1}


def test_human_intervention_rejects_empty_input():
    with pytest.raises(FreezeError):
        human_interventions([])


def test_human_intervention_multi_arm_breakdown_sorted_by_arm():
    trials = [
        _measured("zzz_arm", "t1", 1.0, human_interventions=1, notes={TRACKED_KEY: True}),
        _measured("aaa_arm", "t1", 1.0, human_interventions=0, notes={TRACKED_KEY: True}),
    ]
    report = human_interventions(trials)
    assert [s.arm for s in report.by_arm] == ["aaa_arm", "zzz_arm"]
