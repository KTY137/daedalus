# G0-PRM-25 — Promotion Effect Rows

## Scope and exact parent

This packet is stacked on the frozen exact head of the typed-manager wiring
packet:

- parent branch: `g0/promotion-manager-wiring-frozen-a824904a`;
- parent revision: `a824904af04b5e7aae11cee187cdad3aacfb4584`;
- source PR represented by that revision: `#140`.

The frozen branch adds no content. It exists only to prevent a concurrently
moving parent ref from changing this Work Packet's review base. No merge,
promotion, OwnerApproval, or effect is performed by creating that branch.

This packet adds only the three missing promotion-execution Event-Store
surfaces to the canonical effect registry:

- `kernel.promotion_execution.open`;
- `kernel.promotion_execution.begin`;
- `kernel.promotion_execution.complete`.

## Registry strangler

The rows bind respectively to:

- durable Event-Store opening and the single-start uniqueness invariant;
- `record_intent` before repository mutation;
- `mark_completed` for the terminal execution receipt.

All three rows declare only `filesystem_write`, require
`spine.intent_ledger`, and remain `local_guards`.

A narrow package-initialization strangler updates the canonical immutable
registry tuple and mapping and refreshes the historical functions' captured
registry defaults before normal callers can observe them. Duplicate, partial,
or contradictory installation refuses. Existing import paths remain valid and
no second registry authority is introduced.

## Honest blocker projection

The scoped promotion inventory remains `closed=false` with exactly four
blockers:

- `python.promote_candidates: registry.not_central:local_guards`;
- `kernel.promotion_execution.open: registry.not_central:local_guards`;
- `kernel.promotion_execution.begin: registry.not_central:local_guards`;
- `kernel.promotion_execution.complete: registry.not_central:local_guards`.

The prior missing-row blockers are resolved. No row is upgraded to `central`.

## Adversarial verification specification

The exact-head workflow defines:

- builder tests for row identity, targets, effects, guards, anchors, and one
  canonical registry state;
- an independent source-level counter-review;
- generic `begin_effect` refusal for all three local rows;
- malformed-input and stale-revision inventory regressions;
- four bounded source mutations covering premature centralization, missing row
  identity, stale captured defaults, and partial installation;
- parent typed-manager wiring regression tests;
- full-suite and isolated-wheel checks;
- Ubuntu and Windows, Python 3.10 and 3.12, and two deterministic hash seeds.

No successful result is claimed before those commands execute against the exact
head. GitHub Actions issue #67 has repeatedly terminated jobs before Step 1
without logs. Such zero-step runs are infrastructure observations, not product,
mutation, packaging, or platform evidence.

## Remaining dependent boundary

A later packet must mechanically compose all of the following around the live
repository effect before any promotion row can honestly become `central`:

- a persisted and exact-scope EffectLease;
- the exact Runtime Manifest;
- a current RuntimeConformanceReceipt;
- current kill-switch generation and authority;
- the selected Docker sandbox and its evidence.

Other production entrypoints, the complete fault-injection matrix, exact-head
release evidence, and independent human review also remain required before Gate
0 may report `closed=true`.

Iron Plan: **ALIGNED BY SCOPE**  
Active gate: **Gate 0**  
Production wiring: **local guards only**  
OwnerApproval: **not issued**  
Promotion: **not requested**
