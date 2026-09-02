# spine.attempt — SCC dossier

Base: main @ 851ff43c. File: `daedalus/spine/attempt.py` (297 lines, read in full).

## Step 1 — Measured edges (raw AST probe)

Command: `.venv/Scripts/python.exe C:/Users/Administrator/scc-scratch/probe.py spine.attempt`

```
### OUTGOING edges FROM spine.attempt to other SCC members
  -> kernel.attempt_execution   MODULE-LEVEL               in <module>
       daedalus/spine/attempt.py:24   from daedalus.kernel import attempt_execution as _owner

### INCOMING edges INTO spine.attempt from other SCC members
  <- build_exec                 FUNCTION-LOCAL (deferred)  in _cancel_requested
       daedalus/build_exec.py:172   from .spine.attempt import _as_predicate
  <- ikarus_supervisor          MODULE-LEVEL               in <module>
       daedalus/ikarus_supervisor.py:65   from .spine.attempt import (
  <- kernel.promotion           FUNCTION-LOCAL (deferred)  in snapshot_promotion_candidates
       daedalus/kernel/promotion.py:174   from daedalus.spine.attempt import (
  <- progress_sources           FUNCTION-LOCAL (deferred)  in track_call
       daedalus/progress_sources.py:339   from .spine.attempt import AttemptResult
  <- spine.bootstrap            FUNCTION-LOCAL (deferred)  in shadow_run
       daedalus/spine/bootstrap.py:617   from daedalus.spine.attempt import (
  <- spine.bootstrap            FUNCTION-LOCAL (deferred)  in main
       daedalus/spine/bootstrap.py:724   from daedalus.spine.attempt import offload_runner
  <- spine.bootstrap            FUNCTION-LOCAL (deferred)  in _gate_binding
       daedalus/spine/bootstrap.py:278   from daedalus.spine.attempt import pytest_gate_argv
  <- spine.picker                FUNCTION-LOCAL (deferred)  in _default_attempt
       daedalus/spine/picker.py:2843   from daedalus.spine.attempt import (
  <- spine.picker                FUNCTION-LOCAL (deferred)  in Candidate.to_task_spec
       daedalus/spine/picker.py:305   from daedalus.spine.attempt import TaskSpec
```
[MEASURED]

Note: incoming-edge count. The task brief states 6 importing members (build_exec, ikarus_supervisor, kernel.promotion, progress_sources, spine.bootstrap, spine.picker) [INHERITED]; the raw probe output above lists 9 edge lines because `spine.bootstrap` and `spine.picker` each import it from more than one function (3 and 2 sites respectively). Distinct **importing modules** = 6, matching the brief. [MEASURED]

### Verification / corrections

- Line 24: `from daedalus.kernel import attempt_execution as _owner` — module-level, not inside `if TYPE_CHECKING:`, confirmed real. [MEASURED — read lines 1-24]
- **Correction to any "annotation-only, free cut" hypothesis**: `_owner.` is referenced **35 times** in the file's 297 lines (grep count), including inside function *bodies* at runtime (`_owner.time.monotonic()`, `_owner._now_iso()`, `_owner.require_storage(...)`, `_owner.TaskAttempt`, `_owner.AttemptResult(...)`, `_owner.STATE_*` constants used as return values, etc. — see `TaskAttempt.run()`, lines 156-250). This import is genuinely load-bearing at runtime; `from __future__ import annotations` (line 16) does not make it a free cut the way it does for `spine.picker`'s `AttemptEvaluatorPort`/`AttemptWorkspacePort`. [MEASURED]
- No `importlib.import_module`, `__import__`, or SCC-member string literals found by grep. [MEASURED — empty match]
- Two additional non-SCC deferred imports inside `TaskAttempt.run()` and `command_gate()` are worth noting because they explain *why* the effect-boundary logic lives here rather than in the kernel: `from daedalus.spine.effect_boundary import (REGISTRY_BY_ID, GuardDecision, begin_effect)` (line 86-90, inside `command_gate`) and `from daedalus.spine.effect_boundary import (REGISTRY_BY_ID, EffectBoundaryError, begin_effect)` plus `from daedalus.spine.receipts import ATTEMPT_ENTRYPOINT_ID` (lines 208-213, inside `TaskAttempt.run`). Neither `effect_boundary` nor `receipts` is one of the 18 SCC members, so these don't add SCC-internal edges, but they are the mechanism by which this module enacts trust-boundary behavior (see Step 3). [MEASURED]

## Step 2 — What it actually does (full 297-line file read)

The module's own docstring (lines 1-15) states its role precisely: a "registered Attempt effect door and fail-closed compatibility facade" whose lifecycle implementation is owned by `kernel.attempt_execution` (`_owner`). Concretely: (1) `command_gate`/`pytest_gate` (lines 71-146) wrap `_owner._command_gate`/`_owner.pytest_gate_argv`, refusing (`AttemptPortMissing`) unless a `scratch_cleanup` capability is injected, and call `daedalus.spine.effect_boundary.begin_effect` with a `GuardDecision` naming `"containment.attempt"` before returning the gate callable — i.e. it enforces a containment precondition the kernel gate itself does not check. (2) `TaskAttempt` (lines 149-250) subclasses `_owner.TaskAttempt` and overrides `run()` to call `_owner.require_storage`, resolve the ledger, then call `begin_effect(ATTEMPT_ENTRYPOINT_ID, ...)` from `spine.effect_boundary` before delegating to `self._run_with_ledger` (inherited from `_owner`) — this is the actual attempt-entrypoint trust-boundary check. (3) The trailing `_AttemptFacade` (`ModuleType` subclass, lines 270-296) replaces the module's own class so that any attribute *not* in the small `_COMPOSITION_NAMES` set (`TaskAttempt`, `run_attempt`, `command_gate`, `pytest_gate`, the two `_remove_gate_tmpdir` names) transparently forwards `getattr`/`setattr` to `_owner` — this is how `AttemptResult`, `TaskSpec`, `offload_runner`, `GateResult`, the `STATE_*` constants, etc. (all listed in `__all__`, lines 27-52) become importable from `spine.attempt` while being *defined* only in `kernel.attempt_execution`.

## Step 3 — Layer

**Verdict: kernel (trust-boundary enforcement), currently mis-sited under `daedalus/spine/`.**

Justification: the only code this module actually *originates* (as opposed to forwards) is effect-boundary enforcement — `begin_effect(ATTEMPT_ENTRYPOINT_ID, ...)` inside `TaskAttempt.run()` and `begin_effect("python.command_gate", ...)` inside `command_gate()`, both calling into `daedalus.spine.effect_boundary`'s `REGISTRY_BY_ID`/`GuardDecision` machinery, plus the fail-closed refusal (`AttemptPortMissing`) when a `scratch_cleanup` port isn't injected. That is exactly the brief's definition of `kernel`: "trust boundary: effects, leases, policy, attempts, promotion, evidence." Everything else in the file (`AttemptResult`, `TaskSpec`, `GateResult`, the `STATE_*` constants, `offload_runner`, `pytest_gate_argv`, etc.) is not defined here at all — it is defined in `daedalus/kernel/attempt_execution.py` and only *reachable* via this module's forwarding facade. Per the brief's instruction not to treat package location as proof: living in `daedalus/spine/` does not make this spine-layer; its only real behavior is a kernel-layer effect-boundary check gating entry into `kernel.attempt_execution`'s lifecycle, so the natural split point is: the `_AttemptFacade` forwarding shell either collapses into `kernel/attempt_execution.py` directly (Step 4, edge analysis below argues this), or — if a compatibility shim must survive for the 6 importers — it should be renamed/relocated to make clear it is a `kernel`-owned door, not `spine` machinery.

## Step 4 — Severance (the one outgoing edge)

### Edge: `attempt.py:24` → `kernel.attempt_execution` (`_owner`, whole-module alias import), MODULE-LEVEL

- Symbols crossing: effectively the **entire module namespace** (35 call sites of `_owner.X` for at least a dozen distinct names: `TaskAttempt`, `AttemptResult`, `time`, `_now_iso`, `require_storage`, `StorageUnavailable`, `STATE_STORAGE_UNAVAILABLE`, `STATE_CANCELLED`, `STATE_WORKTREE_FAILED`, `_existing_ancestor`, `ScratchCleanupPort`, `DEFAULT_GATE_TIMEOUT_S`, `_command_gate`, `pytest_gate_argv`, `AttemptPortMissing`, `_remove_gate_tmpdir`, plus everything reachable only via `__getattr__` forwarding — `TaskSpec`, `GateResult`, `offload_runner`, `PatchArtifact`, `RunnerContext`, `GitCommandError`, `PrimaryCheckoutWrite`, `READ_ONLY_REPO_VERBS`, `INTENT_KIND`, `ATTEMPT_STATES`).
- Call-site count for the module-level alias itself: not a handful of named imports but a wildcard-style `as _owner` alias, so counting "call sites by grepping the imported symbols" is really "grep `_owner\.` → 35", confirming this is not annotation-only and not a narrow seam.
- **Cheapest: (d) genuine merge with the target.** The split between `spine/attempt.py` and `kernel/attempt_execution.py` is artificial: `spine/attempt.py` defines almost nothing of its own (only `command_gate`, `pytest_gate`, `TaskAttempt.run()` override, `run_attempt`, and the `_AttemptFacade` plumbing that exists solely to make the other module's names importable from this path). The 6 real importers (`build_exec`, `ikarus_supervisor`, `kernel.promotion`, `progress_sources`, `spine.bootstrap`, `spine.picker`) either want the effect-door wrappers (`command_gate`/`pytest_gate`/`TaskAttempt`/`run_attempt` — 5 names) or the forwarded kernel types (`AttemptResult`, `TaskSpec`, `offload_runner`, `_as_predicate`, `pytest_gate_argv` — all defined in `kernel.attempt_execution`, not here). Merging the 5 real seams (`command_gate`, `pytest_gate`, `TaskAttempt`, `run_attempt`, `_remove_gate_tmpdir`) directly into `kernel/attempt_execution.py` and re-pointing the 6 importers at `kernel.attempt_execution` collapses this SCC edge to zero (this module becomes a leaf with no outgoing SCC edge, matching what its own docstring already says the *values* are — "the single owner module") — this is confirmed by the brief's own inherited measurement that cutting this exact edge collapses the SCC 18→16.
- **If merge is rejected** (e.g. because `daedalus.spine.attempt` is a historically load-bearing import path for external callers, per the module's own docstring: "keeps the historical import target"), the fallback is **(c) event/late binding through an existing registry**: `daedalus.spine.effect_boundary.REGISTRY_BY_ID` is already the existing registry both `command_gate` and `TaskAttempt.run()` consult; the module could register itself as a *pure* registry entry (its `EntrypointSpec`) without importing `kernel.attempt_execution` by name at module level, deferring the `_owner` binding to first call (this only removes the MODULE-LEVEL classification, not the edge itself, so it's strictly worse than (d)).

### Direct answer to the brief's question

**Is `spine.attempt` a genuine shared contract that should sink to a lower layer with ZERO outgoing edges, or a grab-bag facade?**

It is explicitly, by its own docstring, a **compatibility facade** ("fail-closed compatibility facade... does not select a workspace manager or evaluator... All non-composition attributes are resolved from, and monkeypatch assignments are forwarded to, the single owner module"). It is not a grab-bag in the sense of accreted unrelated responsibilities — every one of its ~5 real (non-forwarded) symbols is the same kind of thing (a fail-closed effect door around one `kernel.attempt_execution` operation) — but it is also not a "shared contract" in the sense of an independent abstraction: it has no types or behavior of its own that `kernel.attempt_execution` doesn't already define or that couldn't move there directly. Given it already has the SCC's highest in-degree (6 distinct importers) and exactly one outgoing edge, sinking it to zero outgoing edges is achievable and is the change the brief's own inherited measurement already priced (18→16). The cheapest way to reach zero outgoing edges is the merge in Step 4, not a "sink layer" placement that keeps it as a separate module — a separate module with zero outgoing edges and one purpose (forward to `kernel.attempt_execution`) is strictly a thinner version of what it already is today.

**Does `spine.attempt` act as the composition root binding `offload_runner` for the kernel?** No — checked directly: `offload_runner` is **defined** in `daedalus/kernel/attempt_execution.py:1198` (`def offload_runner(**offload_kwargs: Any) -> Callable[[RunnerContext], Any]`), not in `spine/attempt.py`. `spine/attempt.py` only *re-exports* the name (it appears in `__all__`, line 48, and is reachable only via `_AttemptFacade.__getattr__` forwarding to `_owner`, since it is not among the 5 names in `_COMPOSITION_NAMES`, lines 258-267, that are actually defined locally). The real composition-root behavior — constructing `offload_runner(**kwargs)` and handing it to a runner — happens at the **call sites** in `daedalus/spine/bootstrap.py:724` and `daedalus/spine/picker.py:2912`, both of which import `offload_runner` from `daedalus.spine.attempt` (the facade) but invoke it themselves. So `spine.attempt` is not itself the composition root for `offload_runner` bindings; it is a name-forwarding pass-through, and the sibling analyst's claim does not hold under direct inspection — the composition happens one layer further out (`spine.bootstrap.main`, `spine.picker._default_attempt`), which is consistent with `spine.attempt`'s own docstring statement that "concrete production composition belongs to `daedalus.orchestration.execution.attempts`."

## Step 5 — Tests that pin this

[MEASURED] Grep of `tests/` for `spine\.attempt|spine import attempt|from daedalus\.spine import attempt`: **44 files**. Grep for the literal substring `daedalus.spine.attempt` (also captured together with `daedalus.spine.picker` above) contributes to the same **112 occurrences / 49 files** combined count; isolating `daedalus.spine.attempt` alone was not separately re-run — treat the per-file counts below as the reliable measurement.

Most directly named test files (function-name counts via `grep '^def test_'`):
- `tests/test_spine_attempt.py` — **39** test functions [MEASURED]
- `tests/test_spine_attempt_containment.py` — **16** test functions [MEASURED]

Other files matching `spine\.attempt` usage (present, not individually function-counted; UNVERIFIED beyond file-level grep match): `tests/contracts/test_import_scc_hierarchy.py`, `tests/test_shed_telemetry.py`, `tests/test_picker_work_queue.py`, `tests/test_killswitch.py`, `tests/test_ikarus_supervisor.py`, `tests/test_ikarus_runtime_role.py`, `tests/test_ignition_gate1.py`, `tests/test_git_is_a_process_launcher.py`, `tests/test_gate_containment.py`, `tests/test_criterion_imports_declaration.py`, `tests/test_criterion_imports.py`, `tests/test_containment_scope.py`, `tests/test_cli_effect_boundary.py`, `tests/test_canonical_execution_limit_policy.py`, `tests/test_attempt_contracts_live_path.py`, `tests/test_attempt_undeclared_scope.py`, `tests/test_attempt_boundary.py`, `tests/test_assurance_hardening.py`, `tests/orchestration/test_attempt_composition_hierarchy.py`, `tests/kernel/test_attempt_lease.py`, `tests/kernel/test_attempt_execution_hierarchy.py`, `tests/contracts/test_uncomposed_gate_callers.py`, `tests/test_unbounded_security_floor.py`, `tests/test_gate_containment_job_caps.py`, `tests/test_system_check.py`, `tests/test_spine_return_arc.py`, `tests/test_shadow_run.py`, `tests/test_selftest.py`, `tests/test_promotion_trust_root_adversarial.py`, `tests/test_primary_tree_fence.py`, `tests/test_promotion_forgery.py`, `tests/test_picker_outcome.py`, `tests/test_kernel_contracts.py`, `tests/test_gate_discrimination.py`, `tests/test_gate_judges_the_candidate.py`, `tests/test_eval_correctness.py`, `tests/test_bootstrap_receipt.py`, `tests/kernel/test_sealed_promotion.py`, `tests/kernel/test_promotion_material_review.py`, `tests/kernel/test_live_promotion_seam.py`, `tests/kernel/test_persisted_promotion_authorization.py`.

**Governance/architecture pin**: `tests/contracts/test_import_scc_hierarchy.py` hardcodes the literal string `"daedalus.spine.attempt"` (line 36) inside the same frozen 18-member `CURRENT_CROSS_DOMAIN_COMPONENT` set discussed in the `spine.picker` dossier, protected by `CURRENT_COMPONENTS_SHA256`. [MEASURED]

No `mock.patch("daedalus.spine.attempt....")` string-target hits were found by grep restricted to that exact prefix pattern (search was combined with `spine.picker` above and returned zero matches for `attempt`; the `mock.patch` hits found were all `daedalus.spine.picker.build_queue`). UNVERIFIED whether any test patches `daedalus.spine.attempt.<name>` by string outside that pattern — not separately re-run.
