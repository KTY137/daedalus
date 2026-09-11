# SCC dossier: `daedalus.build` (`daedalus/build.py`)

Base: main @ 851ff43c (per task header). File is 567 lines [MEASURED, `wc -l`].

## Step 1 — Measured edges (raw AST probe)

Command: `.venv/Scripts/python.exe C:/Users/Administrator/scc-scratch/probe.py build` [MEASURED]

```
### OUTGOING edges FROM build to other SCC members
  -> kairos.scheduler           MODULE-LEVEL               in <module>
       daedalus/build.py:64   from .kairos.scheduler import KairosScheduler

### INCOMING edges INTO build from other SCC members
  <- build_exec                 MODULE-LEVEL               in <module>
       daedalus/build_exec.py:81   from .build import BuildSession, Wave, load_session, wave_path_conflicts
  <- core                       FUNCTION-LOCAL (deferred)  in _one_task_session
       daedalus/core.py:1017   from .build import (
  <- ikarus_supervisor          MODULE-LEVEL               in <module>
       daedalus/ikarus_supervisor.py:52   from .build import BuildSession, BuildTask, Wave, mission_id_for_session
```

### Verification against the source (Read, full file)

- `build.py:64` `from .kairos.scheduler import KairosScheduler` — module level, `<module>` scope, after the module docstring (ends line 52) and `from __future__ import annotations` (line 54). Not inside `TYPE_CHECKING`. Used at line 529: `foreman = KairosScheduler(project=project)` inside `plan_build`, purely to read `foreman.max_workers` and `foreman.active_agents` (lines 530–531) — module docstring itself states this ("Reuse Ikarus purely for its wave sizing + active_agents resolution... No spawning happens", lines 526–528). **Real, reachable, single call site, single instantiation, two attribute reads — not annotation-only** (there is no `KairosScheduler` type annotation anywhere in the file; the only use is the live instantiation).

This is `build`'s **only** outgoing SCC edge. Probe tool correctness confirmed — one edge out, matching the inherited context ("build has exactly ONE outgoing edge").

### Dynamic references (grep)

`importlib.import_module` / `__import__`: **none found** [MEASURED, `Grep` over the file, 0 matches]. No dynamic dispatch, no string literal naming another SCC member.

## Step 2 — What it actually does

`build.py` defines a deterministic, non-effectful planning layer that turns one feature objective into a multi-wave `BuildSession`: it calls `daedalus.kairos.decompose.decompose()` to split a feature into subtasks, `daedalus.router.route_task()` to assign each subtask an owning agent, `daedalus.categories.preset_for()` to derive that agent's lane/tier, and `assign_builder()` to pick `claude` (frontier) vs `ollama` (local bench) off the lane — then chunks the routed `BuildTask`s into `Wave`s bounded by `KairosScheduler(project=project).max_workers`. It defines the canonical identity binding for each task (`BuildSession.bind_work_items`, `mission_id_for_session`, `work_item_identity_sha256`) so that every task carries one deterministic `mission_id`/`work_item_id` pair matching the plan's `MissionContract -> WorkItems` chain (module docstring, lines 32–51), and raises `WorkItemIdentityError` if a re-plan would silently change a task's substance under an already-bound id (lines 306–367). `BuildSession.save()`/`load_session()` persist/reload a session snapshot to/from `runs/build/<slug>-<ts>.json` as JSON, with a best-effort (never-fails) call into `daedalus.bookkeeper.update()` afterward; the module writes to disk only through this one `save()` path and never drives a provider, writes to a repo checkout, or bypasses a lane gate (module docstring, line 24).

## Step 3 — Layer

**Verdict: `orchestration`.** Not mis-sited by role, though its current flat placement under `daedalus/` (rather than a future `daedalus/orchestration/`) is exactly the kind of location the target layout intends to formalize.

Justification: `build.py` is pure mission/work-item **decomposition and wave-scheduling state** — it has zero effect authority (no provider call, no repo write outside its own JSON snapshot, no policy/evidence/promotion logic) and is explicitly scoped by its own docstring as "planning *state around* the harness, not a replacement for it" (line 25) with execution deliberately deferred to `daedalus.build_exec`'s `WaveExecutor` (lines 27–30). It imports only `kairos.scheduler.KairosScheduler` (an orchestration-layer scheduler) for wave sizing, plus non-SCC modules `categories`, `kairos.decompose`, `router`, `schemas` — all orchestration/routing helpers, not kernel/spine/twin modules. It is imported by `build_exec` (the wave executor that actually dispatches through `KairosScheduler`), `core` (deferred, inside a task-session helper), and `ikarus_supervisor` (the top-level orchestration entry point) — three importers, all themselves orchestration-layer. Nothing in `build.py` touches `kernel.*` (policy/effects/promotion) or `spine.*` (ledger/killswitch) directly.

## Step 4 — Severance

### `-> kairos.scheduler` (MODULE-LEVEL, line 64)

Cheapest severance: **(b) callback / parameter injection.** Exactly 1 symbol crosses the edge (`KairosScheduler`), 1 instantiation site (`plan_build`, line 529), and only 2 attributes are actually read off the instance (`foreman.max_workers`, `foreman.active_agents`) — the module docstring itself already frames this as read-only reuse of two config values, not a structural dependency ("Reuse Ikarus purely for its wave sizing + active_agents resolution... No spawning happens"). The cheapest fix: give `plan_build(..., max_workers: int | None = None, active_agents: ... | None = None)` two optional parameters that default to constructing `KairosScheduler(project=project)` internally exactly as today (preserving current call sites with zero changes), while a caller that already holds a `KairosScheduler` (e.g. `build_exec` or `ikarus_supervisor`, both of which import `build` *and* transitively reach scheduler-shaped objects) can pass the two values directly and skip the edge. Because only 2 primitive-typed attributes cross (not the whole `KairosScheduler` API surface), a Protocol extraction is unnecessary ceremony here — plain parameter injection with a lazy-construct default is the smallest correct change, and it is a genuinely free-standing cut: nothing else in `build.py` references `KairosScheduler` or any other `kairos.*` symbol.

### Judgment: pure pass-through vs. real coupling point

**Verdict: near-pure pass-through, and the single edge is a trivially free cut** — but `build.py` is not a *content-free* pass-through module; it is a real, load-bearing planning module that happens to have almost no *coupling surface* into the rest of the SCC. The evidence: one outgoing edge, one call site, two primitive attribute reads, zero writes back into `kairos.scheduler`, and the module's own docstring already disclaims "no spawning happens" through this path. Cutting it via parameter injection (Step 4 above) collapses the SCC from 18 members to 17 [INHERITED], which is consistent with `build.py`'s measured incoming fan-in (3 importers: `build_exec`, `core`, `ikarus_supervisor`) being the actual reason it sits inside the SCC at all — `build` is coupled to the *cycle* through being depended-upon, not through what it itself depends on. This makes `build` a strong first-cut candidate: severing its one outgoing edge requires no design work (no Protocol, no registry, no merge argument), only a two-line signature change plus updating the one call site inside `plan_build`, and the governance test's own component-count assertion (Step 5) is the concrete instrument that would confirm the 18→17 collapse.

## Step 5 — Tests that pin this

Grep of `tests/` for direct `from daedalus.build import ...` / `from daedalus import build` / `import daedalus.build`: **9 files** [MEASURED] (a broader grep for the bare word `build` matched 13 files, but 4 of those — `test_ignition_gate1.py`, `test_loop.py`, `tests/contracts/test_spine_outer_ports.py`, and one more — match the generic English word "build" rather than importing the module, and are excluded below).

1. `tests/test_build.py` (185 lines [MEASURED]) — `from daedalus import build` (line 17) and `from daedalus.build import (BuildSession, ..., load_session, plan_build, ...)` (line 18). Classes/functions that would break: `AssignBuilderTests.test_local_lanes_stay_on_the_bench`, `AssignBuilderTests.test_claude_and_auto_lanes_go_frontier`, `PlanBuildShapeTests.test_produces_bounded_waves`, `PlanBuildShapeTests.test_each_task_carries_owner_category_lane_tier`, `PlanBuildShapeTests.test_frontier_vs_local_follows_the_category_lane`, `RoundTripTests.test_to_dict_from_dict_round_trips`, `RoundTripTests.test_persistence_round_trips_from_disk`, `RoundTripTests.test_persist_false_writes_nothing`, `SingleSubtaskTests.test_single_subtask_is_one_wave`, `BookkeeperIsolationTests.test_update_architecture_false_skips_bookkeeper`, `BookkeeperIsolationTests.test_persist_default_forwards_to_bookkeeper` (11 test functions). Notably these tests already `patch.object(build, "decompose", ...)`, `patch.object(build, "route_task", ...)`, `patch.object(build, "preset_for", ...)` (lines 65–67) — i.e. they already treat `build`'s non-SCC dependencies as injectable, which supports Step 4's parameter-injection approach for `KairosScheduler` as consistent with this file's existing test style.
2. `tests/test_build_vocabulary.py` (348 lines [MEASURED]) — `from daedalus.build import (...)` (line 31). Classes: `WorkItemIdentity`, `MissionFromSession`, `AttemptCarriesTheMission`, `NoSecondKernelNoun` (4 test classes covering the `mission_id`/`work_item_id` identity-binding logic in `build.py`, lines 306–367).
3. `tests/test_assurance_hardening_build.py` (136 lines [MEASURED]) — `from daedalus.build import (...)` (line 28). Test functions: `test_binding_an_unchanged_plan_is_a_no_op`, `test_a_re_planned_task_cannot_keep_a_stale_id`, `test_reordering_the_plan_is_also_a_re_plan`, `test_clearing_the_id_is_how_a_caller_re_plans_deliberately`, `test_a_task_cannot_serve_two_missions`, `test_a_snapshot_written_before_the_digest_existed_reloads_and_re_binds` (6 functions), directly exercising `bind_work_items`/`WorkItemIdentityError`.
4. `tests/orchestration/test_run_mission.py:14` — `from daedalus.build import BuildSession, BuildTask, Wave, WorkItemIdentityError`.
5. `tests/orchestration/test_ikarus_mission_integration.py:13` — `from daedalus.build import BuildSession, BuildTask, Wave`.
6. `tests/test_loop_lease.py:26` — `from daedalus.build import BuildTask, Wave`.
7. `tests/test_loop_spend_refused.py:54,261` — `from daedalus.build import BuildTask, Wave` (module level) and `from daedalus.build import BuildSession` (deferred, inside a test function) — 2 matching lines in this one file.
8. `tests/test_wave_spend_reservation_concurrency.py:26` — `from daedalus.build import BuildTask, Wave`.
9. `tests/test_wave_spend_reservation.py:44` — `from daedalus.build import BuildTask, Wave`.

Plus the governance test, which pins the SCC structure `build` participates in rather than its public symbols directly:

10. `tests/contracts/test_import_scc_hierarchy.py:19` — `"daedalus.build"` listed in `OLD_CROSS_DOMAIN_COMPONENT`. `test_observation_contract_breaks_the_next_cross_domain_scc` (line 198) asserts exact `CENSUS_EDGES` count, component count/max-size, and a SHA-256 digest of the component partition — severing `build -> kairos.scheduler` per Step 4 is exactly the kind of change this test is built to catch (and, per the inherited context, is expected to collapse the SCC 18→17, changing `len(components)`/`max(map(len, components))`/the hash, all three of which must be re-measured and updated deliberately).

**Counts: 9 test files with a direct `daedalus.build` import (11 matching import lines across them, since 2 files have 2 lines each), ~22 named test functions/methods enumerated above across the 3 files with full class/function grep, plus 1 governance test file whose SCC-structure assertions are also implicated.**
