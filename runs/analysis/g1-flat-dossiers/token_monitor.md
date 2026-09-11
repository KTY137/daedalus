# daedalus/token_monitor.py

Scope note: all searches below are scoped to `daedalus/`, `tests/`, `tools/`
only (Grep `path=`). `.claude/worktrees/agent-*/` holds full duplicate copies
of `daedalus/` and `tests/` and was explicitly excluded to avoid double
counting.

## Importers (MEASURED) — DISAGREES WITH THE LEAD, evidence below

The lead's precomputed count: 7 total = 1 daedalus/ + 6 tests/ + 0 tools/;
3 deferred.

What I measured: **8 total = 1 daedalus/ + 7 tests/ + 0 tools/; 3 deferred.**
The daedalus/ count (1) and the deferred count (3) both match the lead
exactly. The disagreement is specifically in the tests/ count: I find **7**
distinct real import statements across 7 distinct test files, not 6. Full
enumeration, each verified by reading the actual line (not just a substring
match):

daedalus/ (1 site, deferred):
- `daedalus/cli.py:1212` — `from .token_monitor import main as m; raise SystemExit(m(rest))` (deferred, inside the CLI subcommand dispatcher).

tests/ (7 sites, 2 deferred, 7 distinct files):
1. `tests/test_agent_env.py:15` — `from daedalus.token_monitor import STATUS_PATH, UsageSample, checkpoint_if_needed, should_checkpoint, summarize_usage` (module-level).
2. `tests/test_cli_token_verb.py:56` — `import daedalus.token_monitor as tm` (deferred, inside a test function, alongside `import daedalus.memory as memory` at line 55).
3. `tests/test_cli_effect_boundary.py:158` — `from daedalus.token_monitor import main` (deferred, inside `test_token_monitor_refuses_fail_closed_without_the_contract`).
4. `tests/test_hardening.py:33` — `from daedalus.token_monitor import read_usage_samples, summarize_usage` (module-level).
5. `tests/test_token_monitor_write_roots.py:73` — `import daedalus.token_monitor as tm` (module-level, alongside `daedalus.budget`/`daedalus.memory` at lines 71-72).
6. `tests/test_uncapped_budget_consumers.py:5` — `from daedalus.token_monitor import _render_budget_view` (module-level).
7. `tests/test_uncapped_scope_usage.py:11` — `from daedalus import ikarus_os, token_monitor` (module-level).

Every one of these 7 lines was read with 2-3 lines of surrounding context to
confirm it is an executable import statement, not a string literal or
comment — unlike the excluded matches below. I cannot identify which one the
lead's extractor would have dropped; all 7 look identical in shape to the
other four modules' importer sites that DID match the lead's counts exactly
(see `semantic_route.md`, `token_policy.md`, `runbook.md` in this same
directory, where my counts agree with the lead's on every axis). This reads
as a genuine one-off miss in the lead's AST extractor for this module
specifically, not a scoping error on my part (all 7 files are under
`tests/`, none under a worktree copy).

Not counted as importers: `tests/test_registry_new_doors.py:38` (prose
mentioning `cli.token_monitor` the registry row, not an import),
`tests/test_slice_egress_gate.py:60` and `tests/test_slice_secret_value_shape.py:252`
(the string `"daedalus/token_monitor.py"` / `"token_monitor.py"` inside a
path-literal list passed to a checker, not an import).

tools/: 0 matches for `token_monitor` anywhere under `tools/`.

Dynamic/string references searched: `python -m daedalus.token_monitor` is
documented (module docstring `daedalus/token_monitor.py:320`, and
`docs/LANGGRAPH_ADAPTER_20260825.md` is unrelated — the real hit is
`docs/FEATURE_INVENTORY.json`, which records a `bus:...` entry point at line
43072-43074 for `token_monitor.py`'s `watch` function). No
`importlib`/`__import__` reference found. No `pyproject.toml` console_scripts
entry — it is reached via `daedalus/cli.py:1212`'s manual subcommand table,
not a packaged entry point.

## Identity

Absolute path: `C:/Users/Administrator/daedalus/daedalus/token_monitor.py`.
394 lines. Read-only observability CLI (`daedalus tokens`) that reports local
Claude token usage, the spend ledger, and the intent spine, and checkpoints a
TODO snapshot under token pressure — explicitly documented as deciding
nothing about the ledger it reads.

## Imports (MEASURED)

Module-level:
- `daedalus/token_monitor.py:32` — `from .limit_policy import ExecutionLimitPolicy, load_from_env` → `daedalus.limit_policy`.
- `daedalus/token_monitor.py:33` — `from .memory import MEMORY_DIR, MemoryEvent, append_event, refresh_todo_snapshot` → `daedalus.memory`.
- `daedalus/token_monitor.py:34` — `from .projects import ROOT as REPO_ROOT, resolve_repo_root` → `daedalus.projects`.
- stdlib: `argparse`, `json`, `time`, `dataclasses`, `pathlib`, `typing`.

Deferred/function-scope:
- `daedalus/token_monitor.py:250` — `from .budget import BudgetError, Ledger` → `daedalus.budget`, inside `_budget_view`.
- `daedalus/token_monitor.py:289` — `from .spine.ledger import SpineLedger, default_db_path` → `daedalus.spine`, inside `_spine_view`.
- `daedalus/token_monitor.py:332-333` — `from .budget import process_guard_boundary_decision` and `from .spine.effect_boundary import REGISTRY_BY_ID, begin_effect`, inside `main()` (a second, separate deferred use of both `budget` and `spine`).

Outbound profile: `{budget, limit_policy, memory, projects, spine}`, 0
third-party. Deferred count: the lead's "4 deferred" is measured against
distinct import *statements* (lines 250, 289, 332, 333 = 4), which matches
what I count here.

## What it does

`token_monitor` reads Claude's local session logs plus the canonical spend
ledger (read-only, via `daedalus.budget.Ledger.state()`) and the intent spine
(opened `read_only=True`, so SQLite itself refuses a write) to render a
combined usage/spend/in-flight-work report, either as `daedalus tokens` or
`python -m daedalus.token_monitor`. It writes exactly one artifact of its
own, `memory/token_status.local.json`, and its checkpoint decision
(`should_checkpoint`) is deliberately computed *before* the budget/spine
views are assembled so no future edit could make a spend number silently
influence the checkpoint verdict without changing that function's signature
in the diff — a test pins this ordering. 394 lines, and every mutating code
path (the `begin_effect` call) runs before argument parsing so both entry
doors (`daedalus tokens` and the bare module) pass the same guard.

## Proposed destination

**interfaces.cli.**

Argument: it is a registered CLI verb (`cli.token_monitor` effect-boundary
row, `daedalus/spine/effect_boundary.py:681-704`) reached from
`daedalus/cli.py:1212`'s subcommand dispatch, its own module docstring frames
it as `daedalus tokens`, and `docs/FEATURE_INVENTORY.json` classifies it
`"status": "wired", "classification": "entry"`. Its role is user/operator-
facing reporting, not a dependency any other production module reaches into
— the only daedalus/ importer is the CLI dispatcher itself.

Strongest counter-argument: it could be `runtimes` instead, since its
subject matter (token/spend/ledger observability) is runtime-execution
adjacent and it imports `daedalus.budget`/`daedalus.spine` (both allowed
targets even for `kernel`). This loses because those two imports are
strictly read-only views assembled for a human-facing report, not
runtime-execution logic reused by other runtime code — nothing under
`daedalus/runtimes` imports it (confirmed clean per the lead's boundary
measurement below), and its entire external contract is "a CLI verb prints a
report", which is the defining shape of `interfaces.cli`, not `runtimes`.

## Boundary-rule verdict after the move

Landing in `interfaces.cli` is not a rule source for any of the four rules
(all bind only `daedalus.kernel`, `daedalus.runtimes`, `daedalus.spine`,
`daedalus.twin` as sources), so all four rules are
**N-A-not-a-rule-source** for direction (a).

(b) reverse direction — **CLEAN**, per the lead's positive-controlled
measurement: no file under `daedalus/kernel`, `daedalus/spine`,
`daedalus/twin`, `daedalus/runtimes` imports any of the five packet modules
at any AST scope, and the complete flat-module import set of those 142
layer-files does not include `token_monitor`. Attributed to the lead.

Hypothetical (a), if it had landed in a rule-source layer anyway (imports:
`limit_policy`, `memory`, `projects` module-level; `budget`, `spine` deferred):
- `kernel-no-outer-layers`: `limit_policy` allowed, `budget` allowed, `spine`
  allowed. `daedalus.memory` **not** on the allowlist → refused
  (`daedalus/token_monitor.py:33`). `daedalus.projects` **not** on the
  allowlist → refused (`daedalus/token_monitor.py:34`).
- `spine-no-outer-layers`: same two refusals (`memory` line 33, `projects`
  line 34); `limit_policy`/`budget` allowed; `daedalus.spine` is the rule's
  own source (n/a to self).
- `twin-no-outer-layers`: allowlist is only `{kernel, spine, structcore}`.
  `limit_policy` refused (line 32), `memory` refused (line 33), `projects`
  refused (line 34), `budget` refused (line 250/332) — only the deferred
  `daedalus.spine` import (line 289/333) is clean.
- `runtimes-no-gates`: N/A — never imports `daedalus.gates` at any scope.

One-line verdict: **N-A-not-a-rule-source** (destination is interfaces.cli);
had it landed under kernel or spine it would be **REFUSED** (`daedalus.memory`
line 33, `daedalus.projects` line 34); under twin, **REFUSED** on four of
five distinct target lines.

## Dead-code signals

Not dead. `docs/FEATURE_INVENTORY.json` lines 2543-2548 record `"status":
"wired", "classification": "entry", "reason": "declared entry point",
"entry_kinds": ["bus", ...]` — an independent static instrument agrees it is
live, and additionally records a `bus:...:watch` entry point
(lines 43072-43074) for its `--watch` loop mode. No entry for
`daedalus.token_monitor` in `docs/architecture/shim-registry.json` (checked;
21 entries enumerated by a peer worker, none match — not a compatibility
facade). Chased one hop on its sole daedalus/ importer, `daedalus/cli.py`:
line 1212 sits inside the live `daedalus` console command's subcommand table
(confirmed by reading surrounding dispatch code), not a second unwired path.
The module's own docstring is explicit about what it does NOT do
(`should_checkpoint` "is the only function here that returns a decision" and
"nothing here reserves, settles, or rolls the budget ledger") — that promise
is testable and is exactly what `tests/test_token_monitor_write_roots.py`'s
"MUTATION NOTE" (line 36) pins against regression.

## Confidence

Medium-high. High confidence in the module's own content, imports, and
liveness (independently corroborated by FEATURE_INVENTORY and the
effect-boundary registry). Medium confidence specifically on the exact
importer *count*, because I disagree with the lead's tests/ number (7 vs 6)
and could not identify which of my 7 verified sites the lead's extractor
might have dropped — re-running the lead's own AST tool against this one
module, or a second independent worker's count, would raise this to high.
