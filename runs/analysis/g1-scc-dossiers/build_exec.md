# SCC dossier: `daedalus/build_exec.py` (key `build_exec`)

Base: main @ 851ff43c. Read-only static analysis. Interpreter used for the
probe: `.venv/Scripts/python.exe`.

## Step 1 — Measured edges (raw AST probe)

Command: `.venv/Scripts/python.exe C:/Users/Administrator/scc-scratch/probe.py build_exec`

```
### OUTGOING edges FROM build_exec to other SCC members
  -> progress                   MODULE-LEVEL               in <module>
       daedalus/build_exec.py:80   from . import progress
  -> build                      MODULE-LEVEL               in <module>
       daedalus/build_exec.py:81   from .build import BuildSession, Wave, load_session, wave_path_conflicts
  -> kairos.scheduler           MODULE-LEVEL               in <module>
       daedalus/build_exec.py:82   from .kairos.scheduler import (
  -> spine.attempt              FUNCTION-LOCAL (deferred)  in _cancel_requested
       daedalus/build_exec.py:172   from .spine.attempt import _as_predicate
  -> kairos.gated_writes        FUNCTION-LOCAL (deferred)  in WaveExecutor.run_wave
       daedalus/build_exec.py:1099   from .kairos.gated_writes import run_write_wave

### INCOMING edges INTO build_exec from other SCC members
  <- core                       FUNCTION-LOCAL (deferred)  in _try_ikarus
       daedalus/core.py:1243   from .build_exec import EffectBounds, WaveExecutor
```

[MEASURED] 5 outgoing edges, 1 incoming edge — matches the inherited count
(5 outgoing, second-highest out-degree after `core`'s 9).

### Verification of each outgoing edge

- **`-> progress` (line 80, module-level)** [MEASURED]. Read: real, reachable,
  no `TYPE_CHECKING` guard (`from __future__ import annotations` is present at
  line 68, but `progress` is used for runtime calls, not just annotations —
  see below). Not a free cut.
- **`-> build` (line 81, module-level)** [MEASURED]. Real, unconditional.
  `BuildSession`, `Wave` are used as runtime type hints in `def` signatures
  *and* as runtime values (`BuildSession(...)`, `Wave(index=0, ...)` are
  constructed, `type(task) is not BuildTask` is a runtime `is` check at
  line 611 in `ikarus_supervisor.py`'s neighbour file — for `build_exec.py`
  itself, `Wave` is instantiated implicitly via `wave.index`/`wave.tasks`
  attribute access throughout, and `load_session`/`wave_path_conflicts` are
  called functions, not types). Not annotation-only; not a free cut.
- **`-> kairos.scheduler` (line 82, module-level)** [MEASURED]. Real.
  `KairosScheduler` is instantiated/typed AND its instance methods
  (`.accept`, `.dispatch`, `.policy`, `.max_parallel_writes`,
  `.max_workers`, `.project`) are called at runtime (lines 730, 836, 1067,
  1091, 1142, 411/418/422/440/441, 565, 878). `Assignment` is a return-type
  annotation but also constructed/consumed as data flowing from `.accept()`.
  `spend_refused_result`, `SPEND_REFUSED_STATUS`, `SPEND_REFUSED_SKIPPED_STATUS`
  are called/compared at runtime (line 290 and others). Not a free cut.
- **`-> spine.attempt` (line 172, function-local, in `_cancel_requested`)**
  [MEASURED, corrected enclosing-function check]. Read lines 155-174: the
  import is genuinely inside `def _cancel_requested(cancel)`, at line 172,
  immediately called at line 174 (`_as_predicate(cancel)()`). Confirmed
  deferred, confirmed reachable (not behind a dead branch — it is the entire
  function body). The probe's attribution to `_cancel_requested` is correct.
- **`-> kairos.gated_writes` (line 1099, function-local, in
  `WaveExecutor.run_wave`)** [MEASURED, corrected enclosing-function check].
  `run_wave` is defined at line 814 (`def run_wave(self, scheduler:
  KairosScheduler, wave: Wave, repo_root: str, *, ...)`); the import at line
  1099 sits inside its body, inside an `if gated_write_wave:` branch that is
  reached in normal live-write execution (not dead code, not
  `TYPE_CHECKING`). The probe's attribution is correct.

### Dynamic-reference grep

[MEASURED] `grep -n "importlib.import_module\|__import__("
daedalus/build_exec.py` → no matches. No string literals naming another SCC
member module path were found as dynamic-import targets (the only
`"status"`-shaped string literals in the file are dict status values like
`"effect_lease_denied"`, unrelated to the `daedalus.status` module).

## Step 2 — What it actually does

`WaveExecutor` (the module's one real class, ~1482 lines total) takes a saved
`BuildSession`/`Wave` plan from `daedalus.build` and actually runs it: for each
wave it classifies write-vs-dry-run via `KairosScheduler.accept`, acquires an
`EffectLease`/`SpendEnvelope` for the wave's declared cost, then either calls
`KairosScheduler.dispatch(...)` (dry-run/read-only path) or
`kairos.gated_writes.run_write_wave(...)` (live-write path, one isolated
worktree per task, never a live write to `repo_root`). It emits progress
events (`progress.open_unit/claim_unit/heartbeat/record_gate_verdict/
record_done`) throughout, reconciles results back onto `BuildTask.status`, and
persists via `BuildSession.save()`. `UnsafeParallelWriteError` is a hard
refusal, not a downgrade, if a caller asks for `parallel=True` over a wave
that turns out to contain a write.

## Step 3 — Layer

**Verdict: `orchestration`.** `WaveExecutor` schedules and dispatches typed
work units (`BuildTask`/`Wave`) across a scheduler and a write-gate, manages
budgets/leases per wave, tracks progress, and reconciles attempt outcomes —
this is mission/work-item execution driving, not a trust-boundary primitive
itself (it *calls into* `kairos.gated_writes`, which is closer to the
kernel/spine trust boundary, but `build_exec` itself owns no policy or
promotion decision). It is currently mis-sited at `daedalus/build_exec.py`
(flat top-level package, no `orchestration/` home yet) — by role it belongs
next to `daedalus.build` under a future `orchestration/` package, not under
`kernel/` or `spine/`. Evidence for the boundary: `tests/contracts/
test_spine_outer_ports.py` FORBIDDEN_PREFIXES explicitly lists
`daedalus.build_exec` as a layer `daedalus.spine.*` must never import
(line 74) — i.e. the architecture contract already treats `build_exec` as an
"outer" (orchestration-side) layer relative to `spine`.

## Step 4 — Severance

- **`-> build` (module-level, `BuildSession, Wave, load_session,
  wave_path_conflicts`).** Cheapest: **(d) not a genuine merge, keep split.**
  `build.py` (567 lines) is a pure data/plan model — dataclasses
  (`BuildTask`, `Wave`, `BuildSession`) plus serialization
  (`load_session`) and a pure conflict check (`wave_path_conflicts`); it
  contains no execution and [MEASURED] does **not** import `build_exec`
  anywhere (`grep -n "build_exec" daedalus/build.py` only matches
  docstrings/comments, zero import statements). The SCC cycle that catches
  both modules routes through `daedalus.core` (which imports both
  `build_exec` and `ikarus_supervisor`, deferred, from `_try_ikarus` at
  core.py:1243-1244), not through mutual `build_exec <-> build` coupling.
  Since there is no reciprocal edge, merging would fuse a data-model module
  into an execution-engine module for no cycle-breaking benefit. If a cut is
  wanted anyway, treat it as **(a) port/protocol extraction**: a
  `BuildPlanPort` Protocol carrying exactly `BuildSession`, `Wave`,
  `load_session(path) -> BuildSession`, `wave_path_conflicts(wave) -> list`,
  living in a new low-level module (e.g. `daedalus/build_types.py`) that both
  `build.py` and `build_exec.py` import instead of `build_exec` reaching into
  `build.py` directly. Cost: 4 symbols cross the edge, used pervasively (every
  method signature takes `wave: Wave`; `BuildSession` threads through `run`,
  `_scheduler_for`, `run_wave`'s callers) — this is a real but *mechanical*
  rename-the-import cut, not a design change.

- **`-> progress` (module-level, extra-depth analysis requested).**
  [MEASURED] Real call sites (excluding docstring/comment mentions at lines
  128, 134, 149, 401, 1074, 1077, 1273, which are prose, not code): 6 call
  sites at lines 602, 771, 803, 1040, 1064, 1087, naming 6 distinct `progress`
  symbols — `now_iso`, `record_gate_verdict`, `record_done`, `open_unit`,
  `claim_unit`, `heartbeat`. `progress.py` is 782 lines with a much larger
  public surface (`ProgressEvent`, `ProgressLog`, `snapshot`, `render`,
  `to_payload`, a CLI `main`, etc.) — `build_exec` uses none of that; it only
  ever emits.
  **Cheapest: (b) callback/parameter injection — this is already a de-facto
  seam.** `WaveExecutor._emit(self, fn: Any, unit_id: str, **kw: Any)` at
  line 732 already takes the progress function itself as a first-class
  parameter (`fn(unit_id, source=PROGRESS_SOURCE, log=self._progress_log,
  **kw)`, wrapped in a swallow-all `try/except`) — every call site passes
  `progress.open_unit` / `.claim_unit` / `.heartbeat` / `.record_gate_verdict`
  / `.record_done` *as values* into `_emit`, not as direct calls. The module
  has effectively already built the port; it just still imports the concrete
  `progress` module to obtain the 5 function values instead of receiving them
  through a constructor-injected `ProgressSink` Protocol (5 methods:
  `open_unit`, `claim_unit`, `heartbeat`, `record_gate_verdict`,
  `record_done`; `now_iso()` is a free-standing timestamp helper used once at
  line 602 and can be inlined with `datetime.now(UTC).isoformat()` or kept as
  a 6th Protocol method). [INHERITED, confirmed by re-measurement] Cutting
  this edge alone was reported to collapse the SCC 18 -> 16; this is
  consistent with `progress` having no back-edge into `build_exec` in this
  file's own inspection and being a low-fan-in leaf-ward module for the
  handful of symbols actually used.

- **`-> kairos.scheduler` (module-level, `KairosScheduler, Assignment,
  spend_refused_result, SPEND_REFUSED_STATUS, SPEND_REFUSED_SKIPPED_STATUS`).**
  [MEASURED] `KairosScheduler` is a constructor/type-hint parameter passed in
  by the caller (never instantiated inside `build_exec.py` itself — `grep -c
  "KairosScheduler("` finds 0 constructor calls in this file; every use is
  `scheduler: KairosScheduler` typing or a `scheduler.<method>` call).
  Real method surface actually invoked: `.accept`, `.dispatch`, `.policy`,
  `.max_parallel_writes`, `.max_workers`, `.project` — 6 attributes/methods.
  **Cheapest: (a) port/protocol extraction.** Name a `SchedulerPort` Protocol
  in `daedalus/kairos/scheduler.py` itself (or a new tiny
  `daedalus/kairos/scheduler_port.py`) carrying exactly those 6 members plus
  `Assignment` as a shared dataclass import and the 3 spend-refusal
  constants/`spend_refused_result` helper; `build_exec` would type its
  `scheduler` parameters against the Protocol instead of the concrete class.
  Because `build_exec` never constructs a `KairosScheduler`, this is a type
  narrowing exercise, not a runtime restructuring — cheap, but not as cheap as
  the `progress` cut because the caller (whoever builds `WaveExecutor` and
  hands it a live `KairosScheduler`) still needs to satisfy the Protocol,
  i.e., `KairosScheduler` itself remains unchanged and just needs to
  structurally match.

- **`-> spine.attempt` (function-local, `_as_predicate`, in
  `_cancel_requested`).** [MEASURED] 1 symbol, 1 call site
  (`_as_predicate(cancel)()` at line 174), already deferred — this import is
  already its own de-facto port seam (it only pays the import cost on first
  use of a cancel token, and the module's own docstring at lines 156-171
  argues *for* the coupling: reusing the private normalizer avoids a second,
  possibly-diverging answer to "was this cancelled"). **Cheapest: (b)
  callback/parameter injection**, but marginal: `WaveExecutor.run`/`run_wave`
  could accept an already-normalized `cancel_requested: Callable[[], bool]`
  from the caller (who is closer to `spine.attempt` already) instead of
  reaching for the private `_as_predicate` itself. Given it is a single
  private-name import already deferred, leaving it as-is (already the
  cheapest available seam) is also defensible — the docstring explicitly
  rejects re-deriving a second normalizer as strictly worse.

- **`-> kairos.gated_writes` (function-local, `run_write_wave`, in
  `WaveExecutor.run_wave`).** [MEASURED] 1 symbol, 1 call site (line 1138),
  already deferred, and the surrounding comment (lines 1101-1118) explicitly
  argues the deferred/`inspect.signature`-probed style (`_accepts_cancel`,
  `_accepts_kwarg` at lines 1120, 1129) is deliberate because
  `gated_writes.py` is "owned elsewhere" and its `cancel` support is still
  landing. **Cheapest: (b) callback/parameter injection**, matching the
  existing pattern — `run_write_wave` could be passed into `WaveExecutor` as
  a constructor-injected callable (parameter name e.g. `write_wave_runner`)
  by whichever caller assembles the executor, rather than imported by name.
  Already a near-ideal deferred seam; not urgent to cut first.

## Step 5 — Tests that pin this

[MEASURED] `grep -rl "build_exec" tests/ --include="*.py"` → 13 files, `grep -r
"build_exec" tests/ --include="*.py" | wc -l` → matches across those 13 (71
total lines counting `__pycache__`, 13 distinct `.py` files).

Files and what breaks:

- `tests/contracts/test_import_scc_hierarchy.py` — governance test.
  `daedalus.build_exec` is a literal member of `OLD_CROSS_DOMAIN_COMPONENT`
  (line 20) and `CURRENT_CROSS_DOMAIN_COMPONENT`. Rewiring ANY of the 5
  outgoing edges changes SCC membership/size and will break
  `test_observation_contract_breaks_the_next_cross_domain_scc` (asserts
  `len(components) == 12`, `max(map(len, components)) == 18`, and a SHA-256
  digest `CURRENT_COMPONENTS_SHA256` over the sorted component list) and
  potentially `test_intent_ledger_port_breaks_the_selected_cross_domain_scc`.
- `tests/contracts/test_spine_outer_ports.py` — `daedalus.build_exec` is
  listed in `FORBIDDEN_PREFIXES` (line 74): `spine.*` may never import it.
  Function `test_...` bodies (8 test functions in file) scan for that.
- `tests/test_registry_new_doors.py` (9 test functions) — CLI door registry
  pins `"cli.build_exec": "daedalus.build_exec:main"` (line 113) and a
  `repository_mutation` capability binding (line 184); also directly greps
  `build_exec.py`'s source text for the string `"gated_writes.run_write_wave"`
  hand-down (lines 654-666) — moving that call out from under `run_wave`
  without leaving the string would break this.
- `tests/test_build_vocabulary.py` — references `origin="daedalus.build_exec"`
  provenance string (line 224) and documents the `WaveResult.results` dict
  identity contract with `gated_writes`/`build_exec` (line 248).
- `tests/test_dynamic.py` — 4 `mock.patch("daedalus.build_exec.WaveExecutor
  .run_wave", ...)` string targets (lines 181, 225, 270, 388): renaming
  `WaveExecutor` or `run_wave`, or moving the class to another module, breaks
  these patches silently (wrong-target patch, not an ImportError).
- `tests/test_loop.py` — imports `WaveExecutor, _accepts_cancel` (line 589)
  and `WaveExecutor` (line 605) via deferred in-test imports.
- `tests/test_loop_cap_policy.py` (5 tests), `tests/test_loop_lease.py`
  (16 tests, e.g. `test_one_wave_acquires_exactly_one_lease`,
  `test_offload_receives_the_wave_lease`,
  `test_engaged_kill_switch_refuses_the_wave_before_any_offload`),
  `tests/test_loop_spend_refused.py` (11 tests) — import `EffectBounds,
  WaveExecutor[, WaveResult]` at module level and exercise
  `WaveExecutor.run`/`run_wave` against a fake scheduler.
- `tests/test_wave_spend_reservation.py` (10 tests, e.g.
  `test_granted_lease_reserves_its_ceiling_on_the_budget_ledger`,
  `test_the_hold_is_released_even_when_the_wave_raises`) and
  `tests/test_wave_spend_reservation_concurrency.py` (5 tests) — same
  `EffectBounds, WaveExecutor` import, exercise the lease/spend-envelope path
  that crosses into `kairos.scheduler` and `kairos.gated_writes`.
- `tests/orchestration/test_ikarus_mission_integration.py` (7 tests) and
  `tests/orchestration/test_run_mission.py` (7 tests) — import
  `BuildRunReport, EffectBounds, WaveExecutor[, WaveResult]`, full-mission
  integration through the same executor.

Total: 13 distinct test files [MEASURED], at least 71 non-pycache matching
lines for the literal string `build_exec` across `tests/` [MEASURED].
