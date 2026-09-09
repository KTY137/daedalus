"""Does fusion's gain concentrate where cross-plane gold is? The placebo check, run.

The cross-plane task set was built with two strata and said why
(`taskset_xplane.json::census.not_sampled`):

    The control is a placebo, not a second measurement: it exists to check
    whether a cross-plane method's gain concentrates where cross-plane gold is.

That check appears never to have been run. s10 reports one number over all 88
cases, and `case_groups` in the kill input is empty, so the criteria evaluate
the pooled mean and the strata are invisible to them.

This matters more than sample size. A pooled INCONCLUSIVE at n=88 says "we
cannot tell yet". A stratified result says something the pooled number cannot,
in either direction, AT THE SAME n:

* effect concentrated in the cross-plane stratum and ~0 in the control is the
  signature the mechanism predicts -- weak evidence FOR, and a reason the
  pooled estimate is diluted;
* effect equal in both strata means whatever fusion is buying has nothing to do
  with crossing planes, and the mechanism's story is wrong even if the pooled
  mean is positive;
* effect concentrated in the CONTROL is worse than either.

Recovering the strata: the kill input carries `gold_planes` only for cases whose
gold sits in exactly one plane (30 of them). The other 58 are the cross-plane
stratum. That is the same 58/30 split the taskset census reports, checked here
rather than assumed.

Read-only. Changes nothing, re-runs no retriever.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = (
    REPO / "experiments" / "forest_v2" / "s09_eval" / "results" / "s10_adapter_runs"
    / "kill_input_xplane88_fusion_2026-08-24.json"
)

COMPARISONS = (
    ("14.1", "fusion_rrf/raw#full", "code_only_bm25/raw#code_only"),
    ("14.1", "fusion_rrf/raw#full", "bm25/raw"),
    ("14.3", "fusion_rrf/raw#fusion", "separate_indices_bm25/raw#separate_indices"),
)


def _scores(payload: dict, arm_id: str) -> dict[str, float]:
    for arm in payload["arms"]:
        if arm["arm_id"] == arm_id:
            return arm["scores"]["reciprocal_rank"]
    raise SystemExit(f"arm not found: {arm_id}")


def _bootstrap(deltas, *, resamples: int, seed: int, confidence: float = 0.95):
    rng = random.Random(seed)
    n = len(deltas)
    if n == 0:
        return (float("nan"), float("nan"))
    means = []
    for _ in range(resamples):
        means.append(sum(deltas[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    lo = means[int((1.0 - confidence) / 2.0 * resamples)]
    hi = means[int((1.0 + confidence) / 2.0 * resamples) - 1]
    return lo, hi


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--resamples", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20260818)
    parser.add_argument("--json", dest="as_json", action="store_true")
    args = parser.parse_args(argv)

    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    cases = payload["cases"]
    single_plane = payload["gold_planes"]
    control = [c for c in cases if c in single_plane]
    cross = [c for c in cases if c not in single_plane]

    out: dict[str, object] = {
        "n_total": len(cases),
        "n_cross_plane": len(cross),
        "n_control_single_plane": len(control),
        "comparisons": [],
    }

    for criterion, subject, reference in COMPARISONS:
        s = _scores(payload, subject)
        r = _scores(payload, reference)
        row: dict[str, object] = {
            "criterion": criterion,
            "subject": subject,
            "reference": reference,
            "strata": {},
        }
        for name, group in (
            ("pooled", cases),
            ("cross_plane", cross),
            ("control_single_plane", control),
        ):
            deltas = [s[c] - r[c] for c in group]
            point = sum(deltas) / len(deltas)
            lo, hi = _bootstrap(
                deltas, resamples=args.resamples, seed=args.seed
            )
            row["strata"][name] = {
                "n": len(deltas),
                "point": round(point, 6),
                "ci95_low": round(lo, 6),
                "ci95_high": round(hi, 6),
                "excludes_zero": bool(lo > 0 or hi < 0),
                "wins": sum(1 for d in deltas if d > 0),
                "losses": sum(1 for d in deltas if d < 0),
                "ties": sum(1 for d in deltas if d == 0),
            }
        out["comparisons"].append(row)

    if args.as_json:
        print(json.dumps(out, indent=1, sort_keys=True))
        return 0

    print("=" * 78)
    print("Stratified fusion effect -- does the gain sit where cross-plane gold is?")
    print("=" * 78)
    print(f"cases {out['n_total']}   cross-plane {out['n_cross_plane']}   "
          f"single-plane control {out['n_control_single_plane']}")
    print()
    for row in out["comparisons"]:
        print(f"--- {row['criterion']}  {row['subject']}")
        print(f"           vs {row['reference']}")
        for name in ("pooled", "cross_plane", "control_single_plane"):
            st = row["strata"][name]
            flag = "  *excludes 0*" if st["excludes_zero"] else ""
            print(f"    {name:<22} n={st['n']:>3}  point={st['point']:+.4f}  "
                  f"CI95=[{st['ci95_low']:+.4f},{st['ci95_high']:+.4f}]  "
                  f"w/l/t={st['wins']}/{st['losses']}/{st['ties']}{flag}")
        cross_pt = row["strata"]["cross_plane"]["point"]
        ctrl_pt = row["strata"]["control_single_plane"]["point"]
        print(f"    cross-plane minus control: {cross_pt - ctrl_pt:+.4f}")
        print()
    print("Reading: the mechanism predicts a POSITIVE cross-plane point and a")
    print("control point near zero. Equal effects in both strata mean whatever")
    print("fusion buys is not about crossing planes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
