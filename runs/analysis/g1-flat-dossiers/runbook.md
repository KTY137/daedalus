# daedalus/runbook.py

Scope note: all searches below are scoped to `daedalus/`, `tests/`, `tools/`
only (Grep `path=`). `.claude/worktrees/agent-*/` holds full duplicate copies
of `daedalus/` and `tests/` and was explicitly excluded to avoid double
counting.

POLICY CONTEXT READ FIRST, per the steer: `CLAUDE.md`'s "Orchestrierung in
diesem Repo: LangGraph" section and `docs/LANGGRAPH_ADAPTER_20260825.md` both
name `daedalus.runbook.create_run(..., engine="langgraph")` as the **one**
canonical multi-step orchestration seam in the repo today, with
`engine="stdlib"` remaining the default. Any new mehrstufige (multi-step)
execution work is required to be modeled as a LangGraph node *inside this
adapter* rather than as a second, parallel runner — this module is
constitutionally load-bearing for that rule, not an ordinary flat module.

## Identity

Absolute path: `C:/Users/Administrator/daedalus/daedalus/runbook.py`. 97
lines. Composes one pruned agent "run brief" (routed agent + `AgentTask` +
`RunState` + `task_created` event) via either a four-step stdlib path or an
equivalent LangGraph graph, and writes it — through a single writer function
— to `runs/<run_id>.json`.

## Importers (MEASURED)

Total found: 2 sites (0 daedalus/ + 2 tests/ + 0 tools/), 1 deferred —
matches the lead's precomputed count exactly.

daedalus/: **0 matches.** No file under `daedalus/` imports
`daedalus.runbook` at any scope, module-level or deferred.

tests/ (2 sites, 1 deferred):
- `tests/test_cli_effect_boundary.py:76` — `from daedalus import runbook` (deferred, inside `test_runbook_refuses_fail_closed_without_the_contract`, which then monkeypatches `runbook.RUN_DIR` and calls `runbook.main()` at line 83).
- `tests/test_langgraph_adapter.py:23` — `from daedalus import langgraph_adapter, runbook` (module-level; this is the adapter-equivalence test file the policy doc names directly as the contract's proof).

tools/: 0 matches for `runbook` under `tools/`.

Dynamic/string references searched: `python -m daedalus.runbook` is
documented and reproducible — it appears in `docs/LANGGRAPH_ADAPTER_20260825.md`'s
"How to reproduce" section (lines 141-143):
`python -m daedalus.runbook "add a docstring" --paths daedalus/router.py --engine langgraph`
and the stdlib equivalent. No `importlib`/`__import__` reference to
`runbook` found anywhere in `daedalus/`, `tests/`, or `tools/`. No
`pyproject.toml` console_scripts entry for it (checked; no `runbook|shift|
token_monitor|token_policy|semantic_route` matches in `pyproject.toml` at
all).

## Imports (MEASURED)

Module-level:
- `daedalus/runbook.py:8` — `from .router import ROOT, route_task` → `daedalus.router`.
- `daedalus/runbook.py:9` — `from .schemas import AgentTask, RunState` → `daedalus.schemas`.
- stdlib: `argparse`, `json`, `pathlib`, `uuid`.

Deferred/function-scope:
- `daedalus/runbook.py:30` — `from .langgraph_adapter import run_brief`, inside `create_run`, only on the `engine == "langgraph"` branch → `daedalus.langgraph_adapter`.
- `daedalus/runbook.py:84` — `from daedalus.budget import process_guard_boundary_decision`, inside `main()` → `daedalus.budget`.
- `daedalus/runbook.py:85` — `from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect`, inside `main()` → `daedalus.spine`.

Outbound profile: `{budget, langgraph_adapter, router, schemas, spine}`, 0
third-party, 3 deferred — matches the lead's precomputed profile exactly.

## What it does

`create_run` composes a single pruned "run brief" for one agent task in
exactly four logical steps (route the objective to an agent, build the
`AgentTask`, open a `RunState`, record one `task_created` event), selectable
between a zero-dependency stdlib path (default) and an equivalent
three-node LangGraph graph reached only via the deferred import at line 30,
with both engines converging on the same single writer, `_write_brief`. An
unknown `engine` value or a `"langgraph"` request when the optional
`orchestration` extra is not installed raises before any file is written —
there is deliberately no silent fallback between the two engines. 97 lines,
and its `main()` CLI tail runs through the canonical `begin_effect`
guard before doing any work.

## Deferred `langgraph_adapter` import: cycle-avoidance or optional-dependency isolation?

**Optional-dependency isolation, not cycle-avoidance.** Evidence:

- `docs/LANGGRAPH_ADAPTER_20260825.md` states this explicitly as the
  designed failure mode, not an accident: "library absent, `engine="langgraph"`
  → raises `LangGraphUnavailable`; **no brief is written**" — the deferral
  exists specifically so that importing `daedalus.runbook` (or anything that
  transitively imports it) never requires `langgraph`/`langsmith`/
  `langchain-core` (9.80 MB, 14 packages, MEASURED in that doc) to be
  installed, since core `dependencies = []` in `pyproject.toml` and
  `orchestration` is an opt-in extra.
- The same doc's own adversarial test, `test_nothing_imports_langgraph_at_module_scope`,
  is an AST walk over every `daedalus/**/*.py` specifically asserting no
  module reaches for the library at module scope — i.e. the deferral is a
  *tested contract*, not incidental placement.
- It is not cycle-avoidance: `daedalus.langgraph_adapter` does not import
  `daedalus.runbook` back (it calls into `router`/`schemas` independently to
  build an equivalent graph — confirmed by the doc's description of the
  adapter expressing "those same four steps as a three-node LangGraph graph
  over the *same* state keys," which does not describe a circular
  dependency), so there is no import cycle here for the deferral to break.
- Egress is a second, related reason the doc names for keeping the import
  cold: installing the extra pulls `langsmith`, whose tracing defaults are
  explicitly pinned off before the first LangGraph import rather than relied
  upon by absence.

## Proposed destination

**orchestration.**

Argument: it is the policy-designated canonical multi-step orchestration
composition seam (CLAUDE.md, quoted above) and its module-level imports are
`daedalus.router` (task routing) and `daedalus.schemas` (task/state
contracts) — both orchestration-shaped concerns, matching the same
`ikarus_*`/`kairos` family a peer worker already classified `orchestration`.
Its deferred `langgraph_adapter` import is the literal implementation of
plan §6's "LangGraph is Default-Substanz" rule: "kein zweiter, danebenstehender
Runner" — this file *is* the one sanctioned adapter, so it belongs with the
orchestration layer it composes for, not with `runtimes` (which supplies
providers) or `interfaces.cli` (its CLI tail is a thin, generic
`argparse` wrapper, not its architectural reason to exist).

Strongest counter-argument: it has **zero daedalus/ importers** — nothing in
production actually calls `create_run` — which could argue for
`interfaces.cli` (it is, mechanically, just a CLI script today) or even
`delete`/unwired-seam status. This does not overturn the destination, for
the reason laid out in Dead-code signals below: the policy that names this
file as the canonical seam was written explicitly for *future* multi-step
work to land here, and its liveness is measured by direct invocation and by
`test_langgraph_adapter.py`'s adapter-equivalence contract, not by
production callers that do not exist yet by design (`engine="stdlib"` stays
default until a Work Packet flips it, per CLAUDE.md's own "eigenes Work
Packet, kein Nebeneffekt dieser Regel" line).

## Boundary-rule verdict after the move

Landing in `orchestration` is not a rule source for any of the four rules
(all bind only `daedalus.kernel`, `daedalus.runtimes`, `daedalus.spine`,
`daedalus.twin` as sources), so all four rules are
**N-A-not-a-rule-source** for direction (a).

(b) reverse direction — **CLEAN**, per the lead's positive-controlled
measurement: no file under `daedalus/kernel`, `daedalus/spine`,
`daedalus/twin`, `daedalus/runtimes` imports any of the five packet modules
at any AST scope, and the complete flat-module import set of those 142
layer-files does not include `runbook`. Attributed to the lead.

Hypothetical (a), if it had landed in a rule-source layer anyway (using the
concrete measured lines above — this is the packet's named worked example:
`daedalus.runtimes`/`daedalus.schemas` are forbidden targets for kernel,
spine, and twin alike):
- `kernel-no-outer-layers`: `daedalus.schemas` is explicitly in
  `forbidden_target_prefixes` → **REFUSED** (`daedalus/runbook.py:9`).
  `daedalus.router` is on none of kernel's allowed prefixes → **REFUSED**
  (`daedalus/runbook.py:8`). `daedalus.langgraph_adapter` is on none of
  them either → **REFUSED** (`daedalus/runbook.py:30`, and this refusal
  fires even though the import is deferred — "the checker parses the WHOLE
  AST ... deferred imports checked exactly like module-level," per the
  packet's own boundary-contract note). `daedalus.budget` is allowed
  (line 84, clean). `daedalus.spine` is allowed (line 85, clean).
- `spine-no-outer-layers`: same three refusals (`schemas` line 9, `router`
  line 8, `langgraph_adapter` line 30 — none are on this rule's allowlist
  either); `budget` allowed (line 84); `daedalus.spine` is the rule's own
  source prefix (n/a to self, line 85).
- `twin-no-outer-layers`: allowlist is only `{kernel, spine, structcore}`.
  `router` refused (line 8), `schemas` refused (line 9, also explicitly
  denylisted), `langgraph_adapter` refused (line 30), `budget` refused
  (line 84, not on twin's allowlist) — only `daedalus.spine` (line 85) is
  clean.
- `runtimes-no-gates`: N/A — `runbook.py` never imports `daedalus.gates` at
  any scope, module-level or deferred.

One-line verdict: **N-A-not-a-rule-source** (destination is orchestration);
had it landed under kernel or spine it would be **REFUSED** on three of five
import lines (`router` line 8, `schemas` line 9, `langgraph_adapter` line
30); under twin, **REFUSED** on four of five.

## Dead-code signals — main event for this module

Zero daedalus/ importers, exactly as the steer warns not to read alone.
Two independent lines of evidence say this is a **live, policy-anchored
public API surface awaiting its flip**, not an unwired seam:

1. **`docs/FEATURE_INVENTORY.json:1949-1954`** — an independent static
   reachability instrument classifies it `"status": "wired",
   "classification": "entry", "reason": "declared entry point",
   "entry_kinds": ["main_guard"]`. The same file's "LangGraph adapter"
   feature entry (around line 1548-1553) lists `daedalus/runbook.py` and
   `tests/test_langgraph_adapter.py` as the feature's own module set,
   independent of my grep.
2. **The docstring makes an explicit, testable promise**, and the promise is
   kept: `create_run`'s docstring (lines 17-27) states the exact contract
   ("`engine` selects who COMPOSES the brief, never who writes it... raises
   `LangGraphUnavailable` if the extra is not installed — deliberately,
   rather than degrading silently"), and `tests/test_langgraph_adapter.py`
   is precisely the reader that holds it to that promise — the doc names
   three specific pinned tests
   (`test_the_agreement_is_not_vacuous`,
   `test_the_clock_is_the_only_permitted_difference`,
   `test_nothing_imports_langgraph_at_module_scope`) plus a documented
   mutation-check (changing one word in one constraint string turned exactly
   one test red, restored byte-exact per sha256).

Contrast with the packet's own worked negative case (`mission_control`:
zero importers, no `__main__` guard, genuinely retirable): `runbook.py`
*does* have a `__main__` guard (line 96-97), *is* reproducibly invocable
(`docs/LANGGRAPH_ADAPTER_20260825.md`'s exact reproduction commands, quoted
above), and is the explicit subject of active repo governance
(`CLAUDE.md`'s "Orchestrierung in diesem Repo" section names it by dotted
path). Zero importers here reflects that `engine="langgraph"` is
*intentionally* not yet the default — the doc says flipping the default "is
a separate Work Packet, not a side effect of this rule" — not that the seam
is unused or forgotten. No entry for `daedalus.runbook` in
`docs/architecture/shim-registry.json` (checked; not a compatibility facade).

## Confidence

High. Importer/import counts match the lead's precomputed numbers exactly
(2 total, 1 deferred; profile `{budget, langgraph_adapter, router, schemas,
spine}`, 0 third-party, 3 deferred), the cycle-avoidance-vs-isolation
question is answered directly by the adapter doc's own stated design intent
and its dedicated AST regression test rather than by inference, and the
boundary-refusal lines were checked against the actual `import-boundaries.json`
prefix lists rather than assumed from the rule names.
