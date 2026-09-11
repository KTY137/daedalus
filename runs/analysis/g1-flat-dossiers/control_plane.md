# daedalus/control_plane.py

## 1. Size and shape

268 lines (`wc -l daedalus/control_plane.py` = 268).

- 0 classes.
- 11 top-level functions: `_read_json` (control_plane.py:40), `_repo_root`
  (:50), `_norm_mode` (:54), `claude_surface` (:59), `codex_surface` (:104),
  `_capabilities_for` (:135), `_sync_status` (:149), `_autonomy_config`
  (:161), `resolve_autonomy` (:171), `unified_profiles` (:190),
  `save_autonomy` (:236) — plus one nested closure `mutate` defined inside
  `save_autonomy` (:256), 12 function objects total.
- Module-level state: `AUTONOMY_MODES` tuple (:23), `_MODE_RANK` dict
  comprehension (:24), `CAPABILITY_GATES` — a 10-entry list of dicts, the
  capability-gate registry (:26-37). All three are frozen-at-import constant
  data; nothing later reassigns them (grep for `AUTONOMY_MODES =`,
  `_MODE_RANK =`, `CAPABILITY_GATES =` in the file shows exactly the one
  definition each, no rebinding). No singleton, no cache, no lazy-init
  pattern.
- No module-level side effects at import: no file reads, no env reads, no
  network calls, no registry mutation executed at import time. Every file
  read (`_read_json`, `.claude/settings.json`, `.mcp.json`, `AGENTS.md`) and
  every filesystem stat (`.exists()`) happens lazily, inside a function body,
  only when a caller invokes `claude_surface`/`codex_surface`/
  `unified_profiles`.

## 2. What it does

It reads a project's on-disk Claude Code configuration (`.claude/settings.json`,
`.claude/settings.local.json`, `.mcp.json`) and Codex configuration
(`AGENTS.md`) and turns them into typed status payloads (`claude_surface`,
`codex_surface`). It merges those with the Daedalus agent-role registry
(`router.load_agents`) and the project's own team/autonomy configuration to
produce one `unified_profiles` payload per agent — sync status, capabilities,
and a resolved per-capability autonomy mode (`resolve_autonomy`, which picks
the most restrictive of project/agent/capability mode). `save_autonomy`
validates and writes an autonomy patch back into the project registry through
`projects.rewrite_project_team`, then returns a freshly recomputed
`unified_profiles`.

## 3. Who imports it (MEASURED)

Searched `daedalus/`, `tests/`, `tools/`, `apps/`, `docs/`, `.claude/` for
`control_plane` as an import token and as a bare string.

**TOTAL: 6 distinct files import it in Python** (4 production, 2 test), plus
one non-Python HTTP-contract reference. All 4 production edges are
MODULE-LEVEL.

Production (all layer = flat legacy monolith / `interfaces/http` split):

- `daedalus/ikarus_chat.py:13` — `from . import agents_registry, control_plane, core, hierarchy` (MODULE-LEVEL). Used at `ikarus_chat.py:207`:
  `"control_plane": control_plane.unified_profiles(project)`. `ikarus_chat.py`
  is itself flat/unclassified (not in your two modules, not in the declared
  SCC list).
- `daedalus/web_api.py:22-33` — `from . import (..., control_plane, ...)`
  (MODULE-LEVEL). `web_api.py` is the flat legacy HTTP host being split into
  `daedalus/interfaces/http/*`.
- `daedalus/interfaces/http/read.py:9-17` — `from ... import (..., control_plane, ...)` (MODULE-LEVEL, package = `interfaces/http`). Used at
  `read.py:128`: `self._send_json(control_plane.unified_profiles(project))`,
  serving `GET /api/projects/<id>/control-plane` (route match at
  `read.py:126`).
- `daedalus/interfaces/http/effects.py:11-23` — `from ... import (..., control_plane, ...)` (MODULE-LEVEL, package = `interfaces/http`). Used at
  `effects.py:65`: `self._send_json(control_plane.save_autonomy(parts[2], body))`, serving the `.../autonomy` mutation route
  (`effects.py:64`).

Tests (package = `tests/`):

- `tests/test_web_api.py:12` — part of `from daedalus import (control_plane, conversation as conversation_mod, ...)` (MODULE-LEVEL). Exercises
  `control_plane.unified_profiles` (:102) and `control_plane.resolve_autonomy`
  (:122).
- `tests/test_project_row_rewrite.py:25` — `from daedalus import atomic, control_plane, hierarchy, projects, web_api` (MODULE-LEVEL, in the test
  file's own top-level namespace). A second occurrence at
  `test_project_row_rewrite.py:37` — `from daedalus import control_plane, hierarchy, projects` — is **not** a real import executed by this test
  file's process: it is source text inside the `_PROCESS_ROW_REWRITE_RACER`
  string literal (:31, `r"""..."""`) that gets written out and run as a
  **separate subprocess** to test concurrent registry-row rewrites. It is a
  genuine MODULE-LEVEL import, but of a spawned child script, not of the
  pytest process itself. Also monkeypatches
  `control_plane.unified_profiles` (:58, :179, :675) and calls
  `control_plane.save_autonomy` (:69, :187, :688).

Non-Python:

- `apps/web/src/shared/contracts/index.ts:166` — `control_plane?: ControlPlanePayload;`, the TypeScript type for the JSON body `unified_profiles`
  returns. This is an HTTP-contract consumer of the endpoint, not a Python
  import; it does not appear in the module's Python dependency graph.
- `daedalus/tools/inventory.py:4` mentions `control_plane.py` only in a
  prose docstring about a design gap ("could list the MCP servers... and did
  nothing"), not an import or dynamic reference.
- Various `docs/**` and `runs/**` hits (architecture-state.json,
  architecture-map.html, inventory slices, ADRs, swarm census shards,
  HANDOFF_ANTIGRAVITY.md) are historical documentation/report artifacts that
  name the file; none is a code importer.

No hits under `.claude/`.

## 4. What it imports (MEASURED)

All MODULE-LEVEL, all `daedalus.*` (no third-party imports beyond stdlib
`json`, `pathlib.Path`, `typing.Any`):

- `from . import core` — control_plane.py:13. Target: **SCC-owned** (`core`
  is one of the 11 modules in the declared 18-module SCC; do not classify,
  only record). Used for `core.team_config`, `core.get_categories`,
  `core.envelope` (unified_profiles:196,198,220).
- `from .claude_detect import detect_claude_crew` — control_plane.py:14.
  Target: **flat**, unclassified in this packet (not in the declared
  package list, not in the SCC list, not FOUNDATION).
- `from .projects import (ProjectRegistryUnavailable, ProjectRowUpdateError, load_project, rewrite_project_team)` — control_plane.py:15-20. Target:
  **flat**, unclassified in this packet.
- `from .router import load_agents` — control_plane.py:21. Target: **flat**,
  unclassified in this packet.

No imports of `kernel`, `spine`, `twin`, `orchestration`, `runtimes`, or
`schemas` anywhere in the file.

## 5. Proposed destination

**orchestration**. Confidence: **medium-high**.

Argument from measured edges, not the name:

- Every production caller (`ikarus_chat.py`, `web_api.py`,
  `interfaces/http/read.py`, `interfaces/http/effects.py`) treats
  `control_plane` as a logic module sitting *behind* a thin HTTP dispatch
  layer, never as a dispatch layer itself. `interfaces/http/read.py`'s own
  docstring calls itself "Read-only HTTP route dispatch behind the legacy web
  facade" and `effects.py` calls itself "Mutation route dispatch behind the
  registered legacy effect facade" — both literally just unpack the route and
  call straight into `control_plane.unified_profiles`/`save_autonomy` and
  serialize the result. The interface layer is the thin shell; `control_plane`
  is the logic it shells out to.
- What that logic computes matches the master plan's own definition of the
  orchestration layer's job almost verbatim: master plan §7 says "The
  orchestration layer answers who works, with which runtime, context,
  capabilities, budget, workspace, and review chain." `control_plane.py`
  computes exactly that: per-agent capability sets (`_capabilities_for`),
  resolved per-capability autonomy mode against project/agent/capability
  policy (`resolve_autonomy`), and cross-runtime sync status between the
  Daedalus role registry and the live Claude Code subagent roster
  (`_sync_status`).
- No kernel/spine/twin module imports `control_plane` today (measured: `grep
  control_plane daedalus/kernel daedalus/spine daedalus/twin` — zero hits),
  so nothing currently green would break by the move (see §6d).

What would change my mind: if the hierarchy lead is treating
`interfaces/http` as "everything that only a route handler calls, regardless
of how much logic it holds," `control_plane` would land in `interfaces/http`
instead — its only two effectful/read entrypoints are in fact single HTTP
routes (`GET .../control-plane`, `POST/PUT .../autonomy`), and `ikarus_chat.py`
(its one non-HTTP caller) is itself unclassified and could just as easily be
`interfaces` as `orchestration`. I did not find a measured edge that forces
one reading over the other; the call is on where "capability/autonomy
resolution logic reachable from exactly one HTTP route and one chat-apply
path" belongs, which is a product-shape judgment more than an import-graph
fact.

This module is not fused — it is one coherent responsibility (unify
Daedalus+Claude+Codex agent status and resolve autonomy), not two things that
need splitting.

## 6. Boundary-rule check after the move

Read `docs/architecture/import-boundaries.json`. It defines four rules,
sourced from `daedalus.kernel`, `daedalus.runtimes`, `daedalus.spine`, and
`daedalus.twin` respectively. None is sourced from `daedalus.orchestration`
or `daedalus.interfaces.*`.

(a) If `control_plane.py` moves to `daedalus/orchestration/...`, would its
own imports be refused? **No.** None of the four rules constrains what
`daedalus.orchestration` (or any interfaces package) may import — they only
constrain what `daedalus.kernel`, `daedalus.runtimes`, `daedalus.spine`, and
`daedalus.twin` may import. `control_plane.py`'s own imports (`core`,
`claude_detect`, `projects`, `router` — all flat, none is `chip_design`,
`eval`, `gates`, `kairos`, `providers`, `runtimes`, `schemas`, or `orchestration`
itself) would not trip any existing rule even if one were added later with
today's shape, since it imports no kernel/spine/twin/runtimes/gates module at
all.

(b) Does any CURRENT rule name this module by prefix? Not `control_plane`
specifically — no rule enumerates `daedalus.control_plane`. But
`kernel-no-outer-layers`, `spine-no-outer-layers`, and `twin-no-outer-layers`
all already forbid the **prefix** `daedalus.orchestration` in their
`forbidden_target_prefixes`. Moving `control_plane.py` under
`daedalus/orchestration/` therefore does not require a new named rule: it
falls under an already-forbidden prefix automatically. The question is only
whether that forbidding is currently vacuous or would newly bite — see (d).

(c) N/A — the proposed destination is `orchestration`, not `kernel`/`spine`/
`twin`, so the allowlist rules for those three sources do not apply to this
module's own imports.

(d) Highest-value check: does any kernel/spine/twin module currently import
`daedalus.control_plane`, such that moving it into `orchestration` turns a
currently-green edge into a violation? **Measured: no.**
`grep -r control_plane daedalus/kernel daedalus/spine daedalus/twin` returned
zero hits in all three packages (both as an import and as a bare string).
There is no currently-green edge to break. The move is clean by this check.

## 7. Dead-code signals

Not applicable in the "zero importers" sense — **LIVE**. Measured 4 distinct
production files importing it at module level (§3), wired into two live HTTP
routes (`GET /api/projects/<id>/control-plane` at
`daedalus/interfaces/http/read.py:126-128`, and the autonomy write route at
`daedalus/interfaces/http/effects.py:64-65`), consumed by the frontend
contract (`apps/web/src/shared/contracts/index.ts:166`), and covered by two
test files exercising both the read and write paths
(`tests/test_web_api.py`, `tests/test_project_row_rewrite.py`).
