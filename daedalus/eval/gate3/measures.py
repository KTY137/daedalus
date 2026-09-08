"""measures.py -- five of the nine Gate-3 measures (plan §11 Gate 3, sentence 3).

    success rate, best-so-far AUC, wall time, tokens, compute

The other four (variance, diversity, regressions, human intervention) are
owned by sibling work inside this same packet (G3-BASE-01) and are
deliberately absent from this module.

Every function here is pure: ``Sequence[TrialResult] -> a frozen result``.
None of them mutate, re-score, or re-run anything; they only read the fields
``daedalus.eval.gate3.protocols.run_trial`` already recorded (packet §5d).

Aggregation posture, reused rather than forked (packet §2 "Extend, never
duplicate"):

* Never blend across arms. ``daedalus.eval.harness._by_provenance`` groups
  by provenance/tier and never produces one top-level blended number for
  exactly this reason -- a blended figure hides one bucket collapsing while
  another improves. Every function in this module takes ONE arm's trials at a
  time; a caller comparing arms calls each of these once per arm and reports
  the numbers side by side, never merged into one figure.
* Absent is ABSENT, never a zero. ``daedalus.eval.harness``'s own docstring
  states the rule this package inherits: "any aggregation path that forgets
  to filter on error fails loudly instead of silently averaging a
  placeholder." ``daedalus.eval.gate3.contracts.partition_trials`` is the one
  filter every function below applies before computing a rate or a mean.
* The denominator is the whole point. ``docs/GATE2_FOREST_V2_TRIAGE.md`` lines
  20-45 record "285 scanned / 0 unparseable" computed over a denominator of
  ten -- a rate that looked perfect only because almost everything that could
  have failed was silently excluded from the count entirely. Every structure
  returned here carries its own denominator (``n_measured``, ``n_errored``,
  ``n_trials``) next to the figure, so a reader never has to trust a bare
  float.

EXPERIMENT (packet G3-BASE-01). The active delivery gate is 1. This module is
Gate-3 prework; a value it produces is not Gate-3 baseline evidence until an
owner seals the harness (see ``contracts.RunManifest.sealed``).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from daedalus.eval import harness

from .contracts import FreezeError, TrialResult, partition_trials


def _require_trials(trials: Sequence[TrialResult], measure_name: str) -> None:
    if not trials:
        raise FreezeError(
            f"{measure_name} over zero trials is undefined -- pass at least "
            "one TrialResult, or report 'no data' explicitly rather than "
            "calling this with an empty sequence")


# --------------------------------------------------------------------------- #
# 1. success rate                                                             #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SuccessRate:
    """A success rate that cannot be read without also seeing its denominator.

    ``n_measured`` and ``n_errored`` partition the trials this was computed
    from (``contracts.partition_trials``); their sum is ``n_total``. An
    errored trial is EXCLUDED from ``n_success``/``n_measured`` -- it is never
    silently counted as a failure (which would deflate the rate) or dropped
    from the report entirely (which would inflate it by shrinking the
    denominator, the exact defect named in this module's docstring).

    ``rate`` is ``None``, not ``0.0``, when ``n_measured == 0`` (every trial
    in the input errored): a rate computed over zero measured trials is not a
    real zero, it is an absence, and returning a float here would let a
    caller average it into a mean that quietly treats "never measured" as
    "measured and failed."
    """

    n_success: int
    n_measured: int
    n_errored: int

    def __post_init__(self) -> None:
        for f_name in ("n_success", "n_measured", "n_errored"):
            if getattr(self, f_name) < 0:
                raise FreezeError(f"SuccessRate.{f_name} cannot be negative")
        if self.n_success > self.n_measured:
            raise FreezeError(
                f"SuccessRate.n_success ({self.n_success}) cannot exceed "
                f"n_measured ({self.n_measured})")

    @property
    def n_total(self) -> int:
        return self.n_measured + self.n_errored

    @property
    def rate(self) -> float | None:
        """``None`` (absent) when nothing was measured; a fraction in [0, 1]
        otherwise. Never a bare zero standing in for "unmeasured."""
        if self.n_measured == 0:
            return None
        return self.n_success / self.n_measured


def success_rate(trials: Sequence[TrialResult]) -> SuccessRate:
    """Fraction of MEASURED trials that succeeded, for one arm's trials.

    Errored trials are excluded from both the numerator and the measured
    denominator (``partition_trials``) and reported separately via
    ``n_errored`` -- they must never inflate the rate by shrinking the
    denominator they are excluded from, nor deflate it by being counted as
    failures they were not (an unmeasured trial has no success verdict at
    all, per ``TrialResult.__post_init__``).
    """
    _require_trials(trials, "success_rate")
    measured, errored = partition_trials(trials)
    n_success = sum(1 for t in measured if t.success)
    return SuccessRate(n_success=n_success, n_measured=len(measured),
                        n_errored=len(errored))


# --------------------------------------------------------------------------- #
# 2. best-so-far AUC                                                          #
# --------------------------------------------------------------------------- #
def _trial_performance(trial: TrialResult) -> float:
    """One scalar per measured trial: ``score`` when the arm reported one,
    else the success verdict as 1.0/0.0. A measured trial always has a
    non-``None`` ``success`` (``TrialResult.__post_init__``), so this never
    falls through without a value -- it only ever prefers the richer
    ``score`` when both are present."""
    if trial.score is not None:
        return trial.score
    return 1.0 if trial.success else 0.0


def best_so_far_curve(trials: Sequence[TrialResult]) -> list[float]:
    """The running maximum performance seen so far, one entry per MEASURED
    trial, in the order ``trials`` was given.

    Errored trials are excluded (``partition_trials``) -- they contributed no
    performance value to advance the running best. The order of ``trials`` IS
    the "time" axis of this curve; callers must pass trials in the actual
    order they were attempted (e.g. by seed or by proposal index), never
    resorted by score -- sorting by score would turn "best found so far" into
    "best found ever," which is a different (and always higher) curve.

    Monotone non-decreasing BY CONSTRUCTION (each entry is
    ``max(previous_best, this_trial)``); test D2
    (``test_best_so_far_auc_is_monotone``) checks this directly rather than
    trusting the docstring.

    This is computed for ONE arm's trials. Comparing two arms means calling
    this once per arm and comparing the two curves/AUCs side by side, never
    merging trials from different arms into one curve.
    """
    measured, _ = partition_trials(trials)
    curve: list[float] = []
    best = float("-inf")
    for t in measured:
        best = max(best, _trial_performance(t))
        curve.append(best)
    return curve


def best_so_far_auc(trials: Sequence[TrialResult]) -> float | None:
    """Area under the best-so-far curve, normalised so runs of different
    length are comparable.

    NORMALISATION (stated precisely, because an unstated one is how a metric
    quietly stops being comparable): the curve's x-axis -- trial index -- is
    rescaled from ``0..len(curve)-1`` onto the fixed interval ``[0, 1]``
    before the trapezoidal rule integrates it. A 5-trial run and a 50-trial
    run therefore both produce an AUC that is the area under a curve of
    width exactly 1; neither is favoured merely for having more or fewer
    trials. The y-axis is left in the arm's native score units -- this makes
    AUC comparable ACROSS RUNS OF THE SAME ARM/EVALUATOR, but NOT across arms
    whose scores live on different scales (that would need a further,
    evaluator-specific normalisation this module does not invent).

    Returns ``None`` (absent), never ``0.0``, when there is no measured
    trial to build a curve from (every trial errored) -- a curve with no
    points has no area, and area 0.0 would misreport "measured and scored
    zero" instead of "nothing was measured at all."

    A single measured trial has an undefined width-1 trapezoid; by
    definition its "curve" is flat, so the AUC is exactly that one value.
    """
    curve = best_so_far_curve(trials)
    if not curve:
        return None
    if len(curve) == 1:
        return float(curve[0])
    n = len(curve)
    xs = [i / (n - 1) for i in range(n)]
    area = 0.0
    for i in range(1, n):
        area += (curve[i] + curve[i - 1]) / 2.0 * (xs[i] - xs[i - 1])
    return area


# --------------------------------------------------------------------------- #
# 3. wall time                                                                #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class WallTime:
    """Total and per-trial wall-clock cost, over ALL trials passed in
    (measured AND errored -- see ``wall_time``'s docstring for why)."""

    total_seconds: float
    mean_seconds: float
    n_trials: int

    def __post_init__(self) -> None:
        if self.total_seconds < 0:
            raise FreezeError("WallTime.total_seconds cannot be negative")
        if self.n_trials <= 0:
            raise FreezeError("WallTime.n_trials must be positive")


def wall_time(trials: Sequence[TrialResult]) -> WallTime:
    """Total and mean ``TrialResult.wall_seconds`` for one arm's trials.

    WHAT IS INSIDE THE MEASURED WINDOW: exactly what
    ``daedalus.eval.gate3.protocols.run_trial`` times -- the clock starts
    immediately before ``arm.run(...)`` and stops immediately after it
    returns or raises (test D3, ``test_wall_time_excludes_setup``). Every
    ``TrialResult.wall_seconds`` value this function sums is already that
    window; this function performs no further timing of its own.

    WHAT IS OUTSIDE: index building and any other per-repo setup the CALLER
    performs before invoking an arm (see ``protocols.run_arm_over_tasks`` and
    ``daedalus.eval.harness.run_tier1``'s per-repo index cache) is never
    charged to the arm being timed. Charging one arm for a cache another arm
    warmed is the same starvation defect packet rule R1 forbids for budgets
    (``contracts.ArmBudget.split``'s docstring) -- timing has the identical
    failure mode, so it gets the identical rule.

    BOTH measured and errored trials are included here, unlike
    ``success_rate``/``best_so_far_*``: ``wall_seconds`` is recorded by
    ``run_trial`` for every trial, including one that raised inside
    ``arm.run`` (the clock still stopped and the elapsed time is real
    spent time), so excluding errored trials would under-report how much
    wall-clock time the arm actually consumed.
    """
    _require_trials(trials, "wall_time")
    total = sum(t.wall_seconds for t in trials)
    return WallTime(total_seconds=total, mean_seconds=total / len(trials),
                     n_trials=len(trials))


# --------------------------------------------------------------------------- #
# 4. tokens                                                                   #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class TokenUsage:
    """Total and mean ``TrialResult.tokens_used``, bound to the tokenizer
    that produced them.

    ``tokenizer`` is MANDATORY and non-empty: token counts from two different
    tokenizers are not the same unit and must never be compared or summed as
    if they were (test D4, ``test_tokens_use_declared_tokenizer``). This
    mirrors ``daedalus.eval.harness.run_tier1``/``run_arms``, which both
    stamp ``tokenizer_name()`` onto every result dict for the same reason.
    """

    total_tokens: int
    mean_tokens: float
    tokenizer: str
    n_trials: int

    def __post_init__(self) -> None:
        if self.total_tokens < 0:
            raise FreezeError("TokenUsage.total_tokens cannot be negative")
        if self.n_trials <= 0:
            raise FreezeError("TokenUsage.n_trials must be positive")
        if not self.tokenizer.strip():
            raise FreezeError(
                "TokenUsage.tokenizer must be non-empty -- a token count "
                "without a declared tokenizer is not a comparable measurement")


def token_usage(trials: Sequence[TrialResult], tokenizer: str | None = None) -> TokenUsage:
    """Total and mean ``TrialResult.tokens_used`` for one arm's trials.

    ``tokenizer`` defaults to ``daedalus.eval.harness.tokenizer_name()`` --
    the SAME tokenizer identity ``run_tier1``/``run_arms`` already stamp onto
    every result, reused rather than re-derived (packet §2). Pass an explicit
    value only when the trials were produced under a different, already-known
    tokenizer than the one currently active in this process.

    Both measured and errored trials are included: ``ArmOutcome.tokens_used``
    (and therefore ``TrialResult.tokens_used``) can be non-zero even for a
    trial that ultimately errored -- e.g. an arm that assembled a context,
    consumed real tokens building it, and only then failed to score it. That
    token spend is real and must be counted, matching ``wall_time``'s
    identical inclusion rule and for the identical reason.
    """
    _require_trials(trials, "token_usage")
    resolved_tokenizer = tokenizer if tokenizer is not None else harness.tokenizer_name()
    total = sum(t.tokens_used for t in trials)
    return TokenUsage(total_tokens=total, mean_tokens=total / len(trials),
                       tokenizer=resolved_tokenizer, n_trials=len(trials))


# --------------------------------------------------------------------------- #
# 5. compute                                                                  #
# --------------------------------------------------------------------------- #
#: Machine-readable label for the proxy this module reports. Never "flops",
#: never a number that could be mistaken for a hardware FLOP count.
_COMPUTE_PROXY_LABEL = "evaluator_calls_plus_wall_seconds_proxy"


@dataclass(frozen=True)
class ComputeProxy:
    """A DECLARED PROXY for compute cost. This is NOT a FLOP count and MUST
    NOT be reported as one.

    Packet §8, expected failure #3 (recorded before this module was built):
    "'compute' (D5) has no accepted unit here. Expect a declared proxy,
    explicitly labelled, not a fabricated FLOP count." There is no
    instrumented FLOP counter anywhere in this codebase (no CUDA events, no
    perf-counter hardware sampling, no model-architecture-aware FLOP
    estimator) -- inventing a FLOP number from wall time and call count would
    be exactly the fabrication the packet was written to forbid.

    The proxy combines two quantities this harness already measures honestly:
    ``total_evaluator_calls`` (``TrialResult.calls``, the SealedEvaluator's
    own tamper-resistant counter -- see ``protocols.SealedEvaluator``) and
    ``total_wall_seconds`` (``TrialResult.wall_seconds``, see ``wall_time``).
    ``proxy_value`` is their sum in the proxy's own declared unit
    ("calls + seconds"); it is not a physical quantity and has no SI unit
    conversion.

    ``is_proxy`` is always ``True`` and is not a caller-settable escape
    hatch: every ``ComputeProxy`` this module constructs comes from
    ``compute()``, which never produces one with ``is_proxy=False``. The
    field exists so a report renderer can check ``result.is_proxy`` (test D5,
    ``test_compute_recorded``) instead of trusting a docstring it may not
    read.
    """

    total_evaluator_calls: int
    total_wall_seconds: float
    proxy_value: float
    label: str = _COMPUTE_PROXY_LABEL
    is_proxy: bool = True
    note: str = ("NOT FLOPs. This is a declared proxy (evaluator calls + "
                 "wall-clock seconds); there is no accepted compute unit in "
                 "this harness (packet G3-BASE-01 §8, expected failure #3).")

    def __post_init__(self) -> None:
        if not self.is_proxy:
            raise FreezeError(
                "ComputeProxy.is_proxy must be True -- there is no non-proxy "
                "compute measurement in this harness; constructing one that "
                "claims otherwise would misrepresent a proxy as a real unit")
        if self.total_evaluator_calls < 0:
            raise FreezeError("ComputeProxy.total_evaluator_calls cannot be negative")
        if self.total_wall_seconds < 0:
            raise FreezeError("ComputeProxy.total_wall_seconds cannot be negative")


def compute(trials: Sequence[TrialResult]) -> ComputeProxy:
    """Compute a labelled PROXY (never FLOPs) for one arm's trials: total
    evaluator calls plus total wall-clock seconds, summed over ALL trials
    (measured and errored -- a failed trial still consumed evaluator calls
    and wall time, matching ``wall_time``/``token_usage``'s inclusion rule).

    See ``ComputeProxy`` for why this is a proxy and not a FLOP count.
    """
    _require_trials(trials, "compute")
    total_calls = sum(t.calls for t in trials)
    total_seconds = sum(t.wall_seconds for t in trials)
    return ComputeProxy(total_evaluator_calls=total_calls,
                         total_wall_seconds=total_seconds,
                         proxy_value=total_calls + total_seconds)
