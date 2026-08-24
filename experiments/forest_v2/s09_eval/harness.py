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
  the run instead of quietly scoring;
* a retriever loaded through ``--retriever`` is graded against a **pre-image
  bare clone** by default (``--isolate-preimage``, on unless
  ``--no-isolate-preimage``), so the commit whose diff is the answer key is
  not merely unreferenced but absent from the object store it can read.

Timings are NOT a validated property of this harness.  ``rank_seconds`` and
``wall_seconds_total`` are wall-clock on a shared developer box; a re-run of
identical work measured ``bm25`` at 6.5 s against a stored 26.8 s, a 4.1x
swing that is load, not algorithm.  They are recorded for shape only and
carry a disclaimer in the payload.  Do not cite them, do not compare
retrievers by them, and do not put one in a README.

**This module is an effectful entrypoint.**  ``main`` writes ``results/raw.json``
unless ``--no-write`` is passed.  See the boundary note in the slice README:
``experiments`` is not covered by the effect scanner's ``HARNESS_PACKAGES``,
so this write is unscanned.  That gap is recorded as an escalation, not
closed here -- closing it edits kernel policy, which is owner work.

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
import tempfile
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
#: ``scrubbed_basename`` is derived from the frozen case rather than stored in
#: it, so it is available as a measurement without touching the digest.  It is
#: not in ``VARIANTS`` because the published table is the two frozen variants;
#: ask for it explicitly with ``--variant scrubbed_basename``.
EXTRA_VARIANTS = ("scrubbed_basename",)

TIMING_DISCLAIMER = (
    "rank_seconds and wall_seconds_total are unvalidated wall-clock on a "
    "shared box, not a property of the harness: a re-run of identical work "
    "measured bm25 at 6.525 s against a stored 26.806 s (4.1x). Recorded for "
    "shape only. Do not cite them and do not rank retrievers by them."
)


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


class PreimageIsolation:
    """Per-case bare clones that contain the pre-image and nothing after it.

    ``QueryView.revision`` documents "read nothing committed after the case",
    and a documented norm is what an executed probe walked straight through:
    a retriever that followed git forward from the pre-image to its own child
    commit scored MRR 1.000, 20/20 hits, fully separated -- and no check in
    this harness noticed.  That is the oracle hole, and prose cannot close it.

    One clone per case, because reachability is a property of a repository and
    not of a ref: a single clone holding every case's pre-image would still let
    an older case's answer commit be reached as an ancestor of a newer case's
    pre-image.  Clones are cached by revision and torn down with the run.
    """

    def __init__(self, repo: Path, root: Path | None = None) -> None:
        self.repo = repo
        self._tmp = None
        if root is None:
            self._tmp = tempfile.TemporaryDirectory(prefix="s09_preimage_")
            root = Path(self._tmp.name)
        self.root = Path(root)
        self._clones: Dict[str, Path] = {}
        self.built = 0

    def repo_for(self, revision: str) -> str:
        existing = self._clones.get(revision)
        if existing is not None:
            return str(existing)
        dest = self.root / revision[:12]
        gitio.make_preimage_clone(self.repo, revision, dest)
        self.built += 1
        self._clones[revision] = dest
        return str(dest)

    def close(self) -> None:
        if self._tmp is not None:
            self._tmp.cleanup()
            self._tmp = None


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


def comparison_payload(deltas: Sequence[stats.PairedDelta]) -> List[Dict[str, object]]:
    """Serialise paired comparisons, refusing an ambiguous key.

    ``paired_comparisons`` is one flat array across every query variant, so
    ``(subject, reference)`` alone is not a key -- it collides once more than
    one variant runs, and position is no fallback because each variant block
    is independently re-sorted by ``-delta.point``.  A consumer keying on the
    obvious pair silently reads whichever block landed last; that is not a
    hypothetical, it happened to a verifier's script against the first
    published ``raw.json``.

    Rather than trust every future producer to remember the field, this
    refuses to emit an array a consumer could misread.
    """
    rows = [d.as_dict() for d in deltas]
    keys = [(r.get("subject"), r.get("reference"), r.get("variant")) for r in rows]
    missing = [k for k in keys if not k[2]]
    if missing:
        raise ValueError(
            "paired comparison carries no variant, so its key is ambiguous: "
            f"{missing[0][:2]}"
        )
    if len(set(keys)) != len(keys):
        duplicated = sorted({k for k in keys if keys.count(k) > 1})
        raise ValueError(f"colliding paired-comparison keys: {duplicated}")
    return rows


def run(
    repo: Path,
    cases: Sequence[taskset.Case],
    suite: Sequence[object],
    budget: Budget,
    variants: Sequence[str],
    cache: TokenCache,
    universe_provider: Callable[[taskset.Case], List[Candidate]] | None = None,
    repo_provider: Callable[[taskset.Case], str] | None = None,
) -> Tuple[
    List[metrics.Aggregate],
    List[Dict[str, object]],
    Dict[str, object],
    Dict[Tuple[str, str], List[float]],
]:
    """Score every retriever on every case under one budget.

    ``universe_provider`` exists so the budget-equality rules can be tested
    without a repository; production runs leave it at the git-backed default.

    ``repo_provider`` decides which repository path each case's ``QueryView``
    advertises.  Under pre-image isolation it returns a per-case bare clone
    with the future absent; without it, retrievers see nothing at all in that
    field and any repository access they make is their own doing.
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
                repo=repo_provider(case) if repo_provider else "",
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
        "timing_disclaimer": TIMING_DISCLAIMER,
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
    parser.add_argument(
        "--variant", choices=(*VARIANTS, *EXTRA_VARIANTS, "both"), default="both"
    )
    isolation = parser.add_mutually_exclusive_group()
    isolation.add_argument(
        "--isolate-preimage",
        dest="isolate",
        action="store_true",
        default=None,
        help="grade against per-case bare clones with the future absent "
             "(default whenever --retriever is used)",
    )
    isolation.add_argument(
        "--no-isolate-preimage",
        dest="isolate",
        action="store_false",
        help="hand retrievers the live repository; the oracle hole is open",
    )
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
    # Performance only, never correctness -- see the identical comment in
    # run_xplane_harness.py, added in the same beat (s11 fusion
    # continuation, 2026-08-24): a loaded retriever cannot receive the
    # harness's shared TokenCache through the zero-arg module:attribute
    # seam, so one with a duck-typed `.cache` attribute gets it swapped in
    # here instead of tokenizing everything a second time.
    for retriever in suite:
        if hasattr(retriever, "cache"):
            retriever.cache = cache

    # Isolation is the default the moment a retriever this package did not
    # write is in the suite.  A baselines-only run leaves it off: the five
    # baselines are auditable in-tree and 20 clones is real work for a check
    # that only matters for a foreign arm.
    isolate = bool(args.retriever) if args.isolate is None else args.isolate
    isolator = PreimageIsolation(repo) if isolate else None
    repo_provider = (
        (lambda case: isolator.repo_for(case.parent)) if isolator else None
    )
    if isolate:
        print(
            "\npre-image isolation ACTIVE: each retriever sees a bare clone "
            "holding only its case's pre-image and ancestors.  A retriever "
            "that hardcodes a path to the live repository instead of reading "
            "QueryView.repo escapes this; that residue is documented, not "
            "closed."
        )
    elif args.retriever:
        print(
            "\nWARNING: pre-image isolation DISABLED with a foreign retriever "
            "in the suite. A retriever that walks git forward to its own case "
            "commit reads the answer key and scores a perfect 1.000 that "
            "nothing here will flag."
        )

    started = time.perf_counter()
    try:
        aggregates, per_case, cost, rr = run(
            repo, cases, suite, budget, variants, cache, repo_provider=repo_provider
        )
    finally:
        if isolator is not None:
            cost_clones = isolator.built
            isolator.close()
    cost["wall_seconds_total"] = round(time.perf_counter() - started, 2)
    cost["preimage_isolation"] = isolate
    if isolate:
        cost["preimage_clones_built"] = cost_clones

    names = [getattr(r, "name", type(r).__name__) for r in suite]
    reference = args.reference if args.reference in names else names[0]

    # Optional, duck-typed: added for the s11 fusion continuation
    # (2026-08-24). A retriever may expose returned_plane_counts (variant ->
    # plane -> count) as a real measurement of what it returned; the
    # baselines this package ships do not have the attribute and are
    # silently absent from the dict below -- an omission, not a zero,
    # matching s10_kill/schema.py's own "undeclared is not the same as
    # zero" rule for Arm.returned_plane_counts.
    retriever_plane_counts: Dict[str, Dict[str, Dict[str, int]]] = {}
    for retriever, name in zip(suite, names):
        counts = getattr(retriever, "returned_plane_counts", None)
        if counts:
            retriever_plane_counts[name] = counts

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
            stats.paired_delta(
                name,
                reference,
                rr[(name, variant)],
                rr[(reference, variant)],
                variant=variant,
            )
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
        "paired_comparisons": comparison_payload(comparisons),
        "reference_retriever": reference,
        "paired_comparisons_key": ["subject", "reference", "variant"],
        "per_case": per_case,
        "returned_plane_counts": retriever_plane_counts,
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
