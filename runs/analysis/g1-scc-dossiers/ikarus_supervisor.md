# SCC dossier: `daedalus/ikarus_supervisor.py` (key `ikarus_supervisor`)

Base: main @ 851ff43c. Read-only static analysis. Interpreter used for the
probe: `.venv/Scripts/python.exe`.

## Step 1 — Measured edges (raw AST probe)

Command: `.venv/Scripts/python.exe C:/Users/Administrator/scc-scratch/probe.py ikarus_supervisor`

```
### OUTGOING edges FROM ikarus_supervisor to other SCC members
  -> build                      MODULE-LEVEL               in <module>
       daedalus/ikarus_supervisor.py:52   from .build import BuildSession, BuildTask, Wave, mission_id_for_session
  -> spine.attempt              MODULE-LEVEL               in <module>
       daedalus/ikarus_supervisor.py:65   from .spine.attempt import (

### INCOMING edges INTO ikarus_supervisor from other SCC members
  <- core                       FUNCTION-LOCAL (deferred)  in _try_ikarus
       daedalus/core.py:1244   from .ikarus_supervisor import MissionSupervisor
```

[MEASURED] 2 outgoing edges, 1 incoming edge — matches the inherited figures
(2 outgoing edges both module-level, 1 importer deferred).

### Verification of each outgoing edge

- **`-> build` (line 52, module-level)** [MEASURED]. Real, unconditional,
  used well beyond annotations even though `from __future__ import
  annotations` is present (line 41): `BuildSession(...)` and `Wave(index=0,
  tasks=tasks)` are constructed at lines 485/489; `BuildTask(...)` is
  constructed at line 473 and passed to `BuildTask.mark(task,
  terminal_status)` as a runtime static-method call at line 1068;
  `type(task) is not BuildTask` is a runtime `is`-type check at line 611;
  `mission_id_for_session(...)` is called at line 637. Not a free cut —
  4 symbols, all used as runtime values, not just type hints.
- **`-> spine.attempt` (line 65, module-level)** [MEASURED]. Real,
  unconditional. `GateResult` appears in a `Callable[..., Callable[[Any],
  GateResult]]` type alias (line 102/724) — annotation-only for that one
  symbol — but `RunnerContext`, `TaskSpec`, `TaskSpecInvalid` are constructed
  and caught at runtime: `TaskSpec(...)` at lines 169, 875; `RunnerContext(...)`
  at line 201; `except TaskSpecInvalid as exc` at line 890. Because 3 of the 4
  imported names are genuine runtime uses, the import as a whole is not a free
  cut even though `GateResult` alone would qualify.

### Dynamic-reference grep

[MEASURED] `grep -n "importlib.import_module\|__import__("
daedalus/ikarus_supervisor.py` → no matches. String-literal grep for SCC
member module names as dynamic-import targets → no matches (only unrelated
`"status"`-shaped dict-value strings like `"planned"`, `"refused"`,
`"skipped"`, `"dispatched"` at lines 925, 955, 958, 987, 998, 1070, which are
work-item lifecycle states, not the `daedalus.status` module).

## Step 2 — What it actually does

`MissionSupervisor` (line 509, ~1101-line file) drives one pre-planned
mission — a list of `PlannedItem`s built by `plan_mission()` — through
`RoleHarness`-provided runner/gate factories one item at a time, refusing the
whole plan up front if it names a role not present in `roles` (before any
attempt starts). Each step writes one immutable, content-addressed
`StateLedger` revision (chained by `previous_ledger_sha256`, verified by
`verify_state_ledger`) that records typed item state (`planned`,
`dispatched`, `landed`, `bounced`, `skipped`, `refused`) and no transcript —
the ledger is explicitly a non-authoritative projection over the real
`MissionContract`/`AttemptReceipt`/spine-ledger truth. It reuses
`daedalus.build`'s `BuildSession`/`Wave`/`BuildTask` as the underlying
work-item/session shape (via `mission_contract_for_build_session`) and
`daedalus.spine.attempt`'s `TaskSpec`/`RunnerContext`/`TaskSpecInvalid` to
actually construct and dispatch each attempt.

## Step 3 — Layer

**Verdict: `orchestration`.** This module is a mission/work-item scheduling
driver: it turns a caller-declared list of planned items into ordered
attempts against a role registry, one state-ledger revision at a time, and
explicitly disclaims being an LLM, a chat, or an effectful door of its own
(module docstring, lines 21-33) — every actual attempt still goes through
`TaskAttempt`/`spine.attempt`, i.e. it delegates to the trust boundary rather
than being one. It is currently mis-sited at the top level
(`daedalus/ikarus_supervisor.py`) rather than under a future
`orchestration/` package; by role, it belongs there, next to `build_exec.py`
and `daedalus.build` (all three drive typed work through the same
attempt/spine primitives without owning policy, evaluator, or promotion
themselves).

## Step 4 — Severance

- **`-> build` (module-level, `BuildSession, BuildTask, Wave,
  mission_id_for_session`).** Cheapest: **(a) port/protocol extraction**,
  same shape as `build_exec`'s cut. `build.py` again has no import of
  `ikarus_supervisor` [MEASURED: `grep -n "ikarus_supervisor"
  daedalus/build.py` → no matches at all, not even in comments], so this is a
  one-directional dependency, not mutual coupling — the SCC cycle again
  routes through `daedalus.core`, which imports both `build` (deferred, line
  1017) and `ikarus_supervisor` (deferred, line 1244) from the same
  `_try_ikarus` function. A `BuildPlanPort` Protocol (or plain dataclass
  facade module) carrying `BuildSession`, `BuildTask`, `Wave`, and
  `mission_id_for_session(slug, created) -> str` — the same 4 symbols
  `build_exec.py` needs a 3-of-4 overlapping subset of — would let both
  `build_exec.py` and `ikarus_supervisor.py` depend on a shared low-level
  module instead of on each other's sibling `build.py`. Not a genuine merge:
  `build.py` is pure planning data with zero execution semantics;
  `ikarus_supervisor.py` is a mission-driving state machine. Fusing them
  would mix a serializable plan format with an active supervisor holding a
  `StateLedger` and dispatch loop.

- **`-> spine.attempt` (module-level, `GateResult, RunnerContext, TaskSpec,
  TaskSpecInvalid`).** [MEASURED] 4 symbols cross the edge; `TaskSpec` alone
  has the most call sites (constructed at 169, 875; typed at 197-198, 852-853;
  referenced in docstrings at 826). This is the deepest, least severable edge
  in the module: `MissionSupervisor.run` cannot dispatch a single attempt
  without building a `spine.attempt.TaskSpec` and handling
  `TaskSpecInvalid`, and `RunnerContext` is the exact object `RoleHarness`
  factories are handed. **Cheapest available: (c) event/late binding through
  the existing `spine.attempt` module itself is not applicable (it *is* the
  target); genuinely the best option is (a) port/protocol extraction naming a
  narrow `AttemptSpecPort` Protocol** carrying just `TaskSpec`,
  `TaskSpecInvalid`, `RunnerContext` (drop `GateResult` from the port — it is
  annotation-only per Step 1 and can stay a `from __future__ import
  annotations`-only reference, a free cut on its own), living alongside
  `spine.attempt` itself since these are its own public contract types, not
  borrowed internals. Practically this edge is real coupling that a Protocol
  extraction only renames, not removes: `ikarus_supervisor` is a genuine
  consumer of `spine.attempt`'s attempt-construction contract, so cutting the
  SCC here trades an import edge for a structural-typing dependency that
  still has to be satisfied by the same object shapes.

- **Pass-through vs. real-coupling verdict for `ikarus_supervisor` overall
  (both of its 2 outgoing edges plus its 1 deferred importer, `core`).**
  **Real coupling, not pass-through.** Both `build` and `spine.attempt` are
  used for actual runtime construction/dispatch (dataclass instantiation,
  static-method calls, exception handling), not merely re-exported or
  type-only. The single importer, `daedalus.core`, imports `MissionSupervisor`
  deferred inside `_try_ikarus` (core.py:1244) purely to *instantiate and
  drive* it as one integration path among several `_try_*` candidates in
  `core.py` — `core` does not re-export `ikarus_supervisor` symbols onward to
  other SCC members, so `ikarus_supervisor` is a genuine leaf consumer of
  `build`+`spine.attempt` and a genuine leaf provider to `core`, not a
  transparent relay module.

## Step 5 — Tests that pin this

[MEASURED] `grep -rl "ikarus_supervisor" tests/ --include="*.py"` → 7 files;
`grep -r "ikarus_supervisor" tests/ --include="*.py" | wc -l` (non-pycache) →
matches distributed across those 7 files (32 total lines counting
`__pycache__` artifacts).

Files and what breaks:

- `tests/contracts/test_import_scc_hierarchy.py` — governance test.
  `daedalus.ikarus_supervisor` is a literal member of
  `OLD_CROSS_DOMAIN_COMPONENT` (line 26) and (after the two prior amendments
  removing `kernel.offload_lease`/`runtimes.admission.offload_egress` and
  `conversation`) still a member of `CURRENT_CROSS_DOMAIN_COMPONENT`.
  Rewiring either outgoing edge changes SCC membership/size/digest and
  breaks `test_observation_contract_breaks_the_next_cross_domain_scc`
  (`len(components) == 12`, `max(map(len, components)) == 18`, and the
  `CURRENT_COMPONENTS_SHA256` digest assertion) and potentially
  `test_intent_ledger_port_breaks_the_selected_cross_domain_scc`.
- `tests/test_ikarus_supervisor.py` — 6 test functions, direct module import
  (line 19): `test_the_same_plan_yields_the_same_mission_and_work_item_ids`,
  `test_a_green_run_leaves_mission_ledger_and_receipt_digests`,
  `test_a_tampered_or_thinned_ledger_is_refused`,
  `test_an_unknown_role_refuses_the_whole_plan_before_any_attempt`,
  `test_a_bounced_item_stops_dispatch_and_is_named_in_the_ledger`,
  `test_the_ledger_carries_typed_state_and_no_transcript`. These exercise
  `MissionSupervisor.run`, `plan_mission`, `verify_state_ledger` directly —
  any symbol move breaks the import at line 19.
- `tests/test_ikarus_runtime_role.py` — 23 test functions, imports from
  `daedalus.ikarus_supervisor` (line 22, `# noqa: E402`) alongside
  `ikarus_runtime_role` symbols (`RuntimeRoleRegistry`,
  `RuntimeRoleSnapshot`, `INPROCESS_RUNTIME_ID` — themselves imported by
  `ikarus_supervisor.py` at lines 55-58, though `ikarus_runtime_role` is not
  itself an SCC member).
- `tests/test_canonical_execution_limit_policy.py` — 9 test functions, module
  imports `daedalus.ikarus_supervisor` symbols at line 12 to exercise
  `ExecutionLimitPolicy` interaction with mission dispatch.
- `tests/test_bridge_restart.py` — 48 test functions total in file; the
  `ikarus_supervisor` reference is a single deferred `from
  daedalus.ikarus_supervisor import verify_state_ledger` inside one test body
  at line 505 — only that one test (not all 48) depends on this module.
- `tests/orchestration/test_attempt_composition_hierarchy.py` — 9 test
  functions; references `ikarus_supervisor` per the file-level grep hit
  (architecture/composition-hierarchy assertions over the attempt/supervisor
  relationship — no direct top-level import line found, consistent with an
  in-body or string reference).
- `tests/orchestration/test_ikarus_mission_integration.py` — 7 test
  functions, imports `daedalus.ikarus_supervisor` symbols at line 21
  alongside `daedalus.build_exec` (this file exercises the full
  `ikarus_supervisor` + `build_exec` integration together — see the sibling
  `build_exec.md` dossier, Step 5).

No `mock.patch("daedalus.ikarus_supervisor....")` string targets were found
[MEASURED: zero matches for
`patch\("daedalus\.ikarus_supervisor|patch\('daedalus\.ikarus_supervisor`]
— unlike `build_exec.WaveExecutor.run_wave`, tests exercise this module
through direct import and real calls, not string-targeted mocking, so a
rename is more likely to surface as an `ImportError`/`AttributeError` at
collection time than as a silently-wrong-target patch.

Total: 7 distinct test files [MEASURED], at least 32 non-pycache matching
lines for the literal string `ikarus_supervisor` across `tests/` [MEASURED].
