"""The runner: measure any retriever on the frozen set under one budget.

What "budget-equal" means here, concretely, because the phrase is easy to
claim and easy to fake:

* every retriever sees the **same candidate universe object** for a case --
  the same paths, the same truncated bytes, built once;
* every retriever is capped at the **same bytes per file**
  (``Budget.content_budget_bytes``) -- extra context cannot be bought;
* every retriever is scored at the **same cutoffs**, and its ranking is
  truncated to the largest one before scoring;
* tokenization is **pre-warmed once per case** and reported as a shared
  indexing cost, so per-retriever timings do not depend on run order;
* a ranking that names a path outside the universe, or repeats one, aborts
  the run instead of quietly scoring.

Usage::

    python -m experiments.forest_v2.s09_eval.harness              # baselines
    python -m experiments.forest_v2.s09_eval.harness \\
        --retriever s07_module:MyRetriever --retriever s08_module:factory

s07/s08 and any later fusion attach through ``module:attribute`` specs.  This
package never imports them.
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Dict, List, Sequence, Tuple

if __package__ in (None, ""):  # pragma: no cover - direct-script convenience
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from s09_eval import gitio, metrics, retrievers as baselines, stats, taskset
    from s09_eval.contract import Budget, Candidate, QueryView, load_retriever, validate_ranking
    from s09_eval.tokens import TokenCache
else:
    from . import gitio, metrics, retrievers as baselines, stats, taskset
    from .contract import Budget, Candidate, QueryView, load_retriever, validate_ranking
    from .tokens import TokenCache

RESULTS_DIR = Path(__file__).resolve().parent / "results"
VARIANTS = ("raw", "scrubbed")


class BlobStore:
    """Bounded cache of truncated blob bytes, shared across cases.

    Parent trees overlap heavily, so fetching only the blobs not already
    held turns twenty full-tree reads into one plus the deltas.  The cap is
    a byte budget, not an entry count, so a few large files cannot quietly
    grow the process.
    """

    def __init__(self, repo: Path, budget: Budget, max_bytes: int = 256 * 1024 * 1024):
        self.repo = repo
        self.budget = budget
        self.max_bytes = max_bytes
        self._data: Dict[str, bytes] = {}
        self._held = 0
        self.fetched = 0
        self.reused = 0

    def ensure(self, shas: Sequence[str]) -> None:
        missing = [s for s in dict.fromkeys(shas) if s not in self._data]
        self.reused += len(shas) - len(missing)
        if not missing:
            return
        blobs = gitio.read_blobs(self.repo, missing)
        self.fetched += len(blobs)
        for sha, payload in blobs.items():
            clipped = payload[: self.budget.content_budget_bytes]
            if self._held + len(clipped) > self.max_bytes:
                self._data.clear()
                self._held = 0
            self._data[sha] = clipped
            self._held += len(clipped)

    def get(self, sha: str) -> bytes:
        return self._data.get(sha, b"")


def build_universe(
    repo: Path, case: taskset.Case, budget: Budget, store: BlobStore
) -> List[Candidate]:
    """The pre-image tree, filtered by the frozen eligibility rule."""
    tree = gitio.list_tree(repo, case.parent)
    eligible = [
        (path, blob, size)
        for path, (blob, size) in sorted(tree.items())
        if budget.eligible(path, size)
    ]
    store.ensure([blob for _, blob, _ in eligible])
    return [
        Candidate(
            path=path,
            blob=blob,
            size=size,
            raw=store.get(blob),
            content_budget=budget.content_budget_bytes,
        )
        for path, blob, size in eligible
    ]


def run(
    repo: Path,
    cases: Sequence[taskset.Case],
    suite: Sequence[object],
    budget: Budget,
    variants: Sequence[str],
    cache: TokenCache,
    universe_provider: Callable[[taskset.Case], List[Candidate]] | None = None,
) -> Tuple[
    List[metrics.Aggregate],
    List[Dict[str, object]],
    Dict[str, object],
    Dict[Tuple[str, str], List[float]],
]:
    """Score every retriever on every case under one budget.

    ``universe_provider`` exists so the budget-equality rules can be tested
    without a repository; production runs leave it at the git-backed default.
    """
    store = BlobStore(repo, budget)
    provide = universe_provider or (lambda case: build_universe(repo, case, budget, store))
    per_case: List[Dict[str, object]] = []
    scores: Dict[Tuple[str, str], List[metrics.CaseScore]] = {
        (getattr(r, "name", type(r).__name__), v): [] for r in suite for v in variants
    }
    index_seconds = 0.0
    rank_seconds: Dict[str, float] = {getattr(r, "name", type(r).__name__): 0.0 for r in suite}
    universe_sizes: List[int] = []

    for case in cases:
        universe = provide(case)
        universe_sizes.append(len(universe))
        if set(case.gold) - {c.path for c in universe}:
            raise RuntimeError(
                f"{case.case_id}: gold not inside the rebuilt universe -- "
                "the task set and the eligibility rule have diverged"
            )

        # shared, charged once, before anybody ranks
        started = time.perf_counter()
        for cand in universe:
            cache.counts(cand.blob, cand.text)
        index_seconds += time.perf_counter() - started

        for variant in variants:
            query = QueryView(
                case_id=case.case_id,
                text=case.query(variant),
                variant=variant,
                revision=case.parent,
            )
            for retriever in suite:
                name = getattr(retriever, "name", type(retriever).__name__)
                started = time.perf_counter()
                raw_ranking = retriever.rank(query, universe)
                rank_seconds[name] += time.perf_counter() - started
                ranking = validate_ranking(name, raw_ranking, universe, budget.max_k)
                score = metrics.score_case(case.case_id, ranking, case.gold, budget.cutoffs)
                scores[(name, variant)].append(score)
                per_case.append(
                    {
                        "case_id": case.case_id,
                        "retriever": name,
                        "variant": variant,
                        "gold_total": score.gold_total,
                        "hits_at": {str(k): v for k, v in sorted(score.hits_at.items())},
                        "first_hit_rank": score.first_hit_rank,
                        "reciprocal_rank": round(score.reciprocal_rank, 4),
                        "universe_size": len(universe),
                        "returned": len(ranking),
                    }
                )

    aggregates = [
        metrics.aggregate(name, variant, case_scores, budget.cutoffs)
        for (name, variant), case_scores in scores.items()
    ]
    aggregates.sort(key=lambda a: (a.variant, -a.mrr, a.retriever))
    reciprocal_ranks = {
        key: [s.reciprocal_rank for s in case_scores]
        for key, case_scores in scores.items()
    }

    cost = {
        "shared_index_seconds": round(index_seconds, 2),
        "rank_seconds": {k: round(v, 3) for k, v in sorted(rank_seconds.items())},
        "blobs_fetched": store.fetched,
        "blob_lookups_reused": store.reused,
        "token_cache_hits": cache.hits,
        "token_cache_misses": cache.misses,
        "universe_size_min": min(universe_sizes) if universe_sizes else 0,
        "universe_size_max": max(universe_sizes) if universe_sizes else 0,
    }
    return aggregates, per_case, cost, reciprocal_ranks


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[3]))
    parser.add_argument("--taskset", default=str(taskset.DEFAULT_PATH))
    parser.add_argument(
        "--retriever",
        action="append",
        default=[],
        metavar="module:attribute",
        help="add a retriever; repeatable. Baselines always run.",
    )
    parser.add_argument("--variant", choices=(*VARIANTS, "both"), default="both")
    parser.add_argument("--limit-cases", type=int, default=0)
    parser.add_argument(
        "--reference",
        default="recency_prior",
        help="retriever every other one is paired against (default: the query-blind prior)",
    )
    parser.add_argument("--out", default=str(RESULTS_DIR / "raw.json"))
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)

    record, cases = taskset.load(Path(args.taskset))  # digest verified on load
    if args.limit_cases:
        cases = cases[: args.limit_cases]
    variants = VARIANTS if args.variant == "both" else (args.variant,)

    budget = Budget()
    cache = TokenCache()
    repo = Path(args.repo)
    suite = list(baselines.default_suite(cache))
    for spec in args.retriever:
        suite.append(load_retriever(spec))

    started = time.perf_counter()
    aggregates, per_case, cost, rr = run(repo, cases, suite, budget, variants, cache)
    cost["wall_seconds_total"] = round(time.perf_counter() - started, 2)

    names = [getattr(r, "name", type(r).__name__) for r in suite]
    reference = args.reference if args.reference in names else names[0]

    intervals: Dict[str, Dict[str, object]] = {}
    comparisons: List[stats.PairedDelta] = []
    for variant in variants:
        rows = [a for a in aggregates if a.variant == variant]
        print(f"\n### query variant: {variant}  [MEASURED]\n")
        print(metrics.raw_table(rows, budget.cutoffs))

        for name in names:
            key = f"{name}|{variant}"
            intervals[key] = stats.bootstrap_mean(rr[(name, variant)]).as_dict()

        deltas = [
            stats.paired_delta(name, reference, rr[(name, variant)], rr[(reference, variant)])
            for name in names
            if name != reference
        ]
        deltas.sort(key=lambda d: -d.delta.point)
        comparisons.extend(deltas)
        print(
            f"\nMRR with 95% bootstrap CI over {len(cases)} cases, "
            f"paired against '{reference}'  [MEASURED]\n"
        )
        for name in sorted(names, key=lambda n: -intervals[f"{n}|{variant}"]["point"]):
            print(f"  {name:<20} MRR {intervals[f'{name}|{variant}']['point']:.3f} "
                  f"[{intervals[f'{name}|{variant}']['ci95_low']:.3f}, "
                  f"{intervals[f'{name}|{variant}']['ci95_high']:.3f}]")
        print()
        print(stats.comparison_table(deltas))

    payload = {
        "schema": "forest_v2.s09.results/1",
        "taskset_digest": record["digest"],
        "taskset_anchor": record["anchor_commit"],
        "cases": len(cases),
        "budget": budget.as_dict(),
        "retrievers": [getattr(r, "name", type(r).__name__) for r in suite],
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "cost": cost,
        "aggregates": [a.as_dict() for a in aggregates],
        "mrr_intervals": intervals,
        "paired_comparisons": [c.as_dict() for c in comparisons],
        "reference_retriever": reference,
        "per_case": per_case,
    }
    if not args.no_write:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\nwrote {out}")
    print("\ncost " + json.dumps(cost, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
