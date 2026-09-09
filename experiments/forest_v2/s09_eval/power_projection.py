"""How many cases would make criterion 14.1 / 14.3 DECIDABLE, and can this repo supply them?

s10 reports INCONCLUSIVE for the only two criteria the cross-plane run can
reach. "Inconclusive" is not a property of the method under test -- it is a
property of the sample -- so the useful question is the one s10 does not
answer: how many cases would it take, and are they available?

The projection is deliberately simple and its assumption is stated rather than
buried: a percentile-bootstrap interval half-width shrinks as 1/sqrt(n) when
the per-case difference distribution is unchanged. Drawing more cases from the
same repository at the same anchor is exactly the regime where that holds
best, so the numbers below are the OPTIMISTIC bound. If more cases are drawn
from other repositories the variance will very likely rise, and the required n
rises with it.

Reads the retained s10 kill-input, re-derives the intervals through the same
stats module s10 itself uses, and prints the decisive-n windows. Writes
nothing.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = (
    REPO / "experiments" / "forest_v2" / "s09_eval" / "results" / "s10_adapter_runs"
    / "kill_input_xplane88_fusion_2026-08-24.json"
)
DEFAULT_TASKSET = (
    REPO / "experiments" / "forest_v2" / "s09_eval" / "taskset_xplane.json"
)

#: The comparisons s10 actually decides on this run, by (subject, reference)
#: arm_id. Named explicitly so this script cannot quietly project a different
#: pair than the one the report printed.
COMPARISONS = (
    ("14.1", "fusion_rrf/raw#full", "code_only_bm25/raw#code_only"),
    ("14.1", "fusion_rrf/raw#full", "bm25/raw"),
    ("14.3", "fusion_rrf/raw#fusion", "separate_indices_bm25/raw#separate_indices"),
)


def _scores(payload: dict, arm_id: str) -> dict[str, float]:
    for arm in payload["arms"]:
        if arm["arm_id"] == arm_id:
            return arm["scores"]["reciprocal_rank"]
    raise SystemExit(f"arm not found in kill input: {arm_id}")


def _bootstrap(deltas: list[float], *, resamples: int, seed: int, confidence: float):
    import random

    rng = random.Random(seed)
    n = len(deltas)
    means = []
    for _ in range(resamples):
        means.append(sum(deltas[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    lo_i = int((1.0 - confidence) / 2.0 * resamples)
    hi_i = int((1.0 + confidence) / 2.0 * resamples) - 1
    return means[lo_i], means[hi_i]


def _n_for_halfwidth(n0: int, h0: float, target: float) -> float:
    """n such that h0 * sqrt(n0/n) == target."""
    if target <= 0:
        return math.inf
    return n0 * (h0 / target) ** 2


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--taskset", default=str(DEFAULT_TASKSET))
    parser.add_argument("--margin", type=float, default=0.02)
    parser.add_argument("--confidence", type=float, default=0.95)
    parser.add_argument("--resamples", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20260818)
    args = parser.parse_args(argv)

    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    cases = payload["cases"]

    print("=" * 78)
    print("Decisive-n projection for the criteria s10 reports INCONCLUSIVE")
    print("=" * 78)
    print(f"run          {payload['run_id']}")
    print(f"margin       +/-{args.margin}   confidence {args.confidence}")
    print(f"cases now    {len(cases)}")
    print()
    print("ASSUMPTION, stated because it is the whole projection: the bootstrap")
    print("half-width shrinks as 1/sqrt(n) with the per-case difference")
    print("distribution unchanged. This is the OPTIMISTIC bound.")
    print()

    for criterion, subject, reference in COMPARISONS:
        s = _scores(payload, subject)
        r = _scores(payload, reference)
        deltas = [s[c] - r[c] for c in cases]
        point = sum(deltas) / len(deltas)
        lo, hi = _bootstrap(
            deltas,
            resamples=args.resamples,
            seed=args.seed,
            confidence=args.confidence,
        )
        h = (hi - lo) / 2.0
        n0 = len(deltas)

        # SUPERIOR needs ci_low > 0            -> h < point
        # EQUIVALENT needs ci_high < margin    -> h < margin - point
        n_superior = _n_for_halfwidth(n0, h, point) if point > 0 else math.inf
        n_equivalent = (
            _n_for_halfwidth(n0, h, args.margin - point)
            if args.margin - point > 0
            else math.inf
        )

        print(f"--- {criterion}  {subject}")
        print(f"           vs {reference}")
        print(f"    point={point:+.4f}  CI95=[{lo:+.4f},{hi:+.4f}]  halfwidth={h:.4f}  n={n0}")
        print(f"    n for SUPERIOR   (CI excludes 0):        {n_superior:>12,.0f}"
              f"   ({n_superior / n0:.0f}x)")
        print(f"    n for EQUIVALENT (CI inside +/-{args.margin}):    {n_equivalent:>12,.0f}"
              f"   ({n_equivalent / n0:.0f}x)")
        if point < args.margin:
            print(f"    NOTE: the observed effect ({point:+.4f}) is SMALLER than the")
            print(f"          equivalence margin ({args.margin}). Both verdicts stay")
            print("          reachable, but a 'this beats the baseline' reading needs")
            print("          the narrower window, not the wider one.")
        print()

    taskset = json.loads(Path(args.taskset).read_text(encoding="utf-8"))
    supply = taskset["census"]["supply"]
    print("=" * 78)
    print("SUPPLY, from the taskset census (re-derived 2026-09-09, digest identical)")
    print("=" * 78)
    print(f"  commits considered in reachable history : {taskset['census']['commits_considered']:>6,}")
    print(f"  admissible                              : {taskset['census']['commits_admissible']:>6,}")
    print(f"  cross-plane admissible                  : {supply['cross_plane_admissible']:>6,}")
    print(f"  cross-plane accepted                    : {supply['cross_plane_accepted']:>6,}")
    print(f"  cross-plane UNUSED                      : {supply['cross_plane_unused']:>6,}")
    print()
    print("  " + str(supply["note"])[:400])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
