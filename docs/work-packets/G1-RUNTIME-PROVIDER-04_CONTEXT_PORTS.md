# G1-RUNTIME-PROVIDER-04 - Provider context ports

## Frozen packet metadata

- Packet ID: G1-RUNTIME-PROVIDER-04
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: 0ce7414a3c22e3357816e08a76ed0b1478f3e41d
- Dependencies: G1-RUNTIME-PROVIDER-03
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

`daedalus.runtimes.providers.context` owns provider context capacity and graph
brief selection. Sensitivity reads and graph projection are explicit injected
ports, so the runtime owner imports no outer product layer. The legacy
`providers._report` module is reduced to per-call compatibility wrappers and
exact helper reexports.

## Scope

Only the two remaining context helper implementations move. Sensitivity
classification, file contents, graph traversal, provider prompts, report
coercion, admission, network/subprocess calls, Effect targets, stores, and
persistent data remain unchanged.

## Contracts and behavior

- Legacy function signatures, defaults, return values, bounded capacity,
  complete-input capacity calculation, graph-capacity doubling, and
  best-effort empty-brief fallback are unchanged.
- The facade imports the current sensitivity function on each call and passes
  its current graph function bindings on each call. Existing module
  monkeypatch seams therefore remain observable.
- The runtime owner receives callable ports and imports only standard library,
  kernel limit policy, and its sibling execution-policy owner. It cannot reach
  sensitivity, lanes, Kairos, gates, orchestration, interfaces, providers, or
  chip design on its own.
- `providers._report` retains two thin wrappers and no loop, filesystem read,
  retry, or exception-handling implementation.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Live port injection | per-call monkeypatch contract | patched sensitivity/graph ports invoked |
| Capacity compatibility | bounded/unbounded provider tests | identical context and completion conditions |
| Thin facade | AST contract | two wrappers; no loop/try implementation |
| Directed owner | owner import contract | no outer-layer imports |
| Provider behavior | Codex, budget, hardening, report suites | unchanged |
| Architecture/Registry | frozen checks | zero forbidden edges; 18 shims; exact digest |

## Migration and rollback

There is no persistent migration. Rollback restores the two helper bodies in
`providers._report`, removes the context owner, and restores the prior shim
description. No JSON report, ledger, receipt, database, CAS locator, evidence
path, historical run, registered Effect target, or provider admission changes.

## Evidence, expected failures, and review

- Python 3.13: 293 focused context, execution-policy, provider-report,
  agent-environment, budget, Codex, hardening, and architecture tests passed.
- Python 3.10: the same 293 focused tests passed.
- Cold imports and AST checks prove the facade/owner split; changed modules
  compile and `git diff --check` is clean.
- The Effect Registry semantic digest remains exactly
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`.

Review must reject any future default port that imports an outer layer inside
the runtime owner; composition belongs at the compatibility/effect door. The
global Work-Packet index remains deferred to central integration because of
the inherited G1-HERMES-01 section defect. This packet does not edit the Master
Plan, amendment chain, historical `runs/`, generated web distribution,
Registry targets, or promotion state.
