"""Build and freeze the retrieval task set from the real repository history.

One case = one non-merge commit.  The query is the commit message (what a
human asked for, in their own words); the gold set is the files that commit
actually changed *and* that already existed in the parent tree.  The search
universe is the parent tree -- the pre-image, so nothing from the future is
visible.

Three honesty rules are baked into the format rather than promised in prose:

* **Frozen before measurement.**  ``build`` writes ``taskset.json`` with a
  sha256 digest over the canonical case list.  The harness recomputes and
  refuses to score a task set whose digest does not match, so cases cannot
  drift toward whatever a retriever happens to be good at.
* **Files created by the commit are dropped from gold**, not silently
  counted as misses -- they are unretrievable from the pre-image tree by
  construction.  The dropped paths stay in the record.
* **The leak is measured, not hidden.**  These commit messages very often
  name the file they touch, so every case carries a second, scrubbed query
  with every gold-path token removed, plus the list of removed tokens.  The
  gap between the two variants is the honest size of the filename echo.

Known limitation, stated once and not walked back: the commit message is
written *after* the change, so even the scrubbed variant is a post-hoc
description of the work rather than a genuine pre-change request.  This task
set measures retrieval against a hindsight query.  It does not simulate a
user who has not yet seen the diff.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

if __package__ in (None, ""):  # pragma: no cover - direct-script convenience
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from s09_eval import gitio
    from s09_eval.contract import Budget
    from s09_eval.tokens import path_tokens, word_tokens
else:
    from . import gitio
    from .contract import Budget
    from .tokens import path_tokens, word_tokens

SCHEMA = "forest_v2.s09.taskset/1"
DEFAULT_PATH = Path(__file__).resolve().parent / "taskset.json"

#: frozen selection rule -- changing any of these changes the digest
#:
#: Stratified on purpose.  This history is ~95% single-file commits, so an
#: unstratified hash sample drew 20 cases with exactly one gold file each,
#: which degenerates Recall@k into a plain hit rate and never exercises
#: partial credit.  The multi-file stratum is capped by supply (18 such
#: commits exist in the window), and the shortfall is filled from the
#: single-file stratum and recorded in ``strata_actual``.  This rule was
#: last changed before any retriever existed; from the first scored run on,
#: the digest freezes it.
SELECTION = {
    "history_limit": 1200,
    "min_changed": 1,
    "max_changed": 6,
    "require_python_change": True,
    "min_message_chars": 24,
    "case_count": 20,
    "multi_file_target": 8,
    "order": "sha256(commit_sha) ascending, multi-file stratum first",
}


@dataclass(frozen=True)
class Case:
    """One frozen retrieval case."""

    case_id: str
    commit: str
    parent: str
    committed_at: int
    query_raw: str
    query_scrubbed: str
    gold: Tuple[str, ...]
    gold_created_dropped: Tuple[str, ...]
    leak_tokens: Tuple[str, ...]
    universe_size: int

    def query(self, variant: str) -> str:
        if variant == "raw":
            return self.query_raw
        if variant == "scrubbed":
            return self.query_scrubbed
        raise ValueError(f"unknown query variant {variant!r}")


def scrub(message: str, gold: Sequence[str]) -> Tuple[str, List[str]]:
    """Remove every token the gold paths would have handed the retriever."""
    banned = set()
    for path in gold:
        banned |= path_tokens(path)
    kept: List[str] = []
    removed: List[str] = []
    for token in word_tokens(message):
        (removed if token in banned else kept).append(token)
    return " ".join(kept), sorted(set(removed))


def _canonical(cases: Sequence[Case]) -> str:
    return json.dumps([asdict(c) for c in cases], sort_keys=True, separators=(",", ":"))


def digest_of(cases: Sequence[Case]) -> str:
    return "sha256:" + hashlib.sha256(_canonical(cases).encode("utf-8")).hexdigest()


def build(repo: Path, anchor: str, budget: Budget) -> Dict[str, object]:
    """Select cases deterministically and return the frozen record."""
    anchor_sha = gitio.rev_parse(repo, anchor)
    history = gitio.read_history(repo, anchor_sha, int(SELECTION["history_limit"]))

    def admissible(commit: gitio.Commit) -> bool:
        n_changed = len(commit.changed)
        if not (int(SELECTION["min_changed"]) <= n_changed <= int(SELECTION["max_changed"])):
            return False
        if SELECTION["require_python_change"] and not any(
            p.endswith(".py") for p in commit.changed
        ):
            return False
        return len(commit.message) >= int(SELECTION["min_message_chars"])

    ordered = sorted(
        (c for c in history if admissible(c)),
        key=lambda c: hashlib.sha256(c.sha.encode()).hexdigest(),
    )
    multi = [c for c in ordered if len(c.changed) >= 2]
    single = [c for c in ordered if len(c.changed) < 2]

    total = int(SELECTION["case_count"])
    want_multi = int(SELECTION["multi_file_target"])
    accepted: List[Tuple[gitio.Commit, Tuple[str, ...], Tuple[str, ...], int]] = []
    strata_actual = {"multi_file": 0, "single_file": 0}

    def consider(commit: gitio.Commit) -> bool:
        try:
            tree = gitio.list_tree(repo, commit.parent)
        except gitio.GitError:
            return False
        universe = {p for p, (_, size) in tree.items() if budget.eligible(p, size)}
        gold = tuple(sorted(p for p in commit.changed if p in universe))
        if not gold:
            return False
        dropped = tuple(sorted(p for p in commit.changed if p not in universe))
        accepted.append((commit, gold, dropped, len(universe)))
        return True

    for commit in multi:
        if strata_actual["multi_file"] >= want_multi:
            break
        if consider(commit):
            strata_actual["multi_file"] += 1
    for commit in single:
        if len(accepted) >= total:
            break
        if consider(commit):
            strata_actual["single_file"] += 1

    accepted.sort(key=lambda item: hashlib.sha256(item[0].sha.encode()).hexdigest())
    cases: List[Case] = []
    for index, (commit, gold, dropped, universe_size) in enumerate(accepted[:total]):
        scrubbed, removed = scrub(commit.message, gold)
        cases.append(
            Case(
                case_id=f"c{index:02d}",
                commit=commit.sha,
                parent=commit.parent,
                committed_at=commit.committed_at,
                query_raw=commit.message,
                query_scrubbed=scrubbed,
                gold=gold,
                gold_created_dropped=dropped,
                leak_tokens=tuple(removed),
                universe_size=universe_size,
            )
        )

    return {
        "schema": SCHEMA,
        "anchor_commit": anchor_sha,
        "selection": SELECTION,
        "strata_actual": strata_actual,
        "universe_rule": budget.as_dict(),
        "cases": [asdict(c) for c in cases],
        "digest": digest_of(cases),
    }


def load(path: Path = DEFAULT_PATH) -> Tuple[Dict[str, object], List[Case]]:
    """Load a frozen task set and verify its digest before returning it."""
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("schema") != SCHEMA:
        raise ValueError(f"unexpected task-set schema {record.get('schema')!r}")
    cases = [
        Case(
            case_id=c["case_id"],
            commit=c["commit"],
            parent=c["parent"],
            committed_at=c["committed_at"],
            query_raw=c["query_raw"],
            query_scrubbed=c["query_scrubbed"],
            gold=tuple(c["gold"]),
            gold_created_dropped=tuple(c["gold_created_dropped"]),
            leak_tokens=tuple(c["leak_tokens"]),
            universe_size=c["universe_size"],
        )
        for c in record["cases"]
    ]
    actual = digest_of(cases)
    if actual != record.get("digest"):
        raise ValueError(
            f"task set digest mismatch: file says {record.get('digest')}, cases hash to {actual}"
        )
    return record, cases


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[3]))
    parser.add_argument("--anchor", default="HEAD")
    parser.add_argument("--out", default=str(DEFAULT_PATH))
    args = parser.parse_args(argv)

    record = build(Path(args.repo), args.anchor, Budget())
    Path(args.out).write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    cases = record["cases"]
    leaky = sum(1 for c in cases if c["leak_tokens"])
    print(
        json.dumps(
            {
                "cases": len(cases),
                "anchor_commit": record["anchor_commit"],
                "digest": record["digest"],
                "cases_with_leak_tokens": leaky,
                "strata_actual": record["strata_actual"],
                "gold_size_distribution": {
                    str(n): sum(1 for c in cases if len(c["gold"]) == n)
                    for n in sorted({len(c["gold"]) for c in cases})
                },
                "gold_paths_total": sum(len(c["gold"]) for c in cases),
                "created_paths_dropped": sum(len(c["gold_created_dropped"]) for c in cases),
                "median_universe_size": sorted(c["universe_size"] for c in cases)[
                    len(cases) // 2
                ]
                if cases
                else 0,
                "out": args.out,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
