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

from daedalus.foundation import dotenv                                    # noqa: E402
from daedalus.lanes.fanout import FanoutTask, fan_out           # noqa: E402
from daedalus.sensitivity import Policy                         # noqa: E402
import hashlib                                                  # noqa: E402

OUT_DIR = REPO / "runs" / "audit_swarm"

#: Independent answers per unit. Odd on purpose: with three, a 2-1 split is a
#: majority and a 1-1-1 split is a visible non-result rather than a tie broken by
#: whichever answer arrived first.
VOTES = 3

#: Decode temperature. NOT 0.0, and this is the whole reason VOTES means
#: anything. MEASURED 2026-07-30: at 0.0 the decode is deterministic, and 242 of
#: 246 multi-vote units returned byte-identical reports across all three votes --
#: one sample counted three times, presenting as unanimous agreement in every
#: downstream consumer. The fan-out now refuses votes>1 at 0.0 rather than
#: documenting the hazard.
TEMPERATURE = 0.7

#: The audit lane's OWN system prompt, replacing the bridge-protocol default.
#:
#: MEASURED, and the single largest cause of a 0.28% finding rate over 715
#: answers: ``token_policy.STATIC_PROMPT_PREFIX`` (prepended by
#: ``_report.build_prompt``) commands "Minimize tokens ... Prefer file:line
#: references and short summaries ... **Do not include chain-of-thought; include
#: only conclusions and evidence**", and ``report_instructions()`` closes with a
#: worked example whose ``"risks"`` field is ``[]``.
#:
#: Every defect worth finding here is a COMPARISON -- read the claim, read the
#: code, decide whether they agree. Forbidding the scratchpad forbids the work,
#: and no wording in the user message outranks the system one. The empty example
#: then supplied the safe completion.
#:
#: So: reasoning is explicitly invited, and the example shows POPULATED risks.
AUDIT_SYSTEM = """\
You are a code auditor reading one unit of a Python codebase. You are READ-ONLY:
you cannot edit files or run tests, so files_changed and tests_run must be [].

THINK BEFORE YOU ANSWER. Work through the unit step by step -- read each claim
the prose makes, find the code that would have to be true for it, and compare
them. Deciding whether a docstring matches its implementation is a comparison,
and a comparison needs working space. Take it. Only the final json object is
read by the caller, so the reasoning costs you nothing.

Do NOT minimise your output. A short answer is not a better answer here. The
number of entries you return is determined by what the code contains, not by
brevity.

Return ONLY a json object with exactly these keys: status, summary,
files_changed, tests_run, risks, todos, handoff.

Example of a WELL-FORMED answer -- note that risks is POPULATED, which is the
normal case for real code:
{"status": "needs_review",
 "summary": "9 claims: 6 kept, 2 broken, 1 uncheckable; 1 mechanical",
 "files_changed": [], "tests_run": [],
 "risks": ["CLAIM | \\"publishes atomically\\" | _write_json_atomic | BROKEN | uses a fixed .tmp name, so two concurrent publishers share one scratch file",
           "D1 | retry_s | parameter accepted and never read in this unit | WRONG CONCLUSION: a caller believes it can tune the retry"],
 "todos": ["give the temp file a random suffix"],
 "handoff": {}}
"""

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

QUESTION = """This is a CLAIM-CHECKING task, not a code review. You produce one verdict per
claim. The number of lines you output is determined by the code you are given,
not by whether you find anything. There is no shorter answer available.

STEP 1 -- ENUMERATE. Read the module docstring, every function and class
docstring, and every comment in the unit below. Extract every CHECKABLE CLAIM: a
statement about what the code does, guarantees, always or never does, is safe
from, or is ordered by. A claim is checkable only if some code in this unit would
have to be different for it to be false. Ignore prose that is purely intent,
history or rationale.

STEP 2 -- VERDICT EACH. For every claim, in the order you found it, choose one:
  KEPT        the code in this unit does what the prose says.
  BROKEN      the code contradicts the prose. You MUST name the line.
  UNCHECKABLE deciding needs code not in this unit. Name what you would need.
Emit one entry per claim. A unit with fourteen claims produces fourteen entries.
Do not merge, do not summarise, and do not omit a claim because it is KEPT.

STEP 3 -- FOUR MECHANICAL CHECKS, independent of the claims:
  D1 a parameter, keyword argument or module-level constant defined in this unit
     and read nowhere in this unit;
  D2 an `except` that swallows and continues where the surrounding prose says
     refuse, fail-closed, or must not;
  D3 a check that runs after the side effect its own comment says it guards;
  D4 a branch whose condition cannot be true given the assignments above it.
One entry per hit, or a single entry "D: none".

FORMAT. `summary` is a COUNT, never a verdict:
  "<N> claims: <K> kept, <B> broken, <U> uncheckable; <D> mechanical"
`risks` carries one string per STEP-2 claim, then one per STEP-3 hit:
  CLAIM | "<prose quoted, <=120 chars>" | <symbol or line> | KEPT|BROKEN|UNCHECKABLE | <one sentence of why>
  D<n> | <symbol or line> | <what is wrong> | WRONG CONCLUSION: <what a caller would believe>
`todos` carries one per BROKEN: the smallest change that makes the prose true,
or the smallest change that makes the code true.

TWO RULES THAT OVERRIDE EVERYTHING ABOVE:
* QUOTE the prose you are judging. A claim you cannot quote from the text below
  does not exist and must not appear.
* BROKEN requires the line that contradicts it. If you cannot name the line, the
  verdict is UNCHECKABLE, not BROKEN.
"""


def _recipe_id() -> str:
    """Digest of everything that determines an answer but is not the code.

    Question, system prompt, temperature, chunking. Change any of them and
    every task id changes, so `resume` correctly treats old answers as
    belonging to a different experiment instead of serving them as this
    one's. Eight hex chars: enough to separate recipes, short enough that a
    filename stays readable.
    """
    recipe = "".join([
        QUESTION, AUDIT_SYSTEM, str(TEMPERATURE),
        str(CHUNK_BYTES), str(CHUNK_OVERLAP),
    ])
    return hashlib.sha256(recipe.encode("utf-8")).hexdigest()[:8]


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
                # PROMPT IDENTITY IN THE KEY. Without it `resume` serves an
                # answer produced by a DIFFERENT question forever and reports
                # it as `resumed`. MEASURED 2026-07-30: three harness fixes
                # could not reach the 60 units they were written for, because
                # the key was (path, chunk) and the question was not in it.
                # A cache key must contain everything that determines the
                # value -- `structcore.cached_index` says exactly this about
                # its own scope fingerprint, one package over.
                task_id=f"{rel}#c{idx}of{total}#{_recipe_id()}",
                objective=objective,
                paths=(),
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

    # The plan above stays fail-open; the paid fan-out starts at the
    # central boundary with the really-installed spend net.
    from daedalus.budget import process_guard_boundary_decision
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "tools.audit_swarm",
        REGISTRY_BY_ID["tools.audit_swarm"].effects,
        (process_guard_boundary_decision(),),
    )
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
        system_override=AUDIT_SYSTEM,
        temperature=TEMPERATURE,
        resume=True,
        progress_every=10,
    )
    print("\n" + json.dumps(
        {k: v for k, v in summary.items() if k != "results"}, indent=2))
    return 0 if summary.get("state") == "ran" else 1


if __name__ == "__main__":
    raise SystemExit(main())
