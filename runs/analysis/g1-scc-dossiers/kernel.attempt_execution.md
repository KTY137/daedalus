# SCC dossier: `kernel.attempt_execution` (`daedalus/kernel/attempt_execution.py`, 2724 lines)

Base: main @ 851ff43c. Read-only static analysis.

## Measured edges (raw AST probe)

Command: `.venv/Scripts/python.exe C:/Users/Administrator/scc-scratch/probe.py kernel.attempt_execution`

```
### OUTGOING edges FROM kernel.attempt_execution to other SCC members
  -> offload                    FUNCTION-LOCAL (deferred)  in offload_runner._runner
       daedalus/kernel/attempt_execution.py:1209   from daedalus.offload import offload

### INCOMING edges INTO kernel.attempt_execution from other SCC members
  <- spine.attempt              MODULE-LEVEL               in <module>
       daedalus/spine/attempt.py:24   from daedalus.kernel import attempt_execution as _owner
  <- spine.bootstrap            MODULE-LEVEL               in <module>
       daedalus/spine/bootstrap.py:69   from ..kernel.attempt_execution import (
  <- spine.picker                MODULE-LEVEL               in <module>
       daedalus/spine/picker.py:72   from ..kernel.attempt_execution import (
```

**Verification [MEASURED]:** Read `daedalus/kernel/attempt_execution.py:1198-1223` — line 1209 sits inside `_runner`, a closure nested inside
`offload_runner`, exactly as the probe reports; real, reachable, not
`TYPE_CHECKING`. `offload_runner` itself is explicitly opt-in
("Deliberately not the default: `TaskAttempt` refuses to construct without
an explicit runner", `attempt_execution.py:1204-1206`), so the import only
executes when a caller actually invokes the returned closure. The three
incoming module-level edges were spot-read at their cited lines and are real
imports, not `TYPE_CHECKING`. No correction to the probe output needed.

**Dynamic-reference grep** (`importlib.import_module`, `__import__`, string
literals naming SCC members) over `daedalus/kernel/attempt_execution.py`:
zero matches [MEASURED].

## Step 2 — what it actually does

This is the kernel-owned `TaskAttempt` lifecycle core: `storage -> intent ->
worktree -> runner -> patch -> gates -> resolve -> cleanup`, and its own
docstring states four structural properties for why it can never write the
primary checkout — a single git choke point (`_git`, raising
`PrimaryCheckoutWrite` on any overlap with the primary checkout, verb-gated
by `READ_ONLY_REPO_VERBS`), a `RunnerContext` that carries only a worktree
path (never `repo_root`), no apply/checkout/merge/commit path against the
primary tree, and a fenced `artifact_dir`. `TaskAttempt.__init__` requires an
injected `runner: Callable[[RunnerContext], Any]` and an injected
`workspace_port: AttemptWorkspacePort`/`evaluator_port:
AttemptEvaluatorPort` (both `Protocol`s defined at the top of the file,
lines 252-297) — it raises `AttemptPortMissing` rather than discovering a
concrete Kairos workspace manager or evaluator itself. `TaskAttempt.run`
(via `_run_with_ledger`, the largest single method, ~250 lines) drives the
git-worktree-based attempt end to end and always returns one of eight
`AttemptResult` states (`STATE_CLEAN`/`GATES_FAILED`/`NO_CHANGE`/
`RUNNER_FAILED`/`WORKTREE_FAILED`/`STORAGE_UNAVAILABLE`/`CANCELLED`/
`LEASE_REFUSED`) rather than raising, with the candidate patch captured as
inert `PatchArtifact` bytes and persisted through `ArtifactStore`/
`SpineLedger`. The one function that is *not* part of this closed kernel
core is `offload_runner` (lines 1198-1223): a 26-line factory that produces
one concrete `runner` implementation by hardcoding a call to
`daedalus.offload.offload` — everything else in the file (`_git`, the gate
runners `_command_gate`/`_contained_gate_child`, ledger persistence,
criterion-presence checks in `_criterion_imports`/`_tree_kinds`, boundary
guard decisions) only ever touches `daedalus.kernel.*`, `daedalus.storage`,
`daedalus.primary_tree`, and `daedalus.limit_policy`.

## Step 3 — layer

**Verdict: kernel**, and cleanly so apart from the one flagged edge. Every
top-level import except the deferred `daedalus.offload` one is a kernel/spine
primitive: `daedalus.kernel.contracts.base.ContractProvenance`,
`daedalus.kernel.contracts.resources.{ResourceBudget,ResourceUsage}`,
`daedalus.kernel.events.durability.open_gate0_spine_writer`,
`daedalus.kernel.events.envelope.current_trace_id`,
`daedalus.kernel.events.ledger.{SpineLedger,canonical_json}`,
`daedalus.storage.{ArtifactLocator,ArtifactStore,StorageUnavailable,require_storage}`, `daedalus.primary_tree.*`, `daedalus.limit_policy.{ExecutionLimitPolicy,load_from_env}` — attempts, leases (`attempt_lease` constructor
param, `_attach_lease_terminal`/`_finish_lease_terminal`), evidence
(`PatchArtifact`, `ArtifactStore`), and the primary-checkout write fence are
exactly the taxonomy's "kernel" responsibilities. Two governance tests
already enforce this for two of its three outward neighbors:
`tests/kernel/test_attempt_execution_hierarchy.py::test_owner_has_no_kairos_or_evaluator_import_edge` forbids `daedalus.kairos`/`daedalus.eval` imports here,
and the equivalent test for the facade
(`tests/orchestration/test_attempt_composition_hierarchy.py::test_spine_attempt_has_zero_outer_layer_imports_and_no_import_trick`) forbids
`daedalus.eval`/`daedalus.kairos`/`daedalus.orchestration` in
`daedalus/spine/attempt.py`. **Neither test's forbidden-prefix list includes
`daedalus.offload`** — the one remaining outward edge is invisible to the
guard that already polices this exact module for its siblings. Not mis-sited
as a file (it correctly lives under `daedalus/kernel/`); the `offload_runner`
*function* is the mis-sited fragment — it names a concrete outward adapter
(`daedalus.offload`) instead of leaving that binding to a composition point
outside kernel. Split point: lines 1-1197 and 1229-2724 (everything except
`offload_runner`) is kernel; `offload_runner` (1198-1223) is a
`runtimes`-adapter binding that does not belong in this file.

## Step 4 — severance

### Edge: `kernel.attempt_execution -> offload` (`offload`, line 1209, FUNCTION-LOCAL deferred)

**[INHERITED] Cutting this edge alone collapses the SCC 18 -> 12** — the
second-best cut, given the deep read.

- **Symbols crossing:** 1 (`daedalus.offload.offload`, the function).
- **Call sites:** 1, inside `_runner` (`attempt_execution.py:1222`,
  `return offload(ctx.task.instruction, str(ctx.worktree), **kwargs)`).
- **Functions involved:** 1 (`offload_runner`'s inner `_runner` closure);
  `offload_runner` itself is called from exactly 2 production sites —
  `daedalus/spine/bootstrap.py:730` (`runner=offload_runner(**kwargs)`, via
  `from daedalus.spine.attempt import offload_runner` at line 724) and
  `daedalus/spine/picker.py:2912` (`runner=offload_runner(live=bool(args.live))`, imported at line 2845) — both reach it through the
  `daedalus.spine.attempt` facade, not this module directly.
- **Already a de-facto port:** the import is FUNCTION-LOCAL/deferred *and*
  the surrounding factory is explicitly optional (`TaskAttempt` requires an
  injected `runner` callable and has no built-in default). The port
  (`Callable[[RunnerContext], Any]`) already exists as the `__init__`
  parameter type; only the *factory that fills the port with a concrete
  adapter* is misplaced.
- **Cheapest severance: (b) callback/parameter injection.** Generalize the
  factory in place: rename `offload_runner(**offload_kwargs)` to
  `attempt_runner(run_fn: Callable[..., Any], **offload_kwargs)` with an
  otherwise-identical body (`return run_fn(ctx.task.instruction,
  str(ctx.worktree), **kwargs)` instead of the hardcoded `offload(...)`), and
  delete the `from daedalus.offload import offload` line entirely from
  `kernel/attempt_execution.py`. Bind it to the concrete adapter one layer
  up, in `daedalus/spine/attempt.py` — which already carries the
  module-level `from daedalus.kernel import attempt_execution as _owner`
  edge and already states in its own docstring that "registered effect doors
  and legacy default composition remain at `daedalus.spine.attempt`", i.e.
  it is already the file that owns binding ports to concrete adapters for
  this exact class: `from daedalus.offload import offload as _offload; def
  offload_runner(**kwargs): return _owner.attempt_runner(_offload, **kwargs)`. `daedalus/spine/bootstrap.py` and `daedalus/spine/picker.py` need no
  change — they already import `offload_runner` from `daedalus.spine.attempt`, not from `daedalus.kernel.attempt_execution`. This is cheaper
  than a Protocol/port-module extraction (no new file, one symbol, one
  caller-side rebind) and cheaper than a merge (`daedalus.offload` legitimately serves callers with no relation to `TaskAttempt`, e.g. its own CLI
  `main()` and `daedalus/selftest.py`, so folding it into kernel would be
  artificial).

### Is this an inversion?

**Yes, argued from the symbols.** `TaskAttempt` is built as a strict
hexagonal core: every external capability — `workspace_port`,
`evaluator_port`, `runner`, `budget`, `execution_limit_policy` — arrives as
an injected parameter or `Protocol`, and the module's own docstring frames
the whole file as "cannot discover a Kairos workspace manager or an
evaluator: both capabilities arrive through neutral ports." `offload_runner`
breaks that pattern for exactly one capability: instead of leaving the
binding of the `runner` port to a concrete implementation for the
composition point (`daedalus.spine.attempt`, which already performs this
role for `AttemptWorkspacePort`/`AttemptEvaluatorPort` per
`tests/orchestration/test_attempt_composition_hierarchy.py::test_composer_injects_exact_ports_into_the_registered_class`), the kernel module names the
concrete outward, model-and-effect-bearing implementation
(`daedalus.offload.offload`) itself. A kernel module is supposed to be
depended upon, not to depend outward on the thing that calls into it
indirectly (`offload_runner` is dispatched *by* the same lease/attempt
machinery `TaskAttempt` implements) — that is the inversion. It is a small,
already-isolated one (one function, one deferred import, one caller
pattern), which is exactly why moving the binding one layer up to
`daedalus.spine.attempt` (Step 4) both fixes the inversion and is the
cheapest cut measured.

**Caveat for whoever implements this:** `tests/kernel/test_attempt_execution_hierarchy.py::test_legacy_objects_resolve_to_one_owner_except_documented_composition` (line ~75) asserts `facade.offload_runner is
owner.offload_runner` by object identity — i.e. it currently *requires*
`daedalus.spine.attempt.offload_runner` and
`daedalus.kernel.attempt_execution.offload_runner` to be the same function
object. The rename above would need this assertion re-pointed to the new
`attempt_runner`/rebind shape, or the test would need to become "facade
`offload_runner` calls owner `attempt_runner` with `daedalus.offload.offload`" instead of an identity check. Flagging, not fixing — this dossier is
read-only.

## Step 5 — tests that pin this

Grep `tests/ --include=*.py` for the literal module path
(`kernel.attempt_execution` / `kernel import attempt_execution` /
`from daedalus.kernel.attempt_execution`): **5 files, 11 matching lines
[MEASURED]**:

```
tests/contracts/test_import_scc_hierarchy.py
tests/kernel/test_attempt_execution_hierarchy.py
tests/kernel/test_contract_hierarchy.py
tests/orchestration/test_attempt_composition_hierarchy.py
tests/test_architecture_boundaries.py
```

Broader grep for the module's public symbols (`TaskAttempt`, `offload_runner`,
`RunnerContext`, `AttemptResult`) — most tests reach this module through the
`daedalus.spine.attempt` facade rather than importing the owner path
directly, so this is the number that actually bounds blast radius: **43
files, 182 matching lines [MEASURED]**. No `mock.patch("daedalus.kernel.attempt_execution...")` or `monkeypatch.setattr(attempt_execution, ...)`
string targets found in `tests/` [MEASURED, 0 hits] — the module is pinned by
import/identity/composition assertions, not by patch-string targets.

Named tests that would break under a symbol move/rewire of the flagged edge:

- `tests/kernel/test_attempt_execution_hierarchy.py::test_owner_has_no_kairos_or_evaluator_import_edge` and `::test_cold_owner_import_does_not_load_default_composition` — AST/subprocess-based import-edge guards for this
  exact file; would need `daedalus.offload` added to their forbidden-prefix
  list once the edge is cut, or they keep passing vacuously without ever
  having caught this edge.
- `tests/kernel/test_attempt_execution_hierarchy.py::test_legacy_objects_resolve_to_one_owner_except_documented_composition` — asserts
  `facade.offload_runner is owner.offload_runner` by identity; breaks on any
  rename/rebind of `offload_runner` (see Step 4 caveat).
- `tests/kernel/test_attempt_execution_hierarchy.py::test_legacy_pickle_globals_resolve_after_the_owner_cut` — pickles a global reference through
  `daedalus.spine.attempt.TaskAttempt`/`TaskSpec`; sensitive to any symbol
  relocation in this file.
- `tests/orchestration/test_attempt_composition_hierarchy.py::test_spine_attempt_has_zero_outer_layer_imports_and_no_import_trick`,
  `::test_cold_spine_attempt_import_loads_no_composition_owner`,
  `::test_composer_injects_exact_ports_into_the_registered_class`,
  `::test_all_live_attempt_callers_name_explicit_composition` — govern
  exactly the composition-root role `daedalus/spine/attempt.py` would take on
  under the Step-4 severance; would need to gain `daedalus.offload` to (or
  explicitly permit it in) their checked import list.
- `tests/contracts/test_import_scc_hierarchy.py::test_intent_ledger_port_breaks_the_selected_cross_domain_scc`, `::test_observation_contract_breaks_the_next_cross_domain_scc`, `::test_kernel_lease_has_no_spine_picker_import_or_dynamic_escape` — this SCC's own census/membership tests (`OLD_CROSS_DOMAIN_COMPONENT`, `CURRENT_COMPONENTS_SHA256`, `CENSUS_MODULES`); any edge cut here changes the graph these tests assert over and must be re-measured, not hand-edited.
