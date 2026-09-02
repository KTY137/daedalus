# SCC dossier: `offload` (`daedalus/offload.py`)

Base: main @ 851ff43c. Read-only static analysis.

## Measured edges (raw AST probe)

Command: `.venv/Scripts/python.exe C:/Users/Administrator/scc-scratch/probe.py offload`

```
### OUTGOING edges FROM offload to other SCC members
  -> kairos.scheduler           MODULE-LEVEL               in <module>
       daedalus/offload.py:29   from .kairos.scheduler import FREE_LANES
  -> doctor                     FUNCTION-LOCAL (deferred)  in _offload_impl
       daedalus/offload.py:386   from .doctor import check

### INCOMING edges INTO offload from other SCC members
  <- kairos.scheduler           FUNCTION-LOCAL (deferred)  in KairosScheduler.dispatch._run_one
       daedalus/kairos/scheduler.py:273   from ..offload import offload
  <- kernel.attempt_execution   FUNCTION-LOCAL (deferred)  in offload_runner._runner
       daedalus/kernel/attempt_execution.py:1209   from daedalus.offload import offload
```

**Verification [MEASURED]:** Read `daedalus/offload.py:29` — real module-top
`import` statement, not inside `TYPE_CHECKING`, one screen below the module
docstring; `FREE_LANES` is used at lines 414 and 446, both reachable (no dead
branch). Read `daedalus/offload.py:358-393` — line 386 sits inside
`_offload_impl`, guarded by `if availability is None:` (fires whenever a
caller omits `availability`); real, reachable, not `TYPE_CHECKING`. Both
enclosing-function attributions in the probe output are correct; no
correction needed.

**Dynamic-reference grep** (`importlib.import_module`, `__import__`, string
literals naming SCC members) over `daedalus/offload.py`: zero matches
[MEASURED].

## Step 2 — what it actually does

`offload.py` is the seam that dispatches one task to a free-tier bench
(ollama / codex_cli / deepseek), verifies the result, and either accepts it
or rolls it back and escalates to Claude: `_offload_impl` resolves project
policy, calls `route_and_select` to pick a provider, and refuses any live
write when no policy is loaded or when the call is not running inside an
isolated `TaskAttempt` worktree — then, instead of executing, it returns a
private `_LiveDispatch` record that only the leased `offload()` wrapper can
turn into a real run. `offload()` is the public Effect-Lease-consuming
entrypoint: it refuses to execute without a persisted
`LeasedEffectAuthorization`/`EffectExecutionRequest` bound to
`python.offload`, calls `begin_effect`, and always terminalises the lease
(`finish_effect` with `COMPLETED`/`FAILED`/`CANCELLED`) even on exception.
`_leased_bench_cascade` — reachable from exactly one call site — is the
actual write path: it snapshots the repo before/after by content hash,
invokes `worker.run()`, re-runs the blast-radius reachability fence over
what *actually* changed on disk, calls `verify()`, and on failure calls
`worker.rollback()` before reporting `escalated_after_verify_fail`.

## Step 3 — layer

**Verdict: kernel.** `offload.py` owns exactly the trust-boundary
responsibilities the taxonomy assigns to `kernel`: policy enforcement
(fail-closed refusal when no policy is loaded), Effect-Lease consumption
(`begin_effect`/`finish_effect` with receipted terminal states), before/after
disk evidence (`_repo_snapshot`/`_scoped_snapshot` diffing), the write-mode
verify gate, and rollback on failure. It is **mis-sited today**: it lives at
package root (`daedalus/offload.py`) rather than under `daedalus/kernel/`,
even though its sibling `daedalus/kernel/offload_lease.py` (3390 lines)
already exists as the *issuer* half of the exact `python.offload` Effect
Lease this module *consumes* — the split is real today, just spelled with an
inconsistent module path. The one non-kernel sliver is the provider-adapter
selection inside `_leased_bench_cascade`: `worker = get_provider(decision.provider); out = worker.run(**run_kwargs)` (offload.py:587-588,685) is a
`runtimes`-layer concern (dispatch to a concrete CLI/HTTP provider adapter).
Split point: everything before and after that one call — routing, the
policy/lease gate, snapshot/verify/rollback, evidence assembly — is kernel;
`get_provider`/`worker.run` is the runtimes seam.

## Step 4 — severance

### Edge 1: `offload -> kairos.scheduler` (`FREE_LANES`, line 29, MODULE-LEVEL)

- **Symbols crossing:** 1 (`FREE_LANES`, a plain 3-tuple of provider name
  strings — a policy constant, not scheduler behavior).
- **Call sites in offload.py:** 2 (`offload.py:414` `eligible = intended.provider in FREE_LANES`; `offload.py:446` `if decision.provider not in FREE_LANES:`).
- **Cheapest severance: (a) port/protocol extraction — of a constant, not a
  Protocol.** `FREE_LANES` carries no behavior and is defined at
  `kairos/scheduler.py:33` purely as configuration data (which providers
  don't need Claude-tier oversight). Move it into a neutral, already-shared
  home both modules import from without crossing the SCC boundary —
  `daedalus/limit_policy.py`, which `offload.py` already imports from
  (`offload.py:30`) and which sits below the SCC. `kairos/scheduler.py`
  then imports `FREE_LANES` from `limit_policy` instead of defining it, and
  `offload.py`'s import moves from `.kairos.scheduler` to `.limit_policy`.
  This is the cheapest possible cut: one symbol, a constant, zero call-site
  changes required in either module beyond the import line.

### Edge 2: `offload -> doctor` (`check`, line 386, FUNCTION-LOCAL deferred)

**[INHERITED] Cutting this edge alone collapses the SCC 18 -> 8** — the
single best cut of the 18, so it gets the deepest read.

- **Symbols crossing:** 1 (`doctor.check`, a function returning a readiness
  dict).
- **Call sites in offload.py:** 1 (`offload.py:387`, `ready = check()`),
  reached in exactly one function (`_offload_impl`), guarded by
  `if availability is None:`.
- **Already a de-facto port:** the import is FUNCTION-LOCAL/deferred, and the
  function it fills in for — `availability: dict | None = None` — is already
  an injectable parameter on both `_offload_impl` and its public wrapper
  `offload()`. The `doctor.check()` call exists *only* as the default when a
  caller omits `availability`.
- **Who actually relies on the default (measured by grep):**
  `daedalus/kairos/scheduler.py` never triggers it — `KairosScheduler.dispatch`
  computes its own `avail = self.availability or DEFAULT_AVAILABILITY`
  (`kairos/scheduler.py:37,186,257,437`, a *static* dict, no `doctor` import)
  and always passes `availability=avail` into `offload(...)`
  (`kairos/scheduler.py:285-286`). But `daedalus/kernel/attempt_execution.py`'s
  `offload_runner._runner` (line 1222, `return offload(ctx.task.instruction, str(ctx.worktree), **kwargs)`) does **not** set `availability` unless the
  caller passed it in `offload_kwargs`, and neither production caller does:
  `daedalus/spine/bootstrap.py:730` (`runner=offload_runner(**kwargs)`) and
  `daedalus/spine/picker.py:2912` (`runner=offload_runner(live=bool(args.live))`)
  both omit it. So the `kernel.attempt_execution -> offload -> doctor` chain
  is real in production, not merely test-reachable.
- **Cheapest severance: (b) callback/parameter injection**, completing the
  existing partial port. Delete the `if availability is None: from .doctor
  import check; ...` fallback block (`offload.py:385-393`) from
  `_offload_impl`, making `availability` load-bearing rather than
  optional-with-a-hidden-default. Push the defaulting to the two places that
  currently omit it: `offload.py`'s own CLI `main()` (which also relies on
  the default today) gains an explicit `from .doctor import check` call
  before invoking `offload(...)`; `daedalus/spine/bootstrap.py` and
  `daedalus/spine/picker.py` each resolve availability once (a
  `doctor.check()`-backed helper, or the `DEFAULT_AVAILABILITY`-style static
  dict `kairos/scheduler.py` already uses) and pass it into `offload_runner(availability=..., ...)`. This removes `daedalus.doctor` from `offload.py`'s
  import surface entirely with a one-symbol, one-call-site change, and it is
  cheaper than merging (`doctor.check` legitimately serves many callers
  outside this SCC — `doctor.main()`, `selftest.py` — a merge would be
  artificial).

## Step 5 — tests that pin this

Grep `tests/ --include=*.py` for `daedalus.offload` / `from daedalus import
offload` / `from ..offload` / `from .offload` / `import offload`:
**36 test files, 69 matching lines [MEASURED]**:

```
tests/contracts/test_import_scc_hierarchy.py    tests/test_bridge_restart.py
tests/contracts/test_spine_outer_ports.py       tests/test_cascade.py
tests/gates/test_write_evidence_producer.py     tests/test_codex_provider.py
tests/gates/test_write_surface_lease_dominance.py tests/test_drafts.py
tests/kernel/test_chip_eda_effect_boundary.py   tests/test_dynamic.py
tests/kernel/test_leased_offload.py             tests/test_egress_lane_by_host.py
tests/kernel/test_offload_lease_outer_ports.py  tests/test_era1_robustness.py
tests/kernel/test_write_evidence_records.py     tests/test_fake_offload.py
tests/test_architecture_boundaries.py           tests/test_fence_anchoring.py
tests/test_attempt_boundary.py                  tests/test_lanes_checks.py
tests/test_benchmark_authority.py               tests/test_loop_lease.py
tests/test_bootstrap_receipt.py                 tests/test_loop_spend_refused.py
tests/test_offload_automint.py                  tests/test_repair_blast_radius_write.py
tests/test_offload_lease_harness.py             tests/test_selftest.py
tests/test_offload_unleased_planner.py          tests/test_semantic_route_wired.py
tests/test_offload_write_failclose.py           tests/test_unbounded_security_floor.py
tests/test_parallel_dispatch.py                 tests/test_verify_test_budget.py
tests/test_picker_work_queue.py                 tests/test_wave_spend_reservation.py
                                                 tests/test_write_guard_e2e.py
```

**`mock.patch`/`monkeypatch.setattr` string targets that pin exact symbol
paths [MEASURED, 25 lines]:** `"daedalus.offload._offload_impl"` (10x —
`tests/kernel/test_leased_offload.py:122,168`; `tests/test_loop_lease.py:227,257,390,410,439`; `tests/test_loop_spend_refused.py:142,274`;
`tests/test_wave_spend_reservation.py:121,434,455`) and
`"daedalus.offload.offload"` (5x — `tests/test_bootstrap_receipt.py:366`;
`tests/test_loop_lease.py:259`; `tests/test_parallel_dispatch.py:125,143`;
`tests/test_selftest.py:32,44`). `tests/kernel/test_chip_eda_effect_boundary.py`
patches `offload_lease._acquire_effect_lease_impl` (7x), the lease-issuer
side, not this module. A severance that renamed `_offload_impl`/`offload` or
moved the `FREE_LANES`/`check` import off module scope would not by itself
break these patches (they target the public names, not the import lines),
but relocating `_offload_impl`'s internal `if availability is None:` branch
changes behavior the tests in `test_offload_write_failclose.py` and
`test_offload_automint.py` exercise (e.g.
`test_codex_write_without_rollback_is_forced_advisory_and_escalates`,
`test_ollama_write_grant_is_unchanged`,
`test_landed_write_mints_once_into_quarantine`,
`test_advisory_run_never_reaches_the_minter`) and would need re-verification
against the new mandatory-`availability` contract. `tests/gates/test_write_surface_lease_dominance.py::test_the_offload_door_lease_dominates_its_bench_write` and `tests/contracts/test_import_scc_hierarchy.py` directly encode this
SCC's membership and the lease-dominance property of `_leased_bench_cascade`;
both would need re-running (not editing) after either severance.
