"""EXPERIMENT s07: the BM25 baseline scored on the INDEPENDENTLY frozen s09 task set.

    python experiments/forest_v2/s07_bm25/s09_anchor.py --root .

prints one JSON object (`"schema": "forest-v2-s07-s09-anchor/1"`).

WHY
---
``measure_bm25.py`` scores twelve queries that the author of the retriever wrote
by hand, with one gold file each.  Twelve is small enough that a single rank
change moves h@1 by eight percentage points, and author-written queries are the
easiest kind: the wording came from the gold file's own first lines.  Both
facts were already stated as limits.  Stating a limit is not the same as fixing
it.

Slice s09 froze a task set that has neither problem, and froze it before any
retriever was measured against it:

* the queries are commit subjects, written by whoever made the commit, for
  reasons that had nothing to do with retrieval;
* the gold set is the commit's changed files -- mechanical, not judged;
* the candidate universe is the tree at the commit's parent, so nothing the
  commit created can be retrieved from it;
* a ``scrubbed`` variant removes every token the gold paths would have handed
  the retriever, which is a stronger contamination control than anything in
  this slice;
* the whole thing is digest-locked, so it cannot be edited after seeing a score.

This module scores THE SAME ``BM25Index`` against that task set, under the same
per-(query, document) evidence rule, and reports both filtered and unfiltered.

WHAT IS INHERITED AND WHAT IS RE-DERIVED
----------------------------------------
``s09_taskset.json`` here is a byte copy of ``s09_eval/taskset.json`` in the s09
worktree.  Its digest is recomputed from the cases on every run by the same rule
s09 uses (sha256 over the canonical case list), so a drifted or edited copy
fails loudly instead of scoring.

The universes are re-derived here from git, by s09's own stated universe rule
(text suffixes, ``max_file_bytes``, ``content_budget_bytes``, cutoffs -- all read
out of the frozen record, none re-typed).  ``universe_size`` from the frozen
record is compared against the universe this module builds, per case, and any
mismatch is reported rather than smoothed.

NAMED GAP: this is not the s09 harness.  s09 scores retrievers through its
``Retriever`` protocol inside its own package, and that package is in another
worktree and another lane; nothing here writes to it, and no result here is an
s09 result.  Numbers from the two lanes are comparable only insofar as the task
set, universe rule and metric definitions match -- which is exactly why all
three are inherited from the frozen record instead of restated.  The remaining
difference is the ranker's own tokenizer and scoring constants, which is the
thing being measured.

SCOPE CHANGE, DECLARED
----------------------
The s07 frozen spec says "no subprocess".  Reconstructing a historical tree
without one would mean re-implementing git's object database, so this module
relaxes that clause to: **read-only git plumbing only** (``rev-parse``,
``ls-tree``, ``cat-file --batch``), no writes, no network, no other executable.
The relaxation is stated here and in the slice README rather than taken
quietly; ``bm25_index.py``, ``contamination.py`` and ``measure_bm25.py`` remain
subprocess-free.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bm25_index import BM25Index, IndexConfig, token_counts  # noqa: E402
from contamination import ADOPTED_RULE, QUERY_QUOTE_ONLY, EvidenceRule  # noqa: E402

SCHEMA = "forest-v2-s07-s09-anchor/1"
TASKSET_PATH = Path(__file__).resolve().parent / "s09_taskset.json"
VARIANTS = ("raw", "scrubbed")


class AnchorError(RuntimeError):
    """The frozen task set or the repository is not in the state this needs."""


# ---- read-only git plumbing -------------------------------------------


def _git(repo: Path, args: Sequence[str], stdin: bytes | None = None) -> bytes:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        input=stdin,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AnchorError(
            f"git {' '.join(args)} failed: {proc.stderr.decode('utf-8', 'replace').strip()}"
        )
    return proc.stdout


def list_tree(repo: Path, rev: str) -> dict[str, tuple[str, int]]:
    """``path -> (blob sha, size)`` for every blob in ``rev``'s tree."""
    raw = _git(repo, ["ls-tree", "-r", "-l", "-z", rev]).decode("utf-8", "replace")
    out: dict[str, tuple[str, int]] = {}
    for entry in raw.split("\0"):
        if not entry.strip():
            continue
        meta, _, path = entry.partition("\t")
        parts = meta.split()
        if len(parts) < 4 or parts[1] != "blob" or parts[3] == "-":
            continue
        out[path] = (parts[2], int(parts[3]))
    return out


def read_blobs(repo: Path, shas: Sequence[str]) -> dict[str, bytes]:
    """Fetch many blobs in one ``cat-file --batch``; unknown objects are skipped."""
    wanted = list(dict.fromkeys(shas))
    if not wanted:
        return {}
    payload = ("\n".join(wanted) + "\n").encode("ascii")
    buf = _git(repo, ["cat-file", "--batch"], stdin=payload)
    out: dict[str, bytes] = {}
    pos = 0
    while pos < len(buf):
        end = buf.find(b"\n", pos)
        if end == -1:
            break
        header = buf[pos:end].decode("ascii", "replace").split()
        pos = end + 1
        if len(header) < 3:  # "<sha> missing"
            continue
        sha, kind, size_text = header[0], header[1], header[2]
        size = int(size_text)
        body = buf[pos : pos + size]
        pos += size + 1  # trailing newline
        if kind == "blob":
            out[sha] = body
    return out


# ---- the frozen task set ----------------------------------------------


def load_taskset(path: Path = TASKSET_PATH) -> dict:
    """Load the copy and verify its digest by s09's own rule before using it."""
    record = json.loads(path.read_text(encoding="utf-8"))
    canonical = json.dumps(record["cases"], sort_keys=True, separators=(",", ":"))
    actual = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if actual != record.get("digest"):
        raise AnchorError(
            f"task set digest mismatch: record says {record.get('digest')}, cases hash to {actual}"
        )
    record["_file_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return record


# ---- s09's metric definitions, inherited not restated ------------------


def score_case(ranking: Sequence[str], gold: Sequence[str], cutoffs: Sequence[int]) -> dict:
    gold_set = set(gold)
    hits_at = {k: len(gold_set & set(ranking[:k])) for k in cutoffs}
    first = next((i + 1 for i, path in enumerate(ranking) if path in gold_set), None)
    max_k = max(cutoffs) if cutoffs else 0
    return {
        "gold_total": len(gold_set),
        "hits_at": hits_at,
        "first_hit_rank": first,
        "reciprocal_rank": (1.0 / first) if first is not None and first <= max_k else 0.0,
    }


def aggregate(case_scores: Sequence[dict], cutoffs: Sequence[int]) -> dict:
    cases = len(case_scores) or 1
    gold_total = sum(s["gold_total"] for s in case_scores)
    first_ranks = sorted(
        s["first_hit_rank"] for s in case_scores if s["first_hit_rank"] is not None
    )
    return {
        "cases": len(case_scores),
        "gold_total": gold_total,
        "hits_at": {k: sum(s["hits_at"][k] for s in case_scores) for k in cutoffs},
        "macro_recall_at": {
            k: round(
                sum(s["hits_at"][k] / s["gold_total"] if s["gold_total"] else 0.0 for s in case_scores)
                / cases,
                4,
            )
            for k in cutoffs
        },
        "micro_recall_at": {
            k: round(sum(s["hits_at"][k] for s in case_scores) / gold_total, 4) if gold_total else 0.0
            for k in cutoffs
        },
        "mrr": round(sum(s["reciprocal_rank"] for s in case_scores) / cases, 4),
        "cases_with_any_hit": sum(1 for s in case_scores if s["first_hit_rank"] is not None),
        "median_first_hit_rank": (
            first_ranks[len(first_ranks) // 2] if first_ranks else None
        ),
    }


# ---- the run -----------------------------------------------------------


def _eligible(path: str, size: int, suffixes: frozenset[str], max_bytes: int) -> bool:
    """s09's eligibility predicate, reproduced exactly.

    Both edges matter and both were wrong on the first run: empty files are out
    (``size <= 0``), and the suffix match is case-insensitive.  Reproducing the
    rule from prose put 33 extra documents into every one of the twenty
    universes -- which is precisely why ``universe_size`` from the frozen record
    is checked against the rebuilt universe on every run instead of trusted.
    """
    if size <= 0 or size > max_bytes:
        return False
    lowered = path.lower()
    return any(lowered.endswith(suffix) for suffix in suffixes)


def run(root: Path, path_weight: int = 3) -> dict:
    started = time.perf_counter()
    record = load_taskset()
    rule_cfg = record["universe_rule"]
    cutoffs = list(rule_cfg["cutoffs"])
    max_k = max(cutoffs)
    suffixes = frozenset(rule_cfg["text_suffixes"])
    max_bytes = int(rule_cfg["max_file_bytes"])
    budget = int(rule_cfg["content_budget_bytes"])

    anchor = record["anchor_commit"]
    try:
        _git(root, ["cat-file", "-e", f"{anchor}^{{commit}}"])
    except AnchorError as exc:  # pragma: no cover - environment guard
        raise AnchorError(f"anchor commit {anchor} not reachable from {root}") from exc

    counts_cache: dict[str, Counter] = {}
    text_cache: dict[str, str] = {}
    blob_lookups = 0
    blobs_fetched = 0

    config = IndexConfig(path_weight=path_weight)
    filters: dict[str, EvidenceRule | None] = {
        "unfiltered": None,
        "evidence_rule": ADOPTED_RULE,
        "query_quote_only": QUERY_QUOTE_ONLY,
    }
    per_case: list[dict] = []
    scores: dict[tuple[str, str], list[dict]] = {
        (variant, name): [] for variant in VARIANTS for name in filters
    }
    universe_mismatches: list[dict] = []
    withheld_pairs: dict[str, int] = {name: 0 for name in filters}

    for case in record["cases"]:
        tree = list_tree(root, case["parent"])
        universe = {
            path: sha
            for path, (sha, size) in tree.items()
            if _eligible(path, size, suffixes, max_bytes)
        }
        blob_lookups += len(universe)
        missing = [sha for sha in universe.values() if sha not in counts_cache]
        if missing:
            fetched = read_blobs(root, missing)
            blobs_fetched += len(fetched)
            for sha, raw in fetched.items():
                text = raw[:budget].decode("utf-8", "replace")
                text_cache[sha] = text
                counts_cache[sha] = token_counts(text)

        if len(universe) != case["universe_size"]:
            universe_mismatches.append(
                {
                    "case_id": case["case_id"],
                    "frozen": case["universe_size"],
                    "rebuilt": len(universe),
                }
            )

        index = BM25Index.from_counted_documents(
            {path: counts_cache.get(sha, Counter()) for path, sha in universe.items()},
            config,
        )
        gold = list(case["gold"])
        gold_present = sum(1 for g in gold if g in universe)

        for variant in VARIANTS:
            query = case["query_raw"] if variant == "raw" else case["query_scrubbed"]
            withheld_by_filter: dict[str, frozenset[str]] = {}
            for name, rule in filters.items():
                if rule is None:
                    withheld_by_filter[name] = frozenset()
                    continue
                withheld_by_filter[name] = frozenset(
                    path
                    for path, sha in universe.items()
                    if rule.reasons(
                        query=query,
                        gold=gold,
                        doc_path=path,
                        doc_text=text_cache.get(sha, ""),
                    )
                )
            deepest = max(len(v) for v in withheld_by_filter.values())
            hits = index.search(query, k=max_k + deepest)
            row = {
                "case_id": case["case_id"],
                "variant": variant,
                "universe_size": len(universe),
                "gold_total": len(gold),
                "gold_present_in_universe": gold_present,
            }
            for name in filters:
                withheld = withheld_by_filter[name]
                withheld_pairs[name] += len(withheld)
                ranking = [hit.path for hit in hits if hit.path not in withheld][:max_k]
                score = score_case(ranking, gold, cutoffs)
                scores[(variant, name)].append(score)
                row[name] = {
                    "first_hit_rank": score["first_hit_rank"],
                    "reciprocal_rank": round(score["reciprocal_rank"], 4),
                    "withheld": len(withheld),
                    "top1": ranking[0] if ranking else None,
                }
            per_case.append(row)

    aggregates = [
        {
            "variant": variant,
            "filter": name,
            "withheld_pairs": withheld_pairs[name] // len(VARIANTS),
            **aggregate(scores[(variant, name)], cutoffs),
        }
        for variant in VARIANTS
        for name in filters
    ]
    by_key = {(a["variant"], a["filter"]): a for a in aggregates}
    deltas = {
        f"{variant}.{name}_minus_unfiltered": {
            "mrr": round(by_key[(variant, name)]["mrr"] - by_key[(variant, "unfiltered")]["mrr"], 4),
            "macro_recall_at_1": round(
                by_key[(variant, name)]["macro_recall_at"][1]
                - by_key[(variant, "unfiltered")]["macro_recall_at"][1],
                4,
            ),
        }
        for variant in VARIANTS
        for name in filters
        if name != "unfiltered"
    }

    return {
        "schema": SCHEMA,
        "read_only": True,
        "subprocess": "read-only git plumbing only (declared scope change)",
        "root": str(root.resolve()),
        "host": {"python": platform.python_version(), "platform": platform.platform()},
        "taskset": {
            "source": (
                "byte copy of experiments/forest_v2/s09_eval/taskset.json as frozen by "
                "s09 commit 4000f77a8cb66e70e5429b314950c6765aa1c593; "
                "sha256 fe05b1c155c21c377aed619a2395e36f5ff981feeb223bfffd5747d57437260c; "
                "digest re-verified from the cases on every run"
            ),
            "schema": record["schema"],
            "digest": record["digest"],
            "file_sha256": record["_file_sha256"],
            "anchor_commit": record["anchor_commit"],
            "cases": len(record["cases"]),
            "gold_total": sum(len(c["gold"]) for c in record["cases"]),
            "selection": record["selection"],
            "universe_rule": rule_cfg,
        },
        "retriever": {
            "name": "s07_bm25",
            "config": {"k1": config.k1, "b": config.b, "path_weight": config.path_weight},
        },
        "cost": {
            "wall_seconds_total": round(time.perf_counter() - started, 2),
            "blob_lookups": blob_lookups,
            "blobs_tokenised": blobs_fetched,
        },
        "universe_reconstruction_exact": not universe_mismatches,
        "universe_mismatches": universe_mismatches,
        "aggregates": aggregates,
        "deltas": deltas,
        "per_case": per_case,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BM25 baseline on the frozen s09 task set")
    parser.add_argument("--root", default=None)
    parser.add_argument("--path-weight", type=int, default=3)
    args = parser.parse_args(argv)
    root = Path(args.root) if args.root else Path(__file__).resolve().parents[3]
    print(json.dumps(run(root, path_weight=args.path_weight), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
