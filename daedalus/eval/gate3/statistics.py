"""statistics.py -- variance and uncertainty (Gate-3 freeze obligation 6/6).

Plan §4 invariant 9: "Comparative claims use frozen tasks, equal budgets,
declared hardware/models, repeated trials, uncertainty, and relevant
baselines." Plan §14: "run at least 5-10 seeds when stochastic variance
matters." ``SeedPolicy`` (``contracts.py``) enforces that seeds exist; this
module is what makes the variance those seeds produce actually *readable*.

EXPERIMENT (packet G3-BASE-01). The active delivery gate is 1. This is
Gate-3 prework; nothing here is Gate-3 baseline evidence until an owner seals
the harness (see ``contracts.RunManifest``).

Three design rules, each answering a way this repository has previously
mis-measured itself (see the packet doc's §3 starvation rule and §0.8
expected failures):

1. **Absent is absent.** Only ``TrialResult.measured`` rows may contribute a
   score. ``partition_trials`` is the one filter; every function here calls it
   before touching a score, matching ``daedalus.eval.harness``'s established
   contract ("ABSENT, not None -- so any aggregation path that forgets to
   filter on error fails loudly instead of silently averaging a placeholder").
   Errored counts are reported, never dropped silently.
2. **n=1 has no variance, not zero variance.** ``summarize`` REFUSES a single
   value with a ``FreezeError`` naming the refusal. A variance of ``0.0``
   computed from one sample is indistinguishable, downstream, from "we
   measured zero variance" -- the single most common way a stochastic method
   gets reported as though it were deterministic.
3. **No invented significance protocol.** ``compare_arms`` returns a
   difference and an uncertainty interval and lets a human read it. It never
   computes or returns a p-value and never uses the word "significant" --
   this repository has no pre-registered statistical testing protocol (that
   is Gate-3, §11 paragraph 2, "First freeze ... statistical reporting"
   itself, not yet done), and manufacturing one INSIDE the freeze-obligation
   module that is supposed to prevent unearned rigor would be exactly the
   defect plan §4 invariant 9 and AGENTS.md's review rules forbid
   ("unverifiable claims" and "a hook or instruction advertised as a
   complete security guarantee" are the same shape of problem: false
   confidence baked into the plumbing).

INTERVAL METHOD, stated precisely once here (docstrings on individual
functions point back to this paragraph): every interval in this module is a
two-sided 95% confidence interval for a mean, computed as
``mean +/- t_crit * sample_stdev / sqrt(n)`` using the SAMPLE standard
deviation (Bessel-corrected, ``statistics.stdev``, ddof=1) and a Student's-t
critical value. For degrees of freedom 1..30 (i.e. up to n=31 -- comfortably
covering this harness's expected n=5..10 stochastic-seed regime, plan §14)
``t_crit`` is an EXACT lookup from the standard t-table. For degrees of
freedom above 30 there is no t-table in the Python standard library and this
module does not implement an inverse-t or inverse-beta solver; instead it
uses the standard normal critical value ``z_0.975 = 1.959963984540054`` as an
APPROXIMATION. Because ``t_df > z`` for every finite ``df``, this
approximation makes the interval very slightly NARROWER (anti-conservative)
than the exact t-interval; the gap is already under 0.5% at df=30 and shrinks
as df grows further. Every ``SummaryStats`` records which case fired in
``interval_method`` so a report never presents an approximation as exact.
"""
from __future__ import annotations

import math
import statistics as _stdlib_statistics
from dataclasses import dataclass
from typing import Sequence

from .contracts import FreezeError, TrialResult, partition_trials

__all__ = [
    "CONFIDENCE_LEVEL",
    "SummaryStats",
    "PerTaskVariance",
    "SeedVarianceReport",
    "ArmComparison",
    "summarize",
    "variance_across_seeds",
    "compare_arms",
]

# The one confidence level this module computes. Not a parameter: offering a
# knob here (0.90? 0.99?) without a pre-registered protocol choosing one would
# itself be the "invented statistical protocol" rule 3 above forbids. If a
# future Gate-3 spec freezes a different level, that is a deliberate, reviewed
# change to this constant, not a caller-supplied argument.
CONFIDENCE_LEVEL = 0.95

# Exact two-sided 95% Student's-t critical values (t_{0.025, df}) for
# df = 1..30, transcribed from the standard t-table. This covers every n from
# 2 to 31, which comfortably spans plan §14's "5-10 seeds" floor.
_T_TABLE_95: dict[int, float] = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
    6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
    11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
    16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060,
    26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
}

# Standard normal two-sided 95% critical value, used ONLY for df > 30 (see the
# module docstring's INTERVAL METHOD paragraph for the named approximation).
_Z_95 = 1.959963984540054


def _t_critical(df: int) -> tuple[float, str]:
    """95% two-sided critical value for ``df`` degrees of freedom.

    Returns ``(critical_value, method_label)``. ``method_label`` is stored
    verbatim in ``SummaryStats.interval_method`` so no report can present the
    df>30 normal approximation as an exact t-interval.
    """
    if df < 1:
        raise FreezeError(f"_t_critical requires df >= 1, got {df}")
    if df in _T_TABLE_95:
        return _T_TABLE_95[df], f"Student's t, exact table (df={df})"
    return _Z_95, (
        f"normal approximation z=1.959963984540054 in place of Student's t "
        f"(df={df} > 30, outside this module's exact table; t_df > z for all "
        "finite df, so this interval is very slightly narrower than exact)"
    )


@dataclass(frozen=True)
class SummaryStats:
    """Mean, sample standard deviation, and a 95% confidence interval for one
    sample of measured values. See the module docstring's INTERVAL METHOD
    paragraph for exactly how ``ci_low``/``ci_high`` are computed.

    ``interval_method`` names which case produced the critical value (exact
    t-table lookup vs. normal approximation) -- never left implicit.
    """

    n: int
    mean: float
    stdev: float
    ci_low: float
    ci_high: float
    confidence: float
    interval_method: str

    @property
    def half_width(self) -> float:
        return (self.ci_high - self.ci_low) / 2.0


def summarize(values: Sequence[float]) -> SummaryStats:
    """Mean, sample stdev, n, and a 95% confidence interval for ``values``.

    REFUSES (raises ``FreezeError``) rather than returning a result for
    ``n == 0`` or ``n == 1``. An interval computed from a single sample is
    UNDEFINED -- ``statistics.stdev`` itself requires at least two data
    points for exactly this reason -- and silently returning a zero-width
    interval would misrepresent an unmeasured variance as a measured one.
    This is the module's rule-2 refusal (see module docstring); it is the
    floor of plan §14's "5-10 seeds" guidance, not a replacement for it: a
    caller collecting exactly 2 samples gets a real, very wide, honestly
    labelled interval, not an error, but should not mistake that for the
    seed count plan §14 actually requires for a stochastic arm.
    """
    n = len(values)
    if n == 0:
        raise FreezeError(
            "summarize() received zero values -- there is nothing to "
            "summarize. An absent sample is absent, not a zero-variance "
            "measurement.")
    if n == 1:
        raise FreezeError(
            "summarize() refuses n=1: a standard deviation and confidence "
            "interval computed from a single sample are UNDEFINED, not "
            "zero. Reporting a point value as though its variance were "
            "known and zero is the most common way a stochastic method "
            "gets misrepresented as reliable. Collect at least one more "
            "sample (plan §14 requires >=5-10 seeds for a stochastic arm; "
            "this refusal is the floor of that rule, not a substitute).")
    for v in values:
        fv = float(v)
        if math.isnan(fv) or math.isinf(fv):
            raise FreezeError(
                f"summarize() received a non-finite value ({v!r}); a NaN or "
                "infinite score cannot be summarized honestly")

    floats = [float(v) for v in values]
    mean = _stdlib_statistics.fmean(floats)
    stdev = _stdlib_statistics.stdev(floats)  # sample stdev, ddof=1, needs n>=2
    df = n - 1
    t_crit, method = _t_critical(df)
    half_width = t_crit * stdev / math.sqrt(n)
    return SummaryStats(
        n=n, mean=mean, stdev=stdev,
        ci_low=mean - half_width, ci_high=mean + half_width,
        confidence=CONFIDENCE_LEVEL, interval_method=method,
    )


def _single_arm_scores(trials: Sequence[TrialResult], label: str
                        ) -> tuple[str, list[float], int, int]:
    """Shared plumbing for the one-arm functions below.

    Returns ``(arm_name, scores, n_errored, n_measured_without_score)``.
    Refuses trials that mix more than one arm: blending two arms' rows before
    computing a variance is exactly the "no blended cross-arm statistic that
    hides a per-arm collapse" rule this packet is bound by.
    """
    if not trials:
        raise FreezeError(f"{label} received no trials")
    arms = {t.arm for t in trials}
    if len(arms) != 1:
        raise FreezeError(
            f"{label} received trials from multiple arms {sorted(arms)}; "
            "call once per arm. Blending arms into one variance computation "
            "would hide a per-arm collapse behind an average.")
    measured, errored = partition_trials(trials)
    scored = [t.score for t in measured if t.score is not None]
    n_missing_score = len(measured) - len(scored)
    return arms.pop(), [float(s) for s in scored], len(errored), n_missing_score


@dataclass(frozen=True)
class PerTaskVariance:
    """Across-seed variance for one task, within one arm.

    ``stats`` is ``None`` -- an explicit, named undefined result, never a
    zero -- when fewer than two measured-with-score trials exist for this
    task. ``insufficient_reason`` explains why whenever ``stats`` is
    ``None``, so a report can say *why* a task has no interval instead of
    reading a missing value as "no variance."
    """

    task_id: str
    n_seeds_measured: int
    n_seeds_errored: int
    n_seeds_missing_score: int
    stats: SummaryStats | None
    insufficient_reason: str | None = None

    def __post_init__(self) -> None:
        if self.stats is not None and self.insufficient_reason is not None:
            raise FreezeError(
                f"task {self.task_id!r} has both computed stats and an "
                "insufficient_reason -- these are mutually exclusive")
        if self.stats is None and self.insufficient_reason is None:
            raise FreezeError(
                f"task {self.task_id!r} has neither stats nor a reason it "
                "is missing -- an undefined interval must say why")


@dataclass(frozen=True)
class SeedVarianceReport:
    """The distribution of across-seed variance for one arm, one task at a
    time (module docstring rule 1; packet §5d, measure D6).

    ``SeedPolicy`` (``contracts.py``) is what makes this quantity
    measurable in the first place -- it is the thing that forces >= 5 seeds
    for a stochastic arm so a per-task variance is more than an artifact of
    n=2.
    """

    arm: str
    per_task: tuple[PerTaskVariance, ...]

    @property
    def n_tasks(self) -> int:
        return len(self.per_task)

    @property
    def n_tasks_with_interval(self) -> int:
        return sum(1 for p in self.per_task if p.stats is not None)

    @property
    def n_tasks_insufficient(self) -> int:
        return self.n_tasks - self.n_tasks_with_interval


def variance_across_seeds(trials: Sequence[TrialResult]) -> SeedVarianceReport:
    """Group one arm's trials by task, and compute a 95% CI for the
    across-seed score distribution of each task.

    ``trials`` must all belong to one arm (see ``_single_arm_scores``). A
    task whose measured-with-score seed count is 0 or 1 gets an explicit
    ``PerTaskVariance(stats=None, insufficient_reason=...)`` row rather than
    being silently dropped or reported as zero variance -- packet rule
    "an absent measurement is ABSENT, never a zero" applies per-task, not
    only per-run.
    """
    if not trials:
        raise FreezeError("variance_across_seeds() received no trials")
    arms = {t.arm for t in trials}
    if len(arms) != 1:
        raise FreezeError(
            f"variance_across_seeds() received trials from multiple arms "
            f"{sorted(arms)}; call once per arm (see compare_arms for the "
            "two-arm case). Blending arms would hide a per-arm collapse "
            "behind one shared distribution.")
    arm = trials[0].arm

    by_task: dict[str, list[TrialResult]] = {}
    for t in trials:
        by_task.setdefault(t.task_id, []).append(t)

    rows: list[PerTaskVariance] = []
    for task_id in sorted(by_task):
        task_trials = by_task[task_id]
        measured, errored = partition_trials(task_trials)
        scored = [t.score for t in measured if t.score is not None]
        n_missing_score = len(measured) - len(scored)
        if len(scored) >= 2:
            rows.append(PerTaskVariance(
                task_id=task_id,
                n_seeds_measured=len(measured),
                n_seeds_errored=len(errored),
                n_seeds_missing_score=n_missing_score,
                stats=summarize(scored),
            ))
        else:
            rows.append(PerTaskVariance(
                task_id=task_id,
                n_seeds_measured=len(measured),
                n_seeds_errored=len(errored),
                n_seeds_missing_score=n_missing_score,
                stats=None,
                insufficient_reason=(
                    f"only {len(scored)} measured-with-score seed(s) for "
                    f"task {task_id!r}; a variance/interval needs >= 2"
                ),
            ))
    return SeedVarianceReport(arm=arm, per_task=tuple(rows))


@dataclass(frozen=True)
class ArmComparison:
    """A difference between two arms' scores, with an uncertainty interval.

    Deliberately carries NO p-value and NO significance verdict (module
    docstring rule 3): this repository has no pre-registered statistical
    testing protocol, and Gate 3 (plan §11) is the packet that is supposed
    to freeze one -- inventing an ad hoc significance test inside the module
    that exists to prevent unearned rigor would be self-defeating.

    ``diff`` is ``mean_a - mean_b``. ``diff_ci_low``/``diff_ci_high`` are
    computed by plain interval arithmetic over each arm's OWN independent
    95% CI (``[ci_low_a - ci_high_b, ci_high_a - ci_low_b]``) -- not a
    pooled or Welch two-sample t-interval. This is deliberately the more
    conservative (wider) of the two: it makes no assumption about a shared
    or unequal variance model and requires no additional formula beyond the
    two intervals ``summarize`` already computed. Its direct consequence is
    that ``separable`` (no overlap between arm A's and arm B's raw 95% CIs)
    is mathematically identical to "this difference interval excludes
    zero" -- the two are the same check, not two independent claims.

    ``separable`` answers exactly one question: do the two arms' raw
    intervals fail to overlap? It is NOT a hypothesis-test verdict --
    overlapping confidence intervals do not imply "no real difference," and
    ``separable=True`` does not imply "significant" in any formal sense.
    Read the interval; a human decides what it means for the comparison at
    hand.
    """

    arm_a: str
    arm_b: str
    n_a: int
    n_b: int
    mean_a: float
    mean_b: float
    diff: float
    diff_ci_low: float
    diff_ci_high: float
    separable: bool
    interval_method_a: str
    interval_method_b: str


def compare_arms(arm_a_trials: Sequence[TrialResult],
                  arm_b_trials: Sequence[TrialResult]) -> ArmComparison:
    """Compare two arms' measured-with-score trials. See ``ArmComparison``
    for exactly what ``diff``, the diff interval, and ``separable`` mean and
    do not mean.

    Each side is summarized independently with ``summarize`` (so each side's
    own n=0/n=1 refusal applies -- a one-sample arm cannot be "compared" any
    more than it can be "summarized"). Each side must be single-arm trials,
    matching ``variance_across_seeds``'s rule against blending arms.
    """
    name_a, scores_a, _errored_a, _missing_a = _single_arm_scores(
        arm_a_trials, "compare_arms(arm_a_trials, ...)")
    name_b, scores_b, _errored_b, _missing_b = _single_arm_scores(
        arm_b_trials, "compare_arms(..., arm_b_trials)")
    if name_a == name_b:
        raise FreezeError(
            f"compare_arms() received the same arm {name_a!r} on both "
            "sides; a comparison needs two distinct arms")

    stats_a = summarize(scores_a)
    stats_b = summarize(scores_b)

    diff = stats_a.mean - stats_b.mean
    diff_lo = stats_a.ci_low - stats_b.ci_high
    diff_hi = stats_a.ci_high - stats_b.ci_low
    separable = not (diff_lo <= 0.0 <= diff_hi)

    return ArmComparison(
        arm_a=name_a, arm_b=name_b,
        n_a=stats_a.n, n_b=stats_b.n,
        mean_a=stats_a.mean, mean_b=stats_b.mean,
        diff=diff, diff_ci_low=diff_lo, diff_ci_high=diff_hi,
        separable=separable,
        interval_method_a=stats_a.interval_method,
        interval_method_b=stats_b.interval_method,
    )
