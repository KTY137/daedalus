# daedalus/ikarus_supervisor.py

> **SCC member.** Cycle edges are owned by the SCC dossier; this file covers the destination only.

Scope note: every search below was restricted to `daedalus`, `tests`, `tools`
explicitly (Grep `path=`), never the bare repo root, because
`.claude/worktrees/agent-*/` holds full copies of `daedalus/` and `tests/`
that would double-count importers if the search were unscoped.

## Identity

`C:\Users\Administrator\daedalus\daedalus\ikarus_supervisor.py`, 1101 lines
(measured: `wc -l`). It is the reusable Ikarus mission supervisor: compiles
caller-declared `PlannedItem`s into a `BuildSession`/`MissionContract` pair
and drives them through an injected `attempt_factory`, publishing an
append-only, hash-chained `StateLedger` projection revision by revision.

## Importers (MEASURED)

9 sites total, matching the lead's census (3 `daedalus/`, 6 `tests/`, 0 `tools/`).

**daedalus/ (3):**
- `daedalus/core.py:1244` — `from .ikarus_supervisor import MissionSupervisor`, inside `_try_ikarus` (function starts line 1200). **[deferred]**
- `daedalus/orchestration/missions/supervisor_projection.py:17` — `from daedalus.ikarus_supervisor import (MissionSupervisor, StateLedger, SupervisorRefused)`, module level.
- `daedalus/orchestration/missions/service.py:17` — `from daedalus.ikarus_supervisor import MissionSupervisor`, module level.

**tests/ (6):**
- `tests/test_bridge_restart.py:505` — `from daedalus.ikarus_supervisor import verify_state_ledger`, inside `test_leased_provider_completion_survives_crash_before_bridge_report` (function starts line 417). **[deferred]**
- `tests/test_canonical_execution_limit_policy.py:10` — `from daedalus import ikarus_supervisor as supervisor_module`, module level.
- `tests/test_canonical_execution_limit_policy.py:12` — `from daedalus.ikarus_supervisor import (...)`, module level.
- `tests/orchestration/test_ikarus_mission_integration.py:21` — `from daedalus.ikarus_supervisor import (MissionSupervisor, SupervisorRefused, verify_state_ledger)`, module level.
- `tests/test_ikarus_runtime_role.py:22` — `from daedalus.ikarus_supervisor import (...)`, module level.
- `tests/test_ikarus_supervisor.py:19` — `from daedalus.ikarus_supervisor import (...)`, module level.

2 of the 9 are deferred/function-scope (`core.py:1244`, `test_bridge_restart.py:505`); the other 7 are module level — matches the lead's "2 of 9" figure.

Two other tests/ hits were checked and are **not imports**: `tests/contracts/test_import_scc_hierarchy.py:26` holds `"daedalus.ikarus_supervisor"` only as a string literal inside the frozen `OLD_CROSS_DOMAIN_COMPONENT` set (SCC membership fixture, not a Python import), and `tests/orchestration/test_attempt_composition_hierarchy.py:226` / `tests/test_ikarus_runtime_role.py:985` read the module's own source text (`Path(...).read_text(...)`) for a static check, not an import.

**Dynamic/string references searched:** `importlib`/`__import__` sites across `daedalus/` (`Grep "importlib.util|__import__|daedalus\.ikarus_supervisor"` over `daedalus/`) — the only two hits inside `ikarus_supervisor.py` itself are string literals used as an `agent`/`operator` provenance tag (lines 475, 886), not a loader call; every other `importlib`/`__import__` site in the tree belongs to unrelated modules (`accelerators.py`, `ignition/*`, `gates/repository_write_classification.py`, `integrations/hermes/*`, `kernel/*`, `twin/extractors/*`). `pyproject.toml` has no `ikarus_supervisor` reference (checked, no match — no console_scripts entry point). `docs/architecture/import-boundaries.json` has no `ikarus_supervisor` reference (checked, no match — confirms it is not itself named in any boundary rule today). No `subprocess -m daedalus.ikarus_supervisor` or literal-string dynamic reference found anywhere in `daedalus/`, `tests/`, or `tools/`.

## Imports (MEASURED)

**Module-level, all `daedalus.*` (6), none stdlib/third-party is a `daedalus` re-export:**
- `daedalus/ikarus_supervisor.py:52` — `from .build import BuildSession, BuildTask, Wave, mission_id_for_session` → `daedalus.build` **[cycle]**
- `daedalus/ikarus_supervisor.py:53` — `from .limit_policy import ExecutionLimitPolicy` → `daedalus.limit_policy`
- `daedalus/ikarus_supervisor.py:54-58` — `from .ikarus_runtime_role import (INPROCESS_RUNTIME_ID, RuntimeRoleRegistry, RuntimeRoleSnapshot)` → `daedalus.ikarus_runtime_role`
- `daedalus/ikarus_supervisor.py:59-64` — `from .schemas import (MissionContract, ResourceBudget, derive_work_item_id, work_item_identity_sha256)` → `daedalus.schemas`
- `daedalus/ikarus_supervisor.py:65-70` — `from .spine.attempt import (GateResult, RunnerContext, TaskSpec, TaskSpecInvalid)` → `daedalus.spine.attempt` **[cycle]**
- `daedalus/ikarus_supervisor.py:71` — `from .spine.receipts import mission_contract_for_build_session` → `daedalus.spine.receipts`

**Stdlib (8), module level:** `hashlib`, `json`, `math`, `dataclasses.{dataclass,field}`, `datetime.{datetime,timezone}`, `pathlib.Path`, `types.MappingProxyType`, `typing.{Any,Callable,Mapping,Sequence}`.

**Deferred/function-scope: none.** Grepped the file body for indented `from`/`import` statements — zero hits. Every import in this module is module-level; there is no signal here that the cycle forced a deferred import inside `ikarus_supervisor.py` itself (unlike the `spine.picker`/`spine.receipts` deferred-import history the SCC test file documents for other members).

2 of the 6 `daedalus.*` imports are cycle edges (`.build`, `.spine.attempt`), confirmed against the 18-member SCC in `tests/contracts/test_import_scc_hierarchy.py` (`CURRENT_CROSS_DOMAIN_COMPONENT`, which lists `daedalus.ikarus_supervisor` and `daedalus.build`/`daedalus.spine.attempt` as co-members). `.limit_policy`, `.ikarus_runtime_role`, `.schemas`, `.spine.receipts` target modules **not** in that 18-member set, so those four edges are ordinary (non-cycle) dependencies.

## What it does

`MissionSupervisor` and `plan_mission` compile a caller-declared sequence of `PlannedItem`s (objective, role, target paths, optional runtime binding) into one deterministic `BuildSession`/`MissionContract` pair, revalidate that plan against drift before dispatching a single caller-injected `attempt_factory` per item, and publish every state transition as an immutable, hash-chained `StateLedger` revision under the caller's run directory. It owns no LLM call, no chat transcript, and no direct effect execution — attempt construction, workspace, and evaluator wiring are injected by the caller (`daedalus/orchestration/missions/service.py`), matching the module's own docstring claim to be "not a door" with "no module-level effect." Size: 1101 lines.

## Proposed destination

**`daedalus.orchestration`.**

Argument: every production (non-test, non-deferred-bridge) importer already lives under `daedalus/orchestration/missions/` (`service.py:17`, `supervisor_projection.py:17`), both module-level, both treating `MissionSupervisor` as the mission-driving coordinator that `WaveExecutor` (the real production executor per `service.py`'s own docstring) wraps for a disposable ledger projection. The module composes existing kernel/spine primitives (`BuildSession`, `MissionContract`, `TaskSpec`, `ExecutionLimitPolicy`) into caller-facing coordination rather than defining or owning any of them, which is exactly the orchestration layer's job per the master plan §7 ("who works, with which runtime, context, capabilities, budget"). `daedalus.orchestration` is not a rule source in `import-boundaries.json`, so this placement needs no allowlist exception.

Strongest counter-argument: `daedalus.core.py:1244` (`_try_ikarus`) also imports it directly, and `core.py` is itself in the same 18-module SCC — one could argue the module belongs closer to the kernel/spine end of that cycle since two of its own six imports (`.build`, `.spine.attempt`) are cycle edges into modules that are more kernel/spine-flavored (`kernel.attempt_execution`, `kernel.promotion`, `spine.attempt`, `spine.bootstrap`, `spine.picker`). This loses: the boundary rules already carry an explicit, named precedent against it — `spine-no-outer-layers` forbids `daedalus.ikarus` and `daedalus.ikarus_os` by name specifically because spine "cannot depend on product, orchestration, evaluator, provider, runtime, or interface implementations," and `ikarus_supervisor` is squarely an orchestration-shaped coordinator (injected `attempt_factory`, caller-owned role harnesses) even though it currently sits in the cycle. Checked concretely: if this module's own source prefix became `daedalus.kernel` or `daedalus.spine`, its own measured imports of `.build` (target `daedalus.build`, explicitly forbidden under `spine-no-outer-layers` and absent from `kernel-no-outer-layers`'s allowlist), `.schemas` (target `daedalus.schemas`, explicitly forbidden under both rules), and `.ikarus_runtime_role` (absent from both allowlists) would all be refused. `orchestration` is the only destination among the six candidates that accepts every one of this module's six measured `daedalus.*` imports without modification.

SCC-membership flag: `ikarus_supervisor` is one of the 18 modules in `CURRENT_CROSS_DOMAIN_COMPONENT` (measured via `tests/contracts/test_import_scc_hierarchy.py`, `nontrivial_components`). Two of its six imports (`.build`, `.spine.attempt`) are cycle edges. Whether it can move to `daedalus.orchestration` *independently* of its 17 cycle peers, or whether the cycle must be broken first (so the edge direction is settled before any member relocates), is a question for the SCC dossier — flagging, not resolving, per this packet's scope.

## Family note

Imports one `ikarus_*` sibling: `.ikarus_runtime_role` (line 54). No `ikarus_*` sibling imports `ikarus_supervisor` — the only other family hit anywhere in `daedalus/` is a docstring mention in `daedalus/ikarus_runtime_role.py:70` ("pre-existing `daedalus.ikarus_supervisor.RoleHarness` seam"), not an import statement. So `ikarus_supervisor` is a **leaf** in the family import graph: it consumes one sibling and is consumed by none of them (only by `orchestration/missions/*` and `core.py`, both outside the family).

Measured family internal edges (grepped `from .ikarus_` / `from daedalus.ikarus_` across every `ikarus_*.py`):
`ikarus_oneshot → ikarus_runtime_role`; `ikarus_effect_bridge → ikarus_oneshot, ikarus_tool_scope`; `ikarus_tool_scope → ikarus_oneshot`; `ikarus_supervisor → ikarus_runtime_role`; `ikarus_os → ikarus_act` (module-level) and `ikarus_os → ikarus_chat` (deferred, inside a function at line 828). `ikarus_runtime_events` and flat `daedalus/ikarus.py` show no edges to or from any other family member in this grep.

This is **two disconnected clusters**, not one family: {`ikarus_runtime_role`, `ikarus_oneshot`, `ikarus_effect_bridge`, `ikarus_tool_scope`, `ikarus_supervisor`} (runtime-binding/attempt-coordination cluster) versus {`ikarus_os`, `ikarus_act`, `ikarus_chat`} (a separate, OS/chat-shaped cluster), plus two singletons (`ikarus_runtime_events`, flat `ikarus.py`) with no measured edge into either cluster.

**Vote: SEVERAL destinations**, split by cluster rather than one `daedalus.ikarus` package — the two clusters have no measured import relationship and look semantically distinct (coordination/runtime-binding vs. OS/chat surface). Under either option `ikarus_supervisor` itself goes to `daedalus.orchestration`, per the destination argument above: as ONE package, that package's natural home is orchestration (dragged there by its own cluster's real callers); as SEVERAL, it stays in orchestration regardless of what happens to the `ikarus_os`/`ikarus_act`/`ikarus_chat` cluster.

## Boundary-rule verdict after the move

Evaluated against all four rules in `docs/architecture/import-boundaries.json`, both directions, for the chosen destination `daedalus.orchestration`:

- **kernel-no-outer-layers** (source `daedalus.kernel`): N-A-not-a-rule-source in either direction — `daedalus.orchestration` is not `daedalus.kernel`, and nothing in `daedalus.kernel` imports `ikarus_supervisor` (measured: zero hits for `ikarus_supervisor` anywhere under a `daedalus/kernel/` path in the importer sweep above).
- **runtimes-no-gates** (source `daedalus.runtimes`): N-A-not-a-rule-source — not a runtimes module, and no `daedalus.runtimes` importer of it was found.
- **spine-no-outer-layers** (source `daedalus.spine`): **vacuously CLEAN**, per the lead's measurement: the AST census of every module under `daedalus/kernel`, `daedalus/spine`, `daedalus/twin`, `daedalus/runtimes` shows those 142 layer-files import only `{budget, sensitivity, structcore, limit_policy, primary_tree, config, storage, atomic, mapping, offload, providers, resources}` among flat daedalus modules — `ikarus_supervisor` is absent from that set, so no spine (or kernel/twin/runtimes) module reaches it today, at any AST scope. Direction (b) is settled by that measurement, not by this dossier.
- **twin-no-outer-layers** (source `daedalus.twin`): N-A-not-a-rule-source / clean by the same lead measurement — no twin module imports `ikarus_supervisor`.

Direction (a) — `ikarus_supervisor`'s own imports, evaluated as if its *source* prefix were each rule's source: since the chosen destination `daedalus.orchestration` is not itself a rule source, this direction is **N-A** for the actual proposal. For completeness (this is what the counter-argument in "Proposed destination" checked): had it landed in `daedalus.kernel` or `daedalus.spine` instead, its own measured imports of `.build` (line 52, target `daedalus.build`) and `.schemas` (line 59, target `daedalus.schemas`) would be refused under both rules (explicitly forbidden or absent from both allowlists), and `.ikarus_runtime_role` (line 54, target `daedalus.ikarus_runtime_role`) would be refused as absent from both allowlists.

**One-line verdict: N-A-not-a-rule-source** (destination `daedalus.orchestration` is not bound by any of the four rules in either direction; direction (b) is additionally vacuously CLEAN per the lead's cross-layer measurement).

## Dead-code signals

Not dead code. 9 importers across 2 non-test files plus 6 test files is a real, exercised surface, and the 3 `daedalus/` importers are themselves live production code, not orphaned scaffolding:
- `daedalus/orchestration/missions/service.py` is the module whose own docstring calls itself "One internal entry point for an admitted build mission" — it imports `MissionSupervisor` at module level and constructs it as part of `run_mission`, the production wave-execution entry point.
- `daedalus/orchestration/missions/supervisor_projection.py`'s docstring: *"Disposable MissionSupervisor projection for canonical wave execution. The production executor remains `WaveExecutor`. These functions use the existing `MissionSupervisor` object only as the owner of a run directory and its existing chained `StateLedger` projection."* — confirms `MissionSupervisor` is deliberately kept alive as a ledger-projection owner even though `WaveExecutor` is the actual execution engine.
- `daedalus/core.py:1244`'s `_try_ikarus` imports it deferred, inside a `try:` block alongside `.build_exec` and `.orchestration`, to build a one-task session and supervisor for the bridge's ikarus lane — a live runtime path, not dead.

## Confidence

**High** for importer/import enumeration, dynamic-reference absence, and SCC/boundary-rule facts — all directly grepped/read and cross-checked against the lead's pinned numbers (9 importers 3/6/0, 2/9 deferred, 18-member SCC, vacuous (b)-clean claim), which matched exactly. **Medium** for the family "SEVERAL vs ONE" vote and the OS/chat cluster boundary, since that vote used one grep pattern (`from .ikarus_` / `from daedalus.ikarus_`) rather than a full AST sweep of every `ikarus_*` file's imports; a dynamic or re-exported edge between the two clusters (e.g. through `daedalus/ikarus.py` or `ikarus_runtime_events.py`, which showed zero edges in this grep) would raise confidence if ruled out by the family's own dossier owner.
