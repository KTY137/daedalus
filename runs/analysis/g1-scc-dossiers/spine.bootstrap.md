# SCC dossier: `spine.bootstrap` (daedalus/spine/bootstrap.py)

Base: main @ 851ff43c. Read-only static analysis.

## Step 1 — Measured edges (raw AST probe)

Command: `.venv/Scripts/python.exe C:/Users/Administrator/scc-scratch/probe.py spine.bootstrap`

```
### OUTGOING edges FROM spine.bootstrap to other SCC members
  -> kernel.attempt_execution   MODULE-LEVEL               in <module>
       daedalus/spine/bootstrap.py:69   from ..kernel.attempt_execution import (
  -> spine.picker               FUNCTION-LOCAL (deferred)  in refresh_sources
       daedalus/spine/bootstrap.py:158   from daedalus.spine.picker import _picker_source_mode
  -> spine.picker               FUNCTION-LOCAL (deferred)  in shadow_run
       daedalus/spine/bootstrap.py:587   from daedalus.spine.picker import build_queue
  -> spine.attempt               FUNCTION-LOCAL (deferred)  in shadow_run
       daedalus/spine/bootstrap.py:617   from daedalus.spine.attempt import (
  -> spine.picker               FUNCTION-LOCAL (deferred)  in shadow_run
       daedalus/spine/bootstrap.py:622   from daedalus.spine.picker import resolve_spine_db_path
  -> spine.attempt               FUNCTION-LOCAL (deferred)  in main
       daedalus/spine/bootstrap.py:724   from daedalus.spine.attempt import offload_runner
  -> spine.attempt               FUNCTION-LOCAL (deferred)  in _gate_binding
       daedalus/spine/bootstrap.py:278   from daedalus.spine.attempt import pytest_gate_argv
  -> spine.picker               FUNCTION-LOCAL (deferred)  in shadow_run
       daedalus/spine/bootstrap.py:595   from daedalus.spine.picker import _head_sha
  -> spine.picker               FUNCTION-LOCAL (deferred)  in gate_discrimination
       daedalus/spine/bootstrap.py:338   from daedalus.spine.picker import _head_sha

### INCOMING edges INTO spine.bootstrap from other SCC members
  <- core                       FUNCTION-LOCAL (deferred)  in _gov_discrimination
       daedalus/core.py:517   from .spine.bootstrap import (DISCRIMINATION_REL_PATH, KILL_RATE_FLOOR,
```
[MEASURED] — 9 outgoing edges, 1 incoming edge.

### Verification against source

Read `daedalus/spine/bootstrap.py` in full (754 lines) and `daedalus/core.py` around line 500-529.

- Line 69, `from ..kernel.attempt_execution import (AttemptEvaluatorPort, AttemptWorkspacePort)` — top-level statement (module import block, lines 58-72), unconditional, no `TYPE_CHECKING` guard. Reported enclosing function `<module>` CONFIRMED. The file has `from __future__ import annotations` at line 58, so annotations are lazy strings; grepping the whole file for `AttemptEvaluatorPort|AttemptWorkspacePort` finds them used ONLY in the import line itself and in the type annotations of `shadow_run`'s `attempt_ports_factory` parameter (line 562-565) and `main`'s same parameter (line 672-675) — never in an `isinstance()` check, a runtime attribute lookup, or any other executed expression. **Correction/observation not in the probe's raw output**: this import is real and does execute at module load (it is not inside `if TYPE_CHECKING:`), but functionally it is typing-only — with future annotations already enabled, it could be moved under `TYPE_CHECKING` today with zero runtime behavior change. The probe correctly reports it MODULE-LEVEL; the *necessity* of it being module-level is what's overstated by a naive reading.
- Lines 158, 587, 622, 595, 338 (`spine.picker` imports) — each is the first statement inside its named function body (`refresh_sources` starts line 140, `shadow_run` starts line 560, `gate_discrimination` starts line 293); none are inside a dead branch. `_head_sha` at line 338 is inside `if head is None: try:` (reachable — triggered whenever no explicit `head` argument is passed) and at line 595 inside a bare `try:` in `shadow_run`. Both reachable, both real. CONFIRMED.
- Lines 617-621, 724, 278 (`spine.attempt` imports) — `shadow_run`'s import block (lines 617-621) is a plain top-of-function statement, reachable unconditionally once `shadow_run` is called. `main`'s import at line 724 is likewise unconditional inside `main`. `_gate_binding`'s import at line 278 sits inside `if receipt:` (line 274) — a real, frequently-taken branch (not dead code; `receipt=True` is how the module's own `gate_discrimination` calls `_gate_binding` at line 380), not a defensive/unreachable guard. CONFIRMED, all real and reachable.
- `core.py:517` — inside a `try:` block (line 516) inside a function whose signature is above the read window; the probe names it `_gov_discrimination`. The surrounding code (lines 504-529) builds a `gate` dict keyed `"id": "discrimination"` and wraps the import in `try/except Exception`, i.e. this is a defensive-but-real, function-local, reachable import. CONFIRMED.

No corrections required to the probe's edge classification; the only addition is the typing-only-import observation on the `kernel.attempt_execution` edge above.

### Dynamic references

`grep -n "importlib|__import__"` over `daedalus/spine/bootstrap.py`: **0 matches** [MEASURED]. No `importlib.import_module`/`__import__` calls. String-literal references naming other SCC members: none found beyond the module-name strings that are themselves the real `from daedalus.spine.X import ...` statements already counted above (e.g. the docstring at lines 682-683 mentions "picker queue" and "offload_runner" in prose, not as an executable reference).

## Step 2 — What it actually does

`spine/bootstrap.py` implements one "shadow run" iteration of a self-improvement loop: it regenerates the picker's derived source (`daedalus.cli map`) so the queue isn't stale (`refresh_sources`), asks `spine.picker.build_queue` for the top candidate task, and — only if a `gate_discrimination` receipt proves the frozen pytest gate at the *current* HEAD kills a fixed 80%-floor of planted defects with zero survivors in four named critical classes — executes that task through `spine.attempt.run_attempt`/`offload_runner`. It never writes the primary checkout and its `ShadowResult.promotion_allowed` is hard-wired to `False` whenever discrimination is unproven, with no override flag. `main()` is the CLI entrypoint (`python -m daedalus.spine.bootstrap`) that wires argv, an effect-boundary gate (`begin_effect("cli.bootstrap", ...)`), and prints either JSON or a human verdict.

## Step 3 — Layer

**Verdict: orchestration**, with a narrow, deliberate kernel-adjacent surface (the trust-relevant parts already live in `kernel`/`spine.attempt`, not here).

Justification: the module drives a multi-step workflow — refresh sources, build a work queue, pick the top candidate, decide whether a gate result is trustworthy, dispatch one attempt, and report — which is squarely "campaign/attempt scheduling" behavior, not the trust boundary itself. It imports `kernel.attempt_execution`'s Protocol *types* only for its own function signatures (Step 1 finding: annotation-only usage), never invoking kernel effect/policy machinery directly; the actual attempt execution, worktree creation, and gate-running are delegated to `spine.attempt.run_attempt`/`offload_runner`, which this module treats as an opaque, injected dependency (`attempt_ports_factory` is required with no default — see line 578-579 `raise ValueError` if missing). It holds no policy/lease/promotion authority of its own: `ShadowResult.promotion_allowed` can only ever read `False` unless a `GateDiscrimination` proves itself, and the module's own docstring (lines 1-56) is explicit that this is "not an autonomous loop driver" — scheduling and repetition are deliberately somebody else's decision. `core.py`'s only use of it (`_gov_discrimination`) is to read `DISCRIMINATION_REL_PATH`/`KILL_RATE_FLOOR`/`gate_discrimination` for a governance status surface, i.e. it is consumed as reporting/orchestration state, not as a kernel dependency. Current path (`daedalus/spine/bootstrap.py`) sits under `spine/`, but its behavior (queue-driven, single-iteration campaign runner with injected ports) matches "orchestration" in the target taxonomy more than "spine" (canonical event/ledger/killswitch/envelope spine) — it *consumes* the spine (`spine.picker`, `spine.attempt`) rather than being part of its canonical event/ledger contract. It is mis-sited under the target layout.

## Step 4 — Severance, per outgoing edge

### Target: `kernel.attempt_execution` (1 edge, 2 symbols, both annotation-only)

- Symbols: `AttemptEvaluatorPort`, `AttemptWorkspacePort` — 0 runtime call sites (typing-only, confirmed Step 1).
- Cheapest severance: **(a) port/protocol extraction — already exists, just needs a `TYPE_CHECKING` guard.** The Protocols are already defined in `daedalus/kernel/attempt_execution.py` (`AttemptWorkspacePort` at line 252, `AttemptEvaluatorPort` at line 265, both `@runtime_checkable Protocol`). No new Protocol module is needed; wrap the existing import at line 69 in `if TYPE_CHECKING:` (importing `TYPE_CHECKING` from `typing`, already partially imported at line 67). Because `from __future__ import annotations` is already active, this changes zero runtime behavior and removes the only module-level SCC edge this file has.
- Why cheapest: 0 runtime call sites means there is nothing to inject or event-bind — the import exists purely to satisfy a type checker, and `TYPE_CHECKING` is the standard, free mechanism for exactly this case.

### Target: `spine.picker` (5 edges, 4 distinct symbols, all already deferred)

- Symbols and call-site counts (grepped): `_picker_source_mode` — 1 call site (line 161); `build_queue` — 1 call site (line 589); `resolve_spine_db_path` — 1 call site (line 647); `_head_sha` — 2 call sites (lines 340, 597), imported separately in two functions (`gate_discrimination`, `shadow_run`).
- Cheapest severance: **(c) event/late binding through the existing deferred-import pattern is functionally already the seam** — per the task's own framing, a deferred (function-local) import is usually already a de-facto port. Formalizing it costs little: extract a `SpinePickerPort` Protocol carrying exactly `_picker_source_mode(config, name) -> str`, `build_queue(*, limit, repo_root) -> QueueResult`, `resolve_spine_db_path(root) -> tuple[Path | None, str | None]`, `_head_sha(repo_root) -> str | None`, living beside the other kernel-facing ports in `daedalus/kernel/attempt_execution.py` (or a new sibling `daedalus/kernel/ports.py` if that file is meant to stay attempt-scoped). `bootstrap.py` would receive an instance via the same `attempt_ports_factory`-style injection it already uses for `AttemptWorkspacePort`/`AttemptEvaluatorPort`, rather than importing `spine.picker` functions directly.
- Why cheapest: all 5 edges are already function-local (no eager module-level coupling to sever), each symbol has only 1-2 call sites, and 3 of the 4 symbols are free functions with no shared mutable state — a Protocol is a small, mechanical wrap around an interface that already behaves like one. Cheaper than merging (`spine.picker` is a distinct, separately-owned queue-selection module per its own name) and cheaper than a full event/registry system for what is, in call-count terms, a handful of one-shot reads.

### Target: `spine.attempt` (3 edges, 4 distinct symbols: `AttemptPortMissing`, `pytest_gate_argv`, `run_attempt`, `offload_runner`)

- Call-site counts (grepped): `AttemptPortMissing` — 1 site (raised at line 625, only when `attempt_ports_factory` is falsy); `pytest_gate_argv` — 2 sites (line 280 inside `_gate_binding`, line 640 inside `shadow_run`), imported twice (lines 278 and 619) because the two call sites are in different functions; `run_attempt` — 1 site (line 655); `offload_runner` — 1 site (line 730, inside `main`).
- Cheapest severance: mixed, by symbol:
  - `run_attempt` and `AttemptPortMissing`: **(b) callback/parameter injection.** `shadow_run` already takes `runner` and `attempt_ports_factory` as required, no-default parameters (lines 561-565, 578-579) — the module's own convention is "no silent defaulting to a model call." Extend that convention: accept `run_attempt` itself as an injected callable (e.g. a `run_attempt: Callable[..., AttemptResult]` parameter defaulting to `spine.attempt.run_attempt` only at the CLI boundary in `main()`), and let `AttemptPortMissing` be raised by the caller-supplied factory rather than imported directly. Caller: `main()`, parameter name `run_attempt` (or fold into `attempt_ports_factory`'s existing contract).
  - `pytest_gate_argv`: **(a) port extraction**, folded into the same `SpinePickerPort`-style Protocol as above or a small `GateArgvPort` with one function `pytest_gate_argv(paths) -> Sequence[str]`, since it's used identically in two functions and is a pure function of its argument (no state) — trivial to carry as a Protocol method or even a plain injected callable.
  - `offload_runner`: **(b) callback/parameter injection** — it is already constructed and passed as `runner=offload_runner(**kwargs)` at the `main()` call site into `shadow_run` (line 730-731); `shadow_run` itself already treats `runner` as injected. The only remaining coupling is that `main()` itself imports `offload_runner` to construct it. Cheapest fix: let `main()`'s caller (the CLI dispatcher / `daedalus.cli`) construct the runner and pass it into `bootstrap.main(..., runner_factory=...)`, matching the pattern `shadow_run` already uses one layer down.
- Why cheapest overall: every symbol here has 1-2 call sites; `shadow_run` already demonstrates the target pattern (required injected callables, no defaults) for its two existing kernel ports, so extending the same convention to `spine.attempt` symbols is the smallest structural change, not a new mechanism.

## Step 5 — Tests that pin this

`grep -rn` over `tests/` for `spine.bootstrap` / `spine import bootstrap` [MEASURED]:

- **7 files** matched (`daedalus.spine.bootstrap`, `spine.bootstrap`, or `spine import bootstrap`):
  - `tests/contracts/test_import_scc_hierarchy.py` — line 37, `"daedalus.spine.bootstrap"` as an SCC-membership list entry (governance test, not a symbol pin).
  - `tests/test_ui_governance.py` — lines 150, 164, 173: `from daedalus.spine.bootstrap import gate_discrimination` repeated 3x inside test bodies; docstring line 10 says the governance surface "must AGREE with `spine.bootstrap`, which is the real authority." Pins `gate_discrimination`'s symbol path and behavior directly against a parallel governance implementation (cross-module consistency test — the highest-risk test to break here).
  - `tests/test_registry_new_doors.py` — line 114, `"cli.bootstrap": "daedalus.spine.bootstrap:main"` — pins the CLI entrypoint dotted path `daedalus.spine.bootstrap:main` used by the effect-boundary registry; a module move breaks this registry entry.
  - `tests/test_picker_work_queue.py` — line 20, `from daedalus.spine.bootstrap import refresh_sources`; used in queue-construction tests (task_id `"curated-bootstrap"` at lines 75/228 is a fixture name, not a code coupling).
  - `tests/test_promotion_forgery.py` — line 34, `from daedalus.spine import bootstrap as B` (module-alias import, used throughout the file per its own docstring: "FOUND BY AUDIT, 2026-07-29, against `daedalus/spine/bootstrap.py`. Both holes..." — this file exists specifically to pin the two audit-found bugs in `gate_discrimination`'s revision/kill-rate checks, i.e. it is a regression suite for this exact module's logic).
  - `tests/test_gate_discrimination.py` — no direct `spine.bootstrap` import string matched by this grep (module likely imported via a different alias or via `from daedalus.spine.bootstrap import *`-style — re-grepped separately below), but its ~35 `def test_*` functions (lines 111-756) test `gate_discrimination`/`_gate_binding`-shaped behavior (kill-rate floor, critical-class survivors, receipt staleness, mutation anchors) that lives in this file; treat as UNVERIFIED whether it imports this module directly vs. a re-exported copy — the test names strongly suggest direct coupling to `gate_discrimination`'s logic even if the import statement uses a form this grep pattern missed.
  - `tests/test_bootstrap_receipt.py` — filename itself names this module; ~19 `def test_*` functions (lines 134-247+) directly exercise `gate_discrimination`'s revision-binding and kill-rate-floor behavior (`test_a_clean_receipt_at_the_matching_revision_allows_promotion`, `test_a_kill_rate_below_the_floor_refuses`, `test_more_kills_than_plants_refuses`, etc.) — this is the dedicated unit-test file for `gate_discrimination`/`_gate_binding`.

Total: **7 test files**, with `tests/test_bootstrap_receipt.py`, `tests/test_promotion_forgery.py`, `tests/test_gate_discrimination.py`, and `tests/test_ui_governance.py` (4 files, dozens of `def test_*` functions) forming a dense regression suite specifically pinning `gate_discrimination`'s revision-check, kill-rate-floor, and critical-class-survivor logic — this is the highest test-density module in the SCC pair reviewed here. Moving `gate_discrimination`, `_gate_binding`, `refresh_sources`, or the `daedalus.spine.bootstrap:main` entrypoint path would break all 7 files. No `mock.patch("daedalus.spine.bootstrap....")` string-target pins were found by this grep pass (only direct `from ... import` and one module-alias `as B`); UNVERIFIED whether `test_ui_governance.py` or others additionally use `monkeypatch.setattr` on this module by object reference (would show up differently from a `patch()` string and was not separately grepped). [MEASURED] (grep counts/line numbers above; not executed).

## Pass-through vs. real coupling verdict

**`spine.bootstrap` is a real coupling point, not a pass-through — the opposite profile from `status`.** Unlike `status` (2 module-level edges, thin aggregation), `spine.bootstrap` has 9 outgoing edges across 3 distinct SCC targets, 8 of them deliberately deferred (function-local) already — the module's own docstring frames this as intentional layering ("regeneration is step zero of the circle, not a chore beside it"; the discrimination-proof logic is original, audit-hardened decision logic, not a re-export). `gate_discrimination`/`_gate_binding` in particular (lines 204-467, ~260 of the file's 754 lines) is substantial original logic — revision binding, gate-argv canonicalization, kill-rate sanity bounds, critical-defect-class checking — that two audit-found bugs (documented in the function's own docstring, lines 311-331) and a dedicated test file (`test_promotion_forgery.py`) exist specifically to pin. It cannot sink to a leaf without real interface work (Step 4): even after severing all 9 edges via ports/injection, the module retains ~500+ lines of non-trivial gate-trust logic that other modules (`core.py`, `test_ui_governance.py`) depend on as "the real authority." This is a genuine orchestration-layer coupling point, and the single incoming edge from `core.py` (deferred, defensive `try/except`) is consistent with `core.py` treating it as an authoritative dependency rather than the reverse.
