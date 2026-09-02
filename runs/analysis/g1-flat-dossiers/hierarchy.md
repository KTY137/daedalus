# daedalus/hierarchy.py — classification dossier

## 1. Size and shape

- 186 lines (`wc -l daedalus/hierarchy.py`).
- 6 module-level functions, 0 classes: `capabilities()` (hierarchy.py:50),
  `_node()` (:54), `_edge()` (:58), `_policy_flags()` (:62), `hierarchy()`
  (:73), `save_team()` (:166).
- Module-level state: `CAPABILITIES` (hierarchy.py:10-47), a static list of 5
  dicts describing capability metadata (web_search, github_read,
  ollama_write, deepseek_advisory, claude_escalate). This is read-only data,
  not a mutable registry — nothing appends/removes from it at runtime.
- No import-time side effects: no file reads, no env reads, no registry
  mutation, no network, no path creation happen when the module is imported.
  The only import-time work is binding names from `. import core`,
  `.projects` and `.router` (hierarchy.py:6-8).
- Runtime (call-time, not import-time) side effect: `save_team()`
  (hierarchy.py:166-186) calls `rewrite_project_team(project, mutate)`
  (:185), which is an effectful write to the project registry — this fires
  only when the function is called, never at import.

## 2. What it does

`hierarchy.py` builds a node/edge graph projection of one project's agent
organization — squads, categories, agents, models and capabilities — for the
Agent OS webapp's UI (`hierarchy()`, hierarchy.py:73-163). `capabilities()`
(hierarchy.py:50-51) returns the static capability catalog wrapped in
`core.envelope`, and `save_team()` (hierarchy.py:166-186) validates and
applies a partial patch (max_workers, default_lane, active_agents, squads,
model_assignments, semi_auto) to a project's team config via
`rewrite_project_team`. Everything is expressed as plain dicts built by the
small `_node`/`_edge` helpers (hierarchy.py:54-59), assembled from
`load_project`, `core.team_config`, `core.get_categories` and
`load_agents(repo_root)`.

## 3. Who imports it (MEASURED)

Command: `git grep -n "hierarchy"` over git-tracked files, filtered to actual
import statements, excluding `.daedalus_worktrees/` and `.claude/` (neither
had any hits for "hierarchy" regardless). Verified against the independent
6-importer cross-check — this reproduces it exactly.

TOTAL: 6 module-level import edges. 0 deferred. Per-layer breakdown:
- daedalus (flat): 2 — `ikarus_chat.py`, `web_api.py`
- daedalus.interfaces (http): 2 — `effects.py`, `read.py`
- tests: 2 — `test_project_row_rewrite.py`, `test_web_api.py`

Full list:
1. `daedalus/ikarus_chat.py:13` — `from . import agents_registry, control_plane, core, hierarchy` — MODULE-LEVEL. Also calls `hierarchy.save_team(project, ...)` at ikarus_chat.py:203, a conversational (non-HTTP) path to team mutation.
2. `daedalus/web_api.py:30` — `hierarchy,` inside `from . import (...)` (web_api.py:22-33) — MODULE-LEVEL. (Only re-imports it; no direct call found in web_api.py itself — the actual calls live in the two `interfaces/http` files it composes.)
3. `daedalus/interfaces/http/effects.py:19` — `hierarchy,` inside `from ... import (...)` (effects.py:11-23) — MODULE-LEVEL. Calls `hierarchy.save_team(parts[2], body)` at effects.py:62 for `PUT /api/projects/{id}/team`.
4. `daedalus/interfaces/http/read.py:15` — `hierarchy,` inside `from ... import (...)` (read.py:9-17) — MODULE-LEVEL. Calls `hierarchy.hierarchy(project)` (read.py:125) for `GET /api/projects/{id}/hierarchy` and `hierarchy.capabilities()` (read.py:161).
5. `tests/test_project_row_rewrite.py:25` — `from daedalus import atomic, control_plane, hierarchy, projects, web_api` — MODULE-LEVEL.
6. `tests/test_web_api.py:15` — `hierarchy,` inside an import block — MODULE-LEVEL.

Additional non-AST-visible reference (reported per the measurement warning,
not counted in the 6): `tests/test_project_row_rewrite.py:37` contains a
second `from daedalus import control_plane, hierarchy, projects` line, but it
sits inside a triple-quoted string (`_PROCESS_ROW_REWRITE_RACER`,
test_project_row_rewrite.py:31) that is executed as a subprocess script via
`sys.executable -c`. It is a real runtime import when that subprocess racer
test runs, but it is a `Constant` string node to any AST import-walker, not
an `Import` node, so it is correctly invisible to the 6-importer census —
this reconciles exactly with "tests 2" (test_project_row_rewrite.py:25 +
test_web_api.py:15), not 3.

Two mentions of `hierarchy.hierarchy` / `hierarchy.capabilities` in
`daedalus/mapping/reach.py:526` and `:1185` are docstring prose (illustrating
that reachability tool's own module-level-binding resolution rule), not real
imports or calls — excluded.

## 4. What it imports (MEASURED)

All from `daedalus/hierarchy.py:6-8`, all MODULE-LEVEL, no deferred imports,
no third-party imports:
- `from . import core` (hierarchy.py:6) — flat `daedalus.core`. Used for `core.envelope`, `core.team_config`, `core.get_categories`.
- `from .projects import ProjectRowUpdateError, load_project, rewrite_project_team` (hierarchy.py:7) — flat `daedalus.projects`.
- `from .router import load_agents` (hierarchy.py:8) — flat `daedalus.router`.

`core`, `projects`, `router` are all currently-flat `daedalus/*.py` modules;
none of them is in the declared FOUNDATION list (atomic, budget, config,
limit_policy, primary_tree, sensitivity, storage), and none is in any of the
three ALLOWLISTS (kernel/spine/twin). `daedalus.core` is not itself named in
any of the four given rules' forbidden lists; `daedalus.projects` and
`daedalus.router` are likewise unnamed. (Note: `spine-no-outer-layers` does
forbid a *different* flat module, `daedalus.core`, from being imported by
spine — see §6(a).)

## 5. Proposed destination

**orchestration**, confidence **medium**.

Reading the file rules out both (b) an architecture/introspection utility
and (c) something unrelated to its name: `hierarchy.py` is a **runtime
domain module** — it composes a project's team/agent/capability state into a
graph for the UI and mutates that state. It has nothing to do with the
daedalus *package's* own module-layering hierarchy; the name is a homonym.
See §7 below for the explicit non-overlap finding against
`tests/test_architecture_boundaries.py`.

Argument from measured edges: exactly half of hierarchy.py's direct
importers already live under `daedalus/interfaces/http/` (effects.py,
read.py), which would suggest `interfaces/http` as the destination. But the
other flat importer, `daedalus/ikarus_chat.py`, calls the *same*
`hierarchy.save_team` for a non-HTTP, conversational mutation path
(ikarus_chat.py:203) — i.e. `hierarchy.py` is shared substrate that both an
HTTP-transport module and a chat/orchestration module depend on, not
HTTP-transport logic itself. Folding it into `interfaces/http` would force
`ikarus_chat` (itself orchestration-shaped: chat-driven team dispatch) to
reach into an `interfaces/*` submodule for a plain data mutation, an
inversion of the normal interfaces → orchestration direction. Placing it in
`orchestration` instead keeps `interfaces/http` → `orchestration` as the only
required direction (a legal, unconstrained edge under all four given rules)
and keeps the `ikarus_chat` ↔ `hierarchy` edge intra-layer if `ikarus_chat`
itself lands in orchestration.

What would change my mind: if `ikarus_chat.py` is independently classified
into `interfaces/*` rather than `orchestration`, the argument above collapses
and `interfaces/http` becomes the better fit (nothing in the boundary rules
blocks that alternative either — see §6(d)). Also, if `core`/`projects`/
`router` — the three flat modules hierarchy.py actually depends on — are
classified as `foundation`, that's mechanically compatible with an
`orchestration` destination for hierarchy under the four given rules, but
if any of the three were instead pulled toward `kernel`/`spine`/`twin`, the
picture would need to be re-measured, since those layers' allowlists do not
include `core`, `projects`, or `router` today.

## 6. Boundary-rule check after the move (destination: orchestration)

(a) Moved to `orchestration`, would any of its own imports be REFUSED? None
of the four authoritative rules given (kernel-no-outer-layers,
spine-no-outer-layers, twin-no-outer-layers, runtimes-no-gates) constrain
`daedalus.orchestration` as a *source* — they only bound what kernel/spine/
twin/runtimes may import. So mechanically, nothing refuses `orchestration`
importing `core`, `projects`, or `router`. This is not evidence the edges are
architecturally clean, only that no cited rule currently polices them.

(b) Does any CURRENT rule name `daedalus.hierarchy` by prefix? No. Checked
all four forbidden lists given in the task (kernel-no-outer-layers,
spine-no-outer-layers, twin-no-outer-layers, runtimes-no-gates) — none
mentions `hierarchy`. Nothing breaks or is silently un-forbidden by moving
it, from the rule-naming angle.

(c) N/A — destination is `orchestration`, not kernel/spine/twin, so the
allowlist-widening question doesn't apply to this module's own move. (For
context: even if it did land in one of those three, its imports of `core`
would specifically hit `spine-no-outer-layers`' FORBIDDEN entry
`daedalus.core` — see §4 — which would be refused outright, before any
allowlist-widening question arises. `core`, `projects`, `router` are absent
from all three ALLOWLISTS today, so any of the three landing hierarchy would
require widening a pinned allowlist, a reviewed diff of
`test_the_allowlists_cannot_grow_quietly`.)

(d) No rule currently constrains `daedalus.interfaces` as a SOURCE — confirmed:
none of kernel-no-outer-layers / spine-no-outer-layers / twin-no-outer-layers /
runtimes-no-gates governs what `daedalus.interfaces.*` may import, only what
may import *into* kernel/spine/twin (and `daedalus.ikarus_os`/`daedalus.
ikarus` etc. are named only as forbidden *targets* for other sources).
Concretely: had I instead proposed `interfaces/http` as hierarchy's
destination (the alternative in §5), that move would launder hierarchy's
current imports of `core`/`projects`/`router` behind a source prefix no rule
polices at all — same modules, same edges, but invisible to every boundary
rule after the move. That risk is a real point against the `interfaces/http`
alternative and part of why `orchestration` is favored here, even though
`orchestration` is *also* unconstrained as a source under the given rules —
at least `orchestration` is the semantically correct home for the module's
actual content, not a category picked because it happens to be unpoliced.

(e) If destination is `orchestration`: kernel/spine/twin all forbid
`daedalus.orchestration` as a target. Checked every one of the 6 measured
importers (§3) against layer membership: `ikarus_chat.py` and `web_api.py`
are flat `daedalus/*`; `effects.py` and `read.py` are `daedalus.interfaces.
http`; the two test files are `tests/*`. **None is a kernel/spine/twin
module.** Moving `hierarchy` to `orchestration` does not turn any currently
green kernel/spine/twin → hierarchy edge into a violation, because no such
edge exists today.

## 7. Dead-code signals

Not applicable as a disposition question — hierarchy.py has 6 live,
module-level importers across three layers (flat, interfaces/http, tests)
and an effectful call path exercised by both an HTTP mutation route
(effects.py:62) and a chat-driven mutation route (ikarus_chat.py:203).
Label: **LIVE**.

Duplication check against `tests/test_architecture_boundaries.py` /
`tools/architecture_boundaries.py` (the import-boundaries checker this whole
classification task is measured against): **no overlap**. Confirmed by
reading `daedalus/hierarchy.py` in full — every function operates on
project/team/agent/capability domain data (`load_project`, `core.
team_config`, `core.get_categories`, `load_agents`, `rewrite_project_team`)
and produces a UI graph of *that* domain. It contains no AST parsing, no
`import` statement scanning, no reference to `daedalus.*` module prefixes,
and no contract/rule loading — none of the machinery
`tools/architecture_boundaries.py` uses to check daedalus's own module
layering. The word "hierarchy" in this module's name refers to the agent
organization hierarchy of one project (squads/agents/capabilities), not the
package's import-layer hierarchy; the two are unrelated concepts that happen
to share an English word. Had hierarchy.py implemented a second import-graph
authority, that would be a review-blocking defect under AGENTS.md's "another
event store, artifact identity, graph authority, or promotion path" rule —
it does not, so no such defect exists here.
