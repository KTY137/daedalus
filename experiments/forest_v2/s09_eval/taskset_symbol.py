"""EXPERIMENT (forest_v2 / slice s09): the symbol-level cross-plane corpus.

Read-only against the subject repository.  Pure stdlib.  Prints exactly one
JSON object.

What this is
------------
The corpus ``taskset_xplane.py`` said it was not building::

    Making the Type plane addressable needs gold whose unit is a *symbol* -- a
    (path, qualified name, revision) triple -- which needs a symbol-resolving
    extractor over the pre-image tree and a retriever contract whose candidates
    are symbols rather than files.

A case's gold is a set of ``path#qualname`` strings.  Nothing downstream needed
a new type for that: ``Case.gold`` is already an opaque tuple of strings,
``metrics`` compares strings, ``Candidate.key`` renders one, and
``tokens.path_tokens`` already splits on ``#`` and ``.`` so the existing scrub
bans a symbol's own name without modification.  That is why this file adds a
builder and not a second pipeline.

Why the Type plane is representable here and was not before
------------------------------------------------------------
A file-level gold label can never name the Type plane, because the retrievable
unit is a file and a retriever returning it scores for finding code.  A symbol
*can* carry a type: ``symbols.carries_annotation`` marks the ones that declare
one.  ``G2-SYMGOLD-01`` measured 435 of 440 cross-plane cases on ``black``
carrying at least one such symbol, so the plane is populated rather than
nominally present.

The four honesty rules, inherited unchanged
-------------------------------------------
1. Gold must be retrievable from the **pre-image**.  A symbol created by the
   commit is dropped into ``gold_created_dropped`` and counted, never silently
   discarded.
2. Every rejected commit lands in exactly one reasoned bucket, and the buckets
   sum to the input count.
3. The query is the commit message, which is written *after* the change --
   hindsight, not a request.  Inherited from the file-level corpus and not
   fixed here.
4. Renames are not tracked.  A renamed symbol reads as a deletion plus a
   creation, so it contributes no gold rather than wrong gold.  ``s09``'s
   file-level corpus rejects rename-dominated diffs for the same reason; at
   symbol granularity the effect is recorded, not repaired.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

if __package__ in (None, ""):  # pragma: no cover - direct execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from s09_eval import gitio, symbols, taskset  # noqa: E402

SCHEMA = "forest_v2.s09.taskset_symbol/1"

#: Planes other than ``code``, by suffix.  The plan's plane set is
#: code/type/data/knowledge; ``type`` has no file-level members by
#: construction, which is the whole reason this corpus exists, so it is carried
#: by annotated *symbols* rather than by a suffix.
OTHER_PLANE_SUFFIXES = {
    ".md": "knowledge", ".rst": "knowledge", ".txt": "knowledge",
    ".json": "data", ".yml": "data", ".yaml": "data", ".toml": "data",
    ".csv": "data", ".ini": "data", ".cfg": "data",
}

#: Recall is reported to k=20, so a case with more gold than that is bounded
#: above by 20/G < 1 for every retriever, perfect ones included.
MAX_GOLD = 20

EXCLUSIONS = {
    "no_python_changed": (
        "The commit touches no .py file, so it can contribute no symbol gold."
    ),
    "not_cross_plane": (
        "The commit changes code but nothing in the knowledge or data planes, "
        "so it cannot exercise a cross-plane query."
    ),
    "no_symbol_changed": (
        "Python files changed but no symbol's structure did -- an import "
        "reorder, a comment, or a reformat. Structural identity is what makes "
        "this bucket exist rather than silently inflating the corpus."
    ),
    "no_retrievable_gold_in_pre_image": (
        "Every changed symbol was created by this commit, so nothing it "
        "touched can be retrieved from the pre-image tree. Measured on black: "
        "16 of 438 cross-plane commits, far smaller than the file-level "
        "corpus's report of this as its largest bucket, because symbols are "
        "edited far more often than files are created."
    ),
    "gold_exceeds_largest_cutoff": (
        f"More than {MAX_GOLD} gold symbols, so Recall@{MAX_GOLD} is bounded "
        "above by 20/G < 1 for every retriever and the case adds a term no "
        "method can win."
    ),
}


def other_plane_of(path: str) -> str:
    lowered = path.lower()
    for suffix, plane in OTHER_PLANE_SUFFIXES.items():
        if lowered.endswith(suffix):
            return plane
    return ""


class _TreeReader:
    """Read file text at a revision through ``gitio``'s read-only gate.

    ``gitio._run`` refuses any verb outside ``log``/``rev-parse``/``ls-tree``/
    ``cat-file``, and ``git show`` is not among them. That gate is the point of
    the module -- "read-only on the source" is one checkable property rather
    than a promise repeated in five docstrings -- so this goes through
    ``ls-tree`` plus ``cat-file --batch`` instead of widening the allowlist.

    Trees are cached per revision because a commit and its parent are each read
    once per case, and a linear history revisits the same tree twice.
    """

    def __init__(self, repo: Path) -> None:
        self._repo = repo
        self._trees: Dict[str, Dict[str, Tuple[str, int]]] = {}

    def _tree(self, rev: str) -> Dict[str, Tuple[str, int]]:
        if rev not in self._trees:
            try:
                self._trees[rev] = gitio.list_tree(self._repo, rev)
            except gitio.GitError:
                self._trees[rev] = {}
        return self._trees[rev]

    def text(self, rev: str, path: str) -> str | None:
        entry = self._tree(rev).get(path)
        if entry is None:
            return None
        blob = gitio.read_blobs(self._repo, [entry[0]]).get(entry[0])
        return None if blob is None else blob.decode("utf-8", "replace")


def build_cases(
    repo: Path, anchor: str, limit: int
) -> Tuple[List[taskset.Case], Dict[str, int], Dict[str, int]]:
    """Return frozen cases, an exclusion tally, and corpus statistics."""
    history = gitio.read_history(repo, anchor, limit)
    reader = _TreeReader(repo)
    tally = {name: 0 for name in EXCLUSIONS}
    cases: List[taskset.Case] = []
    typed_cases = 0
    gold_sizes: List[int] = []

    for commit in history:
        changed = list(commit.changed)
        python = [p for p in changed if p.endswith(".py")]
        if not python:
            tally["no_python_changed"] += 1
            continue
        if not any(other_plane_of(p) for p in changed):
            tally["not_cross_plane"] += 1
            continue

        gold: List[str] = []
        created: List[str] = []
        typed = False
        for path in sorted(python):
            pre = reader.text(commit.parent, path)
            post = reader.text(commit.sha, path)
            if pre is None and post is None:
                continue
            for name, kind in sorted(
                symbols.changed_symbols(pre or "", post or "").items()
            ):
                key = f"{path}#{name}"
                if kind == "added":
                    created.append(key)
                    continue
                gold.append(key)
                if pre is not None and symbols.carries_annotation(pre, name):
                    typed = True

        if not gold and not created:
            tally["no_symbol_changed"] += 1
            continue
        if not gold:
            tally["no_retrievable_gold_in_pre_image"] += 1
            continue
        if len(gold) > MAX_GOLD:
            tally["gold_exceeds_largest_cutoff"] += 1
            continue

        gold_tuple = tuple(sorted(gold))
        scrubbed, removed = taskset.scrub(commit.message, gold_tuple)
        cases.append(
            taskset.Case(
                case_id=f"{commit.sha[:12]}",
                commit=commit.sha,
                parent=commit.parent,
                committed_at=commit.committed_at,
                query_raw=commit.message,
                query_scrubbed=scrubbed,
                gold=gold_tuple,
                gold_created_dropped=tuple(sorted(created)),
                leak_tokens=tuple(removed),
                universe_size=0,
            )
        )
        gold_sizes.append(len(gold_tuple))
        typed_cases += 1 if typed else 0

    stats = {
        "commits_read": len(history),
        "cases": len(cases),
        "cases_with_a_type_bearing_gold_symbol": typed_cases,
        "gold_total": sum(gold_sizes),
        "gold_mean_x100": round(100 * sum(gold_sizes) / len(gold_sizes)) if gold_sizes else 0,
    }
    return cases, tally, stats


def build_record(repo: Path, anchor: str, limit: int) -> Dict[str, object]:
    cases, tally, stats = build_cases(repo, anchor, limit)
    accounted = stats["cases"] + sum(tally.values())
    if accounted != stats["commits_read"]:
        raise AssertionError(
            "exclusion tally does not account for every commit: "
            f"{accounted} != {stats['commits_read']}"
        )
    return {
        "schema": SCHEMA,
        "anchor": gitio.rev_parse(repo, anchor),
        "limit": limit,
        "unit": "symbol",
        "type_plane_representable": True,
        "max_gold": MAX_GOLD,
        "statistics": stats,
        "exclusions": {name: {"count": tally[name], "why": EXCLUSIONS[name]} for name in sorted(tally)},
        "cases": [
            {
                "case_id": c.case_id,
                "commit": c.commit,
                "parent": c.parent,
                "committed_at": c.committed_at,
                "query_raw": c.query_raw,
                "query_scrubbed": c.query_scrubbed,
                "gold": list(c.gold),
                "gold_created_dropped": list(c.gold_created_dropped),
                "leak_tokens": list(c.leak_tokens),
            }
            for c in cases
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="s09 symbol-level task set")
    parser.add_argument("repo", help="subject repository")
    parser.add_argument("anchor", help="pinned revision")
    parser.add_argument("--limit", type=int, default=1500)
    parser.add_argument("--summary", action="store_true", help="omit the cases array")
    args = parser.parse_args(argv)
    record = build_record(Path(args.repo), args.anchor, args.limit)
    if args.summary:
        record = {k: v for k, v in record.items() if k != "cases"}
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
