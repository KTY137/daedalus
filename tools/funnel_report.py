"""Read a funnel run back: lane health first, attrition second, content last.

The order is the point.

A report that prints findings before it has shown the answers were DIFFERENT
cannot distinguish "the target is clean" from "the lane is broken". On
2026-07-30 a fan-out over this repo returned 715 answers, 692 of them sharing
one shape, and every consumer downstream read that as a clean codebase. So
this tool refuses to summarise content until it has answered:

  did every unit get a different question?   (distinct objective digests)
  did different answers come back?           (distinct bodies, shape spread)
  how many units are empty, blocked, failed? (and are they attributable?)

Then ATTRITION, which is the only thing that distinguishes a funnel from a
megaphone: how many hypotheses the research tier raised, how many the review
tier killed, and how many reached the plan. A funnel whose review tier refutes
nothing has not reviewed anything.

Then, last, the content.

Handles both funnel shapes:
  document  findings live in `risks` as "<claim> | <severity> | <what> | <check>"
            and are ranked by how many DIFFERENT lenses hit the same claim
  codebase  findings live in `handoff` as hypotheses -> verdicts -> plan items

TUNING THE INSTRUMENT (added 2026-07-31)
----------------------------------------
Everything above answers "what did this run find". Tuning needs a different
question -- "is this run better than the last one" -- and four things were
missing for it. Each was added because a hand-written claim about these runs
turned out to be wrong in a way a standing instrument makes impossible:

* **One directory can hold several runs.** `fan_out` resumes by task id and a
  task id carries the revision, so two runs of one spec sit side by side under
  the same folder. Reporting their union averages a fixed defect together with
  the run that still had it. `--rev` splits them; a mixed directory says so.
* **`blocked` is two opposite things.** A unit the egress fence refused before
  the wire and a unit whose answer failed to parse both land as `blocked`. One
  is the safety fence working exactly as designed, is permanent, costs nothing,
  and no prompt will move it; the other is a defect and is fixable. Counting
  them together produced the claim "run 2 had zero blocked units" about a run
  with five.
* **A model can put its answer in three places.** The field itself,
  `handoff.unexpected_keys` where `coerce_report` parks keys the schema
  refused, and a nested `handoff.handoff` where the model wrapped its payload
  one layer too deep. Reading only the first undercounts; reading all three
  naively DOUBLE-counts, because the nested copy is usually a duplicate.
* **Grounding is not path existence.** `audit_references` repairs a cited path
  by unique basename, deliberately, so that a moved file does not read as an
  invention. That is the right answer to "is this finding about this repo" and
  the wrong answer to "can a human open this path", which is the only thing a
  plan tier's paths are for. Both are reported; the gap between them is itself
  the measurement.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# The grounding logic lives in the library, not here. It was implemented twice
# -- once for write lanes, once for this report -- and the two agreed
# numerically, which is the flattering way to describe duplication.
from daedalus.lanes.grounding import (  # noqa: E402
    audit_references, defined_in, imported_in, judge,
)

SEVERITY = {"critical": 0, "high": 1, "medium": 2, "low": 3, "none": 4}

#: Where each tier keeps its rows, and the vocabulary its prompt actually
#: states. A verdict outside the set is not merely untidy: `funnel.from_tier`
#: filters with `drop_where` on an exact match, so an unlisted spelling passes
#: through a rule written to stop it. "PARTIALLY KEPT" survives
#: `drop_where: {"verdict": ["KEPT"]}` and reaches the next tier as a defect.
VOCABULARY = {
    "claims": {"KEPT", "BROKEN", "UNCHECKABLE"},
    "verdicts": {"REFUTED", "NARROWED", "CONFIRMED", "NEEDS_EVIDENCE"},
    "hypotheses": set(),     # raised, not adjudicated: no verdict field
    "work": set(),
    "items": set(),
}
ROW_FIELDS = tuple(VOCABULARY)

#: An egress refusal is a decision taken before the call, by the safety fence.
_REFUSED = re.compile(r"^\s*Refused:", re.IGNORECASE)

#: Any token shaped like a repository path. Wider than grounding's resolver on
#: purpose: the invented paths are the ones no allowlist of roots predicts.
_PATH = re.compile(
    r"\b((?:[\w.\-]+/)+[\w.\-]+"
    r"\.(?:py|md|json|jsonl|toml|ya?ml|txt|ts|tsx|cfg|ini|sh))\b")

#: What a tier is told to write when it cannot know a path. Counting these as
#: inventions would punish the tier for obeying the instruction.
_ABSTAIN = {"UNKNOWN", "N/A", "NONE", "", "-", "TBD"}


def normalize(value: object) -> str:
    """One spelling per verdict: upper-cased, separators folded to underscore.

    `NEEDS-EVIDENCE` and `NEEDS_EVIDENCE` are one verdict the model spelled two
    ways -- 20 rows and 14 rows of the same thing in the 2026-07-31 run. This
    is also what `funnel.from_tier` must apply before comparing against
    `drop_where`, and the two normalisers must agree, or a row this report
    calls dropped will not be.
    """
    return re.sub(r"[\s\-]+", "_", str(value).strip()).upper()


def read_tier(tier_dir: Path, rev: str = "") -> list[dict]:
    rows = []
    if not tier_dir.is_dir():
        return rows
    for p in sorted(tier_dir.iterdir()):
        if p.suffix != ".json":
            continue
        try:
            unit = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            rows.append({"task_id": p.stem, "answers": [],
                         "errors": [f"unreadable: {exc}"], "meta": {}})
            continue
        if rev and str((unit.get("meta") or {}).get("rev", "")) != rev:
            continue
        rows.append(unit)
    return rows


def revisions(root: Path) -> list[str]:
    """Every revision with units under this run directory."""
    seen: dict[str, None] = {}
    for tier in sorted(p for p in root.iterdir() if p.is_dir()) or [root]:
        for p in tier.glob("*.json"):
            try:
                meta = json.loads(p.read_text(encoding="utf-8")).get("meta") or {}
            except (OSError, ValueError):
                continue
            seen.setdefault(str(meta.get("rev") or "?"), None)
    return sorted(seen)


def harvest(handoff: dict, field: str) -> list:
    """Rows for `field` from every place a model has been observed to put them.

    De-duplicates on the row's own JSON, because the nested copy is normally
    identical: in the 2026-07-31 run all 101 rows found under a nested
    `handoff.handoff` were byte-identical to their outer copies. Counting both
    would have reported a yield gain no model produced.
    """
    if not isinstance(handoff, dict):
        return []
    sources = [handoff]
    for extra in (handoff.get("unexpected_keys"), handoff.get("handoff")):
        if isinstance(extra, dict):
            sources.append(extra)
    found, seen = [], set()
    for source in sources:
        rows = source.get(field)
        if not isinstance(rows, list):
            continue
        for row in rows:
            key = json.dumps(row, sort_keys=True, ensure_ascii=False, default=str)
            if key not in seen:
                seen.add(key)
                found.append(row)
    return found


def strict_paths(rows: list, repo: Path) -> dict:
    """Every path the rows cite, judged ONLY by whether the file is on disk.

    No basename repair, no benefit of the doubt. `daedalus/eval.py` is the
    obvious name for a module in this project, parses cleanly, sits under a
    real directory, and has never existed; the only question that separates it
    from a usable reference is whether a human can open it.
    """
    cited: collections.Counter = collections.Counter()
    abstained = 0
    for row in rows:
        if isinstance(row, dict):
            for key in ("path", "file"):
                value = row.get(key)
                if isinstance(value, str) and normalize(value) in _ABSTAIN:
                    abstained += 1
        blob = json.dumps(row, ensure_ascii=False, default=str)
        for hit in _PATH.findall(blob):
            cited[hit] += 1
    real = {p: n for p, n in cited.items() if (repo / p).is_file()}
    fake = {p: n for p, n in cited.items() if p not in real}
    return {"distinct": len(cited), "real": real, "fake": fake,
            "abstained": abstained,
            "citations": sum(cited.values()),
            "citations_real": sum(real.values())}


def lane_health(name: str, rows: list[dict]) -> dict:
    answers = [a for r in rows for a in (r.get("answers") or [])]
    errors = [e for r in rows for e in (r.get("errors") or [])]
    sent = [a.get("sent") or {} for a in answers]
    digests = {s.get("objective_sha256") for s in sent if s.get("objective_sha256")}
    bodies = collections.Counter(
        hashlib.sha256(json.dumps(a.get("report") or {}, sort_keys=True).encode()
                       ).hexdigest() for a in answers)
    # A blocked unit lands in the same `answers` array as a real result: the
    # unit counts as done, resume never retries it, and it reads as clean in
    # every aggregate. An earlier audit lost 21 of 249 units this way and could
    # not say to what -- so refusals are attributed, never merely counted.
    #
    # They are also SPLIT, because `blocked` covers two opposite events. The
    # egress fence refusing to send a chunk is the fence doing its job: it
    # costs nothing, it is stable across runs, and no prompt or chunk-size
    # change will move it. A transport or schema failure is a defect with a
    # fix. Summing them is how "run 2 blocked nothing" got written about a run
    # that blocked five.
    refused, failed = [], []
    for r in rows:
        label = (r.get("meta") or {}).get("label") or r.get("task_id", "?")
        for a in (r.get("answers") or []):
            rep = a.get("report") or {}
            if rep.get("status") != "blocked":
                continue
            summary = str(rep.get("summary", ""))
            (refused if _REFUSED.match(summary) else failed).append(
                (label, summary[:120]))
    kinds = collections.Counter(
        (e.split(":")[1].strip().split(".")[0] if ":" in e else e[:30])
        for e in errors)
    repairs = collections.Counter()
    for a in answers:
        h = (a.get("report") or {}).get("handoff")
        if not isinstance(h, dict):
            continue
        if h.get("status_was_defaulted"):
            repairs["status defaulted"] += 1
        if h.get("summary_was_defaulted"):
            repairs["summary defaulted"] += 1
        if isinstance(h.get("unexpected_keys"), dict):
            repairs["keys rescued from top level"] += 1
        if isinstance(h.get("handoff"), dict):
            repairs["payload nested one layer deep"] += 1
    top = bodies.most_common(1)[0][1] if bodies else 0
    health = {
        "units": len(rows), "answers": len(answers),
        "empty": sum(1 for r in rows if not (r.get("answers") or [])),
        "errors": len(errors), "error_kinds": dict(kinds),
        "blocked": len(refused) + len(failed),
        "refused_egress": len(refused), "failed_transport": len(failed),
        "repairs": dict(repairs),
        "distinct_prompts": len(digests), "distinct_bodies": len(bodies),
        "top_body_copies": top,
        "temperatures": sorted({s.get("temperature") for s in sent} - {None}),
        "paths": sorted({len(s.get("paths") or []) for s in sent}),
    }
    print(f"\n--- tier {name} ---")
    print(f"  units / answers        : {health['units']} / {health['answers']}"
          f"   (empty {health['empty']}, blocked {health['blocked']})")
    if errors:
        print(f"  errors                 : {len(errors)}  {dict(kinds)}")
    if refused:
        print(f"  REFUSED BY THE FENCE   : {len(refused)}   "
              "(a decision, not a defect: never sent, never charged)")
        for label, why in refused[:6]:
            print(f"      {label}: {why}")
    if failed:
        print(f"  FAILED IN TRANSPORT    : {len(failed)}   (a defect, fixable)")
        for label, why in failed[:6]:
            print(f"      {label}: {why}")
    if repairs:
        print("  harness repairs        : "
              + ", ".join(f"{k} x{v}" for k, v in sorted(repairs.items()))
              + "   (the model did not answer in the shape it was asked for)")
    ok = health["distinct_prompts"] == health["answers"]
    print(f"  distinct prompts       : {health['distinct_prompts']} of "
          f"{health['answers']}   {'OK' if ok else '<< NOT INDEPENDENT'}")
    print(f"  distinct answer bodies : {health['distinct_bodies']} of "
          f"{health['answers']}   (most repeated: {top})")
    print(f"  temperature / paths    : {health['temperatures']} / {health['paths']}")
    return health


def repo_files() -> list[str]:
    """The authoritative file list. `git ls-files`, never a filesystem walk --
    an untracked scratch file must not make an invented citation look real."""
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True).stdout
    return [p for p in out.splitlines() if p.strip()]


def payloads(rows: list[dict]) -> list[dict]:
    return [(a.get("report") or {}).get("handoff") or {}
            for r in rows for a in (r.get("answers") or [])]


def bar(n: int, total: int, width: int = 22) -> str:
    return "" if not total else "#" * round(width * n / total) + "." * (
        width - round(width * n / total))


def tier_yield(name: str, rows: list[dict], repo: Path, tracked: list[str],
               top: int = 10) -> dict:
    """Rows produced, how they are spelled, and whether their paths open.

    The verdict table shows the normalised count and every raw spelling that
    folded into it. Both matter and for different reasons: the normalised
    number is the finding, the spelling count is a defect in the prompt, and a
    value outside the tier's stated vocabulary is a defect in the FILTER --
    `drop_where` compares exact strings, so an unlisted spelling walks through
    a rule written to stop it.
    """
    harvested = {f: [x for r in payloads(rows) for x in harvest(r, f)]
                 for f in ROW_FIELDS}
    harvested = {f: v for f, v in harvested.items() if v}
    everything = [x for v in harvested.values() for x in v]
    strict = strict_paths(everything, repo)

    print(f"\n--- yield {name} ---")
    for field, items in harvested.items():
        print(f"  rows.{field:<11} {len(items)}")
        raw = collections.Counter(
            str(x.get("verdict")) for x in items
            if isinstance(x, dict) and x.get("verdict") is not None)
        if not raw:
            continue
        vocab = VOCABULARY.get(field, set())
        folded = collections.Counter()
        for spelling, n in raw.items():
            folded[normalize(spelling)] += n
        for value, n in folded.most_common():
            spellings = sorted({s for s in raw if normalize(s) == value})
            flag = ""
            if vocab and value not in vocab:
                flag += "   <<< OUTSIDE THIS TIER'S STATED VOCABULARY"
            if len(spellings) > 1:
                flag += ("   <<< %d spellings: %s"
                         % (len(spellings), ", ".join(map(repr, spellings))))
            print(f"    {value:<18} {n:>5}  {bar(n, len(items))}{flag}")

    if strict["distinct"]:
        blob = json.dumps(everything, ensure_ascii=False, default=str)
        lenient = audit_references(blob, tracked, str(repo))
        pct = 100.0 * len(strict["real"]) / strict["distinct"]
        print(f"  paths on disk          : {len(strict['real'])}/"
              f"{strict['distinct']} distinct cited paths exist ({pct:.0f}%)"
              + (f", {strict['abstained']} rows wrote UNKNOWN"
                 if strict["abstained"] else ""))
        if lenient.cited:
            print(f"  paths grounded (lenient): {lenient.resolved}/"
                  f"{lenient.cited} resolve once basenames are repaired "
                  f"({lenient.rate:.0%})   -- the gap is renamed-or-moved, "
                  "not invented")
        if strict["fake"]:
            worst = sorted(strict["fake"].items(), key=lambda kv: -kv[1])[:top]
            print("      cited but NOT ON DISK: "
                  + ", ".join(f"{p} x{n}" for p, n in worst))
    return {"rows": {f: len(v) for f, v in harvested.items()},
            "verdicts": {f: dict(collections.Counter(
                normalize(x.get("verdict")) for x in v
                if isinstance(x, dict) and x.get("verdict") is not None))
                for f, v in harvested.items()},
            "paths_real": len(strict["real"]),
            "paths_cited": strict["distinct"],
            "paths_fake": sorted(strict["fake"])}


def diff(now: dict, before: dict, label_now: str, label_before: str) -> None:
    """What changed between two runs of the same spec.

    Only counts, never conclusions. A tier that produced more rows may have
    lowered its bar, and this cannot tell the difference -- but it can show
    that the number moved, which is the thing no ad-hoc script ever preserved
    long enough to compare.
    """
    def d(a: int, b: int) -> str:
        return (f"{b:>5} -> {a:<5}" +
                ("" if a == b else f"  {'+' if a > b else ''}{a - b}"))

    print("\n" + "=" * 74)
    print(f"DIFF   {label_before}   ->   {label_now}")
    print("=" * 74)
    for tier in sorted(set(now) | set(before)):
        a, b = now.get(tier), before.get(tier)
        if not a or not b:
            print(f"\n-- {tier}: present in only one run "
                  f"({'now' if a else 'before'} only)")
            continue
        print(f"\n-- {tier}")
        for key, label in (("units", "units"), ("answers", "answers"),
                           ("refused_egress", "refused by fence"),
                           ("failed_transport", "failed (defect)"),
                           ("empty", "no answer at all")):
            av, bv = a["health"].get(key, 0), b["health"].get(key, 0)
            if av or bv:
                print(f"   {label:<18} {d(av, bv)}")
        for field in sorted(set(a["yield"]["rows"]) | set(b["yield"]["rows"])):
            print(f"   rows.{field:<13} "
                  f"{d(a['yield']['rows'].get(field, 0), b['yield']['rows'].get(field, 0))}")
            va = a["yield"]["verdicts"].get(field, {})
            vb = b["yield"]["verdicts"].get(field, {})
            for value in sorted(set(va) | set(vb)):
                print(f"     {value:<16} {d(va.get(value, 0), vb.get(value, 0))}")
        if a["yield"]["paths_cited"] or b["yield"]["paths_cited"]:
            def rate(y):
                return (100.0 * y["paths_real"] / y["paths_cited"]
                        if y["paths_cited"] else 0.0)
            print(f"   paths on disk      {b['yield']['paths_real']}/"
                  f"{b['yield']['paths_cited']} ({rate(b['yield']):.0f}%)"
                  f"  ->  {a['yield']['paths_real']}/"
                  f"{a['yield']['paths_cited']} ({rate(a['yield']):.0f}%)")


def survey(root: Path, rev: str, repo: Path, tracked: list[str],
           top: int) -> tuple[dict, dict]:
    """Health and yield for one run. Returns (raw units per tier, summary)."""
    tiers = [p for p in sorted(root.iterdir()) if p.is_dir()] or [root]
    print("=" * 74)
    print(f"LANE HEALTH -- {root}" + (f" @ {rev}" if rev else "")
          + " -- read this before any finding below")
    print("=" * 74)
    data, summary = {}, {}
    for tier in tiers:
        rows = read_tier(tier, rev)
        if not rows:
            continue
        data[tier.name] = rows
        summary[tier.name] = {"health": lane_health(tier.name, rows)}
    for name, rows in data.items():
        summary[name]["yield"] = tier_yield(name, rows, repo, tracked, top)
    return data, summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools.funnel_report")
    ap.add_argument("run_dir", help="runs/funnel/<name>, or a single tier dir")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--min-lenses", type=int, default=1,
                    help="document funnels: only claims hit by N distinct lenses")
    ap.add_argument("--rev", default="",
                    help="report only units whose meta.rev is this revision")
    ap.add_argument("--against", default="",
                    help="a prior run directory to diff against")
    ap.add_argument("--against-rev", default="",
                    help="revision to select in --against; with no --against "
                         "it selects a second revision from the SAME directory, "
                         "which is where a resumed rerun lands")
    ap.add_argument("--repo", default=".", help="repository root for path checks")
    args = ap.parse_args(argv)

    root = Path(args.run_dir)
    if not root.is_dir():
        print(f"no such directory: {root}", file=sys.stderr)
        return 2
    repo = Path(args.repo).resolve()
    tracked = repo_files()

    revs = revisions(root)
    if len(revs) > 1 and not (args.rev or args.against_rev):
        print(f"NOTE: {root} holds {len(revs)} revisions -- {', '.join(revs)}.\n"
              "      They are being reported MERGED, which averages a fixed "
              "defect together\n      with the run that still had it. To "
              f"compare them instead:\n"
              f"        --rev {revs[-1]} --against-rev {revs[0]}\n")

    data, summary = survey(root, args.rev, repo, tracked, args.top)
    if not data:
        print("no results yet", file=sys.stderr)
        return 2

    if args.against or args.against_rev:
        other = Path(args.against) if args.against else root
        print()
        _, before = survey(other, args.against_rev, repo, tracked, args.top)
        if before:
            diff(summary, before,
                 f"{root}{'@' + args.rev if args.rev else ''}",
                 f"{other}{'@' + args.against_rev if args.against_rev else ''}")

    # ---- grounding: do the cited files and symbols exist? -----------------
    print("\n" + "=" * 74)
    print("GROUNDING -- do the cited files and symbols exist in this repo?")
    print("=" * 74)
    for name, rows in data.items():
        blobs = [json.dumps((a.get("report") or {}), ensure_ascii=False)
                 for r in rows for a in (r.get("answers") or [])]
        g = audit_references("\n".join(blobs), tracked, ".")
        if not g.cited:
            print(f"  {name:<10} no file references cited")
            continue
        print(f"  {name:<10} {g.resolved}/{g.cited} references resolve "
              f"({g.rate:.0%})   INVENTED {len(g.invented)} "
              f"({g.invention_rate:.0%})")
        if g.repaired:
            print(f"      {len(g.repaired)} repaired (directory stripped): "
                  + ", ".join(f"{a} -> {b}" for a, b in g.repaired[:3])
                  + (" ..." if len(g.repaired) > 3 else ""))
        if g.ambiguous:
            print(f"      {len(g.ambiguous)} ambiguous basename: "
                  + ", ".join(g.ambiguous[:4]))
        for label, bad in (("INVENTED - no such filename anywhere",
                            list(g.invented)),
                           ("symbol not in file",
                            [f"{p}:{s}" for p, s in g.absent_symbols])):
            if bad:
                print(f"      {len(bad)} {label}: "
                      + ", ".join(sorted(set(bad))[:6])
                      + (" ..." if len(set(bad)) > 6 else ""))
    print("  (a tier with many findings and a poor grounding rate is "
          "generating, not observing)")

    # ---- precision: which findings are provably wrong about the tree? ------
    #
    # Grounding is necessary and not sufficient. MEASURED: the 500-run's
    # highest-ranked, fully-grounded, review-surviving plan item was false.
    # This second pass decides the one class that IS mechanically decidable --
    # a claim that a name is absent, checked against the module it is about.
    # It can prove a finding false; it can never prove one true.
    defined, imported = {}, {}
    for rel in tracked:
        if not rel.endswith(".py"):
            continue
        try:
            body = Path(rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        defined[rel], imported[rel] = defined_in(body), imported_in(body)

    print("\n" + "=" * 74)
    print("PRECISION -- findings provably wrong about this repository")
    print("=" * 74)
    for name, rows in data.items():
        verdicts = collections.Counter()
        shown: list[str] = []
        for r in rows:
            module = (r.get("meta") or {}).get("module", "")
            for a in (r.get("answers") or []):
                rep = a.get("report") or {}
                h = rep.get("handoff") or {}
                claims = [str(o.get("what", "")) for o in (h.get("observations") or [])]
                claims += [f"{c.get('text','')} {c.get('why','')}"
                           for c in (h.get("claims") or [])
                           if str(c.get("verdict", "")).lower() == "broken"]
                claims += [str(x) for x in (rep.get("risks") or [])]
                for text in claims:
                    verdict, why = judge(text, module, defined, imported)
                    verdicts[verdict] += 1
                    if verdict.startswith("false") and len(shown) < 2:
                        shown.append(f"{module}: {text[:100]}  <-- {why}")
        total = sum(verdicts.values())
        if not total:
            continue
        wrong = verdicts["false"] + verdicts["false-elsewhere"]
        print(f"  {name:<10} {wrong} of {total} statements provably false "
              f"({wrong / total:.1%})   {dict(verdicts)}")
        for line in shown:
            print(f"      - {line}")
    print("  (undecided is NOT a pass; 'scoped' means the claim named its own "
          "window and asserts nothing about the program)")

    # ---- attrition: the funnel's whole justification ----------------------
    hyps = [h for r in payloads(data.get("research", []))
            for h in harvest(r, "hypotheses")]
    verdicts = [v for r in payloads(data.get("review", []))
                for v in harvest(r, "verdicts")]
    # A plan tier writes `items` (steps with a `file` each) or `work` (one
    # `path` per row) depending on which spec produced the run. Reading only
    # the first reported "0 plan items" for a run that produced forty.
    items = [i for r in payloads(data.get("plan", []))
             for i in harvest(r, "items")]
    work = [w for r in payloads(data.get("plan", []))
            for w in harvest(r, "work")]
    if hyps or verdicts:
        vc = collections.Counter(normalize(v.get("verdict", "?"))
                                 for v in verdicts)
        killed = vc.get("REFUTED", 0)
        print("\n" + "=" * 74)
        print("ATTRITION -- a review tier that refutes nothing has not reviewed")
        print("=" * 74)
        print(f"  hypotheses raised   : {len(hyps)}")
        print(f"  verdicts returned   : {len(verdicts)}  {dict(vc)}")
        if verdicts:
            print(f"  refuted             : {killed} "
                  f"({killed / len(verdicts):.0%})")
        print(f"  plan items produced : {len(items) + len(work)}"
              + (f"  ({len(items)} as items, {len(work)} as work rows)"
                 if items and work else ""))

    # ---- content: the work list, with every path checked ------------------
    if work:
        # The `work` shape carries ONE path per row, and the tier is told to
        # write UNKNOWN when the input it received never named one. That
        # instruction is the finding: a row that abstains is the tier working
        # correctly, and separating those from inventions is the difference
        # between "the tier lies" and "the tier is being asked a question its
        # input cannot answer".
        real, invented, unknown = [], [], []
        for row in work:
            path = str(row.get("path", "")).strip()
            if normalize(path) in _ABSTAIN:
                unknown.append(row)
            elif (Path(args.repo) / path).is_file():
                real.append(row)
            else:
                invented.append(row)
        print("\n" + "=" * 74)
        print("WORK -- surviving findings, with every cited path opened")
        print("=" * 74)
        print(f"  {len(real)} rows name a path that exists, "
              f"{len(invented)} name one that does not, "
              f"{len(unknown)} correctly wrote UNKNOWN")
        if invented:
            bad = collections.Counter(str(r.get("path")) for r in invented)
            print("  invented: "
                  + ", ".join(f"{p} x{n}" for p, n in bad.most_common(8)))
        for row in real[: args.top]:
            print(f"\n[{row.get('path')}] {str(row.get('what_breaks',''))[:150]}")
            print(f"   fix   : {str(row.get('smallest_fix',''))[:150]}")
            print(f"   check : {str(row.get('check',''))[:150]}")
            if row.get("cost_if_wrong"):
                print(f"   cost  : {str(row['cost_if_wrong'])[:100]}")
        return 0

    # ---- content: codebase shape -----------------------------------------
    if items:
        # An item whose steps point at files nobody can open is not a plan, it
        # is a plausible-sounding paragraph. MEASURED: 29% of the plan tier's
        # cited paths named a file that exists nowhere in the repository under
        # any name -- not a stripped directory, not a rename, simply absent.
        # The tier was offered "UNKNOWN" as a legal answer and did not take it,
        # because the FORMAT demands a path: an actionable step needs a file,
        # so a tier with nothing to cite supplies one. That is induced by the
        # schema, not fixable by asking more politely, so the filter is
        # mechanical and the discarded items are counted out loud.
        def resolve(path: str) -> bool:
            """Does this step point at a file that exists? One implementation."""
            if not path or path.upper() == "UNKNOWN":
                return False
            return audit_references(path, tracked, ".").resolved == 1

        grounded, ungrounded = [], []
        for it in items:
            files = [s.get("file", "") for s in (it.get("steps") or [])]
            if files and all(resolve(f) for f in files):
                grounded.append(it)
            else:
                ungrounded.append(it)
        print("\n" + "=" * 74)
        print("PLAN -- surviving findings, as work")
        print("=" * 74)
        print(f"  {len(grounded)} of {len(items)} items have every step pointing "
              f"at a real file; {len(ungrounded)} discarded as ungrounded")
        if ungrounded:
            print("  discarded, first few: "
                  + "; ".join(str(i.get("title", "?"))[:60]
                              for i in ungrounded[:3]))
        ranked = sorted(grounded, key=lambda i: (str(i.get("gate", "9")),
                                                 int(i.get("rank", 99) or 99)))
        for it in ranked[: args.top]:
            print(f"\n[gate {it.get('gate','?')}] {it.get('title','?')}"
                  f"   ({it.get('effort','?')})")
            print(f"   why now : {it.get('why_now','')}")
            for s in (it.get("steps") or [])[:6]:
                print(f"   - {s.get('do','')}")
                print(f"       file: {s.get('file','')}  "
                      f"verified by: {s.get('verified_by','')}")
            if it.get("depends_on"):
                print(f"   depends on: {it['depends_on']}")
            if it.get("assumption"):
                print(f"   ASSUMES  : {it['assumption']}")
        return 0

    # ---- content: document shape -----------------------------------------
    risks = []
    for name, rows in data.items():
        for r in rows:
            meta = r.get("meta") or {}
            for a in (r.get("answers") or []):
                for raw in ((a.get("report") or {}).get("risks") or []):
                    if not isinstance(raw, str):
                        raw = json.dumps(raw, ensure_ascii=False)
                    parts = [x.strip() for x in raw.split("|")]
                    if len(parts) >= 3 and parts[1].lower() in SEVERITY:
                        risks.append({"claim": parts[0], "severity": parts[1].lower(),
                                      "problem": parts[2],
                                      "settles": parts[3] if len(parts) > 3 else "",
                                      "section": meta.get("section", name),
                                      "lens": meta.get("lens", "?")})
    if not risks:
        print("\nno rankable findings yet (tiers may still be running)")
        return 0

    by_claim = collections.defaultdict(list)
    for x in risks:
        by_claim[(x["section"], x["claim"])].append(x)
    print("\n" + "=" * 74)
    print("FINDINGS -- ranked by how many DIFFERENT lenses hit the same claim")
    print("=" * 74)
    ranked = sorted(by_claim.items(),
                    key=lambda kv: (-len({x["lens"] for x in kv[1]}),
                                    min(SEVERITY.get(x["severity"], 9) for x in kv[1])))
    shown = 0
    for (section, claim), group in ranked:
        lenses = sorted({x["lens"] for x in group})
        if len(lenses) < args.min_lenses:
            continue
        worst = min(group, key=lambda x: SEVERITY.get(x["severity"], 9))
        print(f"\n[{worst['severity'].upper()}] {section} :: {claim}"
              f"   ({len(lenses)} lenses: {', '.join(lenses)})")
        for x in group:
            print(f"   - ({x['lens']}) {x['problem']}")
            if x["settles"]:
                print(f"       settled by: {x['settles']}")
        shown += 1
        if shown >= args.top:
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
