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
* **Paths outside the searchable universe are dropped from gold**, not
  silently counted as misses -- they cannot be retrieved from the pre-image
  tree by construction.  The dropped paths stay in the record.  The per-case
  field is called ``gold_created_dropped``, which is a misnomer kept for
  digest stability: it collects everything outside the *eligible* universe,
  which is files the commit created **plus** files that existed but fail the
  suffix/size rule.  ``dropped_breakdown`` in the record splits the two
  honestly.  The total is unaffected -- an ineligible file is outside the
  universe too, so it really is unretrievable -- and the denominator was
  never shaved.
* **Every rejection is counted.**  Selecting 20 cases meant considering more
  than 20 commits; the ones with no surviving gold used to vanish without a
  trace.  ``acceptance`` records the denominator, the rate, and the reason
  for each rejection, because the rejected population is *not* random -- it
  is dominated by file-creating commits.
* **The leak is measured, not hidden.**  These commit messages very often
  name the file they touch, so every case carries a second, scrubbed query
  with every gold-path token removed, plus the list of removed tokens.  Read
  the caveat on :func:`scrub` before drawing a conclusion from the gap: the
  full scrub removes directory tokens too, so it erases every path signal
  rather than isolating the filename echo.  :func:`scrub_basename` is the
  variant that isolates it.

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

SCHEMA = "forest_v2.s09.taskset/2"
#: ``/2`` is additive over ``/1``: the case list, and therefore the digest, is
#: byte-identical.  What changed is the record *around* the cases -- it now
#: carries the selection census, the acceptance denominator, the dropped-path
#: breakdown, and the plane composition, all of which were previously computed
#: and thrown away.

#: Which Project-Twin plane a gold path is evidence for, by suffix.  A coarse
#: proxy and nothing more: the Type plane has no file-level representative at
#: all, so a corpus can look "three-plane" here while touching two.
PLANE_BY_SUFFIX = {
    ".py": "code", ".ts": "code", ".tsx": "code", ".js": "code",
    ".jsx": "code", ".sh": "code",
    ".md": "knowledge", ".rst": "knowledge", ".txt": "knowledge",
    ".json": "data", ".yml": "data", ".yaml": "data", ".toml": "data",
    ".csv": "data", ".sql": "data", ".ini": "data", ".cfg": "data",
    ".html": "presentation", ".css": "presentation",
}


def plane_of(path: str) -> str:
    """Coarse plane label for a path; ``unknown`` when the suffix is unmapped."""
    lowered = path.lower()
    for suffix, plane in PLANE_BY_SUFFIX.items():
        if lowered.endswith(suffix):
            return plane
    return "unknown"
DEFAULT_PATH = Path(__file__).resolve().parent / "taskset.json"

#: frozen selection rule -- changing any of these changes the digest
#:
#: Stratified on purpose.  This history is ~95% single-file commits, so an
#: unstratified hash sample drew 20 cases with exactly one gold file each,
#: which degenerates Recall@k into a plain hit rate and never exercises
#: partial credit.
#:
#: CORRECTED 2026-08-18 -- the note here used to say the multi-file stratum
#: was "capped by supply (18 such commits exist)" and that a "shortfall is
#: filled from the single-file stratum".  Both were false.  ``multi_file_target``
#: is 8 and the loop breaks at 8, while admissible multi-file supply in the
#: same window is 18: the quota is more than 2x oversubscribed, ten
#: multi-file commits go unused, and no shortfall ever occurred.  The 8/12
#: split is a *choice*, not a ceiling.  ``selection_census`` in the record
#: now carries supply against quota so the claim cannot drift again.
#:
#: This rule was last changed before any retriever existed; from the first
#: scored run on, the digest freezes it.
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
        if variant == "scrubbed_basename":
            # Derived, not stored: it is a function of two frozen fields, so
            # computing it on demand adds a measurement without disturbing
            # the digest that anchors every published number.
            return scrub_basename(self.query_raw, self.gold)[0]
        raise ValueError(f"unknown query variant {variant!r}")


def scrub(message: str, gold: Sequence[str]) -> Tuple[str, List[str]]:
    """Remove every token the gold paths would have handed the retriever.

    Read this before interpreting a path-based retriever's scrubbed score.
    The ban set is ``path_tokens(gold)`` -- *directory* tokens included --
    and a path-token retriever scores exactly the intersection of the query
    tokens with a candidate's path tokens.  For a gold path that intersection
    is empty by construction after this scrub, so such a retriever scores a
    structural zero on gold no matter what the corpus contains.  That zero is
    arithmetic, not evidence about this repository.

    The scrub is still the right control for a *content* retriever, which is
    what it was built for: it removes the answer's name from the query
    without pretending the result isolates the filename echo.  To isolate the
    echo, use :func:`scrub_basename`.
    """
    banned = set()
    for path in gold:
        banned |= path_tokens(path)
    kept: List[str] = []
    removed: List[str] = []
    for token in word_tokens(message):
        (removed if token in banned else kept).append(token)
    return " ".join(kept), sorted(set(removed))


def scrub_basename(message: str, gold: Sequence[str]) -> Tuple[str, List[str]]:
    """Remove only the gold *filename* tokens, leaving directory tokens intact.

    The measurement :func:`scrub` cannot make.  Banning the whole path erases
    every path signal at once; banning just the basename leaves a path
    retriever able to score a gold file through its directory, so what it
    loses is attributable to the commit message naming the file rather than
    to the scrub having removed the only tokens it could ever have matched.
    """
    banned: set = set()
    for path in gold:
        banned |= path_tokens(path.rsplit("/", 1)[-1])
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
    #: Every commit ``consider`` looked at, accepted or not.  Rejections used
    #: to return ``False`` and increment nothing, which hid both a denominator
    #: and a composition bias: the rejected population is the file-*creating*
    #: commits, and those are exactly the cross-plane-shaped ones.
    considered: List[Dict[str, object]] = []
    dropped_detail: Dict[str, Dict[str, List[str]]] = {}

    def consider(commit: gitio.Commit) -> bool:
        stratum = "multi_file" if len(commit.changed) >= 2 else "single_file"
        try:
            tree = gitio.list_tree(repo, commit.parent)
        except gitio.GitError:
            considered.append(
                {
                    "commit": commit.sha,
                    "stratum": stratum,
                    "changed": list(commit.changed),
                    "accepted": False,
                    "reason": "parent_tree_unreadable",
                }
            )
            return False
        universe = {p for p, (_, size) in tree.items() if budget.eligible(p, size)}
        gold = tuple(sorted(p for p in commit.changed if p in universe))
        created = sorted(p for p in commit.changed if p not in tree)
        ineligible = sorted(
            p for p in commit.changed if p in tree and p not in universe
        )
        if not gold:
            considered.append(
                {
                    "commit": commit.sha,
                    "stratum": stratum,
                    "changed": list(commit.changed),
                    "accepted": False,
                    "reason": (
                        "all_changed_files_created_by_this_commit"
                        if not ineligible
                        else "no_changed_file_survives_the_pre_image_filter"
                    ),
                    "created_by_commit": created,
                    "ineligible_in_universe": ineligible,
                }
            )
            return False
        dropped = tuple(sorted(p for p in commit.changed if p not in universe))
        dropped_detail[commit.sha] = {
            "created_by_commit": created,
            "ineligible_in_universe": ineligible,
        }
        considered.append(
            {
                "commit": commit.sha,
                "stratum": stratum,
                "changed": list(commit.changed),
                "accepted": True,
                "reason": "accepted",
            }
        )
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

    kept_shas = {c.commit for c in cases}
    n_considered = len(considered)
    n_accepted = sum(1 for row in considered if row["accepted"])
    rejected = [row for row in considered if not row["accepted"]]
    reasons: Dict[str, int] = {}
    for row in rejected:
        reasons[str(row["reason"])] = reasons.get(str(row["reason"]), 0) + 1

    return {
        "schema": SCHEMA,
        "anchor_commit": anchor_sha,
        "selection": SELECTION,
        "strata_actual": strata_actual,
        "selection_census": {
            "history_scanned": len(history),
            "admissible_total": len(ordered),
            "admissible_multi_file": len(multi),
            "admissible_single_file": len(single),
            "multi_file_quota": want_multi,
            "multi_file_used": strata_actual["multi_file"],
            "multi_file_admissible_unused": max(
                0, len(multi) - strata_actual["multi_file"]
            ),
            "note": (
                "multi_file_quota is a choice, not a ceiling: admissible "
                "multi-file supply exceeds it, so the unused remainder was "
                "left on the table by the quota, not missing from history."
            ),
        },
        "acceptance": {
            "commits_considered": n_considered,
            "commits_accepted": n_accepted,
            "commits_rejected": n_considered - n_accepted,
            "acceptance_rate": round(n_accepted / n_considered, 4) if n_considered else 0.0,
            "rejection_reasons": reasons,
            "rejected_commits": rejected,
            "composition_bias": (
                "Rejections are not a random sample. A commit is rejected when "
                "no file it changed existed in the pre-image tree -- i.e. "
                "file-CREATING commits. Multi-file creators are removed "
                "wholesale, and those are disproportionately the cross-plane "
                "ones (workflow + doc + fixture + test in a single commit). "
                "The corpus is therefore biased toward edits to existing code "
                "and against the introduction of new cross-plane structure."
            ),
        },
        "dropped_breakdown": {
            "field_is_misnamed": (
                "gold_created_dropped collects every changed path outside the "
                "ELIGIBLE universe, not only paths the commit created. Files "
                "that existed in the parent tree but fail the suffix/size rule "
                "land in it too. The total is correct either way -- an "
                "ineligible file is unretrievable as well -- but the label "
                "over-attributes to creation. Kept as-is for digest stability."
            ),
            "created_by_commit": sum(
                len(d["created_by_commit"])
                for sha, d in dropped_detail.items()
                if sha in kept_shas
            ),
            "existed_but_ineligible": sum(
                len(d["ineligible_in_universe"])
                for sha, d in dropped_detail.items()
                if sha in kept_shas
            ),
            "per_case": {
                c.case_id: dropped_detail[c.commit]
                for c in cases
                if c.commit in dropped_detail
                and (
                    dropped_detail[c.commit]["created_by_commit"]
                    or dropped_detail[c.commit]["ineligible_in_universe"]
                )
            },
        },
        "plane_composition": _plane_composition(cases),
        "universe_rule": budget.as_dict(),
        "cases": [asdict(c) for c in cases],
        "digest": digest_of(cases),
    }


def _plane_composition(cases: Sequence[Case]) -> Dict[str, object]:
    """How much of this corpus is anything other than Python.

    Declared as a first-class field because it decides what the corpus is
    *able* to show.  A task set whose gold is ~91% ``.py`` has almost no mass
    on which a cross-plane retrieval win could appear, so a null result from a
    four-plane method here is close to preordained and must not be read as a
    kill criterion firing.
    """
    by_suffix: Dict[str, int] = {}
    by_plane: Dict[str, int] = {}
    gold_total = 0
    multi_plane = 0
    knowledge_cases = 0
    gate1_shape = 0
    for case in cases:
        planes = set()
        suffixes = set()
        for path in case.gold:
            gold_total += 1
            suffix = "." + path.rsplit(".", 1)[-1].lower() if "." in path else "(none)"
            by_suffix[suffix] = by_suffix.get(suffix, 0) + 1
            plane = plane_of(path)
            by_plane[plane] = by_plane.get(plane, 0) + 1
            planes.add(plane)
            suffixes.add(suffix)
        if len(planes) > 1:
            multi_plane += 1
        if "knowledge" in planes:
            knowledge_cases += 1
        if {".py", ".md", ".csv"} <= suffixes:
            gate1_shape += 1
    return {
        "gold_paths_total": gold_total,
        "gold_by_suffix": dict(sorted(by_suffix.items(), key=lambda kv: -kv[1])),
        "gold_by_plane": dict(sorted(by_plane.items(), key=lambda kv: -kv[1])),
        "cases_spanning_more_than_one_plane": multi_plane,
        "cases_touching_the_knowledge_plane": knowledge_cases,
        "cases_matching_the_gate1_python_markdown_csv_shape": gate1_shape,
        "type_plane_representatives": 0,
        "warning": (
            "This corpus grades a hypothesis it cannot exercise. Gold is "
            "overwhelmingly Python; only a handful of cases span more than one "
            "plane; the Type plane has no file-level representative at all; and "
            "the Gate-1 flagship scenario (propagate across Python, Markdown "
            "and CSV) has no representative. A four-plane method can register a "
            "LOSS here, but a cross-plane WIN has almost no mass to appear on. "
            "Read a null result as 'this corpus cannot see it', never as a kill."
        ),
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
                "paths_dropped_from_gold": sum(
                    len(c["gold_created_dropped"]) for c in cases
                ),
                "acceptance": {
                    k: v
                    for k, v in record["acceptance"].items()
                    if k not in ("rejected_commits", "composition_bias")
                },
                "selection_census": {
                    k: v
                    for k, v in record["selection_census"].items()
                    if k != "note"
                },
                "plane_composition": {
                    k: v
                    for k, v in record["plane_composition"].items()
                    if k != "warning"
                },
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
