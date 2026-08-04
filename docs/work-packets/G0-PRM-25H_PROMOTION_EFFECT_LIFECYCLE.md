# G0-PRM-25H — Promotion Effect-Lease Lifecycle Strangler

## Scope

This packet adds a named strangler adapter around the existing sealed promotion callable. The historical implementation remains intact and reviewable. The adapter supplies the missing outer Effect-Lease lifecycle without replacing the established approval, evidence, candidate, target-head, promotion-execution, manager-audit, worktree, cleanup, and primary-checkout protections.

The adapter is not yet installed as the sole public production entrypoint. The canonical promotion inventory row therefore remains `local_guards`.

## Fresh transition order

For a fresh exact subject, the adapter performs:

1. resolve and verify the live target revision;
2. snapshot the submitted candidate batch;
3. reconstruct the persisted promotion authorization from consumed OwnerApproval and EvidencePacket;
4. compare the complete reconstructed authorization with the supplied `PromotionEffectCapability`;
5. grant or exactly replay the persisted Effect Lease;
6. persist the top-level effect start;
7. call the sealed historical promotion entrypoint;
8. strictly reproject both persisted lifecycles;
9. append only the evidence-derived effect terminal when required;
10. return the retained promotion report with bounded lifecycle status.

The preauthorization occurs before any effect start. The effect start occurs before the sealed promotion can persist its own promotion-execution start or enter worktree mutation.

## Restart behavior

The adapter never treats a retained nonterminal start as permission to execute again.

- `fresh`: may run the ordered fresh path;
- `effect-only-pending-reconciliation`: returns pending state, no promotion call;
- `promotion-pending-reconciliation`: returns pending state, no promotion call;
- `effect-terminalization-required`: invokes only the terminal accounting authority from G0-PRM-25G;
- `complete`: returns the exact retained promotion report, no promotion call.

A delegate return value is not evidence. Terminal responses are reconstructed from the strict persisted promotion completion. A forged or incomplete delegate return cannot replace the retained report.

## Cross-ledger fault windows

The packet prepares deterministic tests for every transition window available at this layer:

- preauthorization failure before lease grant leaves no effect start;
- a crash after lease grant but before effect start continues through exact lease replay;
- a failure after effect start but before promotion start leaves `effect-only-pending-reconciliation`;
- a crash after promotion start but before its terminal leaves `promotion-pending-reconciliation`;
- a crash after promotion terminal but before effect terminal is terminalization-only;
- a restart after both terminals returns exact retained completion.

A concurrent effect start suppresses delegate execution. A second call in any pending state does not re-enter the sealed promotion callable. Pending error text is bounded and does not claim automatic execution authority.

## Adversarial batch

Prepared verification includes:

- exact preauthorization argument and complete-subject binding tests;
- ordering proof that the effect start exists before the delegate runs;
- grant-only continuation;
- fresh success, terminal-required restart and complete replay;
- effect-only and promotion-pending no-reexecution tests;
- concurrent effect-start suppression;
- delegate exception without fake terminal;
- forged delegate-return rejection;
- terminalizer failure remaining pending;
- owner-keyring refusal before effect start;
- independent AST/source review;
- nine bounded mutants;
- Ubuntu and Windows, Python 3.10 and 3.12, two hash seeds, full suite, Iron Plan, packaging and isolated-wheel import checks.

The source review permits only one delegated external promotion call, one grant, one effect begin, and terminal-only reconciliation calls. It rejects direct Git, subprocess, worktree, lower-level terminal, approval issuance, approval verification, and automatic-execution authority in this adapter.

## Remaining installation boundary

This packet intentionally exposes a named adapter rather than silently replacing `gated_writes.promote_candidates`. A dependent packet must install one compatibility-preserving public route, inventory or demote the direct bypass, and prove that every production caller reaches the outer lifecycle. It must also define the operator action for `effect-only-pending-reconciliation`, execute the full cross-ledger fault matrix on an exact head, and only then move the registry row to `central`.

All other Gate-0 runtime, Docker sandbox, conformance, entrypoint inventory, fault-matrix, packaging, platform and machine-readable release-report blockers remain in force.

Exact-head execution remains pending because repository GitHub Actions issue #67 currently terminates jobs before Step 1. Zero-step runs are infrastructure observations only and are not verification evidence.

No merge, OwnerApproval, promotion, registry centralization, or Gate transition is requested.
