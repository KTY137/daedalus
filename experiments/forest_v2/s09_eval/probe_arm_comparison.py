"""Paired comparison of any two arms, stratified, straight from a harness run.

``probe_stratified_fusion_effect`` reads an s10 kill-input, which requires every
arm to carry an s10 ROLE. ``plane_calibrated`` deliberately has no role: it is a
candidate arm under test, not one of the plan's named baselines, and inventing a
role for it would let it be compared under a label it has not earned.

So this probe reads the harness output directly. Same metric
(``reciprocal_rank``), same bootstrap, same seed, same margin, same
cross-plane / single-plane split rule as the stratified probe -- only the arm
selection is free.

Read-only. Re-runs nothing and changes nothing.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


def _scores(raw: dict, retriever: str, variant: str) -> dict[str, float]:
    out = {
        row["case_id"]: float(row["reciprocal_rank"])
        for row in raw["per_case"]
        if row["retriever"] == retriever and row["variant"] == variant
    }
    if not out:
        raise SystemExit(f"no per-case rows for {retriever!r} variant={variant!r}")
    return out


def _bootstrap(deltas, *, resamples: int, seed: int, confidence: float = 0.95):
    rng = random.Random(seed)
    n = len(deltas)
    if n == 0:
        return float("nan"), float("nan")
    means = []
    for _ in range(resamples):
        means.append(sum(deltas[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    return (
        means[int((1.0 - confidence) / 2.0 * resamples)],
        means[int((1.0 + confidence) / 2.0 * resamples) - 1],
    )


def compare(raw: dict, subject: str, reference: str, *, variant: str,
            cross: set[str], resamples: int, seed: int) -> dict:
    s, r = _scores(raw, subject, variant), _scores(raw, reference, variant)
    cases = sorted(set(s) & set(r))
    strata = {}
    for name, group in (
        ("pooled", cases),
        ("cross_plane", [c for c in cases if c in cross]),
        ("control_single_plane", [c for c in cases if c not in cross]),
    ):
        deltas = [s[c] - r[c] for c in group]
        if not deltas:
            continue
        point = sum(deltas) / len(deltas)
        lo, hi = _bootstrap(deltas, resamples=resamples, seed=seed)
        strata[name] = {
            "n": len(deltas),
            "point": round(point, 6),
            "ci95_low": round(lo, 6),
            "ci95_high": round(hi, 6),
            "excludes_zero": bool(lo > 0 or hi < 0),
            "wins": sum(1 for d in deltas if d > 0),
            "losses": sum(1 for d in deltas if d < 0),
            "ties": sum(1 for d in deltas if d == 0),
        }
    return {"subject": subject, "reference": reference, "variant": variant,
            "strata": strata}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw", required=True)
    parser.add_argument("--taskset", required=True)
    parser.add_argument(
        "--pair", action="append", required=True, metavar="SUBJECT:REFERENCE",
    )
    parser.add_argument("--variant", default="raw")
    parser.add_argument("--resamples", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20260818)
    parser.add_argument("--json", dest="as_json", action="store_true")
    args = parser.parse_args(argv)

    raw = json.loads(Path(args.raw).read_text(encoding="utf-8"))
    taskset = json.loads(Path(args.taskset).read_text(encoding="utf-8"))

    # Same rule the stratified probe uses: a case is CONTROL when its gold sits
    # in exactly one Twin plane. Derived from the task set's own answer key, not
    # from the harness output, which does not carry it.
    cross: set[str] = set()
    for case in taskset["cases"]:
        planes = case.get("gold_planes") or case.get("twin_planes") or []
        if len(planes) > 1:
            cross.add(case["case_id"])

    results = [
        compare(raw, *pair.split(":", 1), variant=args.variant,
                cross=cross, resamples=args.resamples, seed=args.seed)
        for pair in args.pair
    ]
    payload = {
        "taskset_digest": taskset.get("digest"),
        "variant": args.variant,
        "cross_plane_cases": len(cross),
        "comparisons": results,
    }
    if args.as_json:
        print(json.dumps(payload, indent=1, sort_keys=True))
        return 0

    print("=" * 76)
    print(f"Paired arm comparison   variant={args.variant}   "
          f"cross-plane cases={len(cross)}")
    print("=" * 76)
    for row in results:
        print(f"--- {row['subject']}  vs  {row['reference']}")
        for name in ("pooled", "cross_plane", "control_single_plane"):
            st = row["strata"].get(name)
            if not st:
                continue
            flag = "  *excludes 0*" if st["excludes_zero"] else ""
            print(f"    {name:<22} n={st['n']:>4}  point={st['point']:+.4f}  "
                  f"CI95=[{st['ci95_low']:+.4f},{st['ci95_high']:+.4f}]  "
                  f"w/l/t={st['wins']}/{st['losses']}/{st['ties']}{flag}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
