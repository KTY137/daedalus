# spine.picker — SCC dossier

Base: main @ 851ff43c. File: `daedalus/spine/picker.py` (2925+ lines; `main()` runs to ~3010).

## Step 1 — Measured edges (raw AST probe)

Command: `.venv/Scripts/python.exe C:/Users/Administrator/scc-scratch/probe.py spine.picker`

```
### OUTGOING edges FROM spine.picker to other SCC members
  -> kernel.attempt_execution   MODULE-LEVEL               in <module>
       daedalus/spine/picker.py:72   from ..kernel.attempt_execution import (
  -> spine.attempt              FUNCTION-LOCAL (deferred)  in _default_attempt
       daedalus/spine/picker.py:2843   from daedalus.spine.attempt import (
  -> spine.attempt              FUNCTION-LOCAL (deferred)  in Candidate.to_task_spec
       daedalus/spine/picker.py:305   from daedalus.spine.attempt import TaskSpec

### INCOMING edges INTO spine.picker from other SCC members
  <- core                       FUNCTION-LOCAL (deferred)  in _head_sha_safe
       daedalus/core.py:487   from .spine.picker import _head_sha
  <- health                     FUNCTION-LOCAL (deferred)  in _p_picker
       daedalus/health.py:576   from .spine.picker import build_queue
  <- kairos.gated_writes        FUNCTION-LOCAL (deferred)  in promote_candidates
       daedalus/kairos/gated_writes.py:259   from daedalus.spine.picker import resolve_spine_db_path
  <- spine.bootstrap            FUNCTION-LOCAL (deferred)  in refresh_sources
       daedalus/spine/bootstrap.py:158   from daedalus.spine.picker import _picker_source_mode
  <- spine.bootstrap            FUNCTION-LOCAL (deferred)  in shadow_run
       daedalus/spine/bootstrap.py:587   from daedalus.spine.picker import build_queue
  <- spine.bootstrap            FUNCTION-LOCAL (deferred)  in shadow_run
       daedalus/spine/bootstrap.py:622   from daedalus.spine.picker import resolve_spine_db_path
  <- spine.bootstrap            FUNCTION-LOCAL (deferred)  in shadow_run
       daedalus/spine/bootstrap.py:595   from daedalus.spine.picker import _head_sha
  <- spine.bootstrap            FUNCTION-LOCAL (deferred)  in gate_discrimination
       daedalus/spine/bootstrap.py:338   from daedalus.spine.picker import _head_sha
```
[MEASURED]

### Verification / corrections

- Line 72-75, `daedalus/spine/picker.py`: `from ..kernel.attempt_execution import (AttemptEvaluatorPort, AttemptWorkspacePort)` is real, module-level, not inside `if TYPE_CHECKING:`. [MEASURED — read lines 61-85]
- **Correction to the probe's implied cost**: `AttemptEvaluatorPort` and `AttemptWorkspacePort` are used at exactly two other sites in the file — line 2830 and line 2992 — and both are inside `Callable[[...], tuple[AttemptWorkspacePort, AttemptEvaluatorPort]]` **type annotations only** (grep for both names: 4 total occurrences = the 2 import names + these 2 annotation uses). [MEASURED] The file has `from __future__ import annotations` at line 61 [MEASURED — read line 61], so these annotations are never evaluated at runtime. This import is therefore a **free cut**: it can move under `if TYPE_CHECKING:` (or be dropped in favor of a string/typing-only reference) with zero behavior change.
- Note the *same* line 72 module-level import also line 76/85 pulls `EvaluationPorts` (from `..kernel.contracts.evaluation`) and `ResourceBudget` (from `..kernel.contracts.resources`) — those are **not** SCC members (`kernel.contracts.*` is outside the named 18) so they don't affect this SCC's edge count, but `ResourceBudget` **is** used at runtime (line 2902: `budget=ResourceBudget(max_wall_time_s=...)`), confirming that import is real and non-annotation-only — it's simply irrelevant to the SCC-internal edge.
- Line 305, `Candidate.to_task_spec`: deferred import of `TaskSpec` confirmed real, reachable, docstring explicitly states the reason ("ranking a queue must not drag in the ledger, the worktree manager and the storage watermark"). [MEASURED — read lines 298-325]
- Line 2843-2847, `_default_attempt`: deferred import of `AttemptPortMissing, offload_runner, run_attempt` confirmed real and reachable — this is the CLI attempt-execution path, gated behind `--once`/an injected `attempt_ports_factory`. [MEASURED — read lines 2824-2925]
- No `importlib.import_module`, `__import__`, or string-literal references to other SCC members found by grep (only unrelated `subprocess -m daedalus.spine.docref_gate` and a docstring mention of `daedalus.spine.docrefs.scan`, neither an SCC member). [MEASURED]

## Step 2 — What it actually does

`build_queue()` (line 2259) assembles a `PickedQueue` of `Candidate` objects from up to five cheap-by-default sources (work-queue JSON, generated inventory, map/spectral state, eval baseline/gate misses, hotspot churn×complexity) plus ledger-derived attempt memory (`attempt_history`, `apply_attempt_memory`), then `rank()`s them by `(band, offset)` with a ledger-outcome ceiling. `main()` (line 2987) is the `daedalus improve` CLI entrypoint: it renders the queue (`render_queue`), and with `--once` and an injected `attempt_ports_factory` runs exactly one real `TaskAttempt` via `_default_attempt` → `daedalus.spine.attempt.run_attempt`, then prints a `review_packet`. Every `Candidate` is refused at construction (`_candidate`, `NoEvidence`) unless it carries a non-empty `reason`, numeric `score`, and `evidence` dict, and the module contains no apply/promote path — attempts produce inert `PatchArtifact` bytes for a human to review (enforced by the guard test named in its own comment, `test_there_is_no_apply_path_in_this_module`).

## Step 3 — Layer

**Verdict: split — the file fuses `orchestration` (ranking/selection/CLI, the bulk of the ~2925 lines) with a thin `kernel`-adjacent seam (`to_task_spec`, `_default_attempt`) that should sink toward `spine.attempt`/`kernel`.**

Evidence: the overwhelming majority of the module — `_candidate`, `work_queue_candidates`, `load_inventory`, `map_candidates`, `hotspot_candidates`, `eval_baseline_candidates`, `attempt_history`, `apply_attempt_memory`, `rank`, `render_queue`, `review_packet`, `main`/`_build_parser` — is pure scoring/selection/CLI-rendering logic reading JSON/ledger state off disk: no effect boundary calls, no leases, no policy decisions, matching "orchestration (mission/workitem scheduling... campaign driving)" exactly (it literally decides "what is worth attempting" per its own docstring, line 1-6). Only `Candidate.to_task_spec` (line 298) and `_default_attempt` (line 2824) touch attempt-construction/execution symbols from `spine.attempt`/`kernel.attempt_execution`, and both do so through deferred imports specifically to avoid dragging the kernel/ledger/worktree machinery into the ranking path (stated motive in both docstrings). Living under `daedalus/spine/` is not evidence either way per the brief; behaviorally this is a picker/CLI, not ledger/killswitch/envelope machinery. If split, `to_task_spec` and `_default_attempt` (plus `main`'s attempt-invocation branch) are the natural symbols to move to an `orchestration`-side attempt-launcher module that depends on `spine.attempt`, leaving the scoring/ranking/CLI-render body (`_candidate` through `review_packet`, minus those two) as a clean `orchestration` module with zero SCC-internal edges of its own except the one real module-level one discussed below.

## Step 4 — Severance

### Edge 1: `picker.py:72` → `kernel.attempt_execution` (`AttemptEvaluatorPort`, `AttemptWorkspacePort`), MODULE-LEVEL

- **Cheapest: (free cut via annotation-only import, not one of (a)-(d))**. As shown in Step 1, both symbols are used **only** inside type annotations at lines 2830 and 2992, under `from __future__ import annotations`. Moving the import under `if TYPE_CHECKING:` removes this as a *runtime* import edge entirely (the static AST edge remains for tools that don't understand `TYPE_CHECKING`, but the module no longer needs `kernel.attempt_execution` importable at runtime to function). Cost: 2 symbols crossing, 0 non-annotation call sites, already zero runtime necessity — the cheapest possible severance because no behavior changes at all.
- If a structural (not just typing) port is wanted anyway: **(a) port/protocol extraction** — name it `AttemptPortsFactory` Protocol carrying the signature `Callable[[str|Path|None], tuple[AttemptWorkspacePort, AttemptEvaluatorPort]]` used at lines 2828-2831 and 2990-2993; the Protocol module would live in `daedalus/kernel/contracts/attempts.py` (alongside the other `kernel.contracts.*` port definitions already imported by this file, e.g. `EvaluationPorts`, `ResourceBudget`) so picker never needs `kernel.attempt_execution` by name, only `kernel.contracts`.

### Edge 2: `picker.py:305` (`Candidate.to_task_spec`) → `spine.attempt.TaskSpec`, FUNCTION-LOCAL (already deferred)

- **Cheapest: (b) callback/parameter injection**, but the deferred import is already the de-facto seam. 1 symbol crosses (`TaskSpec`), 1 call site (`TaskSpec(...)` construction at line 307). Because it's a dataclass-style constructor call with no behavior beyond field mapping, the caller (`_default_attempt`, the only caller of `to_task_spec` per grep of `to_task_spec(` in picker.py) could instead pass a `task_spec_factory: Callable[..., TaskSpec]` parameter, or `to_task_spec` could return a plain dict/mapping and let the (already spine.attempt-importing) caller construct `TaskSpec` itself — moving the one remaining `spine.attempt` name-reference out of `picker.py` entirely. Given it's a single symbol at a single call site and already lazily imported, this is cheap; the deferred import already proves the cycle is avoidable without runtime cost, so severance is mostly a matter of taste/ownership, not necessity.

### Edge 3: `picker.py:2843` (`_default_attempt`) → `spine.attempt.{AttemptPortMissing, offload_runner, run_attempt}`, FUNCTION-LOCAL (already deferred)

- **Cheapest: (b) callback/parameter injection.** 3 symbols cross; grep of `AttemptPortMissing|offload_runner|run_attempt` inside `_default_attempt`'s body (lines 2824-2925) shows each used once. `_default_attempt` already accepts an injected `attempt_ports_factory` parameter (line 2827-2831) for exactly this reason (its docstring: "the single injection seam so `--dry-run` can be tested"). The natural extension is an additional injected `attempt_runner: Callable[[TaskSpec], AttemptResult] | None = None` parameter defaulted to `spine.attempt.run_attempt`, supplied by the CLI composition root (`main`/`_build_parser` caller) instead of imported inside the function. This removes the last `spine.attempt` edge from `picker.py`, at the cost of moving the default-wiring decision to whatever module already composes `attempt_ports_factory` for the CLI (already outside this file). Since the import is deferred already (a de-facto port seam per the brief) and the call sites are exactly 3 symbols / 1 call site apiece, this is the cheapest of the four options — no protocol module needed, just widen an injection point that already exists.

## Step 5 — Tests that pin this

[MEASURED] Grep of `tests/` for `spine\.picker|spine import picker|from daedalus\.spine import picker`: **20 files**. Grep for the literal substring `daedalus.spine.picker` or `daedalus.spine.attempt` anywhere in `tests/`: **112 occurrences across 49 files**.

Files with direct, named `mock.patch("daedalus.spine.picker.build_queue", ...)` (symbol-path pins — hardest to move):
- `tests/test_health_surface.py:365,374`
- `tests/test_loop.py:105,270,284,303`

Files most directly exercising this module's public surface (function-name counts via `grep '^def test_'`):
- `tests/test_spine_picker.py` — **40** test functions [MEASURED]
- `tests/test_picker_work_queue.py` — **15** test functions [MEASURED]
- `tests/test_picker_outcome.py` — **17** test functions [MEASURED]
- `tests/test_picker_spectral_enrichment.py`, `tests/test_spine_return_arc.py`, `tests/test_spine_map_source.py`, `tests/test_ignition_bundle.py`, `tests/test_ignition_gate1.py`, `tests/test_generated_inventory.py`, `tests/test_shadow_run.py`, `tests/test_registry_new_doors.py`, `tests/test_loop.py`, `tests/test_loop_cap_policy.py`, `tests/test_canonical_execution_limit_policy.py`, `tests/test_uncapped_scope_usage.py`, `tests/kernel/test_evaluation_port_boundary.py`, `tests/kernel/test_attempt_lease.py`, `tests/contracts/test_spine_outer_ports.py`, `tests/contracts/test_import_scc_hierarchy.py` — present but not individually counted; UNVERIFIED beyond file-level match.
- Naming guard: `tests/test_spine_picker.py` grep hit for `test_there_is_no_apply_path` referenced in picker.py's own comment (line 2872) — UNVERIFIED whether that exact test name lives in `test_spine_picker.py` vs elsewhere; grep for `no_apply_path|test_there_is_no_apply` found it only in `tests/test_spine_picker.py` and `tests/test_spine_attempt.py` (plus two unrelated `test_skills.py`/`test_council_session.py` hits) — [MEASURED].

**Governance/architecture pin**: `tests/contracts/test_import_scc_hierarchy.py` hardcodes `SPINE_PICKER = "daedalus.spine.picker"` as a literal string (line 15) inside a frozen 18-member `CURRENT_CROSS_DOMAIN_COMPONENT` set, and asserts a `CURRENT_COMPONENTS_SHA256` digest (line 49-51) over that set plus `nontrivial_components()` measurements from `daedalus.structcore.cycles`. Any rename, split, or removal of `spine.picker` from the SCC breaks this test's frozen set and digest, and is explicitly designed to (its own comments instruct updating the two totals when a packet "legitimately splits or adds a leaf module" — i.e., this test is written to be touched by exactly the kind of severance work in Step 4). This is the single hardest symbol-path pin found. [MEASURED]
