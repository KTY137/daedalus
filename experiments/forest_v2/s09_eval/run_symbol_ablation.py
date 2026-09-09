"""EXPERIMENT (forest_v2 / slice s09): the Type-plane ablation on symbol gold.

Read-only against the subject repository.  Pure stdlib.  Prints one JSON object.

What it measures
----------------
Two arms over an identical universe of symbol candidates:

``full``          each symbol's source, AST-normalised
``type_ablated``  the same source with every annotation stripped

Both are unparsed, so the difference between them is annotations and nothing
else -- not formatting, which ``ast.unparse`` would otherwise contribute to
whichever arm was left raw.

Protocol is frozen in ``docs/G2_SYMARM_01_PREREGISTRATION_20260909.md``:
recall@10 on the scrubbed variant is primary, CI95 percentile bootstrap with
10 000 resamples at seed 20260818, equivalence margin +/-0.02, paired by case.

The declared confound test travels with the result: mean indexed-token count
per arm is reported, and the pre-registration binds the outcome to
``confounded`` if the arms differ by more than 5%.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

if __package__ in (None, ""):  # pragma: no cover - direct execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from s09_eval import gitio, stats, symbols, taskset_symbol  # noqa: E402
from s09_eval.tokens import word_tokens  # noqa: E402

SCHEMA = "forest_v2.s09.symbol_ablation/1"
CUTOFF = 10
MRR_MAX = 20
TOKEN_CONFOUND_PCT = 5.0
#: The s10 evaluator's bootstrap, adopted verbatim by the pre-registration.
#: Deliberately not s09's DEFAULT_RESAMPLES, which is 2000.
RESAMPLES = 10_000
SEED = 20260818
EQUIVALENCE_MARGIN = 0.02


def _bm25(query: Sequence[str], docs: List[Tuple[str, Counter, int]], k: int) -> List[str]:
    """BM25 with the package's usual k1/b, ranking by candidate key."""
    if not docs:
        return []
    k1, b = 1.2, 0.75
    n = len(docs)
    avgdl = sum(length for _, _, length in docs) / n
    df: Counter = Counter()
    for _, counts, _ in docs:
        for term in counts:
            df[term] += 1
    q_terms = set(query)
    scored: List[Tuple[float, str]] = []
    for key, counts, length in docs:
        score = 0.0
        for term in q_terms:
            tf = counts.get(term, 0)
            if not tf:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * length / avgdl))
        if score > 0:
            scored.append((score, key))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [key for _, key in scored[:k]]


def _recall_at(ranking: Sequence[str], gold: Sequence[str], k: int) -> float:
    gold_set = set(gold)
    if not gold_set:
        return 0.0
    return len(gold_set & set(ranking[:k])) / len(gold_set)


def _mrr(ranking: Sequence[str], gold: Sequence[str], k: int) -> float:
    gold_set = set(gold)
    for position, key in enumerate(ranking[:k], start=1):
        if key in gold_set:
            return 1.0 / position
    return 0.0


class _SymbolIndex:
    """Per-blob symbol extraction, cached because a tree repeats across cases."""

    def __init__(self, repo: Path) -> None:
        self._repo = repo
        self._trees: Dict[str, Dict[str, Tuple[str, int]]] = {}
        self._by_blob: Dict[str, List[Tuple[str, Counter, Counter, int, int]]] = {}

    def _tree(self, rev: str) -> Dict[str, Tuple[str, int]]:
        if rev not in self._trees:
            try:
                self._trees[rev] = gitio.list_tree(self._repo, rev)
            except gitio.GitError:
                self._trees[rev] = {}
        return self._trees[rev]

    def _symbols_of(self, blob: str) -> List[Tuple[str, Counter, Counter, int, int]]:
        """``(qualname, full_counts, ablated_counts, full_len, ablated_len)``."""
        if blob in self._by_blob:
            return self._by_blob[blob]
        raw = gitio.read_blobs(self._repo, [blob]).get(blob)
        rows: List[Tuple[str, Counter, Counter, int, int]] = []
        if raw is not None:
            source = raw.decode("utf-8", "replace")
            import ast

            try:
                tree = ast.parse(source)
            except SyntaxError:
                tree = None
            if tree is not None:
                def walk(node, prefix: str) -> None:
                    for item in getattr(node, "body", []):
                        if not isinstance(
                            item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                        ):
                            continue
                        qualified = f"{prefix}{item.name}"
                        segment = ast.unparse(item)
                        full = Counter(word_tokens(symbols.normalize_source(segment)))
                        ablated = Counter(
                            word_tokens(symbols.strip_annotations(segment))
                        )
                        rows.append(
                            (
                                qualified,
                                full,
                                ablated,
                                sum(full.values()),
                                sum(ablated.values()),
                            )
                        )
                        if isinstance(item, ast.ClassDef):
                            walk(item, f"{qualified}.")

                walk(tree, "")
        self._by_blob[blob] = rows
        return rows

    def universe(self, rev: str) -> Tuple[
        List[Tuple[str, Counter, int]], List[Tuple[str, Counter, int]]
    ]:
        """The two arms' document lists for the tree at ``rev``."""
        full_docs: List[Tuple[str, Counter, int]] = []
        ablated_docs: List[Tuple[str, Counter, int]] = []
        for path, (blob, _size) in sorted(self._tree(rev).items()):
            if not path.endswith(".py"):
                continue
            for qualname, full, ablated, full_len, ablated_len in self._symbols_of(blob):
                key = f"{path}#{qualname}"
                if full_len:
                    full_docs.append((key, full, full_len))
                if ablated_len:
                    ablated_docs.append((key, ablated, ablated_len))
        return full_docs, ablated_docs


def run(repo: Path, anchor: str, limit: int, variant: str) -> Dict[str, object]:
    record = taskset_symbol.build_record(repo, anchor, limit)
    cases = record["cases"]
    index = _SymbolIndex(repo)

    scores: Dict[str, Dict[str, List[float]]] = {
        arm: {"recall": [], "mrr": []} for arm in ("full", "type_ablated")
    }
    tokens_seen = {"full": 0, "type_ablated": 0}
    docs_seen = {"full": 0, "type_ablated": 0}
    used = 0

    for case in cases:
        full_docs, ablated_docs = index.universe(case["parent"])
        if not full_docs:
            continue
        query = word_tokens(
            case["query_scrubbed"] if variant == "scrubbed" else case["query_raw"]
        )
        gold = case["gold"]
        for arm, docs in (("full", full_docs), ("type_ablated", ablated_docs)):
            ranking = _bm25(query, docs, MRR_MAX)
            scores[arm]["recall"].append(_recall_at(ranking, gold, CUTOFF))
            scores[arm]["mrr"].append(_mrr(ranking, gold, MRR_MAX))
            tokens_seen[arm] += sum(length for _, _, length in docs)
            docs_seen[arm] += len(docs)
        used += 1

    mean_tokens = {
        arm: (tokens_seen[arm] / docs_seen[arm]) if docs_seen[arm] else 0.0
        for arm in tokens_seen
    }
    spread = (
        100.0
        * abs(mean_tokens["full"] - mean_tokens["type_ablated"])
        / max(mean_tokens["full"], 1e-9)
    )

    # Resamples and seed are passed explicitly rather than defaulted: s09's
    # DEFAULT_RESAMPLES is 2000 while the s10 evaluator -- whose decision rule
    # the pre-registration adopted verbatim -- uses 10000. Taking the module
    # default here would have silently run a different protocol from the frozen
    # one.
    deltas = {
        metric: stats.paired_delta(
            "full",
            "type_ablated",
            scores["full"][metric],
            scores["type_ablated"][metric],
            resamples=RESAMPLES,
            seed=SEED,
            variant=variant,
        ).as_dict()
        for metric in ("recall", "mrr")
    }

    return {
        "schema": SCHEMA,
        "anchor": record["anchor"],
        "variant": variant,
        "cases_scored": used,
        "cutoff": CUTOFF,
        "mrr_max": MRR_MAX,
        "mean_score": {
            arm: {
                metric: sum(vals) / len(vals) if vals else 0.0
                for metric, vals in metrics.items()
            }
            for arm, metrics in scores.items()
        },
        "paired_delta": deltas,
        "confound_check": {
            "mean_indexed_tokens": mean_tokens,
            "spread_pct": round(spread, 3),
            "threshold_pct": TOKEN_CONFOUND_PCT,
            "confounded": spread > TOKEN_CONFOUND_PCT,
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="s09 Type-plane ablation on symbols")
    parser.add_argument("repo")
    parser.add_argument("anchor")
    parser.add_argument("--limit", type=int, default=1500)
    parser.add_argument("--variant", choices=("scrubbed", "raw"), default="scrubbed")
    args = parser.parse_args(argv)
    print(json.dumps(run(Path(args.repo), args.anchor, args.limit, args.variant),
                     indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
