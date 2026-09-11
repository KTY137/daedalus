# daedalus/ikarus.py — classification dossier

## 1. Size and shape

- 33 lines (`wc -l daedalus/ikarus.py`).
- 0 classes, 0 functions defined locally — it is a pure re-export shim.
  Everything it exposes (`Assignment`, `DEFAULT_AVAILABILITY`, `FREE_LANES`,
  `KairosScheduler`, `_paths_overlap`, `main`) is imported wholesale from
  `.kairos.scheduler` (ikarus.py:8-15).
- Module-level state: two alias bindings — `Ikarus = KairosScheduler`
  (ikarus.py:17) and `MetronScheduler = KairosScheduler` (ikarus.py:18, the
  pre-rename name) — plus the `__all__` list (ikarus.py:20-29).
- Import-time side effect: importing `daedalus.ikarus` triggers execution of
  `daedalus/kairos/scheduler.py` (via the `from .kairos.scheduler import
  (...)` at ikarus.py:8-15); ikarus.py itself performs no file/env reads,
  registry mutation, network access, or path creation. The
  `if __name__ == "__main__": main()` guard (ikarus.py:32-33) only runs
  `main()` when the module is executed directly (e.g. `python -m
  daedalus.ikarus`), never on import.

## 2. What it does

`daedalus/ikarus.py` is a backward-compatible import surface that re-exports
`daedalus.kairos.scheduler`'s public names under their pre-rename identities
(ikarus.py:1-6). It binds `Ikarus` and `MetronScheduler` as aliases of
`KairosScheduler` so that code written against either historical name still
resolves (ikarus.py:17-18). It also forwards `main` so `python -m
daedalus.ikarus` still runs the scheduler CLI entrypoint (ikarus.py:14,
32-33).

## 3. Who imports it (MEASURED)

Command: `git grep -nE 'daedalus\.ikarus\b'` and equivalent `from .ikarus
import` / `from . import ikarus` forms over git-tracked files, excluding
`.daedalus_worktrees/` and `.claude/`, with word-boundary filtering to
exclude `ikarus_os`, `ikarus_supervisor`, `ikarus_chat`, `ikarus_act`,
`ikarus_effect_bridge`, `ikarus_oneshot`, `ikarus_tool_scope` (all distinct
sibling flat modules that share the `ikarus` prefix but are not this file).

**TOTAL: 0 real Python importers, tree-wide.** This reproduces the
independent AST census exactly (0 AST importers). No `from daedalus.ikarus
import ...`, `from . import ikarus`, `from .ikarus import ...`,
`import daedalus.ikarus`, or `importlib.import_module("daedalus.ikarus")`
exists anywhere in the git-tracked tree outside `daedalus/ikarus.py` itself.

Non-importer references to the string `daedalus.ikarus` / names `Ikarus` /
`MetronScheduler` found (none are import edges):
- `docs/architecture/import-boundaries.json:76` and `docs/architecture/
  shim-registry.json:53` — contract/registry entries (see §6(b) and §7).
- `tests/contracts/test_spine_outer_ports.py:81-82` — a `FORBIDDEN_PREFIXES`
  tuple mirroring the contract's forbidden list (includes both
  `"daedalus.ikarus"` and `"daedalus.ikarus_os"` as separate string
  entries), used only to assert cold-import isolation of `daedalus.spine`,
  not to import the module.
- `docs/FEATURE_INVENTORY.json`, `docs/inventory/2026-08-21/*.json`,
  `docs/archive/swarm-2026-07-30/census/SYNTH-structure.md`,
  `experiments/forest_v2/s09_eval/taskset_xplane.json` — historical
  inventory/census artifacts and one replayed commit message, all prose
  describing the shim, not live references.
- `docs/archive/.../SYNTH-structure.md:322` notes a **now-stale** finding
  that `docs/GO_LIVE.md:53` once had `from daedalus.ikarus import Ikarus`;
  re-checked directly (`grep -n ikarus docs/GO_LIVE.md`) — that reference is
  **gone from the current `docs/GO_LIVE.md`**, so even that historical
  documentation caller no longer exists.

No pickle or other serialized reference to `daedalus.ikarus.Ikarus` or
`MetronScheduler` was found anywhere in the tracked tree (`git grep -nE
'ikarus\.Ikarus|MetronScheduler'` over `*.py`/`*.json`/`*.pkl` returns only
ikarus.py's own source and doc/inventory prose — no serialized blob, no
pickled state file).

## 4. What it imports (MEASURED)

`daedalus/ikarus.py:8-15`, MODULE-LEVEL, one statement:
`from .kairos.scheduler import (Assignment, DEFAULT_AVAILABILITY,
FREE_LANES, KairosScheduler, _paths_overlap, main)` — target
`daedalus.kairos.scheduler`, the `kairos` layer (not one of kernel/spine/
twin/runtimes/orchestration/interfaces/foundation in the given target
layout — kairos is its own existing package). No third-party imports, no
other `daedalus.*` imports, no deferred imports.

## 5. Proposed destination

**NONE-retire-per-registry-criteria** — per the owner directive and
confirmed by measurement, this is a **REGISTERED-SHIM**, not a candidate for
a target layer and not a `CANDIDATE-DELETE`. Confidence: **high**.

The shim is registered in `docs/architecture/shim-registry.json:52-60`:
```
"import_path": "daedalus.ikarus",
"owner": "orchestration",
"targets": ["daedalus.kairos.scheduler"],
"kind": "module_reexport",
"removal_criteria": "The Ikarus orchestration package owns the public name
  and all scheduler callers have migrated without changing serialized
  identities."
```
This removal criterion has two conjuncts, both checked directly:
1. **"The Ikarus orchestration package owns the public name"** — **NOT
   MET**. `ls daedalus/ikarus/` — no such directory; no `daedalus/ikarus/`
   package exists. `daedalus/orchestration/` exists (`__init__.py`,
   `execution/`, `missions/`, `legacy_reports.py`,
   `workspace_containment.py`) but nothing under it is named `ikarus` or
   otherwise "owns the public name daedalus.ikarus" — the one file in it
   that mentions "Ikarus" prose-wise, `daedalus/orchestration/missions/
   one_shot.py`, imports three unrelated sibling flat modules
   (`daedalus.ikarus_effect_bridge`, `daedalus.ikarus_oneshot`,
   `daedalus.ikarus_tool_scope`), none of which is `daedalus.ikarus` itself
   or a package claiming that public name.
2. **"...without changing serialized identities"** — vacuously satisfied
   for now (no serialized/pickled reference to `Ikarus`/`MetronScheduler`
   exists per §3), but this conjunct only becomes a real constraint once
   conjunct 1 is met and removal is actually attempted — it is not evidence
   removal is safe today, only that it isn't blocked by this specific risk
   yet.

Since the removal precondition is unmet, the shim's own registry entry does
not license removing it today either — its correct disposition right now is
"stay as a registered compatibility shim, revisit when an
`daedalus/ikarus/` package claims the name." That is exactly
`NONE-retire-per-registry-criteria`, not `CANDIDATE-DELETE` (which would
require severing it now) and not a real target-layer move (moving a shim
defeats the purpose of pinning its import path — see also AGENTS.md's rule
against "a new effectful entrypoint that bypasses policy" / duplicate
authority, which the shim's whole design exists to avoid triggering during
the kairos migration).

## 6. Boundary-rule check after the move

Since disposition is "stays put, not moved," (a) and (c) don't apply in
their literal sense; (b) is mandatory per the task and is answered in full.

(a) N/A — no move is proposed.

(b) **Mandatory — a CURRENT rule names it.** `spine-no-outer-layers`'
`forbidden_target_prefixes` explicitly includes `"daedalus.ikarus"`
(confirmed in `docs/architecture/import-boundaries.json:76` and mirrored in
`tests/contracts/test_spine_outer_ports.py:81` as part of
`FORBIDDEN_PREFIXES`). This means: today, no `daedalus.spine.*` module may
import `daedalus.ikarus` at any scope (module or deferred — the checker
walks the full AST per the task's framing) without failing that contract
row.

**If the shim is ever removed** (i.e. `daedalus/ikarus.py` deleted once its
own removal criteria are eventually met): the `"daedalus.ikarus"` entry in
`spine-no-outer-layers`' forbidden list becomes a **dead/vacuous rule
entry** — there is no measured `daedalus.spine → daedalus.ikarus` edge today
(§3 found zero importers tree-wide, and spine is not one of them), so no
edge silently becomes newly-legal in practice; nothing "opens up." But the
rule text would keep naming a module path that no longer exists on disk,
which is stale contract content, not a live guard. Pruning that dead entry
is a separate, deliberate edit to `docs/architecture/import-boundaries.json`
and to the `FORBIDDEN_PREFIXES` tuple in `tests/contracts/
test_spine_outer_ports.py:72-92` (both must move together, since the latter
is a hand-copied mirror of the former, "the forbidden set minus
`daedalus.schemas`" per that file's own comment at line 70-71) — it is not
covered by `test_the_allowlists_cannot_grow_quietly`, since that test only
pins `allowed_target_prefixes` membership, not `forbidden_target_prefixes`;
removing the dead forbidden entry would need its own reviewed diff of
whichever test (if any) is later added to pin forbidden-list membership, or
at minimum manual review that no other spine module has grown a real
dependency on the shim's replacement path in the interim.

(c) N/A — destination is not kernel/spine/twin.

(d) N/A for this module specifically — no `interfaces/*` destination is
proposed for `daedalus.ikarus`, so the "does an interfaces move launder a
forbidden prefix" question does not arise here (see the `hierarchy.md`
dossier for a live instance of this concern on the sibling module).

(e) N/A — destination is not orchestration.

**CLI routing check (task-mandated)**: `daedalus/cli.py:1146` dispatches the
`ikarus` subcommand as `elif cmd == "ikarus": from .kairos.scheduler import
main as m; m()` (cli.py:1145-1146). This imports `daedalus.kairos.scheduler`
**directly** — it does **not** route through the `daedalus.ikarus` shim at
all. The CLI subcommand and the shim happen to share the name "ikarus," but
the CLI's own migration to the new `kairos` name is already complete; the
shim exists purely for external/library-style importers of
`daedalus.ikarus.Ikarus`, of which measurement found zero in this tree.

## 7. Dead-code signals

Searched: (1) docstring for a promised reader — ikarus.py:1-6 explicitly
states "Existing integrations historically imported
`daedalus.ikarus.Ikarus`... Keep the old API working during that
migration," a promise aimed at *external* integrations, which this repo's
own tree cannot enumerate. (2) `pyproject.toml` console_scripts — checked
(`grep -in ikarus pyproject.toml`); no console_scripts entry names
`daedalus.ikarus` (the one hit is unrelated: the package `description`
field mentioning "Ikarus local bench" as a product-name reference, not an
entrypoint). (3) module name as a bare string across the tracked tree,
including `daedalus/spine/effect_boundary.py`'s registered CLI targets —
checked (§3); `effect_boundary.py` registers `daedalus.ikarus_os:*` targets
only, never `daedalus.ikarus`. (4) `shim-registry.json` membership —
present, confirmed (§5). (5) `git log --follow` on `daedalus/ikarus.py` —
the file was **created already as a shim** in commit `ccb17634`
("refactor(kairos): namespace and harden scheduler execution"), the same
commit that moved scheduling logic into `daedalus/kairos/`; it was never a
"real" implementation module that later lost its consumer — it was born as
a forward-compatibility wrapper with a docstring naming an audience outside
this repository, and it has had exactly one commit touching it since
(`ccb17634` is both its add and its only revision in `git log --follow`
output).

Label: **REGISTERED-SHIM**. Per the owner directive this is explicit and
matches the evidence: zero live importers is a finding consistent with "no
internal caller migrated back to it," not a verdict of dead code, because
(a) it is a registered shim with a promised external-integration reader that
this repo's tree cannot falsify or confirm, and (b) its own removal
criterion is a precondition ("an Ikarus orchestration package owns the
public name") that is verifiably unmet today, meaning the shim has not yet
reached the point where the registry itself would sanction deleting it.
