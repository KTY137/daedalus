# daedalus/cli.py

## 1. Size and shape

1262 lines (`wc -l daedalus/cli.py`).

- Classes: 0.
- Functions: 18 `def` (16 top-level, plus 2 nested `def common(p)` closures inside
  `_agents` at cli.py:373 and `_categories` at cli.py:464). Top-level:
  `_spawn`(107), `_build`(170), `_init`(214), `_projects`(224),
  `_accelerators`(234), `_context`(277), `_agents`(359), `_categories`(449),
  `_drafts`(506), `_council`(557), `_council_pr`(758), `_diff_paths`(826),
  `_canary`(842), `_claude_crew`(1016), `_governance`(1048), `main`(1093).
- Module-level state: none beyond `_USAGE = __doc__` (cli.py:104), a plain
  string alias of the module docstring used for `-h`/`--help`/no-args output
  (cli.py:1096). No singleton, no registry, no mutable module dict.
- Import-time side effects: **none measured**. `from __future__ import
  annotations` and `import sys` are the only module-level imports (cli.py:100,
  102). Every `daedalus.*` import — 41 of them — is inside a function body
  (see §4); none run at import time. No file reads, no env reads, no network,
  no registry mutation happens merely by `import daedalus.cli`. The only
  runtime side effects (`.env` load via `dotenv.load()`, spend-guard
  installation via `budget.install_process_guard()`) happen inside `main()`
  when it is actually called (cli.py:1123-1136), not at import.

Subcommands registered in `main()`'s `argv[0]` dispatch (cli.py:1138-1258),
cross-checked 1:1 against the module docstring's usage block (cli.py:1-98) —
all 36 match, none orphaned either direction:
`doctor, offload, spawn, build, ikarus, dctx, context, metrics, benchmark,
status, health, project-memory, drill, dashboard, models, accelerators,
squads, watcher, review-diff, projects, agents, categories, council, canary,
claude-crew, drafts, selftest, tokens, bookkeeper, map, web, enforce, improve,
init, governance, fault-attestation, fixture-fault-collect,
fixture-fault-attestation`.

## 2. What it does

`cli.py` is the single console-script entry point
(`daedalus = daedalus.cli:main` in `pyproject.toml:78`) that reads
`sys.argv[1]` as the subcommand name, rewrites `sys.argv` so each subparser
sees a clean argv, and dispatches to one of 36 subcommands, each lazily
imported only when selected so an unrelated subcommand never pays another
subsystem's import cost. Before any subcommand runs, `main()` unconditionally
loads `.env` through `dotenv.load()` (refusing to proceed if a tracked `.env`
looks like a leaked secret) and installs the process-wide spend guard via
`budget.install_process_guard()`, making this file the one chokepoint every
downstream vendor call in the process is metered through. A minority of
subcommands (`spawn`, `build`, `init`, `projects`, `accelerators`, `context`,
`agents`, `categories`, `drafts`, `council`/`council_pr`, `canary`,
`claude-crew`, `governance`) are implemented directly in this file with their
own `argparse` subparsers; the rest are one-line redirects into another
module's own `main()`.

## 3. Who imports it (MEASURED)

Searched `daedalus/`, `tests/`, `tools/`, `apps/`, `scripts/`, `docs/`,
`.claude/`, plus repo root, for all required forms (`from daedalus.cli
import`, `from daedalus import cli`, `import daedalus.cli`, `from .cli
import`, `from . import cli`, `importlib.import_module("daedalus.cli"...)`,
bare-string `"daedalus.cli"`).

**TOTAL real Python-import edges: 2** (both test-only, both DEFERRED). Plus
**one bare-string registry reference** (module-level) and **several
subprocess invocations** that are not Python import edges at all.

Per-layer breakdown:

- **daedalus/ production**: **0** Python-level importers. Nothing under
  `daedalus/` does `import daedalus.cli` / `from .cli import ...` /
  `from . import cli` targeting this file. `daedalus/cli.py` is a pure leaf —
  the entrypoint, not a dependency of anything else in the product. Confirmed
  by grepping the whole tree for every listed form; the only `from .cli
  import main` hits are `daedalus/chip_design/__main__.py:1` and
  `daedalus/interfaces/bridge/__init__.py:3`, which resolve to **their own**
  local `cli.py` files (`daedalus/chip_design/cli.py`,
  `daedalus/interfaces/bridge/cli.py`) via relative import inside those
  packages — not this file. (See §5 for why these sibling CLIs matter to the
  destination question.)
- **tests/** (both DEFERRED, inside test functions):
  - `tests/test_cli_token_verb.py:88` — `from daedalus.cli import main as cli_main`
    (inside a test function; drives `cli.main()` end-to-end for the `tokens`
    verb).
  - `tests/test_council_session.py:669` — `from daedalus.cli import _diff_paths`
    (inside a test function; unit-tests the diff-path extractor used by
    `_council`).
- **daedalus/spine (bare-string registry, MODULE-LEVEL)**:
  `daedalus/spine/effect_boundary.py:169` and `:179` register
  `target="daedalus.cli:main"` and `anchors=(GuardAnchor("daedalus.cli:main",
  "install_process_guard"),)` inside the module-level `ENTRYPOINTS` tuple
  (`EntrypointSpec(id="cli.daedalus", surface=Surface.CLI, ...)`,
  effect_boundary.py:166-180). This is a **string label** in a Gate-0
  entrypoint inventory, not a Python `import` statement — the module doesn't
  actually import `daedalus.cli`, it names it as the audited surface. Notable
  because it is already tagged `surface=Surface.CLI` in this repo's own
  effect-boundary inventory.

Non-import references (recorded because the task asks to cover bare strings
and every reasonable form, but these are process invocations, not Python
import edges, so they do not appear in the boundary-checker's AST walk):

- `pyproject.toml:78` — `daedalus = "daedalus.cli:main"` console-script entry
  (the actual production reach path).
- `daedalus/spine/bootstrap.py:184` — `subprocess.run([sys.executable, "-m",
  "daedalus.cli", "map"])`.
- `tools/system_check.py:183,396,664` — spawns `python -m daedalus.cli ...`
  as a subprocess repeatedly (acceptance harness).
- `tools/gui_check.py:200`, `tools/watchdog.py:505` — same subprocess pattern
  in prose/list form.
- `daedalus/bootstrap_prompt.py:37-38`, `daedalus/doctor.py:128` — docstring/
  print-string examples of the shell command, not code.
- `.vscode/tasks.json`, `vscode-agent-env/extension.js` — VS Code task/
  extension configs that shell out to `python -m daedalus.cli ...`; not
  Python.
- `docs/inventory/2026-08-21/preruling/reachability.json`,
  `docs/archive/swarm-2026-07-30/census/SYNTH-claims.md` — historical
  inventory artifacts mentioning the module name; not live references.
- `.claude/agents/docs-dev.md:16`, `.claude/watchdog/docs-sweep-prompt.md:22`,
  and their worktree copies — prose telling an agent which command to run;
  not code.
- `experiments/forest_v2/tensor_embeddings/__main__.py:3` and
  `experiments/forest_v2/s10_kill/test_s10_kill.py:991,998,1007,1016,1025` —
  `from .cli import main`, but these resolve to **their own** local
  `experiments/forest_v2/.../cli.py` files, not `daedalus/cli.py`. Excluded.

## 4. What it imports (MEASURED)

All 41 `daedalus.*` import statements in this file are **DEFERRED**
(function-scoped); there are zero module-level `daedalus.*` imports. No
third-party imports anywhere in the file (only stdlib: `sys`, `argparse`,
`json`, `re`, `dataclasses`, `pathlib`, `subprocess`).

Grouped by target's current layer/package, with counts:

- **SCC-owned (8 edges, do not classify, record only)**: `.build` (135, 177),
  `.build_exec` (136), `.core` (1065), `.doctor` (1139), `.offload` (1141),
  `.status` (1160), `.health` (1162).
- **foundation (2 edges)**: `.config` (216), `.budget` (1134).
- **existing package `kairos` (8 edges)**: `.kairos.scheduler` (112, 1147),
  `.kairos` (512, drafts), `.kairos.control` (1178, 1180, 1184, 1186, 1188 —
  `main_dashboard`, `main_models`, `main_squads`, `main_watcher`,
  `main_review_diff`).
- **existing package `orchestration` (2 edges)**: `.orchestration` (137,
  `run_mission`), `.orchestration.execution` (1222, `attempt_ports`,
  `picker_evaluation_ports`).
- **existing package `council` (4 edges)**: `.council` → `session` (571),
  `vendors` (572), `publish` (771), `canary` (853).
- **existing package `structcore` (2 edges)**: `.structcore.churn` (283,
  `co_change_pairs`), `.structcore.index` (284, `cached_index`).
- **existing package `memory` (1 edge)**: `.memory.projection_worker` (1164).
- **existing package `mapping` (1 edge)**: `.mapping.render` (1216).
- **existing package `spine` (1 edge)**: `.spine.picker` (1226).
- **existing package `runtimes` (3 edges)**:
  `.runtimes.fault_attestation_issuer` (1241),
  `.runtimes.fixture_fault_collector` (1246),
  `.runtimes.fixture_fault_attestation_issuer` (1254).
- **flat module `context_plan` (the sibling module in this packet, 1 edge)**:
  `.context_plan` (281, `plan_context`).
- **other flat modules, unclassified elsewhere (16 edges)**: `.projects`
  (113, 178, 282, 366, 457, 1023 — 6 call sites), `.accelerators` (238),
  `.agents_registry` (365), `.categories` (456), `.claude_detect` (1022),
  `.dotenv` (1123), `.dctx` (1149), `.metrics` (1153), `.benchmark` (1155),
  `.selftest` (1204), `.token_monitor` (1212), `.bookkeeper` (1214),
  `.web_api` (1218), `.enforce` (1220).

Full file:line list (all DEFERRED):
```
112 .kairos.scheduler   113 .projects
135 .build              136 .build_exec        137 .orchestration
177 .build              178 .projects
216 .config
225 .projects
238 .accelerators
281 .context_plan       282 .projects          283 .structcore.churn      284 .structcore.index
365 (. import agents_registry)   366 .projects
456 (. import categories)        457 .projects
512 .kairos (drafts)
571 .council (session)  572 .council (vendors)
771 .council (publish)
853 .council (canary)
1022 .claude_detect     1023 .projects
1065 .core
1123 .dotenv
1134 .budget
1139 .doctor            1141 .offload          1147 .kairos.scheduler
1149 .dctx
1153 .metrics           1155 .benchmark
1160 .status            1162 .health           1164 .memory.projection_worker
1178 .kairos.control    1180 .kairos.control   1184 .kairos.control
1186 .kairos.control    1188 .kairos.control
1204 .selftest
1212 .token_monitor     1214 .bookkeeper       1216 .mapping.render
1218 .web_api           1220 .enforce
1222 .orchestration.execution
1226 .spine.picker
1241 .runtimes.fault_attestation_issuer
1246 .runtimes.fixture_fault_collector
1254 .runtimes.fixture_fault_attestation_issuer
```

## 5. Proposed destination

**`interfaces/cli`** (new subpackage — `daedalus/interfaces/` currently has
`bridge/`, `desktop/`, `http/` but no `cli/`, so this is a proposal to create
it).

Evidence, from measured edges, not the name:

- It is the sole `daedalus` console-script target
  (`pyproject.toml:78`, `daedalus = "daedalus.cli:main"`) — the actual product
  surface a human or script invokes.
- It has **zero production Python importers** (§3) — nothing in the product
  depends on it as a library; it exists to be invoked, not imported. That is
  the textbook shape of an interface/entrypoint module, not a service module.
- The repo's own Gate-0 effect-boundary inventory already labels it
  `surface=Surface.CLI` (`daedalus/spine/effect_boundary.py:167`), independent
  of this dossier.
- **There are already two sibling CLI surfaces living inside their owning
  packages**: `daedalus/chip_design/cli.py` (its own console script,
  `daedalus-chip = daedalus.chip_design.cli:main`) and
  `daedalus/interfaces/bridge/cli.py` (the File Bridge's own parser/dispatch
  module, already under `interfaces/bridge/`). Both establish the convention
  "a CLI surface lives inside `interfaces/<surface>/` or inside the package it
  fronts" — `daedalus/cli.py` is the one generic top-level harness CLI that
  has no package of its own yet, which is exactly the gap `interfaces/cli/`
  would close. There is also `daedalus/structcore/__main__.py` (`python -m
  daedalus.structcore`), a third, narrower CLI surface scoped to one package —
  not a reason to route this file elsewhere, but confirms "more than one CLI
  surface" as the task flagged to check for.
- Its own imports touch **every** layer as a lazy dispatcher (kairos,
  orchestration, council, structcore, memory, mapping, spine, runtimes, and
  the SCC-owned build/build_exec/core/doctor/offload/status/health) — a shape
  that is only legitimate for a true top-level entrypoint sitting outside the
  kernel/spine/twin/runtimes trust boundaries, never for a module those
  layers could plausibly depend on.

Confidence: **high**. What would change my mind: if a future packet decides
the harness CLI's argument-parsing/dispatch logic should be split from its
`main()` install-guard responsibility, part of this file (the guard
installation call, cli.py:1123-1136) might belong closer to
`spine`/`budget` instead — but that is a within-file split, not a different
destination for the dispatcher itself.

**Is this really two things fused?** Partially. `main()`'s first ten lines
(cli.py:1101-1136 — load `.env`, install the spend guard) are policy/kernel
concerns riding along in an interface file; everything else is pure
argv-to-handler dispatch. If a future packet wants a cleaner boundary, the
guard-install call could be pulled one level down into a
`interfaces.cli.bootstrap()` helper that `main()` calls, so the interface
layer still owns the *call site* (defense in depth — an entrypoint that
forgets to call it is still a bug) without the guard's *policy* itself living
in `interfaces/`. Not required for this move; noted as an opportunity, not a
blocker.

## 6. Boundary-rule check after the move

Read `docs/architecture/import-boundaries.json`. Only `kernel`, `spine`,
`twin`, `runtimes` have rules; there is **no `interfaces`-sourced rule** at
all today.

**(a) Would any of cli.py's own imports be refused under `interfaces/cli`?**
No — there is no rule with `source_prefixes` matching `daedalus.interfaces`
(or `daedalus.interfaces.cli`), so nothing is refused. This is a real
constraint check, not a formality: if this file were hypothetically moved to
`kernel`, `spine`, or `twin` instead, it would **fail immediately and
massively** — `kernel-no-outer-layers` forbids `daedalus.orchestration`,
`daedalus.providers`, `daedalus.runtimes`, `daedalus.kairos` (all imported
here); `spine-no-outer-layers` forbids `daedalus.build`, `daedalus.build_exec`,
`daedalus.core`, `daedalus.kairos`, `daedalus.offload`,
`daedalus.orchestration`, `daedalus.runtimes` (all imported here, at cli.py:
135,136,112,1065,512,1147,178/366/457 etc.,1141,137/1222,1241/1246/1254); and
`twin-no-outer-layers` forbids `daedalus.kairos`, `daedalus.orchestration`,
`daedalus.providers`, `daedalus.runtimes` likewise. That cli.py cannot live in
any of the three constrained layers is itself confirmatory evidence for
`interfaces/cli` (or `orchestration`, which is also unconstrained) as the only
viable destinations.

**(b) Does any current rule name this module by prefix?** No rule's
`forbidden_target_prefixes` or `allowed_target_prefixes` names `daedalus.cli`
or `daedalus.interfaces.cli` anywhere. Nothing breaks or is unblocked by the
move at the rule-text level. (The `spine-no-outer-layers` rationale prose
*discusses* `daedalus.cli:main` as an anchor id inside
`effect_boundary.py`'s own `ENTRYPOINTS` data — that is a different file's
string content, not this checker's rule set, and is untouched by where
`cli.py` physically lives as long as the string keeps matching the module's
importable dotted path. If the physical move changes the importable path from
`daedalus.cli` to `daedalus.interfaces.cli`, **`effect_boundary.py:169,179`
must be updated in the same packet** — the console-script entry
(`pyproject.toml:78`) needs the same treatment. This is a real, mechanical
follow-up cost of the move, separate from the import-boundary checker.)

**(c) Allowlist exposure if landed in kernel/spine/twin?** Not applicable —
this move targets `interfaces/cli`, not those three layers. (See (a) for why
those destinations are non-starters regardless.)

**(d) `interfaces` as SOURCE is unconstrained — explicitly.** No rule in
`import-boundaries.json` restricts what `daedalus.interfaces.*` may import.
Moving `cli.py` there does **not** launder anything: cli.py's SCC-owned edges
(`build`, `build_exec`, `core`, `doctor`, `offload`, `status`, `health`) and
its currently-forbidden-elsewhere edges (`orchestration`, `providers`-adjacent
`runtimes`, `kairos`) were **already unconstrained** at cli.py's present flat
location — no rule names `daedalus.cli` as a source today, so the move changes
enforcement exposure for this file from "unconstrained" to "unconstrained,"
not from "constrained" to "unconstrained." Nothing today refuses these edges
before the move; nothing refuses them after. The move is boundary-neutral by
construction, which is the correct outcome for relocating a true top-level
entrypoint.

## 7. Dead-code signals

Not dead. **LIVE.**

- Zero *production* Python importers (§3) is expected and correct for a
  console-script entrypoint, not a red flag — the promised reader is
  `pyproject.toml:78`'s `[project.scripts]` entry, which `pip install -e .`
  turns into an actual `daedalus` executable on `PATH`. That is the
  "promised reader" the dead-code protocol asks to check for, and it exists
  and is wired.
- Confirmed further live via: (1) `daedalus/spine/effect_boundary.py`'s
  Gate-0 `ENTRYPOINTS` inventory naming it as the guarded `Surface.CLI`
  target with `wiring=Wiring.LOCAL_GUARDS`; (2) at least 6 distinct
  subprocess call sites across `tools/system_check.py`,
  `daedalus/spine/bootstrap.py` that shell out to `python -m daedalus.cli
  ...` as part of the acceptance harness and `daedalus map` self-generation;
  (3) two tests (`tests/test_cli_token_verb.py`,
  `tests/test_council_session.py`) that import and drive it directly; (4)
  `git log` shows continuous commits on this file since 2026-07-05
  (`git log --diff-filter=A --format=%ad -- daedalus/cli.py` → first added
  2026-07-05) through the current HEAD, with no removed-consumer signal.
- Searched for the dynamic/bare-string form (`grep -rn "daedalus\.cli"`
  across the whole tree, not just `.py`) — every hit is either the
  console-script entry, the `effect_boundary.py` registry string, a
  subprocess invocation, or prose documentation; no orphaned reference.

**Registered-subcommand reachability**: all 36 subcommands named in the
module docstring (cli.py:1-98) have a matching `elif cmd == "...":` branch in
`main()` (cli.py:1138-1258), and every branch resolves to a real, importable
target (checked by name against the corresponding module/function existing in
the tree). **No unreachable subcommand handler found.**

Label: **LIVE**.
