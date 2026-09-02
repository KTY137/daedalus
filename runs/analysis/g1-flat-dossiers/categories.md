# daedalus/categories.py

## 1. Size and shape

170 lines (`daedalus/categories.py:1-171`).

- 0 classes, 10 functions: `_write_dir_for` (32), `_write_path_for` (39),
  `_read_categories_file` (43), `validate` (53), `normalize` (75), `load`
  (88), `get` (111), `update` (115), `preset_for` (138),
  `get_categories_joined` (150).
- No module-level state and no singleton objects. Module-level constants
  only: `CATEGORIES_PATH = ROOT / "agents" / "categories.json"`
  (`categories.py:26`, a `Path` built from the imported `router.ROOT`
  constant — path construction, not I/O), `LANES` tuple (27), two compiled
  regexes `_ID_RE`/`_COLOR_RE` (28-29).
- No module-level side effects at import time: no file reads, no env reads,
  no registry mutation, no network calls, no directory creation. All I/O
  (`_read_categories_file`, `load`, `update`) is deferred to call time inside
  functions. `update()` is the only writer and it targets
  `<repo_root>/.agentenv/categories.json`, never the shipped
  `agents/categories.json` (`categories.py:32-36`, enforced by raising
  `ValueError` when `repo_root` is falsy).

## 2. What it does

It defines and validates a small role-category taxonomy (id, name, icon,
color, lane, tier, triggers) that groups agent roles for Mission Control's
UI and lets `preset_for` suggest a `{lane, tier}` default for a role from its
`category` field. `load()` merges the shipped global seed
(`agents/categories.json`, read via `resources.read_builtin_text`) with an
optional per-repo `.agentenv/categories.json` override by id, and `update()`
writes only the per-repo override after `validate()`/`normalize()`.
`get_categories_joined()` joins categories with the agent roles tagged into
them (via `router.load_agents`) for `core.get_categories`'s dashboard
payload; the module-level docstring states explicitly that none of this
overrides the authoritative lane gate in `provider_router`/
`core.process_bridge_payload`.

## 3. Who imports it (MEASURED)

Searched `daedalus/`, `tests/`, `tools/`, `apps/`, `docs/`, `.claude/` for
`from daedalus.categories import`, `from daedalus import categories`,
`import daedalus.categories`, `from .categories import`, `from . import
categories`, `importlib.import_module("daedalus.categories")`, and the bare
string `"daedalus.categories"`. Command used:
`grep -rn "\bcategories\b" --include="*.py" daedalus tests tools apps scripts docs .claude`
filtered to actual import statements.

TOTAL real (non-vendored, non-worktree) importer files: **8** — 4 production,
4 test.

Production (all under `daedalus/`, none currently classified into an
existing package — all "flat" or SCC-owned):

- `daedalus/build.py:62` — `from .categories import preset_for` —
  **MODULE-LEVEL**. `build.py` is one of the 11 SCC-owned modules (do not
  classify; edge recorded).
- `daedalus/cli.py:456` — `from . import categories as cats` — **DEFERRED**
  (inside a CLI command function body). `cli.py` is flat/unclassified
  (destined for `interfaces/cli`, not yet moved).
- `daedalus/core.py:911` — `from . import categories as cats` — **DEFERRED**
  (inside `get_categories()`). `core.py` is SCC-owned.
- `daedalus/loop.py:1054` — `from .categories import preset_for` —
  **DEFERRED** (inside a method, 8-space indent). `loop.py` is
  flat/unclassified.

Test (all under `tests/`, all **MODULE-LEVEL**):

- `tests/test_categories.py:6` — `from daedalus import categories as cats`
- `tests/test_categories_integration.py:20` — `from daedalus import
  categories as cats`
- `tests/test_packaged_resources.py:9` — `from daedalus import
  agents_registry, categories, config, gui_catalogue, router`
- `tests/test_web_api.py:418` — `from daedalus import categories` —
  **DEFERRED** (inside a test method body, 8-space indent), despite the file
  also having top-level references to the module name in comments at line
  395.

Vendored/duplicate copies (not counted above; excluded per scope — build
artifacts, not source): `apps/web/src-tauri/backend/_internal/daedalus/*`
and `apps/web/src-tauri/target/{debug,release}/backend/_internal/daedalus/*`
mirror `build.py`/`cli.py`/`core.py`/`loop.py`'s import of `categories`
identically (PyInstaller-bundled backend copies), and 5 `.claude/worktrees/
agent-*` trees mirror the same 4 production + up-to-4 test import sites
(other agents' isolated worktrees of this same repo, not distinct call
sites).

Per-layer breakdown of the 4 production importers: SCC-owned = 2
(`build.py`, `core.py`), flat/unclassified = 2 (`cli.py`, `loop.py`),
existing-package = 0.

## 4. What it imports (MEASURED)

From `daedalus/categories.py:15-24`:

- `.agents_registry` (`MODEL_TIERS`) — `categories.py:22` — **MODULE-LEVEL**.
  `agents_registry.py` is flat/unclassified (not in foundation, not SCC, not
  an existing package).
- `.resources` (`read_builtin_text`) — `categories.py:23` — **MODULE-LEVEL**.
  `resources` is an existing real package (`daedalus/resources/`), not yet
  mapped into the 8-layer target taxonomy given for this exercise.
- `.router` (`ROOT`, `load_agents`) — `categories.py:24` — **MODULE-LEVEL**.
  `router.py` is flat/unclassified.

Third-party: none beyond stdlib (`json`, `re`, `pathlib.Path`,
`typing.Any`).

No SCC-owned module (`build`, `build_exec`, `core`, `doctor`, `file_bridge`,
`health`, `ikarus_supervisor`, `offload`, `progress`, `progress_sources`,
`status`) is imported by `categories.py` itself.

## 5. Proposed destination

**orchestration**. Confidence: **medium**.

Argument from measured edges: `categories.py` has zero kernel/spine/twin/
runtime semantics — it never touches Mission, Attempt, Evidence, EffectLease,
or a canonical event spine. Its own outgoing edges (`agents_registry`,
`router`) are both flat modules that themselves define agent-role dispatch
concepts (`router.load_agents`, `router.route_task` is imported by
`claude_bridge.py`, a sibling module in this same dossier set). Its incoming
edges are dominated by workload-orchestration consumers: `build.py` (SCC,
build-wave task assignment) and `loop.py` (agent build loop, calls
`preset_for` to default a role's `{lane, tier}` before dispatch) both use it
to pre-fill dispatch defaults for agent roles — this is orchestration-layer
configuration, not a kernel/spine/twin primitive. `core.py`'s use
(`get_categories`) is a dashboard read that itself is SCC-owned and out of
scope. `cli.py`'s use is a thin command wrapper over the same `load/get/
update` functions — normal interfaces-calls-orchestration direction, not
evidence against the orchestration placement.

Evidence that would change my mind: if `router.py` and `agents_registry.py`
(its two `daedalus.*` dependencies) are placed in `foundation` or
`interfaces/*` instead of `orchestration` by the modules' own leads, that
would pull `categories.py` toward matching them instead — file a coordinated
placement rather than deciding in isolation. Also, if `cli.py`'s categories
subcommand turns out to be the *only* live production consumer once
`build.py`/`loop.py`/`core.py` are themselves reclassified elsewhere, a
`foundation` or `interfaces/cli`-adjacent placement would become more
defensible.

## 6. Boundary-rule check after the move

`docs/architecture/import-boundaries.json` (read in full) has no rule with
`source_prefixes` containing `daedalus.orchestration`, so moving
`categories.py` under `daedalus.orchestration.*` is not itself a rule
*source* today — only `kernel-no-outer-layers`, `spine-no-outer-layers`, and
`twin-no-outer-layers` forbid importing `daedalus.orchestration` as a
*target*.

(a) Would `categories.py`'s own imports be refused under `orchestration`?
No rule constrains `daedalus.orchestration`'s own outbound imports (there is
no `orchestration-no-*` rule), so a move to `orchestration` refuses nothing
of its own 3 imports (`agents_registry`, `resources`, `router`).

(b) Does any current rule name `categories`/`daedalus.categories` by prefix?
No — grepped the full JSON contents above; no `forbidden_target_prefixes` or
`allowed_target_prefixes` entry mentions `categories` in any of the 4 rules.
Nothing breaks or is unblocked specifically by this module's move; only the
3 rules matter, and none reference it today either as source or target.

(c) N/A at the proposed confidence: the destination is `orchestration`, not
kernel/spine/twin, so the allowlist enumeration rule does not apply. If
forced into `kernel`/`spine`/`twin` instead (not recommended — see §5), its
3 imports would ALL be refused: `agents_registry`, `resources`, and `router`
are each flat modules not present in any of the three allowlists
(`kernel-no-outer-layers` allows only atomic/budget/config/limit_policy/
offload/primary_tree/sensitivity/spine/storage/twin; `spine-no-outer-layers`
allows only atomic/budget/config/kernel/limit_policy/mapping/sensitivity/
structcore; `twin-no-outer-layers` allows only kernel/spine/structcore) — so
none of `categories.py`'s 3 edges would clear any of the three allowlists.

## 7. Dead-code signals

Not applicable as a verdict — importers = 8 (4 production, 4 test), well
above zero, so this is squarely **LIVE**. Verified via §3's measured import
list; also directly exercised by `tests/test_categories.py`,
`tests/test_categories_integration.py`, `tests/test_web_api.py`'s
round-trip test (`categories.load()/update()/get()` at
`tests/test_web_api.py:418-431`), and `tests/test_packaged_resources.py`
(shipped-resource drift check). No candidate-delete signal found.
