"""Build and freeze a SECOND retrieval task set, selected to make the
four-plane question askable.

This module is additive.  It does not read, rebuild, re-freeze or renumber
``taskset.json``; that corpus stays byte-identical and keeps its own digest,
because slice s07 pins it by content.  What lands here is a separate
artifact with its own schema, its own digest and its own selection rule.

Why a second corpus exists at all
---------------------------------
The first one cannot decide anything about cross-plane structure, and that
is a measurement rather than an opinion.  Of its 35 gold slots 32 are
``.py``; 3 of 20 cases span more than one Project-Twin plane; exactly one
touches the Knowledge plane; none touches the Type plane; and the Gate-1
flagship shape (Python, Markdown and CSV moving together) has no
representative.  A cross-plane retrieval arm scored against it returned a
paired MRR delta of exactly +0.000000 with a bootstrap CI of [0, 0] --
degenerate, because the graph signal reached 5 of 35 gold slots and on every
one of them the text baseline had already put the gold at rank 1-3.  That is
an instrument reporting its own blindness, not a result about the world.

What this corpus is, and is not
-------------------------------
It is an instrument awaiting a subject.  A better corpus makes the four-plane
question *askable*.  It does not make an answer *interpretable*, because the
cross-plane edges this repository can currently produce are laundered: all
2,528 of them carry one hardcoded evidence constant, and a deliberately
falsified edge was measured to receive the same ``assurance='verified'``
label as a true one.  Fixing that verifier is production work elsewhere in
the tree and is explicitly not what this file does.  Until it is fixed, a
win measured on this corpus is a win for a label, not for a plane.

The four honesty rules, kept from the first corpus and one added
---------------------------------------------------------------
* **Gold before retriever.**  Gold is derived from git history and frozen
  before any retriever is pointed at it.  This module imports no retriever
  and no scorer -- ``test_taskset_xplane`` proves that by inspecting the
  import graph in a fresh interpreter, not by grepping this docstring.
* **Frozen by digest.**  ``load`` recomputes a sha256 over the canonical case
  list and refuses a record whose digest does not match.
* **The denominator is recorded.**  Every commit the selector looked at is
  counted, and each is attributed either to the rule that rejected it or to
  the stratum quota that did not sample it.  Rejection and non-selection are
  different things and are kept in different buckets.
* **Every rule must be able to reject.**  A rule that fires on nothing in
  this history is not a rule; it is decoration that will be mistaken for a
  safeguard later.  ``rules_dropped_because_they_reject_nothing`` records the
  ones that were tried and removed, with their measured zero.

The Type plane, stated plainly and not walked back
--------------------------------------------------
The Type plane has no file-level node.  A gold label whose unit is a file
path can never name it, so this corpus represents three planes, not four,
and ``type_plane_representable`` is ``false`` in the record.  Counting a
``.py`` file because it happens to carry annotations would be papering over
the gap: the retrievable unit would still be the file, and a retriever that
returned it would score for finding code, not for finding a type.  Making
the Type plane addressable needs gold whose unit is a *symbol* -- a
(path, qualified name, revision) triple -- which needs a symbol-resolving
extractor over the pre-image tree and a retriever contract whose candidates
are symbols rather than files.  Both are out of scope here and neither is
attempted.

Known limitation inherited unchanged from the first corpus: a commit message
is written after the change, so every query is a hindsight description of
the work rather than a request made before it.
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
    from s09_eval.taskset import plane_of, scrub
else:
    from . import gitio
    from .contract import Budget
    from .taskset import plane_of, scrub

SCHEMA = "forest_v2.s09.taskset_xplane/1"

DEFAULT_PATH = Path(__file__).resolve().parent / "taskset_xplane.json"

#: The four planes the master plan actually defines (section 5).  ``plane_of``
#: is reused unchanged from the first corpus so the two artifacts label a path
#: identically, but its ``presentation`` bucket (``.html`` / ``.css``) is NOT a
#: Project-Twin plane and is not counted as plane-span here.  Neither is
#: ``unknown``.  The difference is not cosmetic: counting ``presentation``
#: inflates the cross-plane supply in this history from 61 commits to 70.
TWIN_PLANES = frozenset({"code", "type", "data", "knowledge"})

#: The commit this corpus is cut from.  Pinned, never ``HEAD``: a task set
#: whose anchor moves is not frozen, it is merely stationary until someone
#: commits.
ANCHOR = "d849c2a94d66ffb1bf892de924995645395bf2a6"

#: The frozen selection rule.  Changing any value here changes the digest.
#:
#: ``history_limit`` covers the whole reachable history on purpose.  The first
#: corpus scanned 1,200 commits; 61 commits in this history carry usable
#: cross-plane gold and only 13 of them fall inside that window, so 48 were
#: excluded by window position alone.  Since the total cross-plane supply is
#: 61, a corpus that needs 60 cases cannot afford to lose any of them to a
#: scan limit.
#:
#: ``require_python_change`` is absent by design.  The first corpus required
#: one, which silently deleted the entire ``{data, knowledge}`` stratum -- 10
#: commits in which a document and a schema moved together with no Python at
#: all.  That is the purest cross-plane shape in the history and the old rule
#: could not see it.
SELECTION = {
    "anchor": ANCHOR,
    "history_limit": 100000,
    "max_gold_paths": 20,
    "max_rename_fraction": 0.5,
    "control_min_gold_paths": 2,
    "single_plane_control_target": 30,
    "cross_plane_quota": "every admissible cross-plane commit; supply is the ceiling",
    "order": "sha256(commit_sha) ascending",
}

#: The selection rules, in the order they are applied.  A commit is
#: attributed to the FIRST rule that fires, so the buckets are disjoint and
#: the order is part of the frozen rule rather than an implementation detail.
SELECTION_RULES = (
    "rename_dominated_diff",
    "no_retrievable_gold_in_pre_image",
    "gold_exceeds_largest_cutoff",
)

#: Not a selection rule, and deliberately not listed as one.  It fires zero
#: times in this history and therefore cannot demonstrate a rejection, which
#: by this corpus's own standard disqualifies it from being called a rule.
#: It is kept as an I/O failure branch because it separates "git could not
#: read the parent tree" from "the parent tree holds no gold", two very
#: different facts that would otherwise be merged into the largest rejection
#: bucket and misread as selection bias.
STRUCTURAL_GUARDS = {
    "parent_tree_unreadable": (
        "I/O guard, not a selection criterion. A case needs a pre-image tree "
        "to search; if git cannot produce one, the commit is unusable for a "
        "reason that has nothing to do with what it changed. Measured "
        "rejections in this history: 0. Listed apart from the rules precisely "
        "because a branch that never fires must not be counted as a safeguard."
    ),
}

#: Each rule, with the reason it exists.  The reason is part of the artifact
#: because a threshold without a justification is a number somebody will tune
#: until the result improves.
RULE_REASONS = {
    "rename_dominated_diff": (
        "A content-preserving rename is not a semantic change, and worse, its "
        "gold set is not stable. Measured on commit 946db82a: with git's "
        "default rename detection the commit reports 309 changed paths and "
        "yields 3 gold; with 'diff.renames=false' it reports 558, and the 249 "
        "extra are the pre-rename paths, which DO exist in the parent tree and "
        "ARE eligible, so the same commit would contribute ~249 gold slots. A "
        "corpus whose Recall@k denominator moves when a client-side git config "
        "flag moves is not frozen. Rejecting rename-dominated diffs makes the "
        "corpus invariant to that knob instead of dependent on it."
    ),
    "no_retrievable_gold_in_pre_image": (
        "Every changed path was created by this commit or fails the "
        "suffix/size rule, so nothing it touched can be retrieved from the "
        "pre-image tree. This is the largest bucket and it is biased: it is "
        "dominated by file-CREATING commits, which is exactly the shape that "
        "introduces new cross-plane structure. The bias is not fixable within "
        "a pre-image retrieval task; it is recorded so nobody reads this "
        "corpus as a uniform sample of the repository's history."
    ),
    "gold_exceeds_largest_cutoff": (
        "Recall@k is reported up to k=20. A case with more than 20 gold paths "
        "has Recall@20 bounded above by 20/G < 1 for every retriever, perfect "
        "ones included, so it adds a term that no method can win and that "
        "moves the mean for all of them equally. The cap is set to the largest "
        "cutoff rather than to a taste-chosen small number, and its cost is "
        "recorded in 'cap_cost'."
    ),
}

#: Tried, measured, and removed.  Recorded so the check is not silently
#: repeated by the next person who thinks it sounds prudent.
RULES_DROPPED = {
    "min_message_chars>=24": {
        "measured_rejections": 0,
        "population": "770 gold-bearing commits reachable from the anchor",
        "reason": (
            "It rejects nothing in this history. A rule that cannot reject is "
            "not a rule -- it is a line of configuration that a later reader "
            "will count as a safeguard. Removed rather than kept at zero."
        ),
    },
}


def twin_planes(paths: Sequence[str]) -> Tuple[str, ...]:
    """The Project-Twin planes a gold set is evidence for, sorted."""
    return tuple(sorted({plane_of(p) for p in paths} & TWIN_PLANES))


def _stem(path: str) -> str:
    base = path.rsplit("/", 1)[-1]
    return (base.rsplit(".", 1)[0] if "." in base else base).lower()


def seam_stems(paths: Sequence[str]) -> Tuple[str, ...]:
    """Stems that appear in two or more planes inside one gold set.

    This is the shape worth preferring: one artifact expressed twice, as a
    document and as its machine-readable contract (``PACKET.md`` beside
    ``PACKET.json``), so the two paths are cross-plane *evidence* rather than
    two unrelated files that happened to ride in the same commit.  Two files
    changing together because somebody ran a formatter satisfies "multi-plane"
    and means nothing.

    The label is recorded rather than used as a filter, because measured over
    this whole history the shape occurs in only a handful of commits -- far
    too few to build a corpus from.  That scarcity is itself a finding about
    what this repository can support.
    """
    by_stem: Dict[str, set] = {}
    for path in paths:
        plane = plane_of(path)
        if plane in TWIN_PLANES:
            by_stem.setdefault(_stem(path), set()).add(plane)
    return tuple(sorted(s for s, planes in by_stem.items() if len(planes) >= 2))


@dataclass(frozen=True)
class XCase:
    """One frozen cross-plane retrieval case."""

    case_id: str
    commit: str
    parent: str
    committed_at: int
    stratum: str
    query_raw: str
    query_scrubbed: str
    gold: Tuple[str, ...]
    gold_planes: Tuple[str, ...]
    gold_dropped_created: Tuple[str, ...]
    gold_dropped_ineligible: Tuple[str, ...]
    seam_stems: Tuple[str, ...]
    leak_tokens: Tuple[str, ...]
    universe_size: int


def _canonical(cases: Sequence[XCase]) -> str:
    return json.dumps([asdict(c) for c in cases], sort_keys=True, separators=(",", ":"))


def digest_of(cases: Sequence[XCase]) -> str:
    return "sha256:" + hashlib.sha256(_canonical(cases).encode("utf-8")).hexdigest()


def _order_key(sha: str) -> str:
    return hashlib.sha256(sha.encode()).hexdigest()


def build(repo: Path, anchor: str = ANCHOR, budget: Budget | None = None) -> Dict[str, object]:
    """Select cases deterministically from git history and return the record.

    Nothing in here consults a retriever, a score, or a previous result.  The
    only inputs are the anchor commit, the frozen rule above, and the
    repository's history.
    """
    budget = budget or Budget()
    anchor_sha = gitio.rev_parse(repo, anchor)
    history = gitio.read_history(repo, anchor_sha, int(SELECTION["history_limit"]))
    rename_stats = gitio.read_rename_stats(
        repo, anchor_sha, int(SELECTION["history_limit"])
    )
    max_gold = int(SELECTION["max_gold_paths"])
    max_rename = float(SELECTION["max_rename_fraction"])

    trees: Dict[str, Dict[str, Tuple[str, int]] | None] = {}

    def parent_tree(rev: str):
        if rev not in trees:
            try:
                trees[rev] = gitio.list_tree(repo, rev)
            except gitio.GitError:
                trees[rev] = None
        return trees[rev]

    rejected: List[Dict[str, object]] = []
    admissible: List[Dict[str, object]] = []
    #: counterfactual bookkeeping for ``cap_cost``: what the cap threw away
    over_cap: List[Dict[str, object]] = []
    #: counterfactual bookkeeping for ``supply_chain``: cross-plane commits
    #: each rule removed, so the attrition from raw supply to accepted cases
    #: is a measured chain rather than three numbers that have to be trusted
    #: to be about the same population.
    rule_removed_cross: Dict[str, List[str]] = {name: [] for name in SELECTION_RULES}
    cross_plane_raw: List[str] = []

    for commit in history:
        renames, total = rename_stats.get(commit.sha, (0, 0))
        fraction = (renames / total) if total else 0.0
        tree = parent_tree(commit.parent)
        if tree is None:
            rejected.append(
                {"commit": commit.sha, "rule": "parent_tree_unreadable",
                 "changed": len(commit.changed)}
            )
            continue
        universe = {p for p, (_, size) in tree.items() if budget.eligible(p, size)}
        gold = tuple(sorted(p for p in commit.changed if p in universe))
        planes = twin_planes(gold)
        is_cross = len(planes) >= 2
        if is_cross:
            cross_plane_raw.append(commit.sha)
        if fraction >= max_rename:
            if is_cross:
                rule_removed_cross["rename_dominated_diff"].append(commit.sha)
            rejected.append(
                {"commit": commit.sha, "rule": "rename_dominated_diff",
                 "changed": len(commit.changed), "gold_paths": len(gold),
                 "gold_planes": list(planes),
                 "rename_entries": renames, "diff_entries": total,
                 "rename_fraction": round(fraction, 4)}
            )
            continue
        if not gold:
            created = sorted(p for p in commit.changed if p not in tree)
            rejected.append(
                {"commit": commit.sha, "rule": "no_retrievable_gold_in_pre_image",
                 "changed": len(commit.changed),
                 "all_changed_paths_were_created_here": len(created) == len(commit.changed)}
            )
            continue
        if len(gold) > max_gold:
            if is_cross:
                rule_removed_cross["gold_exceeds_largest_cutoff"].append(commit.sha)
            over_cap.append(
                {"commit": commit.sha, "gold_paths": len(gold),
                 "gold_planes": list(planes), "subject_len": len(commit.subject)}
            )
            rejected.append(
                {"commit": commit.sha, "rule": "gold_exceeds_largest_cutoff",
                 "changed": len(commit.changed), "gold_paths": len(gold),
                 "gold_planes": list(planes)}
            )
            continue
        admissible.append(
            {
                "commit": commit,
                "gold": gold,
                "planes": planes,
                "created": tuple(sorted(p for p in commit.changed if p not in tree)),
                "ineligible": tuple(
                    sorted(p for p in commit.changed if p in tree and p not in universe)
                ),
                "universe_size": len(universe),
            }
        )

    admissible.sort(key=lambda row: _order_key(row["commit"].sha))
    cross = [r for r in admissible if len(r["planes"]) >= 2]
    single = [r for r in admissible if len(r["planes"]) < 2]
    control_min = int(SELECTION["control_min_gold_paths"])
    control_pool = [r for r in single if len(r["gold"]) >= control_min]
    control_quota = int(SELECTION["single_plane_control_target"])
    control = control_pool[:control_quota]

    not_sampled = {
        "single_plane_below_control_min_gold": {
            "count": sum(1 for r in single if len(r["gold"]) < control_min),
            "reason": (
                "Cross-plane cases are multi-file by construction. A control "
                "stratum of single-file cases would confound plane-span with "
                "gold-set size, and any difference between the strata could be "
                "read as either. The control is drawn only from single-plane "
                "commits that are also multi-file, so the two strata differ in "
                "plane-span and not in shape."
            ),
        },
        "single_plane_beyond_control_quota": {
            "count": max(0, len(control_pool) - len(control)),
            "reason": (
                "The control stratum is a placebo, not a second measurement: "
                "it exists to check whether a cross-plane method's gain "
                "concentrates where cross-plane gold is. It is capped so it "
                "cannot outweigh the cross-plane stratum it is meant to "
                "contrast with."
            ),
        },
    }

    selected = sorted(cross + control, key=lambda row: _order_key(row["commit"].sha))
    cases: List[XCase] = []
    for index, row in enumerate(selected):
        commit = row["commit"]
        scrubbed, removed = scrub(commit.message, row["gold"])
        cases.append(
            XCase(
                case_id=f"x{index:02d}",
                commit=commit.sha,
                parent=commit.parent,
                committed_at=commit.committed_at,
                stratum="cross_plane" if len(row["planes"]) >= 2 else "single_plane_control",
                query_raw=commit.message,
                query_scrubbed=scrubbed,
                gold=row["gold"],
                gold_planes=row["planes"],
                gold_dropped_created=row["created"],
                gold_dropped_ineligible=row["ineligible"],
                seam_stems=seam_stems(row["gold"]),
                leak_tokens=tuple(removed),
                universe_size=row["universe_size"],
            )
        )

    reasons: Dict[str, int] = {}
    for row in rejected:
        reasons[str(row["rule"])] = reasons.get(str(row["rule"]), 0) + 1

    return {
        "schema": SCHEMA,
        "anchor_commit": anchor_sha,
        "supersedes_nothing": (
            "This artifact is additive. 'taskset.json' (schema "
            "forest_v2.s09.taskset/2, digest sha256:c3ef36f1...) is neither "
            "read nor rebuilt by this module, keeps its own cases and case "
            "ids, and remains the corpus every number published so far was "
            "measured on."
        ),
        "selection": SELECTION,
        "selection_rules_in_order": list(SELECTION_RULES),
        "rule_reasons": RULE_REASONS,
        "structural_guards_that_are_not_rules": STRUCTURAL_GUARDS,
        "rules_dropped_because_they_reject_nothing": RULES_DROPPED,
        "census": _census(history, rejected, reasons, admissible, cross,
                          control_pool, control, cases, not_sampled),
        "supply_chain": _supply_chain(cross_plane_raw, rule_removed_cross, cross),
        "cap_cost": _cap_cost(over_cap, cross),
        "plane_composition": _plane_composition(cases),
        "universe_rule": budget.as_dict(),
        "cases": [asdict(c) for c in cases],
        "digest": digest_of(cases),
    }


def _census(history, rejected, reasons, admissible, cross, control_pool,
            control, cases, not_sampled) -> Dict[str, object]:
    """Considered, rejected, admissible-but-unsampled, accepted -- all four.

    The first corpus recorded only "35 considered, 20 accepted, 15 rejected"
    and the 15 were not a random sample.  Worse, the commits it never looked
    at at all -- everything outside a 1,200-commit window and everything the
    quota stopped at -- had no counter anywhere.  Four buckets, and they add
    up.
    """
    n_rejected = len(rejected)
    n_unsampled = sum(int(v["count"]) for v in not_sampled.values())
    return {
        "commits_considered": len(history),
        "commits_rejected_by_rule": n_rejected,
        "commits_admissible": len(admissible),
        "commits_admissible_but_not_sampled": n_unsampled,
        "commits_accepted": len(cases),
        "buckets_sum_to_considered": (
            n_rejected + len(admissible) == len(history)
            and len(cases) + n_unsampled == len(admissible)
        ),
        "rejection_reasons": reasons,
        "not_sampled": not_sampled,
        "supply": {
            "cross_plane_admissible": len(cross),
            "cross_plane_accepted": sum(1 for c in cases if c.stratum == "cross_plane"),
            "cross_plane_unused": len(cross)
            - sum(1 for c in cases if c.stratum == "cross_plane"),
            "single_plane_control_pool": len(control_pool),
            "single_plane_control_accepted": len(control),
            "note": (
                "Cross-plane supply is the binding constraint, not a quota: "
                "every admissible cross-plane commit in the whole reachable "
                "history is accepted, and 'cross_plane_unused' is 0 because "
                "there is nothing left to take. Read a demand for more "
                "cross-plane cases as a demand for a different repository."
            ),
        },
    }


def _supply_chain(cross_plane_raw, rule_removed_cross, cross) -> Dict[str, object]:
    """Raw cross-plane supply, then what each rule took, then what is left.

    Three separate numbers about "how many cross-plane commits there are"
    invite the reader to assume they describe the same population.  They do
    not: the raw supply is measured before any rule, and each rule removes
    from what the previous one left.  Written as a chain that has to add up.
    """
    steps = []
    remaining = len(cross_plane_raw)
    for rule in SELECTION_RULES:
        removed = rule_removed_cross.get(rule, [])
        remaining -= len(removed)
        steps.append(
            {
                "rule": rule,
                "cross_plane_removed": len(removed),
                "commits": sorted(removed),
                "cross_plane_remaining": remaining,
            }
        )
    return {
        "cross_plane_before_any_rule": len(cross_plane_raw),
        "steps": steps,
        "cross_plane_admissible": len(cross),
        "chain_closes": remaining == len(cross),
        "note": (
            "'Cross-plane' here means the gold set spans two or more of the "
            "four planes the master plan defines. Counting the ``.html``/"
            "``.css`` 'presentation' bucket as a plane would raise the "
            "pre-rule supply in this history from 61 to 70; it is not a "
            "Project-Twin plane and is not counted as span, though such paths "
            "still appear as gold and are still retrievable."
        ),
    }


def _cap_cost(over_cap, cross) -> Dict[str, object]:
    """What ``max_gold_paths`` cost, in the units it cost it in."""
    lost_cross = [r for r in over_cap if len(r["gold_planes"]) >= 2]
    lost_tri = [r for r in lost_cross if len(r["gold_planes"]) >= 3]
    return {
        "rule": "max_gold_paths <= 20",
        "commits_excluded": len(over_cap),
        "cross_plane_commits_excluded": len(lost_cross),
        "tri_plane_commits_excluded": len(lost_tri),
        "excluded": [
            {"commit": r["commit"], "gold_paths": r["gold_paths"],
             "gold_planes": r["gold_planes"]}
            for r in sorted(over_cap, key=lambda r: -r["gold_paths"])
        ],
        "cross_plane_supply_before_cap": len(cross) + len(lost_cross),
        "cross_plane_supply_after_cap": len(cross),
        "why_not_a_tighter_cap": (
            "A cap of 6 -- the first corpus's max_changed -- leaves 39 "
            "cross-plane commits and collapses the {code,data,knowledge} "
            "stratum from 15 to 3. The tri-plane shape is precisely the one "
            "worth measuring, and it is systematically the one with many gold "
            "paths, so a tight cap does not trim noise, it deletes the "
            "subject. The cap is therefore set where the metric stops being "
            "attainable rather than where the cases stop feeling tidy."
        ),
        "what_it_removed": (
            "Both cross-plane commits above the cap are mechanical mass edits "
            "-- a 56-path central-wiring port and a 28-path rebrand that also "
            "carries 34 renames. Neither is cross-plane evidence: the files "
            "moved together because one substitution was applied to all of "
            "them, not because a change in one plane implied a change in "
            "another. That they are exactly what the cap removes is stated as "
            "an observation, not as the cap's justification -- the "
            "justification is the Recall@k bound above."
        ),
    }


def _plane_composition(cases: Sequence[XCase]) -> Dict[str, object]:
    """Plane composition as a first-class field, not a paragraph of prose."""
    gold_by_plane: Dict[str, int] = {}
    gold_by_suffix: Dict[str, int] = {}
    combo_counts: Dict[str, int] = {}
    gold_total = 0
    multi_plane = 0
    knowledge_cases = 0
    seam_cases = 0
    gate1_shape = 0
    tri_plane = 0
    for case in cases:
        suffixes = set()
        for path in case.gold:
            gold_total += 1
            suffix = "." + path.rsplit(".", 1)[-1].lower() if "." in path else "(none)"
            suffixes.add(suffix)
            gold_by_suffix[suffix] = gold_by_suffix.get(suffix, 0) + 1
            plane = plane_of(path)
            gold_by_plane[plane] = gold_by_plane.get(plane, 0) + 1
        combo = "+".join(case.gold_planes) or "(none)"
        combo_counts[combo] = combo_counts.get(combo, 0) + 1
        if len(case.gold_planes) > 1:
            multi_plane += 1
        if len(case.gold_planes) > 2:
            tri_plane += 1
        if "knowledge" in case.gold_planes:
            knowledge_cases += 1
        if case.seam_stems:
            seam_cases += 1
        if {".py", ".md", ".csv"} <= suffixes:
            gate1_shape += 1
    return {
        "cases_total": len(cases),
        "gold_paths_total": gold_total,
        "gold_slots_by_plane": dict(sorted(gold_by_plane.items(), key=lambda kv: -kv[1])),
        "gold_slots_by_suffix": dict(sorted(gold_by_suffix.items(), key=lambda kv: -kv[1])),
        "cases_by_plane_combination": dict(sorted(combo_counts.items(), key=lambda kv: -kv[1])),
        "cases_spanning_more_than_one_plane": multi_plane,
        "cases_spanning_three_planes": tri_plane,
        "cases_touching_the_knowledge_plane": knowledge_cases,
        "cases_with_a_cross_plane_stem_seam": seam_cases,
        "cases_matching_the_gate1_python_markdown_csv_shape": gate1_shape,
        "type_plane_representable": False,
        "type_plane_gold_slots": gold_by_plane.get("type", 0),
        "presentation_slots_not_counted_as_plane_span": gold_by_plane.get(
            "presentation", 0
        ),
        "presentation_note": (
            "'gold_slots_by_plane' reports a 'presentation' bucket (.html, "
            ".css) inherited from the shared suffix map. It is NOT one of the "
            "four planes and is not counted in 'gold_planes' or in any "
            "cases_spanning_* figure. Such paths are still gold and still "
            "retrievable -- they just cannot make a case cross-plane on their "
            "own. Counting them would inflate the pre-rule cross-plane supply "
            "in this history from 61 commits to 70."
        ),
        "type_plane_note": (
            "Zero, and not for lack of trying. The Type plane has no "
            "file-level node, so a gold label whose unit is a file path cannot "
            "name it. Counting a .py file because it carries annotations would "
            "not fix this: the retrievable unit would still be the file, and a "
            "retriever returning it would be scored for finding code. Making "
            "the Type plane addressable requires gold whose unit is a symbol -- "
            "a (path, qualified name, revision) triple -- plus a symbol-level "
            "extractor over the pre-image tree and a retriever contract whose "
            "candidates are symbols. Not built here, and not claimed."
        ),
        "seam_note": (
            "The tightest cross-plane shape available -- one artifact "
            "expressed as a document and as its machine-readable contract, "
            "e.g. a work packet's .md beside its .json -- occurs in only a "
            "handful of commits in the entire reachable history. It is "
            "labelled per case rather than used as a filter, because filtering "
            "on it would leave a corpus far too small to decide anything. Any "
            "analysis that wants only semantically-tight cross-plane evidence "
            "should restrict to cases with a non-empty 'seam_stems' and report "
            "that reduced n honestly."
        ),
        "what_this_corpus_can_and_cannot_show": (
            "It can show whether cross-plane structure helps retrieval, "
            "because there is now mass on which such a win could appear and a "
            "single-plane control stratum on which it should NOT appear. It "
            "cannot show that any observed win is caused by verified "
            "structure, because the cross-plane edges this repository produces "
            "today are laundered: all 2,528 carry one hardcoded evidence "
            "constant, and a deliberately falsified edge was measured to "
            "receive the same assurance='verified' label as a true one. This "
            "artifact is an instrument awaiting a subject."
        ),
    }


def load(path: Path = DEFAULT_PATH) -> Tuple[Dict[str, object], List[XCase]]:
    """Load the frozen corpus, verifying schema and digest before returning."""
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("schema") != SCHEMA:
        raise ValueError(f"unexpected task-set schema {record.get('schema')!r}")
    cases = [
        XCase(
            case_id=c["case_id"],
            commit=c["commit"],
            parent=c["parent"],
            committed_at=c["committed_at"],
            stratum=c["stratum"],
            query_raw=c["query_raw"],
            query_scrubbed=c["query_scrubbed"],
            gold=tuple(c["gold"]),
            gold_planes=tuple(c["gold_planes"]),
            gold_dropped_created=tuple(c["gold_dropped_created"]),
            gold_dropped_ineligible=tuple(c["gold_dropped_ineligible"]),
            seam_stems=tuple(c["seam_stems"]),
            leak_tokens=tuple(c["leak_tokens"]),
            universe_size=c["universe_size"],
        )
        for c in record["cases"]
    ]
    actual = digest_of(cases)
    if actual != record.get("digest"):
        raise ValueError(
            f"task set digest mismatch: file says {record.get('digest')}, "
            f"cases hash to {actual}"
        )
    return record, cases


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[3]))
    parser.add_argument("--anchor", default=ANCHOR)
    parser.add_argument("--out", default=str(DEFAULT_PATH))
    args = parser.parse_args(argv)

    record = build(Path(args.repo), args.anchor, Budget())
    Path(args.out).write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    summary = {
        "schema": record["schema"],
        "anchor_commit": record["anchor_commit"],
        "digest": record["digest"],
        "census": {
            k: v
            for k, v in record["census"].items()
            if k not in ("not_sampled", "supply")
        },
        "supply": {
            k: v for k, v in record["census"]["supply"].items() if k != "note"
        },
        "supply_chain": {
            k: v for k, v in record["supply_chain"].items() if k != "note"
        },
        "cap_cost": {
            k: v
            for k, v in record["cap_cost"].items()
            if k not in ("why_not_a_tighter_cap", "what_it_removed", "excluded")
        },
        "plane_composition": {
            k: v
            for k, v in record["plane_composition"].items()
            if not k.endswith("_note") and not k.startswith("what_this")
        },
        "out": args.out,
    }
    sys.stdout.write(json.dumps(summary, indent=2) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
