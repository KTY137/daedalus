# kairos.scheduler — SCC dossier

Module: `daedalus/kairos/scheduler.py` (515 lines; [MEASURED] via Read, full file)
Base: main @ 851ff43c (task brief); tree actually read at `wip/g1-freeze-2026-08-31` /
`main @ 54f0975398` working copy (both `git rev-parse HEAD` and the SubagentStart hook
report `54f09753`, not `851ff43c`) — noted, not resolved; no edits made either way.
[MEASURED discrepancy]

## Measured edges (raw AST probe)

Command: `.venv/Scripts/python.exe C:/Users/Administrator/scc-scratch/probe.py kairos.scheduler` [MEASURED]

```
### OUTGOING edges FROM kairos.scheduler to other SCC members
  -> kairos.gated_writes        FUNCTION-LOCAL (deferred)  in KairosScheduler.gate_concurrent_writes
       daedalus/kairos/scheduler.py:436   from .gated_writes import gate_candidates
  -> offload                    FUNCTION-LOCAL (deferred)  in KairosScheduler.dispatch._run_one
       daedalus/kairos/scheduler.py:273   from ..offload import offload

### INCOMING edges INTO kairos.scheduler from other SCC members
  <- build                      MODULE-LEVEL               in <module>
       daedalus/build.py:64   from .kairos.scheduler import KairosScheduler
  <- build_exec                 MODULE-LEVEL               in <module>
       daedalus/build_exec.py:82   from .kairos.scheduler import (
  <- core                       FUNCTION-LOCAL (deferred)  in plan_ikarus
       daedalus/core.py:960   from .kairos.scheduler import KairosScheduler
  <- core                       FUNCTION-LOCAL (deferred)  in _configure_report
       daedalus/core.py:1443   from .kairos.scheduler import KairosScheduler
  <- core                       FUNCTION-LOCAL (deferred)  in _try_ikarus
       daedalus/core.py:1218   from .kairos.scheduler import KairosScheduler
  <- offload                    MODULE-LEVEL               in <module>
       daedalus/offload.py:29   from .kairos.scheduler import FREE_LANES
```

### Verification of the probe

- **Outgoing #1** (`scheduler.py:436`, inside `KairosScheduler.gate_concurrent_writes`): read lines
  404–445. Real, unconditional `from .gated_writes import gate_candidates`, not inside `TYPE_CHECKING` or
  a dead branch — the imported name is called two lines later at line 442. Enclosing function/class
  correct (`KairosScheduler.gate_concurrent_writes`). [MEASURED]
- **Outgoing #2** (`scheduler.py:273`, inside `KairosScheduler.dispatch._run_one`, a nested closure): read
  lines 216–297. Real, unconditional `from ..offload import offload`, called at line 285
  (`offload(a.objective, repo_root, ...)`). Enclosing function is the nested closure `_run_one` defined
  inside `dispatch`, correctly reported by the probe with its qualified name. [MEASURED]
- Neither of these two module-level imports is annotation-only: `gate_candidates` and `offload` are both
  called as functions at runtime, and `from __future__ import annotations` (line 17) is irrelevant here
  since neither import is module-level to begin with — both are already function-local/deferred, so there
  is no "free cut via lazy annotations" available; the deferral has already happened. [MEASURED]
- **Incoming edges** spot-checked: `build.py:64`, `build_exec.py:82` are genuine module-level imports
  (read `daedalus/build.py:55-68` and `daedalus/build_exec.py:75-90`); `core.py`'s three sites (960, 1443,
  1218) are inside named functions per the probe, consistent with `core.py` being a large orchestration
  hub that lazily reaches for `KairosScheduler` only when actually dispatching — not independently
  re-verified line-by-line (out of scope: this dossier verifies **outgoing** edges per the task brief,
  incoming edges are reported as probe output plus one exception below). `offload.py:29` was verified
  directly (see Severance, below) because it is load-bearing for the mutual-cycle assessment.

### Dynamic references (AST-invisible)

Grepped `scheduler.py` for `importlib.import_module`, `__import__`: **0 matches** [MEASURED]. Grepped for
double-quoted string literals naming another SCC member as a bare identifier prefix (`"build`, `"core`,
`"offload`, etc.): the only hits are unrelated string literals (`"status"` dict keys, `"bounced"`,
`"planned"`, `"note"`) — none name another SCC module. [MEASURED] No dynamic cross-SCC reference found.

## What it actually does

`KairosScheduler` routes a list of `{objective, paths}` tasks through `route_and_select` to decide which
task goes to the free local bench (ollama/deepseek/codex_cli, gated by `FREE_LANES`) versus bouncing back
to the senior Claude lane, then either plans (dry run) or dispatches (live, via `offload()`) the accepted
ones, sequentially by default or in a bounded `ThreadPoolExecutor` for advisory-only concurrent work.
`dispatch()` also owns the wave-level `BudgetRefused` handling contract: a refusal mid-wave is reported as
a position-matched `spend_refused`/`spend_refused_not_attempted` result rather than letting the exception
unwind and drop already-produced results (see the large comment block at lines 40–63, itself evidence of a
previously measured bug). `gate_concurrent_writes()` is a second, safer write path that hands write-mode
`Assignment`s to `daedalus.kairos.gated_writes.gate_candidates` for isolated per-worktree gating instead of
sequential in-place writes, returning `GatedCandidate`s that still require a separate, explicit
`promote_candidates()` call — this module never lands a gated write itself.

## Layer

**orchestration**, and currently mis-sited (lives in `daedalus/kairos/`, which is not a target-layout
package name at all). By behaviour this module is pure mission/workitem scheduling and campaign-style wave
driving: task acceptance/routing (`accept`), dry-run planning (`plan`), decomposition (`spawn` →
`kairos.decompose.decompose`), bounded fan-out concurrency (`ThreadPoolExecutor` in `dispatch`), and
budget-aware wave bookkeeping (`spend_refused_result`, the whole comment block on why a refusal ends but
does not unwind a wave). None of that is a trust boundary in its own right: every effectful call is
delegated outward — live writes go through `offload()` (whose own effect-lease refusal is authoritative,
per the docstring at lines 220–256), and concurrent writes go through `gated_writes.gate_candidates` /
`promote_candidates`, neither of which this module authorizes or short-circuits. It also does not touch
policy, leases, evidence, or promotion state directly — it only *asks* for those capabilities via
parameters (`effect_authorization`, `effect_executions`) handed down from a caller, which the docstring at
line 227 explicitly frames as "never mints its own lease from ambient configuration." That is orchestration
behaviour (schedules/decomposes/fans-out, but does not itself hold trust-boundary authority), not kernel
behaviour.

## Severance

**Edge 1 — `-> kairos.gated_writes` (`gate_candidates`, function-local, 1 call site at line 442, 1 symbol
crossing).** Real coupling, not pass-through: `gate_concurrent_writes` exists specifically to delegate
concurrent-write gating to `gate_candidates`; there is no local reimplementation to strip. It is already
deferred (import cost is zero at module-load time). Cheapest severance: **(b) callback/parameter
injection.** Add an optional `gate_fn: Callable[..., list] | None = None` parameter to
`gate_concurrent_writes` (default `None`); when `None`, keep today's deferred `from .gated_writes import
gate_candidates` as the fallback (behaviour-preserving), and let a caller that already has a
`gated_writes.gate_candidates` reference (e.g. an orchestration entrypoint in `core.py`, which already
deferred-imports `KairosScheduler` three times) inject it directly, so `scheduler.py` need not import
`gated_writes` at all on that call path. Cheaper than (a) — one symbol, one call site does not justify a
new Protocol module — and (d) is wrong: per the `kairos.gated_writes` dossier's own conclusion, that module
belongs in `kernel` (trust boundary / promotion seam), not merged into an `orchestration`-layer scheduler.

**Edge 2 — `-> offload` (`offload`, function-local, 1 call site at line 285 inside the nested closure
`_run_one`, 1 symbol crossing).** Real coupling, not pass-through: this is the literal live-execution call
— `dispatch()`'s entire "not dry_run" behaviour is invoking `offload()`. Already deferred. Cheapest
severance: **(b) callback/parameter injection**, same shape as Edge 1 — thread a `runner:
Callable = None` field through `KairosScheduler` (constructor-injectable, lazily defaulting to the current
deferred `offload` import), so a caller that already owns an `offload` reference (`build_exec.WaveExecutor`,
the one production caller per the module's own docstring at lines 230–232) can hand it down instead of
`scheduler.py` importing `offload` itself.

**Assessing the sibling's `FREE_LANES` → `limit_policy.py` proposal, from the scheduler side.** [MEASURED]
`offload.py:29` (`from .kairos.scheduler import FREE_LANES`) is `offload.py`'s **only** dependency on
`kairos.scheduler` — grepped `offload.py` for `scheduler\.|KairosScheduler|Assignment\b` outside the
`FREE_LANES` line: 0 matches. `FREE_LANES` is used at `offload.py:414` and `:446` (`in FREE_LANES`
membership checks), and `daedalus/limit_policy.py` (36 lines, read in full) is already a pure
compatibility facade with **zero** state or SCC-crossing imports — it only re-exports from
`daedalus.kernel.policy.limits`, a non-SCC-member module — and `offload.py` already imports it (line 30,
`from .limit_policy import ExecutionLimitPolicy`). So the proposal's premise "which both sides already
import" is only half true: **`offload.py` already imports `limit_policy.py`; `scheduler.py` does not**
(grepped, 0 matches). The proposal is **correct in direction and sufficient to fully sever this specific
edge**: moving the `FREE_LANES = ("ollama", "deepseek", "codex_cli")` tuple into `limit_policy.py` removes
`offload.py`'s only import of `kairos.scheduler`, and since `scheduler.py`'s own edge to `offload` (Edge 2,
above) is already function-local/deferred, breaking the *offload → scheduler* leg is enough to break the
mutual 2-cycle outright — `scheduler.py` would need a one-line import addition (`from ..limit_policy import
FREE_LANES`) to keep using the constant itself (it is read at `scheduler.py:195`,
`if decision.provider not in FREE_LANES`), which is not an SCC-crossing edge. **Not yet done**: I found no
evidence in this tree that the move has been applied — `FREE_LANES` is still defined at `scheduler.py:33`
and `offload.py:29` still imports it from there. [MEASURED, as of this read]

## Tests that pin this

Grep `daedalus\.kairos\.scheduler|KairosScheduler\b` over `tests/*.py` (excluding `__pycache__`):
**14 files, 74 matching lines** [MEASURED, ripgrep count]. Files: `tests/contracts/test_import_scc_hierarchy.py`,
`tests/orchestration/test_run_mission.py`, `tests/test_agent_env.py`, `tests/test_agents_registry.py`,
`tests/test_bridge_restart.py`, `tests/test_dynamic.py`, `tests/test_loop.py`, `tests/test_loop_lease.py`,
`tests/test_loop_spend_refused.py`, `tests/test_parallel_dispatch.py`,
`tests/test_sensitivity_default_policy_pins.py`, `tests/test_unbounded_security_floor.py`,
`tests/test_wave_spend_reservation.py`, `tests/test_wave_spend_reservation_concurrency.py`.

`mock.patch`/`patch` string targets naming this module directly: **10 matches** [MEASURED] —
`tests/test_dynamic.py:178,222,267,385,415,443` all patch `"daedalus.kairos.scheduler.route_and_select"`
(functions `test_local_lane_eligible_runs_offload_not_claude`,
`test_effect_lease_denial_is_reported_without_claude_fallback`,
`test_terminal_wave_failure_never_dispatches_a_second_provider`,
`test_auto_report_names_external_provider_without_relabelling_lane`,
`test_local_lane_ineligible_refuses_unbrokered_claude_fallback`,
`test_local_only_lane_never_falls_through_to_claude`); `tests/test_loop.py:108,273,288,306` patch
`"daedalus.kairos.scheduler.KairosScheduler"` (line 108 at module/fixture scope; methods
`test_spend_bound_alone_halts`, `test_unreadable_budget_ledger_stops_the_loop`,
`test_budget_period_rollover_stops_rather_than_miscounting`). Every one of these string targets breaks if
`route_and_select` or `KairosScheduler` moves out of `daedalus.kairos.scheduler` (a rename/move edit, not
merely an import-order change) — they patch the name as resolved on the `scheduler` module object, not the
defining module.

Governance/architecture test: `tests/contracts/test_import_scc_hierarchy.py` names
`"daedalus.kairos.scheduler"` explicitly inside `OLD_CROSS_DOMAIN_COMPONENT` /
`CURRENT_CROSS_DOMAIN_COMPONENT` (lines 27–28) and asserts a frozen `CURRENT_COMPONENTS_SHA256` computed
from the *actual* measured SCC via `daedalus.structcore.cycles.nontrivial_components` — cutting either
outgoing edge (or the `offload → scheduler` `FREE_LANES` edge) changes real SCC membership and **must**
break/re-baseline this test by the file's own stated design ("Moving census, not an architecture invariant
... Re-measure and update them in the packet that moves them").

Not run (STATIC ANALYSIS ONLY per task rules); pass/fail after any severance edit is UNVERIFIED until
`.venv/Scripts/python.exe -m pytest` is actually executed by an authorized step.
