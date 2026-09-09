"""summary.py -- ``ArmSummary``: the nine required measures for one arm.

Plan §11, Gate 3, sentence 3:

    Measure success rate, best-so-far AUC, wall time, tokens, compute,
    variance, diversity, regressions, and human intervention.

Those nine live in four sibling modules (``measures``, ``statistics``,
``diversity``, ``regressions``), each owning its own definition and refusals.
This module does NOT reimplement any of them -- it composes them into the one
per-arm record the packet's §4 contract table names, and it is the only place
that knows all nine belong together.

Two rules inherited from the rest of the package:

* **Per arm, never blended.** ``summarize_arms`` returns one summary per arm.
  There is deliberately no grand total: a blended number hides the arm that
  collapsed, which is exactly what ``daedalus.eval.harness``'s aggregation
  docstring warns about and what the mean-preserving-swap test exists to catch.
* **A measure that could not be computed is ABSENT, not zero.** Every field
  that a refusal can produce is ``... | None``, and the refusal reason is
  recorded beside it. ``diversity`` refuses n<2, ``statistics`` refuses n=1,
  and a summary that quietly turned either into ``0.0`` would manufacture
  confidence nobody measured.

EXPERIMENT (packet G3-BASE-01), Gate-3 prework while the active gate is 1.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from .contracts import FreezeError, TrialResult, partition_trials


@dataclass(frozen=True)
class ArmSummary:
    """The nine Gate-3 measures for exactly one arm.

    ``unmeasured`` maps a measure name to the reason it is absent. A reader who
    sees ``variance is None`` can always find out why, instead of guessing
    whether it was zero, missing, or never attempted.
    """

    arm: str
    n_trials: int
    n_measured: int
    n_errored: int

    # 1-5, from .measures
    success_rate: float | None
    best_so_far_auc: float | None
    wall_seconds_total: float
    tokens_total: int
    tokenizer: str
    compute_proxy: float | None

    # 6-9, from .statistics / .diversity / .regressions
    variance: object | None = None
    diversity: object | None = None
    regressions: object | None = None
    human_interventions: int = 0
    human_interventions_recorded: bool = False

    unmeasured: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.n_measured + self.n_errored != self.n_trials:
            raise FreezeError(
                f"arm {self.arm!r}: {self.n_measured} measured + "
                f"{self.n_errored} errored != {self.n_trials} trials -- a lost "
                "trial corrupts every rate computed from this summary")

    @property
    def is_complete(self) -> bool:
        """True only when all nine measures were computable. A summary with
        absences is still publishable -- it just may not be quoted as if every
        measure had been taken."""
        return not self.unmeasured


def summarize_arm(arm: str, trials: Sequence[TrialResult]) -> ArmSummary:
    """Compose the nine measures for one arm's trials.

    Each sibling module is imported lazily and called defensively: a refusal
    (``FreezeError``) is recorded in ``unmeasured`` with its message rather than
    propagated, because "diversity needs at least two candidates" is a fact
    about this run, not a crash. A non-refusal exception is NOT swallowed.
    """
    # Imported from the sibling MODULE, not `from . import measures`: the
    # latter edges through this package's __init__, which imports summary --
    # a cycle, and the repo's SCC contract test catches it (it did).
    from .measures import (best_so_far_auc, compute, success_rate, token_usage,
                           wall_time)

    if not trials:
        raise FreezeError(f"arm {arm!r} has no trials to summarize")
    wrong = sorted({t.arm for t in trials} - {arm})
    if wrong:
        raise FreezeError(
            f"summarize_arm({arm!r}) received trials from other arms {wrong}; "
            "arms are summarized separately, never blended")

    measured, errored = partition_trials(trials)
    unmeasured: dict[str, str] = {}

    sr = success_rate(trials)
    wt = wall_time(trials)
    tu = token_usage(trials)
    cp = compute(trials)
    auc = best_so_far_auc(trials)
    if auc is None:
        unmeasured["best_so_far_auc"] = "no measured trial carried a score"

    variance = _optional(unmeasured, "variance",
                         lambda: _call("statistics", "variance_across_seeds", trials))
    diversity = _optional(unmeasured, "diversity",
                          lambda: _call("diversity", "diversity_of_trials", trials))
    interventions = _optional(unmeasured, "human_interventions",
                              lambda: _call("regressions", "human_interventions", trials))

    total_interventions = sum(t.human_interventions for t in trials)
    recorded = getattr(interventions, "recorded", None)

    return ArmSummary(
        arm=arm,
        n_trials=len(trials),
        n_measured=len(measured),
        n_errored=len(errored),
        success_rate=getattr(sr, "rate", None),
        best_so_far_auc=auc,
        wall_seconds_total=getattr(wt, "total_seconds", 0.0),
        tokens_total=getattr(tu, "total_tokens", 0),
        tokenizer=getattr(tu, "tokenizer", "unknown"),
        compute_proxy=getattr(cp, "proxy_value", None),
        variance=variance,
        diversity=diversity,
        regressions=None,  # needs a baseline run; see summarize_against_baseline
        human_interventions=total_interventions,
        human_interventions_recorded=bool(recorded) if recorded is not None
        else total_interventions > 0,
        unmeasured=unmeasured,
    )


def summarize_arms(trials: Sequence[TrialResult]) -> dict[str, ArmSummary]:
    """One summary per arm, keyed by arm name. Never a blended total."""
    by_arm: dict[str, list[TrialResult]] = {}
    for t in trials:
        by_arm.setdefault(t.arm, []).append(t)
    return {arm: summarize_arm(arm, rows) for arm, rows in sorted(by_arm.items())}


def _call(module_name: str, fn_name: str, trials: Sequence[TrialResult]):
    import importlib

    mod = importlib.import_module(f"{__package__}.{module_name}")
    return getattr(mod, fn_name)(trials)


def _optional(unmeasured: dict[str, str], key: str, fn):
    """Run ``fn``; record a refusal instead of raising.

    Only ``FreezeError`` is caught -- that is this package's "I refuse to
    report a number I did not measure" signal. Anything else is a genuine
    fault and stays loud.
    """
    try:
        return fn()
    except FreezeError as exc:
        unmeasured[key] = str(exc)
        return None
