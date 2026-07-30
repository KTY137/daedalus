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
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
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


def read_tier(tier_dir: Path) -> list[dict]:
    rows = []
    if not tier_dir.is_dir():
        return rows
    for p in sorted(tier_dir.iterdir()):
        if p.suffix != ".json":
            continue
        try:
            rows.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            rows.append({"task_id": p.stem, "answers": [],
                         "errors": [f"unreadable: {exc}"], "meta": {}})
    return rows


def lane_health(name: str, rows: list[dict]) -> dict:
    answers = [a for r in rows for a in (r.get("answers") or [])]
    errors = [e for r in rows for e in (r.get("errors") or [])]
    sent = [a.get("sent") or {} for a in answers]
    digests = {s.get("objective_sha256") for s in sent if s.get("objective_sha256")}
    bodies = collections.Counter(
        hashlib.sha256(json.dumps(a.get("report") or {}, sort_keys=True).encode()
                       ).hexdigest() for a in answers)
    blocked = sum(1 for a in answers
                  if (a.get("report") or {}).get("status") == "blocked")
    kinds = collections.Counter(
        (e.split(":")[1].strip().split(".")[0] if ":" in e else e[:30])
        for e in errors)
    top = bodies.most_common(1)[0][1] if bodies else 0
    health = {
        "units": len(rows), "answers": len(answers),
        "empty": sum(1 for r in rows if not (r.get("answers") or [])),
        "errors": len(errors), "error_kinds": dict(kinds), "blocked": blocked,
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
    if blocked:
        # ATTRIBUTABILITY. A blocked unit lands in the same `answers` array as
        # a real result: the unit counts as done, resume never retries it, and
        # it reads as clean in every aggregate. An earlier audit lost 21 of 249
        # units this way and could not say to what. So the refusal reasons are
        # printed, not just counted -- a refusal you cannot attribute is
        # indistinguishable from a finding of nothing.
        why = collections.Counter(
            (a.get("report") or {}).get("summary", "")[:110]
            for r in rows for a in (r.get("answers") or [])
            if (a.get("report") or {}).get("status") == "blocked")
        for reason, n in why.most_common(4):
            print(f"      blocked x{n}: {reason}")
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools.funnel_report")
    ap.add_argument("run_dir", help="runs/funnel/<name>, or a single tier dir")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--min-lenses", type=int, default=1,
                    help="document funnels: only claims hit by N distinct lenses")
    args = ap.parse_args(argv)

    root = Path(args.run_dir)
    if not root.is_dir():
        print(f"no such directory: {root}", file=sys.stderr)
        return 2
    tiers = [p for p in sorted(root.iterdir()) if p.is_dir()] or [root]

    print("=" * 74)
    print("LANE HEALTH -- read this before any finding below")
    print("=" * 74)
    data = {}
    for tier in tiers:
        rows = read_tier(tier)
        if not rows:
            continue
        lane_health(tier.name, rows)
        data[tier.name] = rows

    if not data:
        print("no results yet", file=sys.stderr)
        return 2

    # ---- grounding: do the cited files and symbols exist? -----------------
    tracked = repo_files()
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
            for h in (r.get("hypotheses") or [])]
    verdicts = [v for r in payloads(data.get("review", []))
                for v in (r.get("verdicts") or [])]
    items = [i for r in payloads(data.get("plan", []))
             for i in (r.get("items") or [])]
    if hyps or verdicts:
        vc = collections.Counter(str(v.get("verdict", "?")).lower()
                                 for v in verdicts)
        killed = vc.get("refuted", 0)
        print("\n" + "=" * 74)
        print("ATTRITION -- a review tier that refutes nothing has not reviewed")
        print("=" * 74)
        print(f"  hypotheses raised   : {len(hyps)}")
        print(f"  verdicts returned   : {len(verdicts)}  {dict(vc)}")
        if verdicts:
            print(f"  refuted             : {killed} "
                  f"({killed / len(verdicts):.0%})")
        print(f"  plan items produced : {len(items)}")

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
