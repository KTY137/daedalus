"""Uncertainty for a twenty-case task set.

Twenty cases is a small sample, and a small sample quoted as a bare point
estimate is how a harness starts lying politely.  The plan asks for
"repeated trials, uncertainty, and relevant baselines" (invariant 9), so
every headline number here carries a bootstrap interval, and every
comparison between two retrievers is **paired** -- resampled over the same
cases for both, because the cases differ far more from each other than the
retrievers differ on any one case.

These are percentile bootstrap intervals over cases, with a fixed seed so a
rerun reproduces them exactly.  They quantify sampling noise across *these*
cases from *this* repository.  They say nothing about whether the result
transfers to another repository -- that needs another corpus, not more
resamples.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

DEFAULT_RESAMPLES = 2000
DEFAULT_SEED = 20260818


@dataclass(frozen=True)
class Interval:
    """A point estimate with a percentile bootstrap interval."""

    point: float
    low: float
    high: float
    resamples: int

    def as_dict(self) -> Dict[str, object]:
        return {
            "point": round(self.point, 4),
            "ci95_low": round(self.low, 4),
            "ci95_high": round(self.high, 4),
            "resamples": self.resamples,
        }

    def __str__(self) -> str:
        return f"{self.point:.3f} [{self.low:.3f}, {self.high:.3f}]"


def _percentiles(values: List[float], low: float, high: float) -> Tuple[float, float]:
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return (0.0, 0.0)

    def pick(p: float) -> float:
        idx = min(n - 1, max(0, int(round(p * (n - 1)))))
        return ordered[idx]

    return pick(low), pick(high)


def _indices(n: int, resamples: int, seed: int) -> List[List[int]]:
    rng = random.Random(seed)
    return [[rng.randrange(n) for _ in range(n)] for _ in range(resamples)]


def bootstrap_mean(
    per_case: Sequence[float],
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
) -> Interval:
    """Bootstrap interval for the mean of a per-case statistic."""
    n = len(per_case)
    if n == 0:
        return Interval(0.0, 0.0, 0.0, 0)
    point = sum(per_case) / n
    means = [
        sum(per_case[i] for i in draw) / n for draw in _indices(n, resamples, seed)
    ]
    low, high = _percentiles(means, 0.025, 0.975)
    return Interval(point, low, high, resamples)


@dataclass(frozen=True)
class PairedDelta:
    """A paired comparison of two retrievers over the same cases."""

    subject: str
    reference: str
    delta: Interval
    share_favouring_subject: float
    cases_better: int
    cases_worse: int
    cases_tied: int

    @property
    def separated(self) -> bool:
        """True when the interval excludes zero -- the weakest honest claim."""
        return self.delta.low > 0 or self.delta.high < 0

    def as_dict(self) -> Dict[str, object]:
        return {
            "subject": self.subject,
            "reference": self.reference,
            "delta_mean": self.delta.as_dict(),
            "share_of_resamples_favouring_subject": round(
                self.share_favouring_subject, 4
            ),
            "cases_better": self.cases_better,
            "cases_worse": self.cases_worse,
            "cases_tied": self.cases_tied,
            "interval_excludes_zero": self.separated,
        }


def paired_delta(
    subject: str,
    reference: str,
    subject_scores: Sequence[float],
    reference_scores: Sequence[float],
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
) -> PairedDelta:
    """Bootstrap the per-case difference ``subject - reference``.

    Both arms are resampled with the *same* case indices, which is the
    entire point: an unpaired comparison on twenty heterogeneous cases would
    drown a real difference in between-case variance.
    """
    if len(subject_scores) != len(reference_scores):
        raise ValueError("paired comparison needs one score per case on both sides")
    diffs = [s - r for s, r in zip(subject_scores, reference_scores)]
    n = len(diffs)
    if n == 0:
        return PairedDelta(subject, reference, Interval(0.0, 0.0, 0.0, 0), 0.0, 0, 0, 0)

    interval = bootstrap_mean(diffs, resamples, seed)
    means = [sum(diffs[i] for i in draw) / n for draw in _indices(n, resamples, seed)]
    favouring = sum(1 for m in means if m > 0) / len(means)
    return PairedDelta(
        subject=subject,
        reference=reference,
        delta=interval,
        share_favouring_subject=favouring,
        cases_better=sum(1 for d in diffs if d > 0),
        cases_worse=sum(1 for d in diffs if d < 0),
        cases_tied=sum(1 for d in diffs if d == 0),
    )


def comparison_table(deltas: Sequence[PairedDelta]) -> str:
    # ASCII only: this prints to a cp1252 console on Windows, where a Greek
    # delta raises UnicodeEncodeError and takes the whole run down with it.
    head = [
        "subject", "vs reference", "delta MRR (95% CI)", "resamples favouring",
        "better/worse/tied", "excludes 0",
    ]
    lines = ["| " + " | ".join(head) + " |"]
    lines.append("| " + " | ".join(["---"] * len(head)) + " |")
    for d in deltas:
        lines.append(
            "| "
            + " | ".join(
                [
                    d.subject,
                    d.reference,
                    str(d.delta),
                    f"{d.share_favouring_subject:.0%}",
                    f"{d.cases_better}/{d.cases_worse}/{d.cases_tied}",
                    "yes" if d.separated else "no",
                ]
            )
            + " |"
        )
    return "\n".join(lines)
