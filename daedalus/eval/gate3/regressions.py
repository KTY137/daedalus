"""regressions.py -- Gate-3 measures: REGRESSIONS (D8) and HUMAN INTERVENTION (D9).

Plan §11 Gate 3, sentence 3 names nine required measures; this module owns two
of them: "regressions" and "human intervention".

REGRESSIONS -- the arm-comparison analogue of ``run_gate``
------------------------------------------------------------
``daedalus.eval.harness.run_gate`` (see its docstring, lines ~757-854) already
establishes the binding design for this measure: compare a CURRENT run against
a stored baseline, per PRIMARY-tier task, NEVER on a mean -- "a mean hides one
task collapsing while another improves" (its own docstring, proven by
``tests/test_eval_oracle.py::test_gate_mean_preserving_swap_fails``). It also
splits errored rows out by tier rather than folding them into ``regressions``,
and reports a task present in baseline but absent now as ``missing_tasks``.

This module needs the identical guarantee for a Gate-3 baseline COMPARISON --
two ``TrialResult`` sequences, either two runs of the same arm (a regression
ratchet across time) or two different arms (a head-to-head) -- broken down per
task. It reuses ``run_gate``'s vocabulary and per-task-never-mean rule, but it
does NOT call, import, or fork ``run_gate``: that function is bound to
``daedalus.eval.harness``'s own task/recall shape (module-level ``TASKS``,
``.recall``, ``baseline.json`` on disk), and packet §2/§6 forbid a second gate
and forbid editing ``harness.py``. ``regressions()`` here is the arm-comparison
analogue: it operates on the Gate-3 ``TrialResult`` contract instead (arbitrary
``score``/``success``, absent-is-absent errors via ``partition_trials``).

An ERRORED current trial for a task that was measured (had a score) in the
baseline is its own regression kind, ``newly_errored`` -- never silently
dropped and never folded into ``regressed``, because a broken task is a
qualitatively different failure than "scored lower" and dropping it is
precisely how a broken task becomes an invisible pass. A task present in
baseline but absent from the current run is ``missing``, mirroring
``run_gate``'s ``missing_tasks``. A task errored in BOTH runs is ``still_errored``
-- excluded from any score-based verdict (there is no score to compare) but
still reported, never dropped.

HUMAN INTERVENTION -- a measured count, not a structural zero
------------------------------------------------------------
Plan §11 lists human intervention as a required Gate-3 measure precisely
because an autonomous-looking result that needed five nudges is not
autonomous. ``TrialResult.human_interventions`` (``daedalus/eval/gate3/contracts.py``)
defaults to ``0`` at the dataclass level, which means a run whose arm never
even tracks interventions is INDISTINGUISHABLE, at the field level alone, from
a run that measured zero. That is exactly the s06 defect named in
``docs/GATE2_FOREST_V2_TRIAGE.md`` line 107 ("8466 konforme Karten, 0
abgelehnt, 0 Verstosse" -- "die beiden Null-Zaehler sind strukturell
garantiert, nicht gemessen"): a counter that cannot be non-zero is not a
measurement.

This module closes that gap through ``TrialResult.notes``, the one field an
arm already controls per trial (``daedalus/eval/gate3/protocols.py``
``ArmOutcome.notes`` flows through ``run_trial`` unchanged): an arm that
actively tracks human intervention marks it by setting
``notes[TRACKED_KEY] = True`` on its ``ArmOutcome``. An arm whose trials never
set that key is reported with ``recorded=False`` -- its total is still summed
(never hidden; a silently dropped count is its own defect), but the report
marks the arm unrecorded so "zero measured" and "never measured" stay visible
as two different facts, distinguishable at the exact boundary a reader looks
at (``ArmInterventionSummary.recorded`` / ``InterventionReport.unrecorded_arms``).

EXPERIMENT (packet G3-BASE-01). The active delivery gate is 1. This module is
Gate-3 prework prototyped under plan §11's later-gate allowance; a value it
produces is not Gate-3 baseline evidence until an owner seals the harness.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .contracts import FreezeError, TrialResult, partition_trials

# An arm declares that it actively tracks human intervention by setting this
# key truthy in ArmOutcome.notes (which flows verbatim into TrialResult.notes
# via run_trial). Absence of the key on every one of an arm's trials means the
# arm's human_interventions=0 default was never measured -- see module
# docstring and docs/GATE2_FOREST_V2_TRIAGE.md line 107.
TRACKED_KEY = "human_interventions_tracked"


# --------------------------------------------------------------------------- #
# regressions (D8)                                                            #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class TaskRegression:
    """One task's verdict in a ``regressions()`` comparison.

    ``kind`` is one of: ``regressed``, ``improved``, ``unchanged``,
    ``newly_errored``, ``still_errored``, ``missing``, ``new``. Only the first
    three carry both scores and a ``delta``; the error kinds carry the error
    text instead of a score for whichever side errored, and never fabricate a
    0.0 score for an absent measurement.
    """

    task_id: str
    kind: str
    baseline_score: float | None = None
    current_score: float | None = None
    delta: float | None = None
    baseline_error: str | None = None
    current_error: str | None = None


@dataclass(frozen=True)
class RegressionReport:
    """Per-task partition of a baseline-vs-current comparison. Every list is
    sorted by ``task_id`` (matching ``run_gate``'s own sorted output)."""

    regressed: tuple[TaskRegression, ...]
    improved: tuple[TaskRegression, ...]
    unchanged: tuple[TaskRegression, ...]
    newly_errored: tuple[TaskRegression, ...]
    still_errored: tuple[TaskRegression, ...]
    missing: tuple[TaskRegression, ...]
    new: tuple[TaskRegression, ...]

    @property
    def passed(self) -> bool:
        """No PER-TASK regression and no newly-errored task. Never computed
        from a mean -- see module docstring."""
        return not self.regressed and not self.newly_errored


def _metric(trial: TrialResult) -> float:
    """The comparable number for one MEASURED trial. Prefers ``score``; falls
    back to ``success`` as 1.0/0.0 for arms that only report a verdict. Never
    called on an errored trial -- callers gate on ``.measured`` first, and a
    measured trial's ``TrialResult.__post_init__`` already guarantees
    ``success is not None`` when ``score`` is absent."""
    if trial.score is not None:
        return float(trial.score)
    return 1.0 if trial.success else 0.0


def _index_by_task(trials: Sequence[TrialResult], label: str) -> dict[str, TrialResult]:
    """One row per task. Raises loudly on a duplicate task id in the SAME run
    -- ``regressions()`` compares one row per task, so a caller with multiple
    seeds or multiple arms in one sequence must aggregate before calling this
    (ambiguity here would silently pick one seed's outcome over another's)."""
    index: dict[str, TrialResult] = {}
    for t in trials:
        if t.task_id in index:
            raise FreezeError(
                f"{label} trials contain more than one row for task "
                f"{t.task_id!r} (e.g. multiple seeds or multiple arms mixed "
                "into one sequence); regressions() compares exactly one row "
                "per task -- aggregate seeds/arms before calling it")
        index[t.task_id] = t
    return index


def regressions(baseline_trials: Sequence[TrialResult],
                current_trials: Sequence[TrialResult]) -> RegressionReport:
    """Per-task comparison between two runs (same arm across time, or two
    different arms head-to-head). NEVER decides via a mean: a task that
    collapsed while another improved must show up even when the mean of all
    tasks is unchanged (the mean-preserving-swap case, packet test D8).

    Uses ``partition_trials`` on each side so an absent score stays absent --
    it is never coerced to 0.0, matching every other aggregator in this
    package.
    """
    baseline_measured, baseline_errored = partition_trials(baseline_trials)
    current_measured, current_errored = partition_trials(current_trials)

    baseline_by_task = _index_by_task(baseline_measured + baseline_errored, "baseline")
    current_by_task = _index_by_task(current_measured + current_errored, "current")

    all_ids = sorted(set(baseline_by_task) | set(current_by_task))

    regressed: list[TaskRegression] = []
    improved: list[TaskRegression] = []
    unchanged: list[TaskRegression] = []
    newly_errored: list[TaskRegression] = []
    still_errored: list[TaskRegression] = []
    missing: list[TaskRegression] = []
    new: list[TaskRegression] = []

    for task_id in all_ids:
        b = baseline_by_task.get(task_id)
        c = current_by_task.get(task_id)

        if c is None:
            # Present in baseline, absent now -- mirrors run_gate's
            # missing_tasks. Never silently dropped.
            missing.append(TaskRegression(
                task_id=task_id, kind="missing",
                baseline_score=_metric(b) if b.measured else None,
                baseline_error=b.error,
            ))
            continue

        if b is None:
            # Present now, absent from baseline -- a genuinely new task, not
            # a regression or improvement against anything.
            new.append(TaskRegression(
                task_id=task_id, kind="new",
                current_score=_metric(c) if c.measured else None,
                current_error=c.error,
            ))
            continue

        if b.measured and not c.measured:
            # A distinct regression kind: broken now, not merely "scored
            # lower". Dropping this is how a broken task becomes an
            # invisible pass -- it must never be folded into `regressed`.
            newly_errored.append(TaskRegression(
                task_id=task_id, kind="newly_errored",
                baseline_score=_metric(b), current_error=c.error,
            ))
            continue

        if not b.measured and not c.measured:
            # Errored in both runs: excluded from any score-based verdict
            # (there is no score to compare), but still counted, never
            # silently dropped.
            still_errored.append(TaskRegression(
                task_id=task_id, kind="still_errored",
                baseline_error=b.error, current_error=c.error,
            ))
            continue

        if not b.measured and c.measured:
            # Recovered from an error to a measured score: a real
            # improvement, reported as such rather than dropped.
            improved.append(TaskRegression(
                task_id=task_id, kind="improved",
                baseline_error=b.error, current_score=_metric(c),
            ))
            continue

        # Both measured: the only case with a genuine score delta. Compared
        # PER TASK, right here -- never via any aggregate/mean.
        b_score = _metric(b)
        c_score = _metric(c)
        delta = c_score - b_score
        if delta < 0:
            kind, bucket = "regressed", regressed
        elif delta > 0:
            kind, bucket = "improved", improved
        else:
            kind, bucket = "unchanged", unchanged
        bucket.append(TaskRegression(task_id=task_id, kind=kind,
                                      baseline_score=b_score, current_score=c_score,
                                      delta=delta))

    return RegressionReport(
        regressed=tuple(sorted(regressed, key=lambda r: r.task_id)),
        improved=tuple(sorted(improved, key=lambda r: r.task_id)),
        unchanged=tuple(sorted(unchanged, key=lambda r: r.task_id)),
        newly_errored=tuple(sorted(newly_errored, key=lambda r: r.task_id)),
        still_errored=tuple(sorted(still_errored, key=lambda r: r.task_id)),
        missing=tuple(sorted(missing, key=lambda r: r.task_id)),
        new=tuple(sorted(new, key=lambda r: r.task_id)),
    )


# --------------------------------------------------------------------------- #
# human intervention (D9)                                                     #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ArmInterventionSummary:
    """One arm's human-intervention count.

    ``recorded`` is the s06-defect guard: True only if at least one of this
    arm's trials explicitly declared ``notes[TRACKED_KEY]`` truthy. An arm
    that never declares tracking gets ``recorded=False`` even when its
    summed ``total`` is 0 -- a structurally-guaranteed zero is not a
    measurement (module docstring; ``docs/GATE2_FOREST_V2_TRIAGE.md`` line 107).
    """

    arm: str
    n_trials: int
    total: int
    per_task: Mapping[str, int]
    recorded: bool

    def __post_init__(self) -> None:
        if self.total < 0:
            raise FreezeError(f"arm {self.arm!r} has a negative intervention total")
        if self.n_trials <= 0:
            raise FreezeError(f"arm {self.arm!r} has no trials to summarize")


@dataclass(frozen=True)
class InterventionReport:
    """Sum and per-arm breakdown, sorted by arm name."""

    total: int
    by_arm: tuple[ArmInterventionSummary, ...]

    @property
    def unrecorded_arms(self) -> tuple[str, ...]:
        """Arms whose human-intervention count was never actually measured
        (see ``ArmInterventionSummary.recorded``). A caller rendering this
        report MUST NOT present ``total`` for these arms as if it were a
        measured zero."""
        return tuple(sorted(s.arm for s in self.by_arm if not s.recorded))


def human_interventions(trials: Sequence[TrialResult]) -> InterventionReport:
    """Sum and per-arm breakdown of ``TrialResult.human_interventions``.

    Every trial's count is summed, measured and errored alike -- an
    intervention that happened before a trial errored still happened; a
    silently dropped count would be its own defect. (This is independent of
    the score-comparison exclusion rule in ``regressions()``: that rule is
    about SCORE deltas, not about counting interventions.)

    The count is MEASURED from the rows, never assumed zero: see
    ``TRACKED_KEY`` and ``ArmInterventionSummary.recorded`` / this report's
    ``unrecorded_arms`` for the "zero recorded" vs. "never recorded"
    distinction plan §11 requires.
    """
    if not trials:
        raise FreezeError("human_interventions() was given no trials to measure")

    by_arm: dict[str, list[TrialResult]] = {}
    for t in trials:
        by_arm.setdefault(t.arm, []).append(t)

    summaries: list[ArmInterventionSummary] = []
    for arm in sorted(by_arm):
        arm_trials = by_arm[arm]
        per_task: dict[str, int] = {}
        recorded = False
        for t in arm_trials:
            per_task[t.task_id] = per_task.get(t.task_id, 0) + t.human_interventions
            if bool(t.notes.get(TRACKED_KEY, False)):
                recorded = True
        summaries.append(ArmInterventionSummary(
            arm=arm,
            n_trials=len(arm_trials),
            total=sum(t.human_interventions for t in arm_trials),
            per_task=dict(sorted(per_task.items())),
            recorded=recorded,
        ))

    return InterventionReport(
        total=sum(s.total for s in summaries),
        by_arm=tuple(summaries),
    )
