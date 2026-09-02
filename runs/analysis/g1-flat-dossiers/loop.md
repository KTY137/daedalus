# Flat-module classification dossier: daedalus/loop.py

Scope note: every search below was restricted to `daedalus`, `tests`, `tools`
explicitly (Grep `path=` parameter / targeted greps), never the bare repo
root, because `.claude/worktrees/agent-*/` holds full copies of `daedalus/`
and `tests/` that would double-count every importer if a scope-free grep were
run. No worktree path appears anywhere below.

## Identity

- Absolute path: `C:/Users/Administrator/daedalus/daedalus/loop.py`
- Line count: 1727 (`wc -l`, MEASURED)
- One sentence: it is a standalone, self-guarding CLI driver (`python -m
  daedalus.loop`) that repeatedly runs pick -> attempt -> gate -> nominate
  until a stated bound stops it — a multi-iteration orchestration loop, not a
  library module other code composes with.

## Importers (MEASURED)

Search performed: `Grep pattern:"daedalus\.loop\b" path:daedalus`,
same pattern under `path:tests` and `path:tools`, plus a second pass for
`from .loop import|from ..loop import|from daedalus import loop|import
daedalus.loop` under `daedalus/` to catch relative-import spellings, plus a
literal-string sanity check (`importlib`/`__import__` grep for "loop" in
`daedalus/`, zero hits) and a `pyproject.toml` grep for "loop" (zero hits —
no console_scripts entry). Disambiguation: `daedalus.loop` only ever appears
as the dotted module path or a quoted `"daedalus.loop"` string; the search
pattern requires the literal `daedalus.loop` token, so it cannot match
`asyncio`/`event.loop()` calls or `for`/`while` loop keywords — none of the
hits below are false positives of that kind (all were read in context).

**Real Python `import` statements of `daedalus.loop` (the only load-bearing
importers) — 10 statements across 9 files, all under `tests/`:**

1. `tests/test_envelope_join.py:38` — `from daedalus.loop import LoopBounds, LoopLedger, LoopReport, render`
2. `tests/test_loop.py:31` — `from daedalus.loop import (...)`
3. `tests/test_loop_bound_safety.py:17` — `from daedalus.loop import LoopBounds, LoopMisconfigured`
4. `tests/test_loop_cap_policy.py:14` — `from daedalus.loop import LoopBounds, LoopDriver, LoopLedger, LoopMisconfigured, _Spend`
5. `tests/test_loop_governance_head.py:36` — `from daedalus.loop import LoopBounds, LoopDriver, _same_revision`
6. `tests/test_loop_lease_receipt.py:18` — `from daedalus.loop import IterationResult, LoopBounds, LoopDriver, LoopReport`
7. `tests/test_loop_lease_receipt.py:127` — `from daedalus.loop import LoopLedger` (deferred, inside `test_ledger_detail_carries_the_capability`)
8. `tests/test_loop_spend_refused.py:64` — `from daedalus.loop import LoopBounds, LoopDriver`
9. `tests/test_loop_terminal_rendering.py:9` — `from daedalus.loop import IterationResult, LoopBounds, LoopReport, render`
10. `tests/test_loop_entrypoint_guard.py:91` — `import daedalus.loop as loop`

**COUNT: 10 import statements, 9 files, 100% under `tests/`. Zero importers
under `daedalus/` or `tools/`.** No production module composes with
`loop.py` as a library.

**Dynamic / subprocess references — `python -m daedalus.loop` (searched:
literal `-m daedalus.loop`/`daedalus.loop` strings; no `importlib`/
`__import__` hits anywhere in `daedalus/`):**

- `tests/test_envelope_join.py:425` — `subprocess` call:
  `[sys.executable, "-m", "daedalus.loop", "--dry-run", ...]` (an end-to-end
  entrypoint test, not a library import).
- `tools/continuous_daedalus.ps1:313` — PowerShell scheduler spawns
  `python -m daedalus.loop` as a child process (`:90` and `:128` also name
  it, in a guard check and an argv list respectively). This is the one
  operational launcher for the module.

**String-only references (not imports — documentation, schema strings, or a
policy-registry row; listed because the task asked for exhaustiveness, not
because they couple code):**

- `daedalus/build.py:50,104,294` — docstring mentions of `daedalus.loop` as
  the caller BuildSession serves.
- `daedalus/kernel/events/envelope.py:628` — quotes the ledger schema name
  `"daedalus.loop.ledger/2"` in a docstring, not an import.
- `daedalus/sensitivity.py:210` — a comment naming the CLI invocation shape.
- `daedalus/spine/effect_boundary.py:564-588` — an `EntrypointSpec` registry
  row (`id="cli.loop"`, `target="daedalus.loop:main"`,
  `GuardAnchor("daedalus.loop:main", "begin_effect")`). This is a policy
  table entry that *names* the module as a registered console door, not a
  Python `import`; see "Proposed destination" below — its own rationale text
  calls `loop.py` "a SECOND console door into the same effects as
  cli.daedalus."
- `tests/contracts/test_spine_outer_ports.py:85` — `"daedalus.loop"` appears
  in `FORBIDDEN_PREFIXES`, a literal copy of the `spine-no-outer-layers`
  contract's forbidden list, used to assert a cold `daedalus.spine` import
  never pulls in `daedalus.loop`. Confirms the boundary contract's stance
  (see below); not a functional coupling.

## Imports (MEASURED)

Produced by a small AST script (`.venv/Scripts/python.exe`) walking
`ast.parse(open("daedalus/loop.py"))`, visiting every `Import`/`ImportFrom`
node including ones nested inside `FunctionDef`/`AsyncFunctionDef`, and
printing `lineno, kind, module, names, enclosing-function-stack`. Full
script output (28 import statements total):

```
72  from  __future__          annotations                                    MODULE-LEVEL
74  import argparse           None                                           MODULE-LEVEL
75  import json                None                                          MODULE-LEVEL
76  import math                None                                          MODULE-LEVEL
77  import os                  None                                          MODULE-LEVEL
78  import sys                 None                                          MODULE-LEVEL
79  import time                None                                          MODULE-LEVEL
80  import uuid                None                                          MODULE-LEVEL
81  from  dataclasses          dataclass, field                              MODULE-LEVEL
82  from  pathlib               Path                                          MODULE-LEVEL
83  from  typing                Any, Mapping, Sequence                       MODULE-LEVEL
85  from  .                     progress                                     MODULE-LEVEL
86  from  .atomic                write_text_atomic                           MODULE-LEVEL
87  from  .limit_policy          ExecutionLimitPolicy, LimitPolicyError, load_from_env   MODULE-LEVEL
92  from  .spine.attempt          ATTEMPT_STATES, STATE_CANCELLED             MODULE-LEVEL
93  from  .spine.envelope         PREDICATE_LOOP_LEDGER, canonical_sha, current_trace_id, new_trace_id, statement, subject_for, trace_context, unwrap   MODULE-LEVEL
103 from  .spine.killswitch       KillSwitch, LoopHalted                      MODULE-LEVEL
104 from  .text_integrity         safe_terminal_text                         MODULE-LEVEL
126 from  .kairos.scheduler       SPEND_REFUSED_SKIPPED_STATUS, SPEND_REFUSED_STATUS, spend_refused_result   MODULE-LEVEL
474 import subprocess          None                                          in _head_revision
810 from  .                     budget                                       in read_spend
882 from  .build_exec            EffectBounds, WaveExecutor                  in __init__
995 from  .spine.picker           build_queue                                 in _pick
1053 from .build                 BuildSession, BuildTask, Wave, assign_builder   in _session_for
1054 from .categories             preset_for                                   in _session_for
1055 from .kairos.scheduler        KairosScheduler                              in _session_for
1056 from .router                  route_task                                   in _session_for
1097 from .budget                  BudgetRefused                                in _run_iteration
1098 from .kairos.scheduler        KairosScheduler                              in _run_iteration
1309 from .                       core                                         in run
1625 from .budget                  install_process_guard, process_guard_boundary_decision   in main
1626 from .spine.effect_boundary    REGISTRY_BY_ID, begin_effect                 in main
1661 from .dotenv                  DotEnvRefused, load                          in main
```

**Module-level (13 statements, lines 72-126):** stdlib/typing (`argparse`,
`json`, `math`, `os`, `sys`, `time`, `uuid`, `dataclasses`, `pathlib`,
`typing`, `__future__`) — 11 stdlib; `daedalus.*` — 8 statements:
`daedalus.progress`, `daedalus.atomic`, `daedalus.limit_policy`,
`daedalus.spine.attempt`, `daedalus.spine.envelope`,
`daedalus.spine.killswitch`, `daedalus.text_integrity`,
`daedalus.kairos.scheduler`.

**Deferred / function-scope (15 statements):** 1 stdlib (`subprocess`, in
`_head_revision`); 14 `daedalus.*`, spread across 7 enclosing functions/
methods: `read_spend` (`daedalus.budget`), `__init__`
(`daedalus.build_exec`), `_pick` (`daedalus.spine.picker`), `_session_for`
(`daedalus.build`, `daedalus.categories`, `daedalus.kairos.scheduler`,
`daedalus.router` — 4 imports), `_run_iteration` (`daedalus.budget`,
`daedalus.kairos.scheduler` — 2 imports), `run` (`daedalus.core`), `main`
(`daedalus.budget`, `daedalus.spine.effect_boundary`, `daedalus.dotenv` — 3
imports).

**Total `daedalus.*` targets touched (module-level + deferred), by flat
name:** `progress`, `atomic`, `limit_policy`, `spine.attempt`,
`spine.envelope`, `spine.killswitch`, `text_integrity`, `kairos.scheduler`,
`budget`, `build_exec`, `spine.picker`, `build`, `categories`, `router`,
`core`, `spine.effect_boundary`, `dotenv` — 17 distinct `daedalus.*` targets,
6 of them under `daedalus.spine.*`, 1 under `daedalus.kairos.*`, and the
remaining 10 flat top-level modules (`progress`, `atomic`, `limit_policy`,
`text_integrity`, `budget`, `build_exec`, `build`, `categories`, `router`,
`core`).

## What it does

`daedalus/loop.py` implements a bounded, resumable pick -> attempt -> gate ->
nominate -> re-pick control loop, gated by four independent bounds
(iterations, wall clock, spend, per-candidate attempts) plus a killswitch,
and it never promotes — every candidate it produces is a held artifact for a
separate owner-controlled promotion action. It composes existing pieces
rather than re-implementing them: `daedalus.spine.picker.build_queue` for
ranking, `daedalus.build_exec.WaveExecutor`/`daedalus.kairos.scheduler` for
the attempt+gate+sealed-handoff wave, and `daedalus.spine.killswitch` for the
stop signal, while its own `main()` installs the process spend guard and
calls `daedalus.spine.effect_boundary.begin_effect` before any effect. Size:
1727 lines.

## Proposed destination

**`daedalus.orchestration`.**

Argument, from measured evidence: loop.py sits one layer above every module
it composes (`spine.picker`, `spine.killswitch`, `kairos.scheduler`,
`build_exec.WaveExecutor`, `budget`, `build`, `router`, `categories`,
`core`) — none of them is a "foundation" concern, all are orchestration-level
collaborators, and loop.py's own docstring states its only job is choosing
*when* to call them in a bounded cycle, never *how* they work. It has zero
importers under `daedalus/` — nothing in production code depends on it as a
library — and its only functional consumers are its own test suite and a
`python -m daedalus.loop` subprocess launcher (`tools/continuous_daedalus.ps1`).
The boundary contract independently corroborates this: `spine-no-outer-layers`
already lists `daedalus.loop` by name in `forbidden_target_prefixes`
alongside `daedalus.build`, `daedalus.build_exec`, `daedalus.core`,
`daedalus.kairos`, `daedalus.orchestration`, `daedalus.web_api` — i.e. the
contract's authors already classified `loop.py` as belonging to the same
outer, non-canonical layer as `daedalus.orchestration` itself, before this
dossier was written. That is direct, pre-existing evidence for exactly this
destination.

Is it a second runner? **Yes, explicitly, in its own words and in the
boundary registry's.** `daedalus/spine/effect_boundary.py:578` (the
`EntrypointSpec` row `id="cli.loop"`) states outright: "`python -m
daedalus.loop` is a SECOND console door into the same effects as
cli.daedalus and never passes through cli.main's dispatch." `loop.py`'s own
`main()` (lines 1619-1653) repeats the same admission almost verbatim: "the
module tail is a door of its own," reachable outside `cli.main`'s dispatch,
requiring its own hand-installed spend guard because "nothing mechanically
required it." This is CLAUDE.md's "second, ad-hoc executor" pattern by the
project's own diagnosis, not by inference. However, it is not a *second
LangGraph-shaped* multi-step agent-tool orchestrator — it does not run LLM
tool calls itself; it schedules calls into `WaveExecutor`/`KairosScheduler`,
which are the actual attempt runners. Its "second-ness" is at the console/
CLI-entrypoint level (an un-gated door bypassing `cli.main`), not at the
execution-engine level where the LangGraph rule (`daedalus/langgraph_adapter.py`
composing `daedalus.runbook.create_run`) applies. That distinction keeps it
short of an outright `delete`/migrate-to-LangGraph verdict: the fix implied
by the effect-boundary note is to route it through `cli.main`'s dispatch (or
retire the bare module-tail door), not to rewrite its scheduling logic as a
graph — nothing here composes stateful multi-step *tool/agent* execution the
way the LangGraph adapter does.

Counter-argument: loop.py could be classified `interfaces.cli`, since its
entire externally-reachable surface is `main()`/`argparse`/`python -m`. It
loses because the CLI-ness is a thin tail (roughly the last 110 of 1727
lines); the other ~1600 lines are bound/ledger/report/driver logic
(`LoopBounds`, `LoopLedger`, `LoopDriver`, `LoopReport`, `render`) consumed
directly by 9 test files via non-CLI imports (`LoopDriver`, `LoopBounds`,
etc.) — i.e. the module's substance is an orchestration driver with a CLI
tail bolted on, not a CLI module with orchestration logic bolted on. An
`interfaces.cli` classification would also do nothing to address the "second
door" defect the registry names; the real fix (per the registry's own
`notes`) is about `cli.main` dispatch wiring, which is an orchestration/entry-
point concern regardless of which directory the file lives in.

## Boundary-rule verdict after the move

Moving `daedalus/loop.py` to `daedalus/orchestration/loop.py` (or any
`daedalus.orchestration.*` path):

**(a) As SOURCE** — `daedalus.orchestration` is not a `source_prefixes`
entry in any of the four rules (`kernel-no-outer-layers`,
`runtimes-no-gates`, `spine-no-outer-layers`, `twin-no-outer-layers` all bind
only `daedalus.kernel`, `daedalus.runtimes`, `daedalus.spine`,
`daedalus.twin`). None of loop.py's measured imports would be evaluated as a
rule source. **N/A — not a rule source** at the proposed destination.

  - For completeness (the dossier's own falsification check): had loop.py
    instead landed in a rule-source layer, it would fail immediately.
    `kernel-no-outer-layers` and `twin-no-outer-layers` are strict allowlists
    that do not include `daedalus.progress`, `daedalus.text_integrity`,
    `daedalus.build`, `daedalus.build_exec`, `daedalus.categories`,
    `daedalus.router`, or `daedalus.core` — e.g. `daedalus/loop.py:85 from .
    import progress` and `daedalus/loop.py:1053 from .build import
    BuildSession, ...` (inside `_session_for`) would both be refused under
    either rule. `spine-no-outer-layers` explicitly forbids
    `daedalus.build`, `daedalus.build_exec`, `daedalus.core`,
    `daedalus.kairos` by name, so `daedalus/loop.py:126 from .kairos.scheduler
    import ...`, `:882 from .build_exec import EffectBounds, WaveExecutor`,
    `:1053 from .build import ...`, and `:1309 from . import core` would each
    be refused. Only `runtimes-no-gates` (denylist-only, forbids just
    `daedalus.gates`) would pass loop.py's current import set as a source,
    since none of its imports touch `daedalus.gates`.

**(b) As TARGET** — measured importers of `daedalus.loop` today are 100%
under `tests/` (9 files) plus one subprocess launcher
(`tools/continuous_daedalus.ps1`); **zero** live under
`daedalus.kernel`, `daedalus.spine`, `daedalus.twin`, or `daedalus.runtimes`.
No rule-bound importer exists to be refused today, in either direction.
`spine-no-outer-layers` already names `daedalus.loop` in its
`forbidden_target_prefixes` (`docs/architecture/import-boundaries.json`
lines 81, mirrored in `tests/contracts/test_spine_outer_ports.py:85`) —
prospectively, with the rule's own rationale text citing other prefixes
(`daedalus.orchestration`) as "listed for a leak that has not happened yet."
Moving loop.py under `daedalus.orchestration` does not weaken this: that
prefix is *already* separately listed in the same forbidden set (line 83), so
the rule keeps covering the module under its new dotted name with no edit
required.

**Verdict: CLEAN** (N-A-not-a-rule-source as SOURCE at the proposed
destination; no live TARGET violation exists today, and the one rule that
already names it prospectively continues to cover it after the move under
its new prefix).

## Dead-code signals

Zero importers under `daedalus/` and `tools/` is a **finding**, not a
verdict — the module's own docstring promises a reader and states its
purpose plainly: "The loop driver: pick -> attempt -> gate -> nominate ->
re-pick, repeatedly... Run it:: `python -m daedalus.loop --max-iterations 5
--max-spend-usd 2.00`." That promised reader is a human operator running the
console command, and `tools/continuous_daedalus.ps1` confirms the promise is
kept operationally — it is the scheduled launcher for exactly that
invocation (`:90` even asserts `RepoRoot does not contain daedalus.loop` as
a startup precondition). `pyproject.toml` has no `console_scripts` entry
naming `loop` (grepped, zero hits), so the only two ways to reach it are the
documented `python -m` form and direct import (used exclusively by its own
9-file test suite).

For deletion to be safe, it would have to be true that (1) nothing schedules
`python -m daedalus.loop` any more, (2) the 9 test files exercising
`LoopDriver`/`LoopBounds`/`LoopLedger`/`LoopReport`/`render` are also deleted
or rewritten against a replacement, and (3) the "second console door" defect
`effect_boundary.py` names is resolved by removing the door rather than by
routing it through `cli.main`. None of these is true today:
`continuous_daedalus.ps1` is a live, current launcher; the test suite is
large and green-shaped (10 import statements across 9 files); and the
registry note treats the second-door problem as a defect to close, not
evidence the module should vanish. **Deletion is not safe today.**

## Confidence

**High** for the importer/import measurements (AST script output shown
verbatim, grep scope stated and disambiguated, pyproject/dynamic-import
checks performed with zero-hit results reported honestly). **Medium** for
the destination argument specifically: `daedalus.orchestration` is inferred
from the boundary contract's own classification of `daedalus.loop` as an
outer-layer prefix and from the module's compositional role, but no
Work Packet or amendment record was found that assigns loop.py a target
package by name — this dossier's classification is evidence-based inference,
not a citation of an existing decision. Confidence would rise to high with
either (a) an explicit Work Packet naming loop.py's destination, or (b) a
second AST pass confirming no other repo file does a deferred/string-based
dynamic import this static walk could have missed (mitigated already by the
zero-hit `importlib`/`__import__` grep, but that grep is pattern-based, not
exhaustive over every possible dynamic-loading idiom).
