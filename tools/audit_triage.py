# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Turn swarm claims into ranked, mechanically-checked findings. Local, free.

Phase 3 of the audit chain, and the reason the chain has a phase 3 at all: a
model's claim is a *hypothesis*, and this repo has measured what happens when
hypotheses are treated as findings. On 2026-07-30 a cheap model produced 154
UNWIRED candidates of which **147 were false** -- a 95.5% false-positive rate.
Triaging that by hand costs more than the findings are worth, and the cost is
paid by whoever reads the list, which is why nobody reads the second one.

So every claim is checked against the tree before a human sees it, by the two
mechanical tests that are cheap and decisive:

**DOES THE SYMBOL EXIST?** A claim about ``validate_receipt`` in a file that
defines no such name is not a finding about the file, it is a finding about the
model. This is the same check as
``lanes.checks.unresolved_first_party_imports``, pointed at claims instead of
imports, and it caught three invented module names that day.

**DID MORE THAN ONE AGENT SEE IT?** Every unit is asked three times
independently, so agreement is available -- and agreement is the thing that was
NOT available on 29 July, when 1,226 claims had a largest cluster of two because
the fan-out gave every agent a different target. A claim named by 3 of 3 votes
and a claim named by 1 of 3 are different objects and must not appear in one
undifferentiated list.

WHAT THIS DELIBERATELY DOES NOT DO: decide whether a finding is real. A symbol
that exists and three agents agreeing is *worth reading*, not *true*. The verdict
belongs to a stronger model and then to a human, and calling this step
"verification" would be the same overreach as a syntax gate calling itself a
test.

    python tools/audit_triage.py                      # ranked report
    python tools/audit_triage.py --json out.json      # machine-readable
    python tools/audit_triage.py --min-votes 2        # only corroborated
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
IN_DIR = REPO / "runs" / "audit_swarm"

#: The packed risk format the swarm question asks for:
#:   SYMBOL @ LINE_HINT | DEFECT | TRIGGER: ... | WRONG CONCLUSION: ... | CONF: x
#: Parsed leniently on purpose -- a model that packs it imperfectly has still
#: told us something, and discarding a real finding over a missing pipe would be
#: this script committing the error it exists to catch.
_CONF = re.compile(r"CONF(?:IDENCE)?\s*[:=]\s*(high|medium|low)", re.I)
_TRIGGER = re.compile(r"TRIGGER\s*[:=]\s*(.+?)(?:\||$)", re.I | re.S)
_WRONG = re.compile(r"WRONG\s+CONCLUSION\s*[:=]\s*(.+?)(?:\||$)", re.I | re.S)
_LINE = re.compile(r"@\s*(?:line\s*)?(\d+)", re.I)

#: Words that are not symbols. A claim whose "symbol" is one of these is a claim
#: about the file in general, which is not locatable and ranks below one that
#: names something.
_NON_SYMBOLS = frozenset({
    "module", "file", "whole file", "n/a", "none", "global", "top", "various",
    "multiple", "several", "class", "function", "unknown", "-", "",
})


@dataclass
class Claim:
    module: str
    chunk: int
    vote: int
    raw: str
    symbol: str = ""
    line: int | None = None
    defect: str = ""
    trigger: str = ""
    wrong_conclusion: str = ""
    confidence: str = ""
    #: Mechanical checks. None = not applicable (e.g. no symbol named).
    symbol_exists: bool | None = None
    line_in_file: bool | None = None

    @property
    def locatable(self) -> bool:
        return bool(self.symbol) and self.symbol.lower() not in _NON_SYMBOLS

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class Group:
    """One suspected defect, as named by one or more votes."""

    module: str
    symbol: str
    claims: list[Claim] = field(default_factory=list)

    @property
    def votes(self) -> int:
        return len({c.vote for c in self.claims})

    @property
    def symbol_exists(self) -> bool | None:
        for c in self.claims:
            if c.symbol_exists is not None:
                return c.symbol_exists
        return None

    @property
    def best_confidence(self) -> str:
        order = {"high": 3, "medium": 2, "low": 1, "": 0}
        return max((c.confidence for c in self.claims),
                   key=lambda c: order.get(c.lower(), 0), default="")

    def rank_key(self) -> tuple:
        """Corroborated and locatable first. Ordering IS the product here.

        A list that puts a 1-of-3 claim about an invented symbol above a 3-of-3
        claim about a real one wastes the reader's first ten minutes, and the
        reader's first ten minutes are the only ones you reliably get.
        """
        return (
            -(self.votes),
            0 if self.symbol_exists else 1,          # existing symbols first
            {"high": 0, "medium": 1, "low": 2}.get(self.best_confidence.lower(), 3),
            self.module,
            self.symbol,
        )


def _symbols_of(path: Path) -> set[str]:
    """Every name a claim could legitimately reference in this file.

    Includes nested defs and methods, unlike ``lanes.graph_brief.file_symbols``
    which lists API only: a claim about a private nested helper is perfectly
    legitimate, and rejecting it as "invented" would be a false refutation.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError, RecursionError):
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
    return names


def parse_claim(module: str, chunk: int, vote: int, raw: str) -> Claim:
    c = Claim(module=module, chunk=chunk, vote=vote, raw=raw.strip())
    parts = [p.strip() for p in raw.split("|")]
    head = parts[0] if parts else ""
    if "@" in head:
        sym, _, _tail = head.partition("@")
        c.symbol = sym.strip().strip("`'\"")
        m = _LINE.search(head)
        if m:
            c.line = int(m.group(1))
    else:
        c.symbol = head.strip().strip("`'\"")
    # The defect is the first segment that is not the head and not a labelled
    # field -- models order these inconsistently and insisting on position would
    # drop real content.
    for p in parts[1:]:
        if not re.match(r"(TRIGGER|WRONG|CONF)", p, re.I) and not c.defect:
            c.defect = p
    if (m := _TRIGGER.search(raw)):
        c.trigger = m.group(1).strip()
    if (m := _WRONG.search(raw)):
        c.wrong_conclusion = m.group(1).strip()
    if (m := _CONF.search(raw)):
        c.confidence = m.group(1).lower()
    return c


def load_claims(in_dir: Path) -> tuple[list[Claim], dict[str, int]]:
    stats = defaultdict(int)
    claims: list[Claim] = []
    sym_cache: dict[str, set[str]] = {}
    for f in sorted(in_dir.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stats["unreadable_result_files"] += 1
            continue
        module = (d.get("meta") or {}).get("module") or "?"
        chunk = (d.get("meta") or {}).get("chunk") or 1
        stats["units"] += 1
        if not d.get("answers"):
            stats["units_with_no_answer"] += 1
            continue
        for a in d["answers"]:
            rep = a.get("report") or {}
            if rep.get("status") == "blocked":
                stats["answers_blocked_by_fence"] += 1
                continue
            stats["answers_usable"] += 1
            risks = rep.get("risks") or []
            if not risks:
                stats["answers_clean"] += 1
                continue
            for raw in risks:
                if not isinstance(raw, str) or len(raw.strip()) < 8:
                    stats["risks_too_short_to_use"] += 1
                    continue
                c = parse_claim(module, chunk, a.get("vote", 0), raw)
                path = REPO / module
                if c.locatable and path.is_file():
                    if module not in sym_cache:
                        sym_cache[module] = _symbols_of(path)
                    c.symbol_exists = c.symbol in sym_cache[module]
                    if not c.symbol_exists:
                        stats["claims_naming_a_symbol_that_does_not_exist"] += 1
                if c.line is not None and path.is_file():
                    try:
                        n = len(path.read_text(encoding="utf-8",
                                               errors="replace").splitlines())
                        c.line_in_file = 1 <= c.line <= n
                    except OSError:
                        pass
                claims.append(c)
                stats["claims"] += 1
    return claims, dict(stats)


def group_claims(claims: list[Claim]) -> list[Group]:
    buckets: dict[tuple[str, str], Group] = {}
    for c in claims:
        # Grouped by (module, symbol) -- the unit a fix would touch. Grouping by
        # the defect TEXT would split three agents describing one bug in three
        # wordings, which is exactly the agreement this exists to find.
        key = (c.module, c.symbol.lower())
        g = buckets.setdefault(key, Group(module=c.module, symbol=c.symbol))
        g.claims.append(c)
    return sorted(buckets.values(), key=lambda g: g.rank_key())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tools.audit_triage")
    p.add_argument("--in-dir", default=str(IN_DIR))
    p.add_argument("--min-votes", type=int, default=1)
    p.add_argument("--json", metavar="PATH", default=None)
    p.add_argument("--top", type=int, default=40)
    args = p.parse_args(argv)

    if args.json:
        # The printed triage stays fail-open read-only inspection; the JSON
        # worklist write starts at the central boundary.
        from daedalus.budget import process_guard_boundary_decision
        from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

        begin_effect(
            "tools.audit_triage",
            REGISTRY_BY_ID["tools.audit_triage"].effects,
            (process_guard_boundary_decision(),),
        )
    in_dir = Path(args.in_dir)
    if not in_dir.is_dir():
        print(f"no results at {in_dir}")
        return 1
    claims, stats = load_claims(in_dir)
    groups = [g for g in group_claims(claims) if g.votes >= args.min_votes]

    print("=== INTAKE ===")
    for k in ("units", "units_with_no_answer", "answers_usable", "answers_clean",
              "answers_blocked_by_fence", "claims",
              "claims_naming_a_symbol_that_does_not_exist",
              "risks_too_short_to_use", "unreadable_result_files"):
        if k in stats:
            print(f"  {k:46} {stats[k]}")
    # THE RATE THAT DECIDES WHETHER THIS WAS WORTH RUNNING. Printed even when it
    # is zero, because a zero finding rate reported as silence reads as a clean
    # bill of health -- and on the first run of this swarm it meant the budget
    # had been spent on the smallest files in the package.
    usable = stats.get("answers_usable", 0)
    if usable:
        print(f"  {'finding rate (answers with >=1 risk)':46} "
              f"{usable - stats.get('answers_clean', 0)}/{usable}")

    print(f"\n=== {len(groups)} SUSPECTED DEFECTS (min-votes={args.min_votes}) ===")
    if not groups:
        print("  none. Either the code is clean or the harness is suppressing "
              "findings -- those two look identical from here, so check the "
              "intake numbers above before concluding the first.")
    for g in groups[:args.top]:
        exists = {True: "symbol OK", False: "SYMBOL NOT FOUND",
                  None: "not locatable"}[g.symbol_exists]
        print(f"\n[{g.votes}/3 votes] {g.module} :: {g.symbol or '(unnamed)'}"
              f"   ({exists}, conf={g.best_confidence or '?'})")
        for c in g.claims:
            print(f"    v{c.vote}: {c.defect[:200] or c.raw[:200]}")
            if c.trigger:
                print(f"        trigger: {c.trigger[:160]}")
            if c.wrong_conclusion:
                print(f"        would wrongly conclude: {c.wrong_conclusion[:160]}")

    if args.json:
        Path(args.json).write_text(json.dumps({
            "stats": stats,
            "groups": [{"module": g.module, "symbol": g.symbol,
                        "votes": g.votes, "symbol_exists": g.symbol_exists,
                        "confidence": g.best_confidence,
                        "claims": [c.to_dict() for c in g.claims]}
                       for g in groups],
        }, indent=1), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
