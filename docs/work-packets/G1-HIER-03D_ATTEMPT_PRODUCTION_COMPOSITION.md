# G1-HIER-03D - Attempt production composition

## Frozen packet metadata

- Packet ID: `G1-HIER-03D`
- Artifact role: `primary`
- Active gate: `1`
- Classification: `ALIGNED`
- Owner: repository owner
- Base revision: `aded80f1a619124b0594ffa2e106e29ef6fa4b5e`
- Dependencies: G1-HIER-01, G1-HIER-03B, G1-HIER-03C, G1-ORCH-01, G1-IKARUS-15
- Parent program: `G1-HIER-03`
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`
- Authority boundary: no merge, promotion, Gate transition, live provider,
  network, or EDA call is part of this packet.

## Primary acceptance claim

The registered `daedalus.spine.attempt` doors retain their Effect Registry
targets, anchors, objects, JSON/digest behavior, and lifecycle owner while the
spine facade imports neither Kairos nor Eval. Production workspace and
evaluator capabilities are freshly and explicitly composed under
`daedalus.orchestration.execution`; an uncomposed internal caller fails closed
with `AttemptPortMissing` before worktree, runner, gate process, or scratch
cleanup effects.

## Scope

This is the bounded follow-up to G1-HIER-03B. It removes the two remaining
machine-readable `spine-no-outer-layers` edges in `spine/attempt.py`, adds one
concrete orchestration adapter over the existing Kairos worktree manager and
existing correctness evaluator, and migrates the live Ignition, legacy
MissionSupervisor, Picker/CLI, Bootstrap, and retained Gated-Writes call paths.

No lifecycle, workspace, evaluator, event-store, artifact, receipt, policy,
scheduler, conversation, or promotion authority is copied. The existing
kernel `AttemptWorkspacePort`, `AttemptEvaluatorPort`, and
`ScratchCleanupPort` remain the only neutral contracts. No global service
locator, mutable port registry, dynamic import string, or implicit kernel
default is introduced.

The read-only ontology preflight used repository label `g1-hier-03d` and no
snapshot. It measured 1,384 Python files under CPython 3.13.5, excluded three
configured-directory and 29 sensitive-name paths, executed no target module,
wrote no workspace or ontology state, used no network or LLM, and reported the
Python adapter as partial. Dynamic imports, descriptor dispatch, generated
code, monkeypatches, and runtime metaprogramming remain outside that static
model; its correlations are not causal proof. RDF/Turtle remains the portable
export, with an extension map required for store-specific formats.

## Contracts and behavior

- `kernel.attempt_execution` remains the single Attempt lifecycle owner.
- `spine.attempt.TaskAttempt` remains the registered subclass and pickle
  global. Its constructor now delegates only supplied capabilities and refuses
  missing ports through the kernel contract.
- `spine.attempt.run_attempt` remains the exact registry target. The
  orchestration runner injects ports, then invokes that same target.
- `TaskAttempt.run` retains the `begin_effect` anchor and the complete existing
  intent, lease, artifact, gate, evidence, cleanup, and replay ordering.
- `spine.attempt.command_gate` retains its registry target and anchor. It now
  requires an injected scratch-cleanup port; orchestration binds the existing
  `remove_tree_no_follow` implementation.
- `AttemptEvaluatorAdapter` builds the byte/field-equivalent correctness task
  mapping and delegates to the existing evaluator authority.
- Every orchestration composition creates fresh adapter objects. There is no
  singleton or ambient registration.
- Ignition explicitly calls `compose_task_attempt` before it acquires and binds
  the existing Attempt lease. MissionSupervisor requires an injected
  `attempt_factory` before it writes its standalone projection or dispatches.
- `daedalus improve` injects a fresh orchestration-owned workspace/evaluator
  port factory into the stable Picker facade. Picker and Bootstrap invoke the
  unchanged registered `spine.attempt.run_attempt` target with those neutral
  capabilities. Direct uncomposed `spine.picker --once` and candidate-bearing
  `spine.bootstrap` internal starts refuse instead of rediscovering outer
  layers. Their arguments, output structures, Effect Registry rows, and normal
  composed CLI behavior are unchanged.
- The integrity-bound retained Gated-Writes resource now names the
  orchestration runner/gate composition at every live Attempt and cumulative
  gate call. Its resource blob pin changes from the reviewed parent blob to
  reviewed packet blob `0783f7e68e22f9c8e6c687a42e3b8ef294fb57c2`;
  its scheduler, isolation, receipt, candidate, and promotion semantics do not
  change.
- Private monkeypatch forwarding remains on the spine facade. The historical
  one-path `_remove_gate_tmpdir` replacement seam remains callable by the
  registered gate; direct use of the shipped helper now needs the explicit
  cleanup port. This is the deliberate internal compatibility boundary needed
  to remove ambient Kairos trust.
- The shim registry records `daedalus.spine.attempt` with owner
  `kernel-attempt-execution`, target `daedalus.kernel.attempt_execution`, and
  complete source/runtime/wheel/docs/registry/monkeypatch/pickle retirement
  criteria.

## Acceptance matrix

| Claim or refusal | Evidence | Expected |
|---|---|---|
| Directed hierarchy | tracked import scan plus focused AST | zero `spine.attempt -> eval|kairos|orchestration` edges |
| Cold compatibility import | isolated interpreter probe | no Eval, Kairos, or execution-composition module loaded |
| Missing workspace/evaluator | direct registered constructor/runner tests | `AttemptPortMissing`, no runner or workspace effect |
| Missing scratch cleanup | registered command-gate test | refusal before `begin_effect` or process creation |
| Exact composition | injected sentinel ports | exact `spine.attempt.TaskAttempt`, exact supplied ports |
| Evaluator authority | correctness adapter mapping test | identical task fields, root, timeout, and result object |
| Product callers | AST/source plus Ignition/Supervisor/Picker/Bootstrap/Gated-Writes suites | every live call explicitly composed |
| Compatibility | identity, pickle, monkeypatch and broad Attempt tests | stable registered class and private review seams |
| Effect authority | Registry row and semantic digest | unchanged target, anchor, effects, wiring, and digest |
| Retained resource | Git-blob integrity test | exact packet blob, alteration refused before exec |
| Provider/network budget | builder-only tests | no live provider, network, EDA, merge, or promotion |

## Migration and rollback

There is no persistent-data, SQLite, ledger, JSON, CAS, artifact, evidence,
branch, policy, receipt, mission, or runtime migration. Rollback restores the
temporary spine default composition, the previous retained-resource blob pin,
and the previous direct internal callers. The registered facades continue to
carry the prior implementation throughout rollback; no stored locator changes.

The `spine.attempt` facade can be retired only in a dedicated Registry-target
packet after source, runtime-string, installed-wheel, documentation, Effect
Registry, monkeypatch, and pickle audits show no caller, and after provenance
compatibility is explicitly resolved. This packet does not authorize that
retirement or a Registry digest change.

## Evidence expected failures and review

The frozen whole-repository architecture-baseline equality test remains
expected red until the independent `kernel/offload_lease.py` hierarchy packets
remove their ten current outer-layer edges and the baseline is deliberately
refrozen. This packet narrows current `spine-no-outer-layers` findings from two
to zero; it does not rewrite the historical baseline to paint the unrelated
kernel work green.

The older `test_registry_new_doors.py` lower-bound derivation is also already
red at the frozen parent: three tests report 14 unmodelled effect witnesses
after earlier module-alias and retained-source moves. A parent-vs-packet probe
produced the exact same sorted 14 `(row, effect)` pairs. In particular,
`cli.picker` and `cli.bootstrap` still derive `repository_mutation` through the
unchanged registered `spine.attempt.run_attempt` call. This packet neither adds
a bridge nor edits that historical audit to hide its stale model.

Builder evidence must record exact interpreter, test selection/count, cold
import, current tracked import findings, retained-resource digest, Effect
Registry digest, and clean atomic commit. Independent review must confirm that
the orchestration adapter only composes existing owners, the retained source
change is limited to composition imports, direct uncomposed paths refuse, and
no hidden dynamic import or second scheduler/evaluator/workspace authority was
introduced.

Measured builder evidence on the final packet tree:

- CPython 3.13.5 product/caller matrix: `377 passed, 1 skipped`; changed CLI
  and telemetry tests: `61 passed`.
- CPython 3.13.5 Attempt, Registry, retained-source, architecture-helper, and
  Loop matrix: `198 passed, 1 deselected, 1 xfailed`. The deselection is the
  explicitly stale exact-baseline assertion described above.
- CPython 3.10.11 compatibility matrix across Attempt, Picker, Bootstrap,
  Ignition, Supervisor, and Effect Registry: `283 passed, 1 skipped`.
- Work-Packet contract parser tests: `4 passed, 18 deselected`; direct parsing
  identifies `G1-HIER-03D` as a complete post-index primary artifact.
- Tracked architecture measurement: 399 Python files, ten current findings,
  zero `spine-no-outer-layers` findings, ten registered shims. The ten current
  findings are the unrelated kernel baseline drift; no baseline was rewritten.
- Cold `daedalus.spine.attempt` import loads zero Eval, Kairos, or orchestration
  execution-composition modules.
- Retained-resource Git blob:
  `0783f7e68e22f9c8e6c687a42e3b8ef294fb57c2`.
- Effect Registry source blob:
  `65b7c8891b5fab22f5e1bbb993e36e3b63292db0`; semantic digest remains
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`.

No builder result promotes or merges this packet.
