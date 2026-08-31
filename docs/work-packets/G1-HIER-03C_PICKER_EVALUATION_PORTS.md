# G1-HIER-03C - Picker evaluation ports

## Frozen packet metadata

- Packet ID: G1-HIER-03C
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: e9cf58a9e97db93d8f2627b52a59e2d58808db4b
- Dependencies: G1-HIER-01, G1-HIER-02, G1-HIER-03A, G1-ORCH-01
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

The registered `daedalus.spine.picker:main` effect door retains its target,
anchor, CLI name, queue semantics, and monkeypatch seams while the canonical
spine no longer imports `daedalus.eval`. The ordinary `daedalus improve`
composition injects the existing evaluator through neutral kernel ports.

## Scope

This packet adds `EvaluationBaselinePort`, `EvaluationGatePort`, and
`EvaluationPorts` under `kernel.contracts`. The concrete adapter lives under
`orchestration.execution`; evaluator implementation and baseline authority
remain in `daedalus.eval.harness`. It removes the two frozen
`spine-no-outer-layers` import edges without moving the registered target or
creating another evaluator, event store, artifact identity, policy, or
promotion path.

## Contracts and behavior

- `daedalus improve` injects both evaluator functions for each invocation.
- The cheap retained baseline is still available to a direct module start by
  reading the same immutable JSON path and preserving the historical
  missing-file empty baseline.
- A direct `python -m daedalus.spine.picker --eval` without an orchestration
  composition fails closed as an unavailable source; it never reaches across
  the spine boundary or silently reports a fresh pass.
- Existing `_load_baseline` and `_run_eval_gate` seams remain callable and
  monkeypatchable for compatibility tests.
- `EvaluationPorts` are capabilities, not result or serialization authority.
  Gate results retain their existing dictionary contract and evaluator owner.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Directed hierarchy | tracked import scan and focused AST test | zero `spine -> eval` imports |
| Import isolation | fresh isolated interpreter probe | importing picker loads no `daedalus.eval` module |
| Production composition | CLI source/behavior tests | exact injected baseline and gate ports |
| Direct-start refusal | uncomposed `include_eval` test | explicit unavailable-source result, no fresh verdict |
| Compatibility | picker, queue, health, loop and registry suites | stable public names and queue behavior |
| Effect authority | semantic Registry digest | unchanged digest above |
| Provider/network budget | builder tests only | zero live provider or network calls |

## Migration and rollback

Rollback restores the two lazy evaluator imports in `spine.picker` and removes
the neutral port and orchestration adapter modules. There is no persistent-data
migration, effect target migration, baseline rewrite, or historical evidence
move.

## Evidence expected failures and review

The frozen whole-repository architecture baseline is expected to remain red
until all Gate-1 hierarchy packets remove the other recorded edges and the
operational baseline is deliberately refreshed. Existing integration-only
painted-effect diagnostics outside this packet remain retained negative
evidence. Independent review must confirm that the semantic Effect Registry
digest is unchanged, the normal CLI still supplies the evaluator, and no
dynamic import hides an evaluator dependency inside the spine.
