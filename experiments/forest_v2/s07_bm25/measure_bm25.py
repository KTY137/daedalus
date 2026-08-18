"""EXPERIMENT s07: the RAW baseline measurement for the BM25 retriever.

    python experiments/forest_v2/s07_bm25/measure_bm25.py --root .

prints one JSON object (`"schema": "forest-v2-s07-bm25-measure/1"`) with the
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

CONTAMINATION FIREWALL
----------------------
This file and the self-test file live *inside the corpus they measure* and
contain every query string verbatim.  The first run of this measurement duly
retrieved ``measure_bm25.py`` at rank 1 for four unrelated queries.  So the
query carriers are excluded from every scored arm, and one extra arm keeps them
in, on purpose, to report how large the leak was.  A retrieval evaluation that
indexes its own question sheet is measuring nothing.

HONEST LIMITS OF THIS MEASUREMENT
---------------------------------
* 12 queries, one gold file each, hand-written by the same agent that wrote the
  retriever.  That is enough to catch "retrieval is broken", not enough for a
  publishable comparison; Gate 3 needs a frozen task set from someone else.
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
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bm25_index import (  # noqa: E402
    CODE_DOC_EXTENSIONS,
    DEFAULT_EXTENSIONS,
    BM25Index,
    IndexConfig,
)

SCHEMA = "forest-v2-s07-bm25-measure/1"
RANK_LIMIT = 100

# The files that carry the query strings themselves.  Excluded from every
# scored arm; see CONTAMINATION FIREWALL above.
QUERY_CARRIERS: frozenset[str] = frozenset(
    {
        "experiments/forest_v2/s07_bm25/measure_bm25.py",
        "experiments/forest_v2/s07_bm25/test_bm25_index.py",
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


def evaluate(index: BM25Index, query_set: Sequence[tuple[str, str]]) -> dict:
    """Run the frozen query set; report every rank RAW, plus the usual rollups."""
    per_query: list[dict] = []
    latencies_ms: list[float] = []
    for query, gold in query_set:
        started = time.perf_counter()
        hits = index.search(query, k=RANK_LIMIT)
        latencies_ms.append((time.perf_counter() - started) * 1000.0)
        rank = next((hit.rank for hit in hits if hit.path == gold), None)
        per_query.append(
            {
                "query": query,
                "gold": gold,
                "rank": rank,
                "gold_indexed": gold in index.paths,
                "top1": hits[0].path if hits else None,
                "top5": [hit.path for hit in hits[:5]],
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
        "median_rank_when_found": (
            sorted(found)[len(found) // 2] if found else None
        ),
        "worst_rank_when_found": max(found) if found else None,
        "query_ms_mean": round(sum(latencies_ms) / len(latencies_ms), 2),
        "query_ms_max": round(max(latencies_ms), 2),
        "per_query": per_query,
    }


def _corpus_config(
    extensions: tuple[str, ...],
    path_weight: int,
    exclude: frozenset[str] = QUERY_CARRIERS,
) -> IndexConfig:
    return IndexConfig(extensions=extensions, path_weight=path_weight, exclude_paths=exclude)


def run(root: Path) -> dict:
    arms: list[dict] = []

    # Arm group 1: corpus + path weight need a real rebuild.
    builds = [
        ("full_corpus.path_weight_3", DEFAULT_EXTENSIONS, 3, QUERY_CARRIERS),
        ("full_corpus.path_weight_1", DEFAULT_EXTENSIONS, 1, QUERY_CARRIERS),
        ("full_corpus.path_weight_0", DEFAULT_EXTENSIONS, 0, QUERY_CARRIERS),
        ("code_and_prose.path_weight_3", CODE_DOC_EXTENSIONS, 3, QUERY_CARRIERS),
        # Deliberately contaminated control: the query carriers stay in the
        # corpus so the size of the leak is a number, not a worry.
        ("full_corpus.leaky_control", DEFAULT_EXTENSIONS, 3, frozenset()),
    ]
    reference: BM25Index | None = None
    for name, extensions, path_weight, exclude in builds:
        index = BM25Index.build(root, _corpus_config(extensions, path_weight, exclude))
        arms.append(
            {
                "arm": name,
                "rebuild": True,
                "index": index.stats(),
                "result": evaluate(index, QUERY_SET),
            }
        )
        if name == "full_corpus.path_weight_3":
            reference = index

    # Arm group 2: k1/b are query-time only -- same postings, no rebuild.
    assert reference is not None
    for name, k1, b in (
        ("full_corpus.no_length_norm_b0", None, 0.0),
        ("full_corpus.presence_only_k1_0", 0.0, None),
    ):
        view = reference.with_scoring(k1=k1, b=b)
        arms.append(
            {
                "arm": name,
                "rebuild": False,
                "index": {"config": view.stats()["config"], "documents": view.num_documents},
                "result": evaluate(view, QUERY_SET),
            }
        )

    return {
        "schema": SCHEMA,
        "read_only": True,
        "root": str(root.resolve()),
        "rank_limit": RANK_LIMIT,
        "host": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "query_set_size": len(QUERY_SET),
        "query_carriers_excluded": sorted(QUERY_CARRIERS),
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
