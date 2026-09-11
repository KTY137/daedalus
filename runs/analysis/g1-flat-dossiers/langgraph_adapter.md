# `daedalus/langgraph_adapter.py`

Scoping note: every search below is restricted to `daedalus`, `tests`,
`tools` (via `git grep -- daedalus tests tools`, or `Grep path=`).
`.claude/worktrees/agent-*/` holds full copies of `daedalus/` and `tests/`
and was deliberately excluded to avoid double-counting importer sites.

Read first, per steer: `CLAUDE.md` (repo root) and
`docs/LANGGRAPH_ADAPTER_20260825.md`.

## Repo policy context (read before the rest)

`CLAUDE.md`'s "Orchestrierung in diesem Repo: LangGraph" section is
authoritative and precise about what this file is: "`daedalus/langgraph_adapter.py`
deckt genau *einen* Ablauf ab — die Komposition des Run-Briefs in
`daedalus.runbook.create_run(..., engine="langgraph")`. Default bleibt
`engine="stdlib"`." It states the binding rule: new multi-step execution
(attempts, verifier cascades, repair loops, Genesis WorkItems) must be
modelled as a LangGraph node **inside this existing adapter** — "Kein
zweiter, danebenstehender Runner" (no second, adjacent runner) — because
master-plan §13 forbids a parallel control plane and the adapter exists
specifically to prevent one. `docs/LANGGRAPH_ADAPTER_20260825.md` confirms
and measures the same contract: `engine` "selects who **composes** the
brief, never who **writes** it. Both engines return through `_write_brief`,
the single writer, which is the only effect either path produces. That is
what keeps this an adapter rather than the 'parallel control plane' §13
forbids." — i.e. `_write_brief` (in `daedalus/runbook.py`) remains the sole
writer; this module composes only and performs zero effects itself.

## Identity

Absolute path: `C:/Users/Administrator/daedalus/daedalus/langgraph_adapter.py`
Line count: 375 (`wc -l`, confirmed 2026-09-02).
One sentence: a pure, opt-in LangGraph re-expression of `runbook.create_run`'s
four-step run-brief composition plus a second, unrelated pure advisory-fleet
allocation graph, both of which compute-and-return without ever writing.

## Importers (MEASURED)

Total unique importer sites found by this scope: **3** = 1 daedalus/ + 2
tests/ + 0 tools/, matching the lead's precomputed count exactly; **1
deferred**, also matching.

daedalus/ (1, deferred):

- `daedalus/runbook.py:30` — `from .langgraph_adapter import run_brief`,
  inside `create_run(objective, paths, repo_root, engine="stdlib")` (def at
  line 15), guarded by `if engine == "langgraph":` at line 29. This is the
  file's *only* production import, and it is deliberately deferred: per the
  module's own docstring (quoted below) and `docs/LANGGRAPH_ADAPTER_20260825.md`
  test `test_nothing_imports_langgraph_at_module_scope`, the point is that
  `daedalus` must still import with zero third-party dependencies installed
  when a caller never asks for `engine="langgraph"`.

tests/ (2, both module-level real imports):

- `tests/test_langgraph_adapter.py:23` — `from daedalus import
  langgraph_adapter, runbook`
- `tests/test_opus_fleet_watchdog.py:15` — `from daedalus.langgraph_adapter
  import LangGraphUnavailable`

(`daedalus/langgraph_adapter.py:29` and `daedalus/runbook.py:23` are the
module's own docstring text mentioning its own name/path, not importer
sites; excluded. The remaining ~20 hits in `tests/test_langgraph_adapter.py`
are usages of the already-imported `langgraph_adapter` name, not additional
import statements; excluded.)

**Dynamic/string references searched and found:** searched
`importlib`/`__import__` combined with the module name, literal dotted
strings, and `pyproject.toml`. Found: `pyproject.toml:26` — a comment,
`# Optional graph engine for composing a run brief (daedalus/langgraph_adapter.py).`,
naming the file directly, adjacent to the `orchestration` extra it belongs
to; not a reference the checker or Python resolves, but confirms the
packaging story matches the code (an optional extra, not a core dependency —
`docs/LANGGRAPH_ADAPTER_20260825.md`: "core stays `dependencies = []`").
`[project.scripts]` has only `daedalus`/`daedalus-chip`, neither naming this
module. No `importlib.import_module`/`__import__` reference exists in scope.
One CLI-shaped invocation exists but is documentation, not code: the
reproduction section of `docs/LANGGRAPH_ADAPTER_20260825.md` shows `python -m
daedalus.runbook "..." --engine langgraph`, which reaches this module only
through the same deferred import at `runbook.py:30` already counted above.

## Imports (MEASURED)

**Module-level (file:line), stdlib only — 0 daedalus, 0 third-party:**

- `os` — line 63
- `typing.Any, TypedDict` — line 64

**Deferred / function-scope (file:line + enclosing function):**

daedalus.* (3):
- line 151, `from .router import route_task`, inside `_node_route(state:
  BriefState)` (def at line 148)
- line 161, `from .schemas import AgentTask`, inside `_node_build_task(state:
  BriefState)` (def at line 157)
- line 187, `from .schemas import RunState`, inside `_node_open_state(state:
  BriefState)` (def at line 185)

third-party (2):
- line 306, `from langgraph.graph import END, START, StateGraph`, inside
  `build_graph()` (def at line 298)
- line 327, `from langgraph.graph import END, START, StateGraph`, inside
  `build_advisory_fleet_graph()` (def at line 319)

Total: 2 stdlib module-level imports; 0 daedalus.* module-level imports (by
design — this is what keeps `daedalus` importable with the `orchestration`
extra absent); 3 daedalus.* deferred imports + 2 third-party (`langgraph`)
deferred imports = 5 deferred imports total, all function-scoped, none at
module level.

## What it does

`build_graph()`/`run_brief()` compile and invoke a 3-node LangGraph
(`route` → `build_task` → `open_state`) that reproduces
`runbook.create_run`'s stdlib composition step-for-step over the identical
`RunState`/`AgentTask` state shape and returns the payload without writing
anything; `build_advisory_fleet_graph()`/`plan_advisory_fleet()` is an
unrelated second pure graph (`validate` → `allocate` → `seal`) that
round-robin-allocates a single global capacity (hard-capped at 20) of
project/role slots and likewise writes nothing. Both graph builders pin
`LANGSMITH_TRACING`/`LANGCHAIN_TRACING_V2`/`LANGSMITH_TRACING_V2` to
`"false"` explicitly before the first `langgraph` import (rather than
relying on their absence) and raise `LangGraphUnavailable` — never silently
falling back to the stdlib path — when the optional dependency is missing.
Size: 375 lines. **Composes only; it does not write.** The one production
call site, `runbook.py:30`, immediately hands this module's return value to
`_write_brief`, confirming `_write_brief` remains the sole writer exactly as
`CLAUDE.md` and `docs/LANGGRAPH_ADAPTER_20260825.md` require.

## Proposed destination

**Proposed: `orchestration`.**

This is the module the repo policy already names as the canonical, sole
multi-step orchestration adapter — `orchestration` is not a naming
coincidence here, it is the literal architectural role `CLAUDE.md` assigns
it ("no second runner"). Its only production consumer,
`daedalus/runbook.py`, composes and dispatches Ikarus run briefs (routing an
objective to an agent, building `AgentTask`, opening `RunState`) — squarely
orchestration-tier work, not kernel/spine/twin/runtimes state. Its deferred
daedalus.* dependencies, `.router` and `.schemas`, are themselves
orchestration/contract-tier modules the stdlib composition path in
`runbook.py` already depends on identically, so the move introduces no new
coupling.

**Strongest counter-argument:** because this module's stated future role
(per `CLAUDE.md`) is to host *every* new multi-step LangGraph node — attempts,
verifier cascades, repair loops, Genesis WorkItems — some of which will
genuinely coordinate kernel/spine/twin/runtimes-tier work, one could argue
for a dedicated top-level package (e.g. `daedalus.orchestration.langgraph`)
rather than folding it into a general `orchestration` package alongside
unrelated modules. This does not change the destination proposed here, only
its internal path within `orchestration`: the measured evidence (sole
consumer is `runbook.py`, zero kernel/spine/twin/runtimes imports in or out)
supports `orchestration` as the top-level package regardless of how it is
subdivided later, and subdividing prematurely without a second real LangGraph
consumer would be exactly the kind of speculative structure master-plan §5
warns against ("Erzeuge keine spekulativen Abstraktionen für hypothetische
Zukunftsfälle").

## Boundary-rule verdict after the move

Four rules by id (`kernel-no-outer-layers`, `runtimes-no-gates`,
`spine-no-outer-layers`, `twin-no-outer-layers`), both directions:

- **(b) inbound:** VACUOUSLY CLEAN, attributed to the lead's AST sweep: no
  file under `daedalus/kernel`, `daedalus/spine`, `daedalus/twin`,
  `daedalus/runtimes` imports any of the five dossier modules at any AST
  scope, and the complete flat-module import set of those 142 layer-files is
  `{budget, sensitivity, structcore, limit_policy, primary_tree, config,
  storage, atomic, mapping, offload, providers, resources}` —
  `langgraph_adapter` is not in it. Independently reconfirmed: this
  module's only importer, `runbook.py`, is not under
  kernel/spine/twin/runtimes.
- **(a) outbound / `daedalus.gates` check:** this module's daedalus.*
  imports are `.router` and `.schemas` (both deferred) — never
  `daedalus.gates`. Grep confirms directly: `git grep -n "daedalus.gates\|from
  \.gates\|from \.\.gates\|import gates" -- daedalus/langgraph_adapter.py`
  returns no matches. Note the checker parses the whole AST including
  deferred imports (`docs/architecture/import-boundaries.json` boundary
  contract, confirmed by `tools/architecture_boundaries.py`'s
  `forbidden_target`/`_is_allowed` walking every candidate the AST sweep
  finds, module-level or not), so this module's genuinely deferred `.router`
  and `.schemas` imports would still be caught by the rule if either were
  `daedalus.gates` — they are not. If hypothetically moved into
  `daedalus.runtimes`, rule `runtimes-no-gates` (denylist-only) would still
  pass: **CLEAN**.
- Because the proposed destination is `orchestration`, which is not a
  `source_prefixes` entry for any of the four rules
  (`docs/architecture/import-boundaries.json`), none of the four rules binds
  this module as a source after the move.

**One-line verdict: N-A-not-a-rule-source (destination `orchestration`); the
hypothetical `daedalus.runtimes` landing would also be CLEAN (no
`daedalus.gates` import at any scope, deferred or otherwise).**

## Dead-code signals

Not dead: 3 measured importer sites (1 production, 2 test), a full green
adversarial test suite per `docs/LANGGRAPH_ADAPTER_20260825.md`
(equivalence, clock-only-difference, no-module-scope-import, mutation-checked,
telemetry-pinned-off tests all named and passing), and a documented
reproduction path. The module's own docstring (quoted from lines 1–60,
excerpted) is unusually explicit about scope, exactly matching `CLAUDE.md`'s
framing:

> "WHAT THIS IS. `daedalus.runbook.create_run` composes a run brief in four
> steps... This module expresses the *same four steps* as a LangGraph graph
> over the *same state keys*... WHAT IT IS NOT, and this is the load-bearing
> part. It is not a second orchestration model... the graph is **pure** — it
> computes the payload and writes nothing. The one writer stays
> `create_run`... it is **opt-in**. `create_run` defaults to the stdlib path
> and takes `engine='langgraph'` only when a caller asks for it by name...
> REPLACEMENT PATH. Delete this file and the `orchestration` extra in
> `pyproject.toml`. Nothing else changes."

The docstring names its own replacement path and cost (one file deletion),
which is itself evidence this is deliberate, bounded, reversible
infrastructure rather than rot — a module documenting its own deletion path
this precisely is not an abandoned experiment. Chasing one hop on the sole
importer: `runbook.py` is live production code (`create_run` is the
production entrypoint for Ikarus run-brief composition, defaulting to
`engine="stdlib"` and switching to this module only on explicit request).

## Confidence

**High.** The 3/1/2/0/1 counts match the lead's precomputed figures exactly,
including correctly identifying the single deferred production import at
`runbook.py:30` and the two additional deferred third-party `langgraph`
imports inside `build_graph`/`build_advisory_fleet_graph`. The
composes-only/`_write_brief`-stays-sole-writer claim is independently
verified by reading `runbook.py:29-33` directly (the `engine == "langgraph"`
branch calls `run_brief(...)` then immediately calls `_write_brief(run_id,
payload)`, identically to the stdlib branch below it). The destination
argument is grounded in explicit repo policy (`CLAUDE.md`) rather than
inference.
