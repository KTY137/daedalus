# G1-HIER-03B - Kernel-owned Attempt execution ports

## Frozen packet metadata

- Packet ID: `G1-HIER-03B`
- Artifact role: `primary`
- Active gate: `1`
- Classification: `ALIGNED`
- Owner: repository owner
- Base revision: `59d16ba55fd914cd25ce24c046a2171b7c7f0b8b`
- Dependencies: `G1-HIER-03A` at
  `59d16ba55fd914cd25ce24c046a2171b7c7f0b8b`
- Parent program: `G1-HIER-03`
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Authority boundary: no merge, promotion, Gate transition, provider call,
  network call, or EDA execution is part of this packet.

The packet is a bounded Strangler slice. It moves the productive Attempt
lifecycle core from `daedalus.spine.attempt` to
`daedalus.kernel.attempt_execution`. The historical spine locator remains the
registered effect and compatibility door; it is not a second lifecycle owner.

## Primary acceptance claim

The productive Attempt lifecycle has one implementation core under
`daedalus.kernel.attempt_execution`; that core discovers neither Kairos nor an
evaluator. Workspace and evaluator behavior enter through neutral injected
ports, while the unchanged registered `spine.attempt` targets remain a bounded
compatibility and composition door.

## Scope

In scope are the productive Attempt lifecycle owner move, neutral workspace and
evaluator ports, the legacy registered composition facade, exact import/private
compatibility where it is not a composition seam, writer-inventory recognition
of the canonical Event owner, active mutation-locator updates, and focused
architecture/replay/containment evidence.

Out of scope are kill-switch/cancellation ownership moves, receipt and
containment ownership moves, `offload_lease.py`, Registry target or digest
migration, persistent-data migration, live providers, network, EDA, promotion,
Master Plan edits, and amendment edits.

### Tracked baseline inventory

Before the move, the canonical isolated lifecycle files
`kernel/attempt_contracts.py`, `attempt_ledger.py`, `attempt_workspace.py`, and
`attempts.py` already had zero direct imports of `daedalus.kairos` or
`daedalus.eval`. The productive legacy `TaskAttempt` path still held both
implicit dependencies:

- a top-level `GitWorktreeManager` / `remove_tree_no_follow` import from
  `daedalus.kairos.worktree`;
- a lazy `daedalus.eval.correctness.correctness_gate` import selected by
  FAIL_TO_PASS/PASS_TO_PASS metadata.

The only other tracked direct `kernel -> kairos|eval` edge at the frozen base
is the unrelated lazy repository-default import in
`kernel/offload_lease.py` (worktree/repository ownership split belongs to
`G1-HIER-04`). It is not hidden or changed by this packet.

Product callers found before the move were:

- direct `TaskAttempt` composition in `ignition/gate1.py` and
  `ikarus_supervisor.py`, both already supplying runner and gate callables;
- `spine/bootstrap.py` and `spine/picker.py` through the stable
  `run_attempt`, `offload_runner`, and gate helpers;
- `eval/correctness.py` through the shared read-only git vocabulary and
  `GateResult` compatibility types;
- local promotion material readers through the old type locator.

Concrete compatibility seams found and retained:

- module monkeypatches of `RunnerContext`, `require_storage`,
  `open_gate0_spine_writer`, `_contained_gate_child`, `_remove_gate_tmpdir`,
  `command_gate`, `pytest_gate`, and `run_attempt`;
- Effect Registry runtime targets
  `daedalus.spine.attempt:run_attempt` and
  `daedalus.spine.attempt:command_gate`, plus the anchor
  `daedalus.spine.attempt:TaskAttempt.run`;
- the canonical provenance string `daedalus.spine.attempt.TaskAttempt`;
- legacy pickle globals under `daedalus.spine.attempt`.

No tracked persisted pickle of a TaskAttempt instance was found. Protocol-0
global resolution is nevertheless covered because the legacy locator is a
public Python compatibility seam.

### Implementation and authority

`daedalus.kernel.attempt_execution` now owns the existing Task/Runner/Gate/
Result types, git choke point, patch capture, lifecycle transitions, evidence
projection, replay, cleanup, and bounded gate core. It defines structural,
neutral ports:

- `AttemptWorkspacePort` for create/cleanup/reap under an external root;
- `AttemptEvaluatorPort` for command, correctness, and pytest gate selection;
- `ScratchCleanupPort` for the guarded gate scratch-tree cleanup.

The kernel core has no default port registry, singleton, service locator,
Kairos import, evaluator import, or dynamic import string for either domain.
Missing workspace or implicit evaluator composition raises
`AttemptPortMissing` before a lifecycle effect starts. An explicit caller gate
does not require an evaluator port.

`daedalus.spine.attempt` is deliberately not a pure object alias for five
composition seams. Its thin `TaskAttempt` subclass owns the already-registered
`run` effect door and injects a fresh Kairos manager and a fresh evaluator
adapter per construction. Its `command_gate` owns the unchanged registry
boundary and injects the existing safe cleanup walker. The evaluator adapter
loads correctness lazily to preserve the historical cycle and builds the same
minimal task mapping. Every other public and practically imported private name
resolves to the exact kernel-owner object. Module-level monkeypatch assignment
is forwarded to the owner, so tests and callers do not patch a dead copy.

The Event Store opens through the new canonical
`kernel.events.durability.open_gate0_spine_writer` owner. The syntax-based
writer inventory recognizes that canonical locator as the same Gate-0 factory;
no writer authority or database format was added.

## Contracts and behavior

- Registry IDs, targets, effects, wiring, anchors, and digest are unchanged.
- Attempt state strings, task/result JSON shapes, provenance strings, branch
  names, SQLite rows, canonical JSON/digests, evidence locators, and cleanup
  ordering are unchanged.
- Old `spine.attempt` imports remain valid. Non-composition classes/functions
  are object-identical to the kernel owner. `spine.TaskAttempt` is the
  documented registered composition subclass; old pickle globals resolve to
  that door while data/result globals resolve to the owner objects.
- Active mutation rows follow the moved implementation owner. Historical
  mutation evidence and files under `runs/` are untouched.

### Deliberate remaining hierarchy edges

This first complete slice removes the two requested domain discoveries, but it
does not pretend the whole Attempt dependency closure has moved. The kernel
core still consumes existing spine-owned receipts, effect-decision types,
containment, and cancellation machinery. Those are explicit transition edges,
not new authorities. Moving them belongs to their receipt/runtime packets; a
mass copy here would create the duplicate contract and containment authorities
the program forbids.

The legacy facade still imports Kairos and lazily invokes Eval because it is
the temporary default composition owner. Production callers can retire that
default independently by constructing the kernel core with explicit ports and
retaining the registered admission door. The unrelated `offload_lease ->
kairos.worktree` edge remains assigned to `G1-HIER-04`.

## Acceptance matrix

Required deterministic checks:

- AST: no `kernel/attempt_execution.py -> daedalus.kairos|daedalus.eval`;
- cold import: importing only the owner loads neither Kairos nor Eval;
- explicit missing-port refusal and exact injected port use;
- old/new identity for non-composition objects and documented subclass shape;
- legacy pickle-global resolution;
- byte/behavior-equivalent Attempt, gate, workspace, evaluator, ledger replay,
  lease, and containment suites;
- Event-Store writer inventory classifies the canonical event-owner factory;
- active Attempt mutation anchors remain present and unique;
- static Effect conformance has no blocker and the Registry digest remains
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`.

Builder results are appended only after the exact packet tree is measured.
The known frozen Forest-v2 corpus-count and missing optional fourth-corpus
failures are parent evidence and must not be rewritten to make this packet
green.

## Migration and rollback

There is no database, JSON, digest, CAS, branch, evidence-path, or ledger
migration. The legacy module composes the previous defaults and resolves the
same public/private objects, so rollback restores the old spine implementation
and removes the kernel core without transforming persistent state.

### Shim retirement criteria

Retire the `spine.attempt` composition shim only after all of the following:

1. Registry targets and anchors move in a dedicated, digest-changing packet;
2. every production caller supplies admitted workspace/evaluator composition;
3. source imports, runtime strings, monkeypatch targets, docs, mutation specs,
   wheel imports, and legacy pickle globals have an exact-head audit;
4. provenance compatibility is either retained or migrated as an explicit
   wire-contract packet;
5. no caller obtains a default workspace/evaluator by importing the kernel;
6. replay, crash, lease, candidate-gate, and primary-checkout-fence tests pass
   against both the final target and the temporary legacy locator.

## Evidence expected failures and review

Builder evidence must name interpreter, exact test selection and count, static
import/conformance results, mutation-anchor status, Effect Registry digest,
and clean-tree commit. Independent review remains required; builder tests do
not promote the packet.

Measured builder evidence on the packet worktree:

- CPython 3.13 pre-move baseline: **216 passed, 22 subtests passed** across
  Attempt, boundary, live-contract, gate, correctness, containment and lease
  suites.
- CPython 3.13 post-move consumer inventory: **1163 passed, 7 skipped,
  7 xfailed, 51 subtests passed** across all 48 test files that import or name
  the legacy Attempt locator, plus the new hierarchy and writer-inventory
  acceptance tests.
- CPython 3.10 focused post-move matrix: **233 passed, 1 skipped,
  22 subtests passed**.
- Registry/effect/mutation/writer/hierarchy matrix: **139 passed, 3 skipped**;
  both active Attempt mutation anchors were present exactly once at the new
  owner path.
- Static Effect conformance: **129 review findings, 0 blockers**. The findings
  include the repository's declared harness inventory; this packet claims only
  the blocker result, not that unrelated review debt disappeared.
- Cold owner import loaded no `daedalus.kairos*` or `daedalus.eval*` module.
  The owner AST has zero direct imports to either domain.
- Effect Registry SHA-256 remained
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`.
- Full-suite `-x` probe reached **43 passed, 2 skipped** and stopped at the
  retained Forest-v2 function pin: **5559 current functions versus 5285**.
  Running that experiment module directly produced **6 passed, 2 failed**;
  the second retained failure was **3 present corpora versus at least 4**.

Expected parent failures are the frozen Forest-v2 function-count pin (current
tree exceeds the historical `5285` row) and the absent optional fourth external
corpus (`kernel`, `fixture_alias`, and `stdlib` are the three present postures).
They must reproduce outside the packet and must not be rewritten. The frozen
parent's missing `daedalus.kernel.campaigns` remains honest prerequisite
evidence; this packet does not fabricate Campaigns.

Review should focus on whether the facade is only composition/admission,
whether any private monkeypatch lands on a dead copy, cold-import behavior,
gate/Attempt boundary ordering, old pickle globals, writer-inventory admission,
and the explicit remaining `kernel -> spine` transition edges.
