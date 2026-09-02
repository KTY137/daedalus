# SCC dossier: `core` (daedalus/core.py)

Base revision: main @ 74008fab (per task header; working tree also observed on
`wip/g1-freeze-2026-08-31`, file content identical for `daedalus/core.py` at
time of read). File length: 1507 lines [MEASURED, `wc -l`].

## Measured edges (raw AST probe)

Command:
`C:/Users/Administrator/daedalus/.venv/Scripts/python.exe C:/Users/Administrator/scc-scratch/probe.py core`

Raw output:

```
### OUTGOING edges FROM core to other SCC members
  -> status                     MODULE-LEVEL               in <module>
       daedalus/core.py:19   from .status import collect_status
  -> file_bridge                FUNCTION-LOCAL (deferred)  in queue_task
       daedalus/core.py:931   from .file_bridge import enqueue
  -> kairos.scheduler           FUNCTION-LOCAL (deferred)  in plan_ikarus
       daedalus/core.py:960   from .kairos.scheduler import KairosScheduler
  -> doctor                     FUNCTION-LOCAL (deferred)  in _availability_from_doctor
       daedalus/core.py:976   from .doctor import check
  -> build                      FUNCTION-LOCAL (deferred)  in _one_task_session
       daedalus/core.py:1017   from .build import (
  -> kairos.scheduler           FUNCTION-LOCAL (deferred)  in _configure_report
       daedalus/core.py:1443   from .kairos.scheduler import KairosScheduler
  -> spine.picker               FUNCTION-LOCAL (deferred)  in _head_sha_safe
       daedalus/core.py:487   from .spine.picker import _head_sha
  -> spine.bootstrap            FUNCTION-LOCAL (deferred)  in _gov_discrimination
       daedalus/core.py:517   from .spine.bootstrap import (DISCRIMINATION_REL_PATH, KILL_RATE_FLOOR,
  -> kairos.scheduler           FUNCTION-LOCAL (deferred)  in _try_ikarus
       daedalus/core.py:1218   from .kairos.scheduler import KairosScheduler
  -> build_exec                 FUNCTION-LOCAL (deferred)  in _try_ikarus
       daedalus/core.py:1243   from .build_exec import EffectBounds, WaveExecutor
  -> ikarus_supervisor           FUNCTION-LOCAL (deferred)  in _try_ikarus
       daedalus/core.py:1244   from .ikarus_supervisor import MissionSupervisor

### INCOMING edges INTO core from other SCC members
  <- file_bridge                FUNCTION-LOCAL (deferred)  in _process_request_claimed
       daedalus/file_bridge.py:766   from .core import process_bridge_payload
```

[MEASURED] 10 outgoing edges (9 distinct target modules; `kairos.scheduler`
appears 3x), 1 incoming edge.

### Manual verification of every outgoing edge

All 10 sites read directly (`daedalus/core.py` lines 19, 487, 517, 931, 960,
976, 1017-1024, 1218, 1243-1244, 1443). Findings:

- **All confirmed real and reachable.** None sit inside `if TYPE_CHECKING:`,
  none inside dead/unreachable branches. The 9 deferred ones are each inside a
  `try:` block or plain function body that executes on the normal call path
  (no guard suppresses the import itself, only downstream exceptions from the
  *call*, e.g. `_head_sha_safe`'s `except Exception: return None` wraps the
  call to `_head_sha`, not the import).
- **Enclosing function names all correct** as reported, with one nuance: the
  `_try_ikarus` edges (kairos.scheduler:1218, build_exec/ikarus_supervisor:
  1243-1244) sit in two different `try:` blocks of the same function — first
  the scheduler accept/assign block, then a second try for
  `build_exec`+`ikarus_supervisor`+`orchestration.run_mission` (the probe did
  not report the third symbol, `.orchestration`, because `orchestration` is
  not an SCC member — correct exclusion, not a bug).
- **Correction to the raw probe:** line 517's cited import also pulls
  `gate_discrimination`, which the probe's line hint truncates
  (`from .spine.bootstrap import (DISCRIMINATION_REL_PATH, KILL_RATE_FLOOR,` —
  the statement continues to `gate_discrimination)` on line 518). Confirmed by
  reading lines 516-521.

### Dynamic references (grep, not covered by AST)

```
grep -n "importlib\.import_module|__import__\(|\"core\"|'core'|\"status\"|'status'|\"file_bridge\"|'file_bridge'|\"kairos...|\"doctor\"|...|\"spine\." daedalus/core.py
```
No `importlib.import_module`, no `__import__`, and the only string-literal
hits are unrelated dict keys (`"status"` used ~9x as a JSON field name in
report/envelope dicts, e.g. line 273, 1068, 1134 — not a module reference).
[MEASURED] 0 dynamic SCC-member references found.

## What it actually does

`core.py` is the Mission Control backend hub: it assembles dashboard/status/
governance/queue envelopes for the UI (`get_dashboard`, `get_governance`,
`get_queue`, `routing_summary`, `_gov_discrimination`, `_gov_write_confinement`)
by reading receipts and calling `status.collect_status`, `spine.bootstrap`, and
`spine.picker`. Separately, it is the bridge-request dispatcher:
`process_bridge_payload` / `_try_ikarus` / `_one_task_session` turn one queued
bridge request into a `KairosScheduler` assignment, then drive `build_exec`'s
`WaveExecutor` (leased, capability-bounded execution) through
`ikarus_supervisor.MissionSupervisor` and `.orchestration.run_mission`.
`queue_task` is the write-side entrypoint that stamps a routed category and
calls `file_bridge.enqueue`.

## Layer

**Verdict: orchestration (currently mis-sited / a fused god-module).**

Justification: the module's highest-stakes code path —
`process_bridge_payload` → `_try_ikarus` → `KairosScheduler.accept` →
`WaveExecutor`/`MissionSupervisor`/`run_mission` — is squarely mission/
work-item scheduling and campaign driving, which is the `orchestration`
layer's definition. It holds no policy or evidence state itself (it reads
`spine.bootstrap`'s discrimination gate and `spine.picker`'s HEAD, but does not
decide promotion — `_gov_discrimination` explicitly returns "unknown"/refused
states rather than authorizing anything), so it is not `kernel`. But roughly
half the module (`get_dashboard`, `get_governance`, `get_queue`,
`routing_summary`, `envelope()`-wrapped return values) is pure envelope-shaping
for a UI client — the `interfaces` layer's definition — and is called directly
from `daedalus/interfaces/http/read.py:115` and `daedalus/kairos/control.py:11`.
This module currently does both jobs in one 1507-line file, which is why it
sits in an 18-member cross-domain SCC at all: it is the single node degree-
connected to `status`, `doctor`, `build`, `build_exec`, `ikarus_supervisor`,
`kairos.scheduler`, `spine.picker`, and `spine.bootstrap` simultaneously. It is
explicitly mis-sited against the target layout in `docs/IKARUS_ARIADNE_MASTER_PLAN.md`
section 3: no target layer is "dashboard backend + bridge dispatcher" — that is
two modules pretending to be one.

## Severance, edge by edge

1. **`core -> status`** (`collect_status`, **MODULE-LEVEL**, line 19).
   1 call site (`_safe_collect_status`, line 89), 1 symbol crossing.
   This is the *only* non-deferred outgoing edge — the one that actually
   forces eager import-time coupling; every other edge is already lazy.
   Cheapest: **(b) callback/parameter injection.** Thread a
   `status_fn: Callable[[str], dict[str, Any]]` parameter through
   `get_dashboard`/`_safe_collect_status`, with the concrete
   `daedalus.status.collect_status` supplied by the caller at the interfaces
   boundary — `daedalus/interfaces/http/read.py:115` (`core.get_dashboard(...)`)
   and `daedalus/kairos/control.py:11` are the two real external callers that
   would pass it. This removes the module-level `from .status import
   collect_status` entirely; `status.py` no longer needs a static consumer
   inside `core.py`.

2. **`core -> file_bridge`** (`enqueue`, deferred, line 931, in `queue_task`).
   1 call site, 1 symbol. Already a de-facto port seam (deferred import).
   Cheapest: **(a) port extraction.** Name a `TaskEnqueuePort` Protocol
   carrying `enqueue(objective, repo_root, paths, *, lane, project, source,
   strategy, category) -> Path`, living in a new
   `daedalus/spine/ports.py` (or beside `file_bridge.py` as
   `file_bridge_port.py`) — `core.queue_task` already only calls `enqueue`
   once, so formalizing the existing deferred import into a typed Protocol
   parameter costs one signature change, no behavior change.

3. **`core -> kairos.scheduler`** (`KairosScheduler`, deferred, 3 call sites:
   lines 960 `plan_ikarus`, 1218 `_try_ikarus`, 1443 `_configure_report`).
   1 symbol, 3 call sites, all constructing the same class with different
   kwargs then calling `.spawn`/`.accept`/`.configure`.
   Cheapest: **(a) port extraction.** Name a `SchedulerPort` Protocol with
   `spawn`, `accept`, `configure` methods matching `KairosScheduler`'s public
   surface, in a new `daedalus/kairos/scheduler_port.py`. 3 call sites but 1
   symbol means one Protocol removes all 3 edges at once — cheaper than 3
   separate callback injections.

4. **`core -> doctor`** (`check`, deferred, line 976, in
   `_availability_from_doctor`). 1 call site, 1 symbol, already deferred.
   Cheapest: **(b) callback/parameter injection.** `_availability_from_doctor`
   has exactly one caller inside `core.py` itself
   (`_ikarus_availability`, line ~992) which itself is called from
   `_try_ikarus`; inject `doctor_check: Callable[[], dict] = doctor.check`
   at the `_try_ikarus` boundary (the orchestration entrypoint), one symbol,
   trivial.

5. **`core -> build`** (`FRONTIER_BUILDER, LOCAL_BUILDER, BuildSession,
   BuildTask, Wave`, deferred, lines 1017-1024, in `_one_task_session`).
   1 call site but **5 symbols** crossing (2 constants + 3 classes) —the
   heaviest edge by symbol count.
   Cheapest: **(a) port extraction.** This is exactly a `Wave`/`BuildTask`
   construction seam; name a `BuildSessionFactory` Protocol (or a single
   function `build_one_task_session(payload, assignment) -> BuildSession`)
   living in `daedalus/build.py` itself, and have `core._one_task_session`
   call that one factory function instead of importing 5 names — collapses 5
   crossing symbols to 1.

6. **`core -> spine.picker`** (`_head_sha`, deferred, line 487, in
   `_head_sha_safe`). 1 call site, 1 symbol, already deferred, wrapped in
   `except Exception: return None` (existing fail-soft port behavior).
   Cheapest: **(b) callback/parameter injection** — `get_governance` (the
   caller chain into `_head_sha_safe`) already accepts a `repo_root` string;
   add a `head_sha_fn` parameter defaulted at the `interfaces` boundary
   (cheaper than a Protocol module for one pure function/one call site).

7. **`core -> spine.bootstrap`** (`DISCRIMINATION_REL_PATH,
   KILL_RATE_FLOOR, gate_discrimination`, deferred, lines 517-518, in
   `_gov_discrimination`). 1 call site, 3 symbols (1 function + 2 constants).
   Cheapest: **(a) port extraction.** Name a `DiscriminationGatePort`
   Protocol carrying `gate_discrimination(...)` plus the two constants, in
   `daedalus/spine/bootstrap_port.py`. Governance/promotion-adjacent
   (kernel-flavored) data flowing into an orchestration/interfaces module is
   a real layer boundary — `_gov_discrimination`'s own docstring frames it as
   "has THIS gate been shown to separate good patches from bad," a
   policy-facing question that deserves a stable contract, not an injected
   callback.

8. **`core -> build_exec`** (`EffectBounds, WaveExecutor`, deferred, line
   1243, in `_try_ikarus`). 1 call site, 2 symbols, paired with edge 9 in the
   same `try:` block — this is the actual leased-execution dispatch, the
   highest-effect edge in the module.
   Cheapest: **(a) port extraction.** Name an `EffectExecutionPort` Protocol
   carrying `WaveExecutor`'s public run method and `EffectBounds`'
   construction, in `daedalus/kernel/execution_port.py` (kernel already owns
   `attempt_execution`/`promotion` in this SCC, so the port's natural home is
   beside them). Grep confirms exactly one construction site
   (`WaveExecutor(` at line 1262) and one bounds construction
   (`EffectBounds(` at line 1264) inside `core.py` — cheap to wrap in one
   factory call.

9. **`core -> ikarus_supervisor`** (`MissionSupervisor`, deferred, line 1244,
   in `_try_ikarus`, same block as edge 8). 1 call site, 1 symbol
   (constructed once, line ~1255-1257, conditional on
   `mission_projection_dir`).
   Cheapest: **(b) callback/parameter injection.** `_try_ikarus` already takes
   `mission_projection_dir` as a parameter that gates whether a supervisor is
   built at all; extend that same parameter list with an optional
   `supervisor_factory: Callable[[Path], MissionSupervisor] | None = None`
   supplied by the same caller that passes `mission_projection_dir` today
   (`process_bridge_payload`). Single symbol, single conditional
   construction — injection is cheaper here than a Protocol module because
   the class already only appears at one call site with one shape.

**Incoming edge** (`file_bridge -> core`, `process_bridge_payload`, deferred,
`file_bridge.py:766`, in `_process_request_claimed`): this is file_bridge's
side of the story, not core's to sever, but note for the counterpart dossier:
1 symbol, 1 call site, already deferred — a clean `BridgeDispatchPort`
Protocol on the `core` side (`process_bridge_payload(payload) -> dict`) would
let `file_bridge` depend on the Protocol instead of `core` directly.

## Tests that pin this

`grep -rn "daedalus\.core\." tests/` (also cross-checked
`from daedalus.core import` / `from daedalus import core`):

- **14 test files** [MEASURED], **51 matching lines** [MEASURED] referencing
  `daedalus.core.<symbol>` (patch targets, direct imports, or
  `mock.patch("daedalus.core...")` strings).

Per-file counts and representative test functions (not exhaustive — see note
below on fixture-mediated blast radius):

| File | Matches | Representative test functions |
|---|---|---|
| `tests/test_bridge_restart.py` | 9 | line 149: shared `work` **fixture**, used by most of the file's ~48 `test_*` (e.g. `test_restart_after_a_crash_produces_exactly_one_of_everything`); direct patches in `test_leased_provider_completion_survives_crash_before_bridge_report` (484), `test_request_json_cannot_choose_the_internal_effect_identity` (588), `test_request_json_cannot_choose_the_mission_projection_directory` (631), `test_memory_provenance_uses_observed_provider_not_requested_lane` (734), `test_concurrent_consumers_serialize_one_request_and_publish_one_success` (768), `test_a_linked_failed_report_is_degraded_and_application_stays_unknown` (1445), `test_a_request_that_hard_kills_the_process_is_not_dispatched_forever` (1822) |
| `tests/test_comms.py` | 9 | `test_review_diff_queues_local_only_without_running_claude`, `test_local_only_bridge_failure_never_calls_claude` (patch `_try_ikarus`/`_ask_claude_report`), `test_models_handles_no_server`/`test_models_parses_ollama_tags` (patch `model_resources`/`watcher_status`) |
| `tests/test_dynamic.py` | 9 | `test_claude_lane_refuses_without_caller_held_broker_authority`, `test_unknown_or_missing_lane_fails_closed_not_claude`, `test_local_lane_eligible_runs_offload_not_claude`, `test_terminal_wave_failure_never_dispatches_a_second_provider` (patch `_try_ikarus`, `_ask_claude_report`, `_head_sha_safe`) |
| `tests/test_categories_integration.py` | 3 | `DashboardCarriesCategoriesTest.setUp` patches `list_projects`/`_process_rows` for `test_dashboard_includes_categories_joined_with_agents`; `QueueTaskCategoryStampTest.setUp` patches `resolve_repo_root` for `test_queue_task_stamps_category_without_altering_requested_lane`, `test_queue_task_falls_back_to_empty_category_when_routing_fails` |
| `tests/test_claude_detect.py` | 2 | `test_dashboard_carries_claude_crew` |
| `tests/test_codex_provider.py` | 1 | `test_codex_lane_never_falls_back_to_claude` (patches `_ask_claude_report`) |
| `tests/test_loop_lease.py` | 1 | inside a helper near `test_single_bridge_task_reaches_offload_through_the_wave_lease` (patches `_availability_from_doctor`) |
| `tests/test_loop_governance_head.py` | 1 | `test_driver_reads_this_repositorys_head_at_run_start` (patches `get_governance`) |
| `tests/test_loop_lease_receipt.py` | 2 | `test_governance_about_another_checkout_locks_promotion`, `test_governance_about_this_checkout_is_left_alone` |
| `tests/test_loop.py` | 4 | `test_red_governance_still_runs_iterations`, `test_promotion_locked_run_still_reports_gated_clean_work`, `test_green_governance_reports_nominating_mode`, `test_green_governance_at_another_revision_stays_locked` (all patch `get_governance`) |
| `tests/test_mission_control.py` | 2 | `test_top_level_keys`-family DashboardContractTest setUp patches `_process_rows`/`list_projects` |
| `tests/test_repair_blast_radius_write.py` | 1 | direct `from daedalus.core import _codex_report` — used across `test_undeclared_write_reaching_a_fenced_module_is_escalated` and siblings |
| `tests/test_ui_governance.py` | 3 | `test_payload_has_the_operator_question_answered` and the whole governance-contract class (patches `get_governance`, `list_projects`, `_process_rows`) |
| `tests/test_ui_contract.py` | 4 | `test_core_dashboard_has_the_shared_contract_keys`, `test_api_dashboard_matches_core_contract`, `test_api_and_core_expose_identical_key_sets` |

Note on blast radius: several of these patches sit in shared `pytest`
fixtures or `unittest.TestCase.setUp` blocks (`test_bridge_restart.py`'s
`work` fixture, `test_categories_integration.py`'s two `setUp`s,
`test_claude_detect.py`, `test_mission_control.py`, `test_ui_governance.py`,
`test_ui_contract.py`), so the effective number of individual test functions
that would break on a rename/move of `process_bridge_payload`,
`get_dashboard`, `get_governance`, `_try_ikarus`, `_ask_claude_report`,
`_availability_from_doctor`, `resolve_repo_root`, `list_projects`, or
`_process_rows` is materially larger than 51 — UNVERIFIED exact count without
running the suite (explicitly out of scope here; this is static analysis
only). All patches target `core` module attributes by string path
(`mock.patch("daedalus.core.X", ...)`/`monkeypatch.setattr("daedalus.core.X",
...)`), so any severance that renames or relocates these symbols out of
`core.py` breaks every one of these 51 sites, not just the ones shown above.
