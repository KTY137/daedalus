"""agent_findings.py — consolidate what the external review lanes actually said.

THE PROBLEM THIS SOLVES
-----------------------
A fan-out of a hundred advisory agents produces a hundred JSON reports, and
reading them one by one costs more attention than the fan-out saved. Worse, the
same defect is reported by four different agents in four different wordings, so
a naive concatenation reads as four problems and a real singleton gets buried
among the duplicates.

So this does three mechanical things and refuses to do a fourth:

1. **Extract** every risk and todo, keeping the agent, the model and the file
   slice each came from. Provenance travels with the claim, because "who said
   this, looking at what" is the first question a reader has.
2. **Cluster** near-duplicates by token overlap, and report the cluster SIZE.
   Agreement between independent agents is evidence -- weak evidence, but it is
   the only signal here that is not one model's opinion.
3. **Rank** by corroboration and by whether the target is a fence module, where
   a wrong answer is expensive.

What it deliberately does NOT do is decide whether a finding is TRUE. Every
claim here came from a model reading a slice, and several will be confidently
wrong. The output is a queue for verification, never a defect list -- so nothing
in it is phrased as though it had been confirmed.

CLUSTERING IS INTENTIONALLY CRUDE
---------------------------------
Jaccard overlap on content words, with a high threshold. A cheap clusterer that
under-merges leaves two rows a human collapses on sight; one that over-merges
hides a real finding inside a popular one, and nobody ever sees it again. The
error that stays visible is the one to prefer.

MEASURED, AND IT CHANGED THE DESIGN
-----------------------------------
On the first real corpus (580 claims) the largest cluster was TWO, even at a
threshold of 0.30. The agents essentially never repeat each other -- which is
obvious in hindsight, because the fan-out gave almost every agent a different
file. Corroboration is therefore not available as a ranking signal, and a
ranking that pretended otherwise would just be sorting noise confidently.

So the primary grouping is by TARGET FILE, and cross-model agreement is reported
only where it is actually possible: on the files that more than one model was
given. Everywhere else the honest statement is "one model, one look", and the
output says so rather than implying a consensus that was never taken.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

#: Modules where a wrong review costs the most -- the fence, the money, and the
#: promotion gate. A finding here is read first even when nobody corroborates it.
HIGH_STAKES = (
    "sensitivity.py", "enforce.py", "budget.py", "config.py", "offload.py",
    "vet.py", "spine/", "gated_writes.py", "killswitch.py", "worktree.py",
    "containment.py", "web_api.py",
)

#: Words carrying no discriminating power in this corpus: every report is about
#: code, files and functions, so they cluster everything with everything.
_STOP = frozenset("""
a an the and or but if then than that this these those is are was were be been
being it its of to in on at by for with from as not no non can could may might
will would should must do does did done have has had not so such when where
which who whom whose what why how all any both each few more most other some
only own same too very s t just now code file files function functions module
modules line lines error errors issue issues case cases value values return
returns use used using call calls make makes made will also there here into
""".split())

_WORD = re.compile(r"[a-zA-Z_][a-zA-Z0-9_.]{2,}")


def _tokens(text: str) -> frozenset:
    return frozenset(w.lower() for w in _WORD.findall(text or "")
                     if w.lower() not in _STOP)


def _similar(a: frozenset, b: frozenset, threshold: float = 0.55) -> bool:
    """Jaccard over content words.

    The threshold is high on purpose: see the module docstring on why
    under-merging is the safer failure.
    """
    if not a or not b:
        return False
    inter = len(a & b)
    if not inter:
        return False
    return inter / len(a | b) >= threshold


def load_reports(root=".") -> list[dict]:
    """Every advisory result on disk, from every fan-out run.

    Files beginning with ``_`` are the runs' own aggregates and roll-ups; taking
    them in would double-count every finding they already contain.
    """
    out = []
    for d in sorted(Path(root, "runs/eval").glob("deepseek*")):
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.json")):
            if f.name.startswith("_"):
                continue
            try:
                r = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            r["_run"] = d.name
            out.append(r)
    return out


def extract(reports: list[dict]) -> list[dict]:
    """One row per claim, carrying who said it and what they were looking at."""
    claims = []
    for r in reports:
        rep = r.get("report")
        if not isinstance(rep, dict):
            # An agent that errored is itself worth surfacing: a lane that fails
            # silently looks exactly like a lane that found nothing.
            if r.get("error"):
                claims.append(dict(kind="lane_error", text=str(r["error"])[:300],
                                   agent=r.get("name", "?"), run=r.get("_run", "?"),
                                   model=r.get("model", "deepseek-chat"), target=""))
            continue
        target = ", ".join(r.get("requested_paths") or []) or _target_from(r)
        for k in ("risks", "todos"):
            for item in (rep.get(k) or []):
                if not isinstance(item, str) or len(item.strip()) < 12:
                    continue
                claims.append(dict(kind=k[:-1], text=item.strip(),
                                   agent=r.get("name", "?"), run=r.get("_run", "?"),
                                   model=r.get("model", "deepseek-chat"),
                                   target=target,
                                   status=rep.get("status", "")))
    return claims


def _target_from(r: dict) -> str:
    """Best-effort file guess for runs that did not record their paths.

    The agent names encode their target by construction (``m07-sensitivity``),
    which is why the convention exists.
    """
    name = r.get("name", "")
    stem = name.split("-", 1)[1] if "-" in name else name
    return f"{stem}.py?" if stem else ""


def cluster(claims: list[dict]) -> list[dict]:
    """Group near-identical claims. Order is stable: longest text first, so the
    representative is the most specific phrasing rather than an arbitrary one."""
    remaining = sorted(claims, key=lambda c: -len(c["text"]))
    toks = {id(c): _tokens(c["text"]) for c in remaining}
    clusters: list[dict] = []
    used: set = set()
    for c in remaining:
        if id(c) in used:
            continue
        members = [c]
        used.add(id(c))
        for other in remaining:
            if id(other) in used:
                continue
            if _similar(toks[id(c)], toks[id(other)]):
                members.append(other)
                used.add(id(other))
        clusters.append(dict(
            text=c["text"], kind=c["kind"], size=len(members),
            agents=sorted({m["agent"] for m in members}),
            models=sorted({m["model"] for m in members}),
            runs=sorted({m["run"] for m in members}),
            targets=sorted({m["target"] for m in members if m["target"]}),
        ))
    return clusters


def _norm_target(t: str) -> str:
    """One canonical file name per target, so the same module audited by two
    runs lands in one group instead of two."""
    first = (t or "").split(",")[0].strip().rstrip("?")
    return Path(first).name if first else "(no file)"


def by_target(clusters: list[dict]) -> list[dict]:
    """Group claims by the file they are about.

    This is the primary structure of the output. It is what the reader actually
    needs -- "what is said about vet.py" -- and it is the only grouping the data
    genuinely supports, since claims almost never repeat across files.
    """
    groups: dict[str, dict] = {}
    for cl in clusters:
        key = _norm_target(cl["targets"][0] if cl["targets"] else "")
        g = groups.setdefault(key, dict(target=key, claims=[], models=set(),
                                        agents=set(), runs=set()))
        g["claims"].append(cl)
        g["models"].update(cl["models"])
        g["agents"].update(cl["agents"])
        g["runs"].update(cl["runs"])
    for g in groups.values():
        g["models"] = sorted(g["models"])
        g["agents"] = sorted(g["agents"])
        g["runs"] = sorted(g["runs"])
        g["high_stakes"] = any(h in g["target"] or g["target"] in h
                               for h in HIGH_STAKES)
        # Only meaningful where more than one model was actually given the file.
        g["multi_model"] = len(g["models"]) > 1
        g["claims"].sort(key=lambda c: (c["kind"] != "risk", -c["size"]))
    return sorted(groups.values(),
                  key=lambda g: (not g["high_stakes"], not g["multi_model"],
                                 -len(g["claims"]), g["target"]))


def render(clusters: list[dict], reports: list[dict], limit: int = 45) -> str:
    groups = by_target(clusters)
    runs = Counter(r.get("_run", "?") for r in reports)
    errs = sum(1 for r in reports if r.get("error"))
    multi = [g for g in groups if g["multi_model"]]
    biggest = max((c["size"] for c in clusters), default=0)
    lines = [
        "# External review findings — consolidated",
        "",
        "Every line below is a CLAIM made by an external advisory agent reading a "
        "slice of this repository. **Nothing here has been verified.** Several of "
        "these will be confidently wrong; that is the expected cost of a cheap "
        "fan-out, and the reason this file is a queue for checking rather than a "
        "defect list.",
        "",
        f"- reports read: **{len(reports)}** across {len(runs)} run(s): "
        + ", ".join(f"`{k}`={v}" for k, v in sorted(runs.items())),
        f"- lane errors (agents that failed rather than found nothing): **{errs}**",
        f"- distinct claims: **{len(clusters)}**, over **{len(groups)}** targets",
        f"- files seen by more than one model: **{len(multi)}**",
        "",
        "## What the corroboration signal is worth here: almost nothing",
        "",
        f"The largest group of agents saying the same thing is **{biggest}**. "
        "Near-duplicate detection was run at thresholds down to 0.30 and barely "
        "merged anything. That is not a bug in the clustering — it follows from "
        "the fan-out design, which gave nearly every agent a different file, so "
        "there was almost no opportunity for two agents to agree.",
        "",
        "The consequence is worth stating plainly: **agreement cannot be used to "
        "rank these findings**, and any confidence they carry has to come from "
        "checking them, not from counting them. Cross-model agreement is noted "
        f"below only for the {len(multi)} file(s) that more than one model was "
        "actually given.",
        "",
        "## Findings by target",
        "",
        "Ordered by whether the target is a module where a wrong answer is "
        "expensive (the fence, the budget, the promotion gate), then by whether "
        "more than one model saw it, then by volume.",
        "",
    ]
    for g in groups[:limit]:
        mark = " ⚠ high-stakes" if g["high_stakes"] else ""
        seen = ("seen by " + ", ".join(g["models"])) if g["multi_model"] \
            else f"one model ({g['models'][0] if g['models'] else '?'}), one look"
        lines += [f"### `{g['target']}`{mark}", "",
                  f"*{len(g['claims'])} claim(s); {seen}; "
                  f"agents: {', '.join(g['agents'][:5])}"
                  + (" …" if len(g["agents"]) > 5 else "") + "*", ""]
        for cl in g["claims"][:8]:
            echo = f" _(also raised by {cl['size'] - 1} other)_" if cl["size"] > 1 else ""
            lines.append(f"- **[{cl['kind']}]** {cl['text']}{echo}")
        if len(g["claims"]) > 8:
            lines.append(f"- *…{len(g['claims']) - 8} more for this target*")
        lines.append("")
    if len(groups) > limit:
        lines.append(f"*{len(groups) - limit} further target(s) not shown; "
                     "full set in `runs/eval/findings.json`.*")
    return "\n".join(lines)


def main(argv: list[str]) -> int:  # pragma: no cover - thin CLI
    root = "."
    reports = load_reports(root)
    claims = extract(reports)
    clusters = cluster(claims)
    out_md = Path(root, "docs/research/EXTERNAL_FINDINGS.md")
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(render(clusters, reports), encoding="utf-8")
    # Grouped by target, matching the markdown -- the JSON is for re-reading the
    # same structure programmatically, not a second, differently-ordered view.
    Path(root, "runs/eval/findings.json").write_text(
        json.dumps(by_target(clusters), indent=1), encoding="utf-8")
    print(f"reports={len(reports)} claims={len(claims)} clusters={len(clusters)}")
    print(f"wrote {out_md}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    raise SystemExit(main(sys.argv[1:]))
