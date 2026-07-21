"""ceiling.py -- temporal co-change CEILING check over the eval corpus (lane A2).

THE QUESTION THIS ANSWERS. The independent_diff corpus has miss tasks: minted
``must_include`` labels the current slice does not contain. The "temporal"
hypothesis says a co-change tier (files that repeatedly change together with
no static import edge -- ``structcore.churn.co_change_pairs``) could recover
them. Before any slice-side enrichment is built, this module measures the
CEILING of that hypothesis: for every missed label, is ANY in-scope file
defining that symbol a co-change partner of the task's focus file at all?
If a label's defining file is not even a partner, no enrichment built on these
pairs can ever surface it -- so this number is a hard upper bound on what a
temporal tier could add, measured for the price of a git log instead of a
build.

BACKTEST-CLEAN, OR THE NUMBER IS A TAUTOLOGY. Every minted task records the
commit it came from (``minted_at_sha``), and that commit CO-CHANGED the focus
and the label sources -- that is what minting means. Counting it would let the
eval "predict" a commit from that same commit's own data. The clean arm
therefore computes pairs over ``git log <minted_at_sha>^`` -- history strictly
before the mint (first-parent semantics; merge SHAs are flagged in the row
rather than silently half-counted). The LEAKY arm (full history) is computed
alongside on purpose: the gap between the two arms is the measured size of the
self-prediction artifact, which is exactly how a "co-change could recover X%
of misses" claim derived from full history gets reconciled with the honest
number.

WHAT THIS IS NOT. Even the clean arm is a walk-forward BACKTEST HIT-RATE --
"did pre-commit co-change history name the files this commit went on to
touch?" -- which is the temporal tier's best case, not a live-use recall
measurement. Never report this ceiling as "slicer recall"; the render says so.

RENAME-AWARE, BECAUSE THE ADVERSARIAL PASS PROVED IT MATTERS. Git numstat
paths carry each commit's OWN spelling; a file renamed since (this repo's
agent_env -> daedalus rebrand renamed 93 files at once) leaves its pre-rename
co-changes invisible to an exact-rel match, understating the ceiling. So this
module resolves every focus/defining file to its full historical alias set
(``git log --follow``) and sums co-change counts across spellings BEFORE
applying ``min_count``. The first version of this check was rename-blind and
published "rename-aware matching does not change it" -- the adversarial review
(Nemesis, 2026-07-21) refuted exactly that sentence by hand-verifying a real
verifier.py<->providers/ollama.py coupling across the rebrand boundary. The
corrected numbers are below; keep the instrument rename-aware or a grown-
corpus re-run will understate again.

MEASURED CLOSE (2026-07-21, agent_env corpus, 7 miss tasks / 43 missed
labels; rename-blind first pass corrected by the Nemesis rename-map recount,
then reproduced by this module): clean ceiling at min_count=2 = 1/43 = 2.3%
(a single label, ``_dispatch``: genuine verifier<->ollama coupling crossing
the rebrand); min_count=1 adds nothing further; leaky full-history arm = 6/43
at min_count=2 and 42/43 at min_count=1 -- the self-prediction artifact,
nearly total at the permissive setting. Structural context that bounds any
future hope here: 41 of 43 missed labels sit on focus files BORN AT THEIR
MINT COMMIT (zero pre-mint history -- test files created by the very feature
commit they were minted from), so for them clean unreachability is structural
truth under ANY enrichment; the remaining NO_INSCOPE_DEF label (``_py_maps``)
is a stale label whose definition the mint commit itself deleted. Conclusion:
the "temporal class" of misses was predominantly the mint commit predicting
itself, and slice-side co-change enrichment was NOT built (design NO-GO'd on
this measurement; 1 recoverable label is below any sane build threshold).

THE REOPEN CONDITION (with a materiality floor -- a lone recoverable label
must not reopen a core-API build): reopen the enrichment lane only when a
re-run on a grown corpus reports a clean, rename-aware ceiling at
min_count >= 2 that clears ``REOPEN_MIN_SHARE`` of scored labels OR touches
``REOPEN_MIN_TASKS`` distinct tasks. Caveat to carry: a corpus whose focus
files are born at their mint commits (like today's) can NEVER trip this
regardless of how real temporal coupling is elsewhere -- the zero generalizes
weakly, so re-run it as the corpus grows rather than citing today's close as
permanent.

Per the package contract, imports only structcore's stable public API plus
sibling eval modules. Read-only: never writes the store, the baseline, or any
file. ADVISORY, like every eval number -- see harness.py's guardrail.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from daedalus.structcore.churn import co_change_pairs
from daedalus.structcore.index import cached_index
from daedalus.structcore.languages import spec_for
from daedalus.structcore.parse import extract_units

from .harness import all_tasks, eval_task_tier1
from .tasks import resolve_task_repo

# Classification of one missed label, in decision order:
#   NO_INSCOPE_DEF -- no in-scope file defines this symbol at all: label
#                     hygiene feedback for the minter, not a temporal case.
#   STATIC_EDGE    -- a defining file already IS a static dep/caller of the
#                     focus. A miss here is edge-but-dropped (a slicer defect,
#                     the class the 2026-07 triage measured at zero) -- if this
#                     ever goes non-zero the render shouts, because it is more
#                     important than anything temporal.
#   REACHABLE      -- a defining file's rename-unified co-change count with
#                     the focus reaches min_count under this arm's history:
#                     the enrichment COULD have added it (upper bound -- no
#                     check that a skeleton line would actually carry the
#                     symbol name).
#   UNREACHABLE    -- not even that: no enrichment on these pairs can ever
#                     surface it.
CLASSES = ("REACHABLE", "UNREACHABLE", "STATIC_EDGE", "NO_INSCOPE_DEF")

# Materiality floor for the machine-printed reopen signal. Rationale: the lane
# this gate reopens is a permanent parameter on the core distiller plus an
# experiment harness -- worth building only if the ceiling says it could move
# a double-digit share of the miss set or several distinct tasks, not one
# label (the 2026-07-21 close measured exactly one, and that must read as
# "stay closed"). Either trigger suffices: breadth (many tasks touched a
# little) and depth (one task's misses largely recoverable) are both real
# signals. Judgment defaults, printed with their inputs so a human can
# overrule them knowingly.
REOPEN_MIN_SHARE = 0.10
REOPEN_MIN_TASKS = 3


def _symbol_defs(repo: str, modules: dict) -> dict[str, set[str]]:
    """symbol name -> set of IN-SCOPE rels defining a unit with that name,
    from the current worktree (the same text the slice would emit)."""
    out: dict[str, set[str]] = defaultdict(set)
    root = Path(repo)
    for rel in modules:
        spec = spec_for(rel)
        if not spec:
            continue
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for u in extract_units(rel, text, spec):
            if u.name:
                out[u.name].add(rel)
    return dict(out)


def _parents_of(repo: str, sha: str, timeout: float = 10.0) -> list[str] | None:
    """Parent SHAs of ``sha``, or None when git/the ref is unavailable --
    the probe that distinguishes "no pre-mint history exists" (root commit /
    unknown ref / no git) from "history exists but shows no coupling", which
    ``co_change_pairs``'s []-on-failure contract deliberately does not."""
    try:
        proc = subprocess.run(
            ["git", "-C", repo, "log", "--format=%P", "-1", sha],
            capture_output=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.split()


class _AliasResolver:
    """Historical alias sets (``git log --follow --name-only``) for the small
    set of rels the ceiling actually inspects (focus + defining files), cached
    per (rev, rel). A probe failure degrades to ``{rel}`` (rename-blind for
    that file, i.e. an UNDER-statement of the ceiling) and is COUNTED -- the
    render surfaces a non-zero failure count rather than letting a degraded
    instrument print an authoritative-looking zero."""

    def __init__(self, repo: str, timeout: float = 15.0):
        self.repo = repo
        self.timeout = timeout
        self.failures = 0
        self._cache: dict[tuple[str | None, str], set[str]] = {}

    def aliases(self, rel: str, rev: str | None) -> set[str]:
        key = (rev, rel)
        if key not in self._cache:
            cmd = ["git", "-C", self.repo, "log", "--follow", "--name-only",
                   "--format="]
            if rev:
                cmd.append(rev)
            cmd += ["--", rel]
            names = {rel}
            try:
                proc = subprocess.run(cmd, capture_output=True, timeout=self.timeout,
                                      encoding="utf-8", errors="replace")
                if proc.returncode == 0:
                    names |= {ln.strip().replace("\\", "/")
                              for ln in proc.stdout.splitlines() if ln.strip()}
                else:
                    self.failures += 1
            except (OSError, subprocess.SubprocessError):
                self.failures += 1
            self._cache[key] = names
        return self._cache[key]


def _partner_counts(focus_aliases: set[str], pairs: list[dict]) -> dict[str, int]:
    """Co-change count per partner SPELLING against ANY alias of the focus.
    ``pairs`` must come from ``co_change_pairs(min_count=1)``: unification has
    to happen BEFORE thresholding, or two spellings of one real pair (count 1
    each) die at min_count=2 that they genuinely clear together -- the exact
    rename-blindness the adversarial pass caught."""
    counts: dict[str, int] = {}
    for r in pairs:
        a_is_focus = r["a"] in focus_aliases
        b_is_focus = r["b"] in focus_aliases
        if a_is_focus == b_is_focus:  # neither, or a self-pair across aliases
            continue
        partner = r["b"] if a_is_focus else r["a"]
        counts[partner] = counts.get(partner, 0) + r["count"]
    return counts


def _classify(missed: list[str], focus: str, def_count, min_count: int,
              sym_defs: dict[str, set[str]], modules: dict,
              edges: dict, rev_edges: dict) -> dict[str, str]:
    """``def_count(rel) -> int`` returns the rename-unified co-change count of
    a defining file with the focus under the arm being classified."""
    static_neigh = set(edges.get(focus, ())) | set(rev_edges.get(focus, ()))
    out: dict[str, str] = {}
    for m in missed:
        defs = {d for d in sym_defs.get(m, ()) if d in modules}
        if not defs:
            out[m] = "NO_INSCOPE_DEF"
        elif defs & static_neigh:
            out[m] = "STATIC_EDGE"
        elif any(def_count(d) >= min_count for d in sorted(defs)):
            out[m] = "REACHABLE"
        else:
            out[m] = "UNREACHABLE"
    return out


def temporal_ceiling(tasks: list[dict] | None = None, min_count: int = 2) -> dict:
    """Both arms of the ceiling over every miss task in ``tasks`` (default:
    ``all_tasks()``). Read-only; returns a plain dict, renders via
    ``render_ceiling``. Errored / focus-withheld tasks are excluded from the
    denominator and reported by id -- same discipline as the harness."""
    tasks = all_tasks() if tasks is None else tasks

    idx_cache: dict[str, dict] = {}
    defs_cache: dict[str, dict[str, set[str]]] = {}
    alias_cache: dict[str, _AliasResolver] = {}
    per_task: list[dict] = []
    excluded: list[str] = []

    for task in tasks:
        try:
            repo = resolve_task_repo(task["repo"])
            if repo not in idx_cache:
                idx_cache[repo] = cached_index(repo)
        except (ValueError, OSError):
            excluded.append(task.get("id", "<unknown>"))
            continue
        idx = idx_cache[repo]
        row = eval_task_tier1(task, idx=idx)
        if "error" in row or row.get("focus_withheld"):
            excluded.append(row["id"])
            continue
        if not row["missed"]:
            continue

        if repo not in defs_cache:
            defs_cache[repo] = _symbol_defs(repo, idx["modules"])
        modules = idx["modules"]
        edges = idx.get("import_edges") or {}
        rev_edges = idx.get("import_edges_reverse") or {}
        focus = row["focus_file"]
        sha = task.get("minted_at_sha")

        parents = _parents_of(repo, sha) if sha else None
        has_rev = bool(parents)
        rev = f"{sha}^" if has_rev else None
        if repo not in alias_cache:
            alias_cache[repo] = _AliasResolver(repo)
        aliases = alias_cache[repo]

        # min_count=1 fetch on BOTH arms: rename-unification must sum counts
        # across spellings before the threshold is applied (see _partner_counts).
        clean_pairs = co_change_pairs(repo, min_count=1, rev=rev) if has_rev else []
        leaky_pairs = co_change_pairs(repo, min_count=1)

        def _def_count(counts: dict[str, int], arm_rev: str | None):
            def count_of(d: str) -> int:
                return sum(counts.get(s, 0) for s in sorted(aliases.aliases(d, arm_rev)))
            return count_of

        clean_counts = _partner_counts(aliases.aliases(focus, rev), clean_pairs)
        leaky_counts = _partner_counts(aliases.aliases(focus, None), leaky_pairs)
        classes_clean = (_classify(row["missed"], focus, _def_count(clean_counts, rev),
                                   min_count, defs_cache[repo], modules, edges, rev_edges)
                         if has_rev else
                         {m: "NO_BACKTEST_REV" for m in row["missed"]})
        classes_leaky = _classify(row["missed"], focus, _def_count(leaky_counts, None),
                                  min_count, defs_cache[repo], modules, edges, rev_edges)
        per_task.append({
            "id": row["id"],
            "target": row["target"],
            "focus_file": focus,
            "label_provenance": row["label_provenance"],
            "label_tier": row["label_tier"],
            "missed": list(row["missed"]),
            "minted_at_sha": sha,
            "backtest_rev": f"{sha}^" if has_rev else None,
            # None parents == probe failed / no sha; [] cannot happen for a
            # resolvable sha (a root commit yields [''] -> filtered to []).
            "backtest_rev_reason": (None if has_rev else
                                    ("no minted_at_sha" if not sha else
                                     "sha unresolvable or root commit")),
            "merge_commit": bool(parents and len(parents) > 1),
            "classes_clean": classes_clean,
            "classes_leaky": classes_leaky,
        })

    def _summary(key: str) -> dict:
        counts: dict[str, int] = {}
        for t in per_task:
            for cls in t[key].values():
                counts[cls] = counts.get(cls, 0) + 1
        return dict(sorted(counts.items()))

    summary_clean = _summary("classes_clean")
    summary_leaky = _summary("classes_leaky")
    n_labels = sum(len(t["missed"]) for t in per_task)
    n_scored_clean = n_labels - summary_clean.get("NO_BACKTEST_REV", 0)

    def _ceiling(summary: dict, denom: int) -> float:
        return (summary.get("REACHABLE", 0) / denom) if denom else 0.0

    ceiling_clean = _ceiling(summary_clean, n_scored_clean)
    n_tasks_reachable_clean = sum(
        1 for t in per_task if "REACHABLE" in t["classes_clean"].values())
    return {
        "min_count": min_count,
        "n_miss_tasks": len(per_task),
        "n_missed_labels": n_labels,
        "n_excluded_tasks": len(excluded),
        "excluded_ids": sorted(excluded),
        "per_task": per_task,
        "summary_clean": summary_clean,
        "summary_leaky": summary_leaky,
        "ceiling_clean": ceiling_clean,
        "ceiling_leaky": _ceiling(summary_leaky, n_labels),
        "n_tasks_reachable_clean": n_tasks_reachable_clean,
        # git --follow probes that failed; >0 means some files were scored
        # rename-BLIND (an understatement risk) -- surfaced in the render.
        "alias_probe_failures": sum(a.failures for a in alias_cache.values()),
        # The lane A2 reopen trigger, stated by the machine so a future session
        # cannot misread the close: the clean rename-aware ceiling must clear
        # the materiality floor (share OR breadth), not merely be non-zero --
        # the 2026-07-21 close measured exactly one recoverable label, and one
        # label must read as "stay closed" (see REOPEN_MIN_* rationale).
        "reopen_min_share": REOPEN_MIN_SHARE,
        "reopen_min_tasks": REOPEN_MIN_TASKS,
        "reopen_temporal_lane": (ceiling_clean >= REOPEN_MIN_SHARE
                                 or n_tasks_reachable_clean >= REOPEN_MIN_TASKS),
    }


def render_ceiling(result: dict) -> str:
    """ASCII-only (raw Windows console), honest-framing render."""
    lines = [
        "TEMPORAL CO-CHANGE CEILING -- upper bound on what a co-change slice",
        "tier could recover of the current miss set. This is a walk-forward",
        "BACKTEST HIT-RATE (best case for temporal coupling), NOT slicer",
        "recall -- see daedalus/eval/ceiling.py.",
        "",
        f"min_count={result['min_count']}  miss_tasks={result['n_miss_tasks']}  "
        f"missed_labels={result['n_missed_labels']}  "
        f"excluded_tasks={result['n_excluded_tasks']}",
        "",
        f"  CLEAN arm (history strictly before each mint): {result['summary_clean']}",
        f"  LEAKY arm (full history, incl. the mint commit): {result['summary_leaky']}",
        "",
        f"  clean ceiling: {100 * result['ceiling_clean']:.1f}%   "
        f"leaky ceiling: {100 * result['ceiling_leaky']:.1f}%",
        "  (the gap between the two arms is the self-prediction artifact:",
        "   coupling that exists only because the minted commit is counted)",
    ]
    static_hits = (result["summary_clean"].get("STATIC_EDGE", 0)
                   + result["summary_leaky"].get("STATIC_EDGE", 0))
    if static_hits:
        lines += [
            "",
            "  !! STATIC_EDGE misses present: a missed label's defining file is",
            "  ALREADY a static neighbour of the focus. That is edge-but-dropped",
            "  -- a slicer defect, strictly more important than anything",
            "  temporal. Fix that first:",
        ]
        for t in result["per_task"]:
            for m, cls in sorted(t["classes_clean"].items()):
                if cls == "STATIC_EDGE":
                    lines.append(f"    {t['id']}  {m}")
    reachable_clean = [(t["id"], m) for t in result["per_task"]
                       for m, cls in sorted(t["classes_clean"].items())
                       if cls == "REACHABLE"]
    if reachable_clean:
        lines.append("")
        lines.append("  clean-arm REACHABLE labels (audit these -- each is a "
                     "claim that pre-mint history named the file):")
        for tid, m in reachable_clean:
            lines.append(f"    {tid}  {m}")
    for t in result["per_task"]:
        if t["merge_commit"]:
            lines.append(f"  note: {t['id']} minted at a MERGE commit; clean arm "
                         "is first-parent history only.")
        if t["backtest_rev_reason"]:
            lines.append(f"  note: {t['id']} has no backtest rev "
                         f"({t['backtest_rev_reason']}); clean arm not scored.")
    if result.get("alias_probe_failures"):
        lines.append(f"  !! {result['alias_probe_failures']} rename-alias probe(s) "
                     "failed: those files were scored rename-BLIND and the "
                     "ceiling may be understated.")
    lines.append("")
    floor = (f"floor: >= {100 * result['reopen_min_share']:.0f}% of scored labels "
             f"or >= {result['reopen_min_tasks']} tasks")
    n_reach = result["summary_clean"].get("REACHABLE", 0)
    if result["reopen_temporal_lane"]:
        lines.append(f"  REOPEN signal: clean rename-aware ceiling clears the "
                     f"materiality floor ({floor}) -- the temporal-enrichment "
                     "lane may be worth reopening (see module docstring).")
        if result["min_count"] < 2:
            lines.append("  ...measured at min_count=1, BELOW the reopen "
                         "threshold: a single co-occurrence is one data point, "
                         "not a pattern (churn.py). The reopen condition is "
                         "defined at min_count >= 2.")
    elif n_reach:
        lines.append(f"  reopen signal: none -- {n_reach} clean-reachable "
                     f"label(s) in {result['n_tasks_reachable_clean']} task(s) "
                     f"is below the materiality floor ({floor}); the temporal "
                     "lane stays closed.")
    else:
        lines.append("  reopen signal: none -- clean ceiling is zero; the "
                     "temporal lane stays closed.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m daedalus.eval.ceiling",
        description="Temporal co-change ceiling over the eval corpus -- the "
                    "lane A2 reopen gate. Read-only, advisory.")
    ap.add_argument("--min-count", type=int, default=2,
                    help="co_change_pairs min_count (default 2; 1 = most "
                         "permissive ceiling, any single prior co-commit).")
    args = ap.parse_args(argv)
    result = temporal_ceiling(min_count=args.min_count)
    text = render_ceiling(result)
    try:
        print(text)
    except UnicodeEncodeError:  # pragma: no cover - defensive
        sys.stdout.buffer.write(text.encode("ascii", "replace") + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
