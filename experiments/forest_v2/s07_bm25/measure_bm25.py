"""EXPERIMENT s07: the RAW baseline measurement for the BM25 retriever.

    python experiments/forest_v2/s07_bm25/measure_bm25.py --root .

prints one JSON object (`"schema": "forest-v2-s07-bm25-measure/2"`) with the
numbers a later graph-conditioned retriever has to beat.  Read-only, stdlib
only, no repository imports, no writes, no network, no subprocess.

THE RULE THIS FILE LIVES BY
---------------------------
The query set below was written **before** the first result was read, from the
first lines of each gold file, and it is frozen.  A query is never reworded to
make a rank improve, and a gold file is never reassigned to whatever BM25
happened to return.  Where BM25 misses, the miss is reported with the file that
beat the gold, because a baseline that has been quietly tuned is worth less
than no baseline at all.

CONTAMINATION: WHAT CHANGED IN SCHEMA /2
----------------------------------------
Schema /1 excluded three whole files from every scored query -- this script, its
self-test, and the slice README -- because they "quote the queries and the gold
paths verbatim".  That was true of the first two, which carry the entire query
set, and wrong about the README, which carries some queries and not others.

Excluding a document from a query it never contaminated does not merely
mis-count: it deletes a *competitor* and lifts the score.  The lift was
measured, not guessed, and it is in the table below.  Since this baseline is the
floor every richer representation will be compared against, a floor raised by an
after-the-fact corpus filter would bias the whole later comparison toward the
hypothesis.

Schema /2 therefore decides contamination per (query, document) pair, by
mechanical substring evidence (see ``contamination.py``), and publishes the
unfiltered run beside the filtered one so the filter's whole effect stays
visible.  The retracted schema /1 arm is still measured, under
``blanket.legacy_rebuild``, so the retraction has a number attached.

FILTERING HAPPENS AFTER RANKING, ON PURPOSE
-------------------------------------------
A withheld document is dropped from the ranking of the query it contaminates,
not from the index.  Corpus statistics (N, idf, average document length) are
therefore identical across every filter arm, so a metric difference between arms
is the filter and nothing else.  ``blanket.legacy_rebuild`` (build-time
exclusion, the schema /1 mechanism) is measured next to ``blanket.postfilter``
(same three files, post-filtered) to show the two mechanisms agree.

HONEST LIMITS OF THIS MEASUREMENT
---------------------------------
* 12 queries, one gold file each, hand-written by the same agent that wrote the
  retriever.  Small enough that one rank change moves h@1 by 8 percentage
  points.  ``s09_anchor.py`` runs the same index against the 20 cases of the
  independently frozen s09 task set for exactly that reason; read the two
  together, and prefer the s09 numbers when they disagree.
* "Gold" means "the file a maintainer would want", judged by the author.  Other
  files are counted as misses even when they are legitimately relevant (a test
  file for the module under query, for instance), so absolute numbers here are
  pessimistic and only comparable *within* this file.
* Single run, single machine, no repetition, no variance estimate.  Timings are
  wall clock on whatever the host was doing at the time.
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path
from typing import Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bm25_index import (  # noqa: E402
    CODE_DOC_EXTENSIONS,
    DEFAULT_EXTENSIONS,
    BM25Index,
    IndexConfig,
    iter_documents,
)
from contamination import (  # noqa: E402
    ADOPTED_RULE,
    QUERY_QUOTE_ONLY,
    ContaminationMap,
    scan,
)

SCHEMA = "forest-v2-s07-bm25-measure/2"
RANK_LIMIT = 100

# RETRACTED in schema /2.  Kept only so the withdrawn number can be reproduced
# and the size of its error stated.  This is the blanket file list: three whole
# documents, withheld from all twelve queries regardless of evidence.  Do not
# use it to score anything.
LEGACY_QUERY_CARRIERS: frozenset[str] = frozenset(
    {
        "experiments/forest_v2/s07_bm25/measure_bm25.py",
        "experiments/forest_v2/s07_bm25/test_bm25_index.py",
        "experiments/forest_v2/README.md",
    }
)

# (query, gold path).  Frozen 2026-08-18.  Do not edit to improve a score.
QUERY_SET: tuple[tuple[str, str], ...] = (
    ("hard ceiling on money ledger backed fail closed", "daedalus/budget.py"),
    ("isolated git worktree for candidate agent written code", "daedalus/kairos/worktree.py"),
    ("verify the master plan digest and block protected edits", "tools/iron_plan_guard.py"),
    ("report drift in the effectful entrypoint registry", "tools/effect_boundary_check.py"),
    (
        "delivery gates constitutional invariants and kill criteria",
        "docs/IKARUS_ARIADNE_MASTER_PLAN.md",
    ),
    ("content addressed artifact store and storage watermark", "daedalus/storage.py"),
    (
        "deterministic checks before accepting a local model result",
        "daedalus/verifier.py",
    ),
    (
        "same module call site resolution baseline probe",
        "experiments/forest_v2/probe_call_resolution.py",
    ),
    ("agent constitution mandatory workflow and handoff trailer", "AGENTS.md"),
    (
        "bm25 ranking baseline over repository files",
        "experiments/forest_v2/s07_bm25/bm25_index.py",
    ),
    ("approval gated writes before touching the working tree", "daedalus/kairos/gated_writes.py"),
    (
        "import binding cross module attribution probe",
        "experiments/forest_v2/probe_cross_module_resolution.py",
    ),
)


def pair_query_set() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """``QUERY_SET`` in the (query, gold-tuple) shape the evidence rule takes."""
    return tuple((query, (gold,)) for query, gold in QUERY_SET)


def evaluate(
    index: BM25Index,
    query_set: Sequence[tuple[str, str]],
    excluded_by_query: Mapping[str, frozenset[str]] | None = None,
) -> dict:
    """Run the frozen query set; report every rank RAW, plus the usual rollups.

    ``excluded_by_query`` withholds documents from the ranking of the query they
    contaminate.  The search reaches deeper than ``RANK_LIMIT`` by exactly the
    number of withheld documents, so a filtered rank of 100 means the same thing
    an unfiltered rank of 100 does.
    """
    per_query: list[dict] = []
    latencies_ms: list[float] = []
    for query, gold in query_set:
        withheld = (excluded_by_query or {}).get(query, frozenset())
        started = time.perf_counter()
        raw_hits = index.search(query, k=RANK_LIMIT + len(withheld))
        latencies_ms.append((time.perf_counter() - started) * 1000.0)
        kept = [hit for hit in raw_hits if hit.path not in withheld][:RANK_LIMIT]
        ranking = [hit.path for hit in kept]
        rank = next((i + 1 for i, path in enumerate(ranking) if path == gold), None)
        per_query.append(
            {
                "query": query,
                "gold": gold,
                "rank": rank,
                "gold_indexed": gold in index.paths,
                "withheld_for_this_query": sorted(withheld & set(index.paths)),
                "displaced_from_top10": sorted(
                    hit.path for hit in raw_hits[:10] if hit.path in withheld
                ),
                "top1": ranking[0] if ranking else None,
                "top5": ranking[:5],
            }
        )

    ranks = [row["rank"] for row in per_query]
    found = [r for r in ranks if r is not None]
    total = len(per_query) or 1
    return {
        "queries": total,
        "hit_at_1": sum(1 for r in found if r == 1),
        "hit_at_3": sum(1 for r in found if r <= 3),
        "hit_at_5": sum(1 for r in found if r <= 5),
        "hit_at_10": sum(1 for r in found if r <= 10),
        "found_within_100": len(found),
        "mrr_at_10": round(sum(1.0 / r for r in found if r <= 10) / total, 4),
        "median_rank_when_found": (sorted(found)[len(found) // 2] if found else None),
        "worst_rank_when_found": max(found) if found else None,
        "query_ms_mean": round(sum(latencies_ms) / len(latencies_ms), 2),
        "query_ms_max": round(max(latencies_ms), 2),
        "per_query": per_query,
    }


def _corpus_config(
    extensions: tuple[str, ...],
    path_weight: int,
    exclude: frozenset[str] = frozenset(),
) -> IndexConfig:
    return IndexConfig(extensions=extensions, path_weight=path_weight, exclude_paths=exclude)


def _blanket_map(paths: Sequence[str]) -> dict[str, frozenset[str]]:
    """The retracted rule, expressed as a per-query map: the same files, always."""
    present = frozenset(LEGACY_QUERY_CARRIERS) & frozenset(paths)
    return {query: present for query, _ in QUERY_SET}


def build_contamination_maps(root: Path, config: IndexConfig) -> dict[str, ContaminationMap]:
    """One walk of the corpus, both evidence rules, reused by every arm."""
    query_set = pair_query_set()
    documents = list(iter_documents(root, config))
    return {
        "evidence_rule": scan(documents, query_set, ADOPTED_RULE, "adopted"),
        "query_quote_only": scan(documents, query_set, QUERY_QUOTE_ONLY, "query_quote_only"),
    }


def _delta(subject: dict, reference: dict) -> dict:
    """Filtered minus unfiltered, on the numbers anyone would quote."""
    return {
        "mrr_at_10": round(subject["mrr_at_10"] - reference["mrr_at_10"], 4),
        "hit_at_1": subject["hit_at_1"] - reference["hit_at_1"],
        "hit_at_3": subject["hit_at_3"] - reference["hit_at_3"],
        "hit_at_10": subject["hit_at_10"] - reference["hit_at_10"],
    }


def run(root: Path) -> dict:
    arms: list[dict] = []
    results: dict[str, dict] = {}

    def record(name: str, index: BM25Index, filter_name: str, excluded, rebuilt: bool) -> dict:
        result = evaluate(index, QUERY_SET, excluded)
        results[name] = result
        arms.append(
            {
                "arm": name,
                "rebuild": rebuilt,
                "filter": filter_name,
                "pairs_withheld_in_this_corpus": sum(
                    len(paths & frozenset(index.paths)) for paths in (excluded or {}).values()
                ),
                "index": index.stats(),
                "result": result,
            }
        )
        return result

    primary_config = _corpus_config(DEFAULT_EXTENSIONS, 3)
    maps = build_contamination_maps(root, primary_config)
    evidence = {q: maps["evidence_rule"].excluded_for(q) for q, _ in QUERY_SET}
    quote_only = {q: maps["query_quote_only"].excluded_for(q) for q, _ in QUERY_SET}

    # ---- the primary corpus, under every filter, on ONE index ----------
    primary = BM25Index.build(root, primary_config)
    blanket = _blanket_map(primary.paths)
    record("full_corpus.pw3.unfiltered", primary, "none", None, True)
    record("full_corpus.pw3.evidence_rule", primary, "evidence_rule (C1+C2)", evidence, False)
    record("full_corpus.pw3.query_quote_only", primary, "evidence_rule (C1)", quote_only, False)
    record("full_corpus.pw3.blanket_postfilter", primary, "RETRACTED blanket", blanket, False)

    # ---- the retracted arm, reproduced by its own mechanism ------------
    legacy = BM25Index.build(root, _corpus_config(DEFAULT_EXTENSIONS, 3, LEGACY_QUERY_CARRIERS))
    record("blanket.legacy_rebuild", legacy, "RETRACTED blanket (build-time)", None, True)

    # ---- corpus and path-weight arms, filtered and unfiltered ----------
    for name, extensions, path_weight in (
        ("full_corpus.pw1", DEFAULT_EXTENSIONS, 1),
        ("full_corpus.pw0", DEFAULT_EXTENSIONS, 0),
        ("code_and_prose.pw3", CODE_DOC_EXTENSIONS, 3),
    ):
        index = BM25Index.build(root, _corpus_config(extensions, path_weight))
        record(f"{name}.unfiltered", index, "none", None, True)
        record(f"{name}.evidence_rule", index, "evidence_rule (C1+C2)", evidence, False)

    # ---- k1/b are query-time only: same postings, no rebuild -----------
    for name, k1, b in (
        ("full_corpus.pw3.b0", None, 0.0),
        ("full_corpus.pw3.k1_0", 0.0, None),
    ):
        view = primary.with_scoring(k1=k1, b=b)
        record(f"{name}.evidence_rule", view, "evidence_rule (C1+C2)", evidence, False)

    unfiltered = results["full_corpus.pw3.unfiltered"]
    return {
        "schema": SCHEMA,
        "read_only": True,
        "root": str(root.resolve()),
        "rank_limit": RANK_LIMIT,
        "host": {"python": platform.python_version(), "platform": platform.platform()},
        "query_set_size": len(QUERY_SET),
        "contamination": {
            "mechanism": "per (query, document) evidence, applied after ranking",
            "evidence_rule": maps["evidence_rule"].as_dict(),
            "query_quote_only": maps["query_quote_only"].as_dict(),
            "retracted_blanket_rule": {
                "documents": sorted(LEGACY_QUERY_CARRIERS),
                "pairs_withheld": len(LEGACY_QUERY_CARRIERS & frozenset(primary.paths))
                * len(QUERY_SET),
                "note": "schema /1 mechanism, retracted; measured here only to size its error",
            },
        },
        "deltas_vs_unfiltered": {
            name: _delta(results[name], unfiltered)
            for name in (
                "full_corpus.pw3.evidence_rule",
                "full_corpus.pw3.query_quote_only",
                "full_corpus.pw3.blanket_postfilter",
                "blanket.legacy_rebuild",
            )
        },
        "blanket_minus_evidence_rule": _delta(
            results["full_corpus.pw3.blanket_postfilter"],
            results["full_corpus.pw3.evidence_rule"],
        ),
        "arms": arms,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RAW BM25 baseline measurement")
    parser.add_argument("--root", default=None)
    args = parser.parse_args(argv)
    root = Path(args.root) if args.root else Path(__file__).resolve().parents[3]
    print(json.dumps(run(root), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
