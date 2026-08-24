"""Run the s09 measurement machinery against the cross-plane corpus.

``harness.py:main`` is wired to slice s09's *first* task set (``taskset.py``,
schema ``forest_v2.s09.taskset/2``, 20 cases, 91.4% Python gold) and cannot
score the second one (``taskset_xplane.py``, schema
``forest_v2.s09.taskset_xplane/1``, 88 cases, 58 of them cross-plane) without
help: ``XCase`` stores its two query variants as plain fields
(``query_raw``/``query_scrubbed``) instead of the ``Case.query(variant)``
method ``harness.run`` calls, and ``main`` hardcodes ``taskset.load``.  This
module is that help -- a thin view that gives an ``XCase`` the one missing
method, and a CLI that calls the *same* ``harness.run`` slice s09 already
ships, on the corpus that slice s09's own README calls "an instrument
awaiting a subject" (continuation 2, 2026-08-18).  No scoring logic, no
statistics, no retriever is duplicated here; only the wiring that lets an
existing runner see a second, already-frozen corpus.

Written for the s09->s10 adapter (``to_s10.py``): the primary 20-case corpus
cannot exercise the four-plane hypothesis it is asked to grade (91.4% Python
gold, 3/20 cases span a plane, 0/20 touch Type) -- correction F4 in the
README says so in words. The cross-plane corpus can be asked; this is what
lets it be asked for real, against the two baselines that exist for real
(``bm25``, ``random_uniform``), not a fabricated fusion arm.

**This module is an effectful entrypoint.**  ``main`` writes a results JSON
(default ``results/raw_xplane.json``) unless ``--no-write`` is passed, the
same way ``harness.py:main`` does and for the same undeclared reason: the
forest_v2 README's boundary note already states that ``experiments/`` is
outside ``daedalus/spine/effect_boundary.py``'s ``HARNESS_PACKAGES`` scan.
This entrypoint is added to that note's table rather than silently added
next to it. It writes only under ``experiments/forest_v2/s09_eval/results/``;
it performs no network egress, no spend, and no model call -- it reads git
plumbing (via ``gitio``, already read-only-gated) and file content only.

Usage::

    python -m experiments.forest_v2.s09_eval.run_xplane_harness
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Sequence

if __package__ in (None, ""):  # pragma: no cover - direct-script convenience
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from s09_eval import harness, retrievers as baselines, stats, taskset_xplane
    from s09_eval.contract import Budget
    from s09_eval.tokens import TokenCache
else:
    from . import harness, retrievers as baselines, stats, taskset_xplane
    from .contract import Budget
    from .tokens import TokenCache

RESULTS_DIR = Path(__file__).resolve().parent / "results"
VARIANTS = ("raw", "scrubbed")


@dataclass(frozen=True)
class _XCaseView:
    """Gives an ``XCase`` the ``.query(variant)`` method ``harness.run`` calls.

    Everything else ``run`` needs (``case_id``, ``parent``, ``gold``) is
    already a field on ``XCase`` with the identical name and meaning as the
    primary corpus's ``Case`` -- only the query accessor differs in shape,
    because the cross-plane corpus stores both variants as plain strings
    rather than a method. No scoring or selection logic lives here.
    """

    inner: object  # taskset_xplane.XCase; kept untyped to avoid importing it twice

    @property
    def case_id(self) -> str:
        return self.inner.case_id

    @property
    def parent(self) -> str:
        return self.inner.parent

    @property
    def gold(self):
        return self.inner.gold

    def query(self, variant: str) -> str:
        if variant == "raw":
            return self.inner.query_raw
        if variant == "scrubbed":
            return self.inner.query_scrubbed
        raise ValueError(f"the cross-plane corpus has no {variant!r} variant")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[3]))
    parser.add_argument("--taskset", default=str(taskset_xplane.DEFAULT_PATH))
    parser.add_argument("--variant", choices=(*VARIANTS, "both"), default="both")
    parser.add_argument("--limit-cases", type=int, default=0)
    parser.add_argument(
        "--reference", default="recency_prior",
        help="retriever every other one is paired against (default: the query-blind prior)",
    )
    parser.add_argument("--out", default=str(RESULTS_DIR / "raw_xplane.json"))
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)

    record, xcases = taskset_xplane.load(Path(args.taskset))  # digest verified on load
    cases = [_XCaseView(c) for c in xcases]
    if args.limit_cases:
        cases = cases[: args.limit_cases]
    variants = VARIANTS if args.variant == "both" else (args.variant,)

    budget = Budget()
    cache = TokenCache()
    repo = Path(args.repo)
    # Baselines only, deliberately: no --retriever hook here, because a
    # foreign arm would need pre-image isolation (see harness.py) and this
    # runner exists to exercise the corpus, not to add isolation machinery
    # a second time. The five baselines are auditable in-tree, same as a
    # baselines-only run of harness.py.
    suite = list(baselines.default_suite(cache))

    started = time.perf_counter()
    aggregates, per_case, cost, rr = harness.run(repo, cases, suite, budget, variants, cache)
    cost["wall_seconds_total"] = round(time.perf_counter() - started, 2)
    cost["preimage_isolation"] = False

    names = [getattr(r, "name", type(r).__name__) for r in suite]
    reference = args.reference if args.reference in names else names[0]

    intervals: Dict[str, Dict[str, object]] = {}
    comparisons = []
    for variant in variants:
        for name in names:
            key = f"{name}|{variant}"
            intervals[key] = stats.bootstrap_mean(rr[(name, variant)]).as_dict()
        deltas = [
            stats.paired_delta(
                name, reference, rr[(name, variant)], rr[(reference, variant)], variant=variant
            )
            for name in names
            if name != reference
        ]
        deltas.sort(key=lambda d: -d.delta.point)
        comparisons.extend(deltas)

    payload = {
        # Same results schema harness.py emits -- to_s10.py reads either
        # without caring which corpus produced it.
        "schema": "forest_v2.s09.results/1",
        "taskset_schema": record["schema"],
        "taskset_digest": record["digest"],
        "taskset_anchor": record["anchor_commit"],
        "cases": len(cases),
        "budget": budget.as_dict(),
        "retrievers": names,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "cost": cost,
        "aggregates": [a.as_dict() for a in aggregates],
        "mrr_intervals": intervals,
        "paired_comparisons": harness.comparison_payload(comparisons),
        "reference_retriever": reference,
        "paired_comparisons_key": ["subject", "reference", "variant"],
        "per_case": per_case,
    }
    if not args.no_write:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {out}")
    print("cost " + json.dumps(cost, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
