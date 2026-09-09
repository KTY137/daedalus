"""Apply G2-TENSOR-CENSUS-01's frozen decision rule to a census report.

The benchmark harness computes its own comparisons, but only on
``reciprocal_rank``.  The pre-registration named **recall@10** primary and the
s09 ``paired_delta`` bootstrap (10 000 resamples, seed 20260818, margin +/-0.02)
as the rule.  Reading the harness's RR-only comparison instead would be reading
a different protocol from the frozen one, so this recomputes from the retained
per-case metrics rather than substituting what is convenient.

Seeds are averaged within a case before pairing, mirroring the harness's own
``_mean_seed_metric``: the frozen hash seeds are repeated views of one case, not
independent samples.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Dict, List, Sequence

if __package__ in (None, ""):  # pragma: no cover - direct execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from experiments.forest_v2.s09_eval import stats  # noqa: E402

RESAMPLES = 10_000
SEED = 20260818
MARGIN = 0.02
PRIMARY = "structured_contraction"
CONTROL = "plane_label_permutation"
REFERENCE = "flattened_cosine_same_scalars"
IDENTITY = "identity_contraction"
IDENTITY_TOLERANCE = 1e-10


def per_case(report: dict, arm: str, metric: str) -> Dict[str, float]:
    """Mean over frozen seeds, keyed by case."""
    seeds = report["arms"][arm]
    out: Dict[str, List[float]] = {}
    for _seed, block in sorted(seeds.items()):
        for case_key, metrics in block["per_case"].items():
            out.setdefault(case_key, []).append(float(metrics[metric]))
    return {key: statistics.fmean(vals) for key, vals in sorted(out.items())}


def verdict(low: float, high: float) -> str:
    """The five frozen branches, applied mechanically."""
    if low > 0.0:
        return "LABELS_CARRY_INFORMATION"
    if high < 0.0:
        return "LABELS_HARM"
    if low >= -MARGIN and high <= MARGIN:
        return "LABELS_NULL"
    return "INCONCLUSIVE"


def analyse(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    report = payload["report"]

    # Validity gate first: a failed identity check means nothing is read.
    left = per_case(report, IDENTITY, "reciprocal_rank")
    right = per_case(report, REFERENCE, "reciprocal_rank")
    drift = max(
        (abs(left[k] - right[k]) for k in left.keys() & right.keys()), default=0.0
    )
    valid = drift <= IDENTITY_TOLERANCE

    rows = []
    for label, subject, reference in (
        ("primary", PRIMARY, CONTROL),
        ("secondary", PRIMARY, REFERENCE),
    ):
        for metric in ("recall_at_10", "reciprocal_rank"):
            a = per_case(report, subject, metric)
            b = per_case(report, reference, metric)
            keys = sorted(a.keys() & b.keys())
            delta = stats.paired_delta(
                subject,
                reference,
                [a[k] for k in keys],
                [b[k] for k in keys],
                resamples=RESAMPLES,
                seed=SEED,
                variant=payload.get("variant", ""),
            ).as_dict()
            dm = delta["delta_mean"]
            rows.append(
                {
                    "comparison": label,
                    "metric": metric,
                    "subject": subject,
                    "reference": reference,
                    "subject_mean": round(statistics.fmean(a[k] for k in keys), 5),
                    "reference_mean": round(statistics.fmean(b[k] for k in keys), 5),
                    "point": round(dm["point"], 5),
                    "ci95_low": round(dm["ci95_low"], 5),
                    "ci95_high": round(dm["ci95_high"], 5),
                    "cases": len(keys),
                    "verdict": verdict(dm["ci95_low"], dm["ci95_high"]),
                }
            )

    return {
        "variant": payload.get("variant"),
        "cases_built": payload.get("cases_built"),
        "mean_universe": payload.get("mean_universe"),
        "seconds_benchmark": payload.get("seconds_benchmark"),
        "identity_check": {
            "max_abs_drift": drift,
            "tolerance": IDENTITY_TOLERANCE,
            "valid": valid,
        },
        "rows": rows,
        "overall": "INVALID" if not valid else None,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="read a tensor census report")
    parser.add_argument("report", nargs="+")
    args = parser.parse_args(argv)
    for item in args.report:
        print(json.dumps(analyse(Path(item)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
