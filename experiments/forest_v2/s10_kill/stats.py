"""Paired comparison statistics, pure stdlib, deterministic.

One methodological point drives this whole module, and getting it wrong is
the most common way a kill-criteria check lies:

    **A non-significant difference is not evidence of equivalence.**

Several section-14 bullets fire on *equivalence* ("degree-preserving
randomised cross-plane edges perform equivalently", "four independent
indices perform equivalently").  If those were implemented as "the
difference was not significant", then a tiny, underpowered, noisy run would
kill the prior automatically -- the less you measure, the more you kill.
That is backwards.

So every comparison here returns three separable states against a
pre-declared practical margin ``delta``:

``superior``     the CI lies entirely above 0
``inferior``     the CI lies entirely below 0
``equivalent``   the CI lies entirely inside (-delta, +delta)

None of them is the negation of another.  A wide CI is none of the three,
and the comparison honestly reports ``inconclusive``.  A very tight CI can
be *both* ``superior`` and ``equivalent`` (a real but practically
irrelevant win); the report shows both rather than picking the flattering
one.

The interval is a percentile bootstrap over the paired per-case
differences.  Bootstrap because the metrics in play (Recall@k, MRR) are
bounded, discrete and visibly non-normal, and because a resampling
interval needs no distributional story to defend.
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from statistics import fmean, pstdev
from typing import List, Optional, Sequence, Tuple

#: Default practical-equivalence margin on a 0..1 metric.  A 2-point
#: absolute difference in Recall@10 is the smallest gap this experiment is
#: willing to call "a real difference"; below it, two arms are the same
#: system as far as the plan's decisions are concerned.
DEFAULT_MARGIN = 0.02
DEFAULT_CONFIDENCE = 0.95
DEFAULT_RESAMPLES = 10_000


@dataclass(frozen=True)
class Paired:
    """The outcome of one paired comparison, with its uncertainty."""

    label: str
    treatment: str
    baseline: str
    n: int
    mean_treatment: float
    mean_baseline: float
    mean_diff: float
    ci_low: float
    ci_high: float
    confidence: float
    margin: float
    resamples: int
    wins: int
    losses: int
    ties: int
    stdev_diff: float

    @property
    def superior(self) -> bool:
        return self.ci_low > 0.0

    @property
    def inferior(self) -> bool:
        return self.ci_high < 0.0

    @property
    def equivalent(self) -> bool:
        """CI entirely inside the practical-equivalence band."""
        return self.ci_low > -self.margin and self.ci_high < self.margin

    @property
    def inconclusive(self) -> bool:
        return not (self.superior or self.inferior or self.equivalent)

    @property
    def state(self) -> str:
        """A single word for the report, precedence: real difference first."""
        if self.superior and not self.equivalent:
            return "SUPERIOR"
        if self.inferior and not self.equivalent:
            return "INFERIOR"
        if self.equivalent and self.superior:
            return "EQUIVALENT(but +)"
        if self.equivalent and self.inferior:
            return "EQUIVALENT(but -)"
        if self.equivalent:
            return "EQUIVALENT"
        return "INCONCLUSIVE"

    def describe(self) -> str:
        return (
            f"{self.treatment} vs {self.baseline}: "
            f"diff={self.mean_diff:+.4f} "
            f"CI{int(self.confidence * 100)}=[{self.ci_low:+.4f},{self.ci_high:+.4f}] "
            f"n={self.n} w/l/t={self.wins}/{self.losses}/{self.ties} "
            f"-> {self.state}"
        )


def stable_seed(base_seed: int, key: str) -> int:
    """A per-comparison seed that does not depend on evaluation order.

    Re-running one comparison in isolation must reproduce the interval it
    had inside a full report, otherwise a disputed number cannot be
    checked on its own.
    """
    digest = hashlib.sha256(f"{base_seed}:{key}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def bootstrap_ci(
    diffs: Sequence[float],
    *,
    confidence: float = DEFAULT_CONFIDENCE,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = 0,
) -> Tuple[float, float]:
    """Percentile bootstrap CI of the mean paired difference."""
    n = len(diffs)
    if n == 0:
        return (float("nan"), float("nan"))
    if n == 1:
        return (diffs[0], diffs[0])
    lo_hi = _degenerate(diffs)
    if lo_hi is not None:
        return lo_hi

    rng = random.Random(seed)
    pick = rng.choices
    means: List[float] = []
    for _ in range(resamples):
        sample = pick(diffs, k=n)
        means.append(sum(sample) / n)
    means.sort()
    alpha = (1.0 - confidence) / 2.0
    lo_idx = int(alpha * resamples)
    hi_idx = int((1.0 - alpha) * resamples) - 1
    lo_idx = max(0, min(resamples - 1, lo_idx))
    hi_idx = max(0, min(resamples - 1, hi_idx))
    return (means[lo_idx], means[hi_idx])


def _degenerate(diffs: Sequence[float]) -> Optional[Tuple[float, float]]:
    """Constant differences have a point interval; resampling adds nothing."""
    first = diffs[0]
    if all(d == first for d in diffs):
        return (first, first)
    return None


def compare(
    label: str,
    treatment_name: str,
    baseline_name: str,
    treatment: Sequence[float],
    baseline: Sequence[float],
    *,
    margin: float = DEFAULT_MARGIN,
    confidence: float = DEFAULT_CONFIDENCE,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = 0,
) -> Paired:
    """Compare two arms case-by-case.  Inputs must already be paired."""
    if len(treatment) != len(baseline):
        raise ValueError(
            f"{label}: unpaired inputs ({len(treatment)} vs {len(baseline)})"
        )
    diffs = [t - b for t, b in zip(treatment, baseline)]
    n = len(diffs)
    ci_low, ci_high = bootstrap_ci(
        diffs,
        confidence=confidence,
        resamples=resamples,
        seed=stable_seed(seed, label),
    )
    return Paired(
        label=label,
        treatment=treatment_name,
        baseline=baseline_name,
        n=n,
        mean_treatment=fmean(treatment) if n else float("nan"),
        mean_baseline=fmean(baseline) if n else float("nan"),
        mean_diff=fmean(diffs) if n else float("nan"),
        ci_low=ci_low,
        ci_high=ci_high,
        confidence=confidence,
        margin=margin,
        resamples=resamples,
        wins=sum(1 for d in diffs if d > 0),
        losses=sum(1 for d in diffs if d < 0),
        ties=sum(1 for d in diffs if d == 0),
        stdev_diff=pstdev(diffs) if n > 1 else 0.0,
    )
