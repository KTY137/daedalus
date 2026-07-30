"""One full adversarial pass over daedalus/ through the cheap external lane.

OPERATOR-AUTHORISED EGRESS, 2026-07-30. The standing default is that the
external lane is advisory and reads only what the egress allow-list permits --
``daedalus/atomic.py`` was REFUSED by ``classify_data`` on exactly that basis
during the smoke test for this run. For this run the owner lifted the
allow-list explicitly, so full file bodies go to the external lane.

TWO THINGS THAT ARE NOT LIFTED, and neither is a matter of preference:

* **The unconditional secret floor.** ``sensitivity.secret_floor_rule`` is
  documented as running "in EVERY lane, no bypass ... cannot be weakened by a
  project config", and ``providers/deepseek.py`` calls it per path independently
  of ``classify_data``. Verified with a fully permissive policy: source files
  pass, ``.env`` is still refused. Nothing here re-implements or routes around
  that.
* **The file list.** It comes from ``git ls-files daedalus`` -- NOT a walk. So
  ``.captures/`` cannot enter scope: it is gitignored, and it holds captured Edge
  profile data including ``Login Data`` and ``Network/Cookies``. MEASURED
  2026-07-30, in the same repo, on the same day the write gate was found hashing
  those files and labelling the result GROUND TRUTH. The secret floor does NOT
  catch them by path (it knows ``.env``, not ``Login Data``), so the protection
  here is structural rather than a check -- which is the same reasoning as
  "express a restriction as a capability, never as an instruction".

CHUNKING, and why it is not a detail. ``spine/picker.py`` is 137 KB and
``health.py`` 94 KB. A single call carrying a whole 137 KB module either blows
the context window or -- worse -- returns a fluent summary of the first part and
nothing about the rest, which reads exactly like a clean bill of health. Large
modules are therefore split, each chunk audited on its own, and the chunk
boundaries are reported so a finding can be located.

CORROBORATION. Every unit is asked ``VOTES`` times independently. The largest
agreement cluster over 1,226 claims on 29 July was TWO, because that fan-out gave
every agent a different target. Agreement is only evidence when more than one
agent looked at the same thing.

    python tools/audit_swarm.py --plan            # what it would do, no calls
    python tools/audit_swarm.py --run             # the real thing
    python tools/audit_swarm.py --run --limit 5   # a taste
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from daedalus import dotenv                                    # noqa: E402
from daedalus.lanes.fanout import FanoutTask, fan_out           # noqa: E402
from daedalus.sensitivity import Policy                         # noqa: E402

OUT_DIR = REPO / "runs" / "audit_swarm"

#: Independent answers per unit. Odd on purpose: with three, a 2-1 split is a
#: majority and a 1-1-1 split is a visible non-result rather than a tie broken by
#: whichever answer arrived first.
VOTES = 3

#: Bytes per chunk. Sized so a chunk plus the brief plus the question sits well
#: inside the model's window with room for a considered answer, rather than at the
#: edge where the reply gets truncated and reads as brevity.
CHUNK_BYTES = 28_000

#: Overlap between consecutive chunks. A defect that straddles a boundary must be
#: visible to at least one chunk in full; without overlap the split itself
#: manufactures blind spots exactly where a reviewer would not look for them.
CHUNK_OVERLAP = 2_000

#: THE OPERATOR-LIFTED POLICY. Allow-list open, content denylist off. The secret
#: floor is deliberately absent from this object because it cannot be expressed
#: here -- it is not part of Policy at all, which is what makes it unliftable.
WIDE_OPEN = Policy(
    deny_substrings=(),
    allow_substrings=("",),
    default_deny=False,
    deny_content=(),
)

QUESTION = """\
You are auditing ONE unit of a Python codebase for REAL DEFECTS. Be specific or
say nothing.

Report only what you can point at. For each finding give:
  1. the symbol or line region,
  2. what is wrong,
  3. the concrete input or state that triggers it,
  4. what a caller would wrongly conclude.

The kinds of defect this project has actually been bitten by, so look for these
first:

  * A DOCSTRING OR COMMENT THAT PROMISES WHAT THE CODE DOES NOT DO. This is the
    single most common real defect here. Examples found in this repo: a function
    documented as "atomic publish" that omits the retry its own sibling
    documents as measured; a module whose docstring says "there is no code path
    from here to a write in repo_root" whose ledger defaults to a path under
    repo_root; a security check documented as binding to a content digest whose
    loader rejected the only input format that could carry one. If the prose and
    the code disagree, the prose is the bug and you should say so.
  * A GUARD THAT CANNOT FIRE. Dead parameters, a check after the side effect it
    guards, a filter defined and never called, a branch whose condition is
    unreachable.
  * FAIL-OPEN WHERE FAIL-CLOSED WAS INTENDED. An except clause that swallows and
    continues, a default that permits, a missing value read as "allowed".
  * AN UNCONDITIONAL PROMISE WITH A CONDITIONAL IMPLEMENTATION. "never raises"
    that catches two exception types; "always" / "every" / "no bypass" claims.
  * CONCURRENCY AND FILESYSTEM: a fixed temp filename two callers share, a
    read-modify-write with no lock, a path assumed to exist.

RULES:
  * If you find nothing real, return an empty findings list. An empty list is a
    valid and useful answer. A padded list is worse than nothing, because someone
    has to spend time refuting each entry -- on 2026-07-30 a cheap model produced
    154 candidates of which 147 were false, and that cost more than it found.
  * Do not report style, naming, type annotations, missing docstrings, or "could
    be more efficient". Not defects.
  * Do not invent symbol names. If you reference something outside this unit, it
    must appear in the structural brief.
  * You may be seeing ONE CHUNK of a larger file. If a defect depends on code you
    cannot see, say so instead of guessing -- "X is never validated" is wrong if
    the validation is in a part you were not shown.

OUTPUT FORMAT -- this is validated and a wrong shape is DISCARDED, so match it
exactly. Return a JSON object with these keys and no others:

{
  "summary": "one sentence, under 600 characters. If you found nothing real, say
              exactly: no defect found",
  "risks": ["one string PER FINDING, packed as:
             SYMBOL @ LINE_HINT | DEFECT | TRIGGER: <input or state> |
             WRONG CONCLUSION: <what a caller would believe> | CONF: high|medium|low"],
  "todos": ["optional: the smallest change that would fix each finding"],
  "files_changed": [],
  "tests_run": [],
  "handoff": {}
}

``risks`` carries the findings because that is the field this project's report
contract already validates -- inventing a new key would get the whole answer
thrown away, which is a defect in the question and not in your analysis. Keep
each risk string self-contained: it is read on its own, out of context, by
whoever triages it.
"""


def tracked_modules() -> list[Path]:
    """Git-tracked ``daedalus/**/*.py``. NOT a walk -- see the module docstring."""
    out = subprocess.run(["git", "ls-files", "daedalus"], cwd=str(REPO),
                         capture_output=True, text=True, check=False)
    return [REPO / f for f in out.stdout.split()
            if f.endswith(".py") and (REPO / f).is_file()]


def chunks_for(path: Path) -> list[tuple[int, int, str]]:
    """``(index, total, text)`` for one module, split if it is large.

    Line-aligned: a chunk that begins mid-statement makes the model spend its
    answer on the syntax error the split created rather than on the code.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= CHUNK_BYTES:
        return [(1, 1, text)]
    lines = text.splitlines(keepends=True)
    pieces: list[str] = []
    buf: list[str] = []
    size = 0
    for line in lines:
        buf.append(line)
        size += len(line)
        if size >= CHUNK_BYTES:
            pieces.append("".join(buf))
            # Carry the tail forward so a straddling defect is whole somewhere.
            tail: list[str] = []
            tail_size = 0
            for prev in reversed(buf):
                if tail_size + len(prev) > CHUNK_OVERLAP:
                    break
                tail.insert(0, prev)
                tail_size += len(prev)
            buf = tail
            size = tail_size
    if buf:
        pieces.append("".join(buf))
    total = len(pieces)
    return [(i + 1, total, p) for i, p in enumerate(pieces)]


def build_tasks(limit: int | None = None) -> list[FanoutTask]:
    tasks: list[FanoutTask] = []
    for path in tracked_modules():
        rel = path.relative_to(REPO).as_posix()
        for idx, total, body in chunks_for(path):
            where = f"{rel} (chunk {idx}/{total})" if total > 1 else rel
            objective = (
                f"{QUESTION}\n\n"
                f"=== UNIT: {where} ===\n"
                + (f"This is chunk {idx} of {total}. You are NOT seeing the whole "
                   f"file.\n" if total > 1 else "")
                + f"\n```python\n{body}\n```\n")
            tasks.append(FanoutTask(
                task_id=f"{rel}#c{idx}of{total}",
                objective=objective,
                paths=(rel,),
                votes=VOTES,
                meta={"module": rel, "chunk": idx, "chunks": total,
                      "bytes": len(body)}))
        if limit and len({t.meta["module"] for t in tasks}) >= limit:
            break
    # LARGEST UNIT FIRST, and this is not cosmetic. MEASURED 2026-07-30: the
    # first run went in git-ls-files order, which is alphabetical, spent its whole
    # budget ceiling on `__init__.py` (262 B), `adapters/*` and `arch_hook.py`
    # (836 B), and returned ZERO findings across 72 answers. It never reached
    # picker.py (137 KB), health.py, web_api.py, correctness.py, sensitivity.py,
    # offload.py or loop.py.
    #
    # A zero read as "the code is clean" when it actually meant "the budget was
    # spent on the smallest files in the package" is the most expensive kind of
    # wrong answer -- it is a false all-clear with a receipt. Ordering by size
    # descending means a ceiling, a timeout or an interruption truncates the TAIL
    # of the work rather than its substance.
    tasks.sort(key=lambda t: (-t.meta.get("bytes", 0), t.task_id))
    return tasks


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tools.audit_swarm")
    p.add_argument("--plan", action="store_true",
                   help="print the plan and the projected call count; no calls")
    p.add_argument("--run", action="store_true")
    p.add_argument("--limit", type=int, default=None,
                   help="only the first N modules")
    p.add_argument("--concurrency", type=int, default=10)
    p.add_argument("--timeout", type=int, default=240)
    args = p.parse_args(argv)

    dotenv.load()
    tasks = build_tasks(args.limit)
    units = len(tasks)
    calls = units * VOTES
    modules = len({t.meta["module"] for t in tasks})
    chunked = sorted({t.meta["module"] for t in tasks if t.meta["chunks"] > 1})
    total_bytes = sum(t.meta["bytes"] for t in tasks)

    print(f"modules      : {modules}")
    print(f"units        : {units}  ({len(chunked)} module(s) split into chunks)")
    print(f"votes        : {VOTES}")
    print(f"PAID CALLS   : {calls}")
    print(f"body bytes   : {total_bytes:,}  (x{VOTES} votes on the wire)")
    print(f"out dir      : {OUT_DIR}")
    if chunked:
        print("chunked      : " + ", ".join(chunked[:8])
              + (f" (+{len(chunked)-8} more)" if len(chunked) > 8 else ""))
    if not args.run:
        print("\n--plan only. Nothing was sent. Re-run with --run.")
        return 0

    summary = fan_out(
        tasks, OUT_DIR,
        repo_root=str(REPO),
        concurrency=args.concurrency,
        timeout_s=args.timeout,
        # HOPS=0, i.e. the target's OWN symbols and nothing else. MEASURED: at
        # hops=1 the brief for picker.py pulled 25 neighbours, blew the 4,000
        # char budget and reported "779 symbol lines omitted" -- so the model
        # received a header, a truncation warning, and almost none of the file's
        # actual API. The question here is about ONE unit, so the neighbourhood
        # is not context, it is crowd-out.
        graph_hops=0,
        brief_budget_chars=6000,
        # OPERATOR-AUTHORISED for this run: allow-list open so full file bodies
        # reach the external lane. The secret floor is not part of Policy and is
        # therefore untouched -- see this module's docstring.
        policy=WIDE_OPEN,
        resume=True,
        progress_every=10,
    )
    print("\n" + json.dumps(
        {k: v for k, v in summary.items() if k != "results"}, indent=2))
    return 0 if summary.get("state") == "ran" else 1


if __name__ == "__main__":
    raise SystemExit(main())
