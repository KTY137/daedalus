# G0-PRM-25 — Promotion Effect Rows

## Scope

This packet is stacked on typed manager wiring at exact parent
`d8b09fd2281080d50e817b022191ad777d1eadb0`. It adds only the three missing
promotion-execution Event-Store surfaces to the canonical effect registry:

- `kernel.promotion_execution.open`;
- `kernel.promotion_execution.begin`;
- `kernel.promotion_execution.complete`.

The rows bind respectively to durable Event-Store open/unique-start setup,
`record_intent`, and `mark_completed`. They declare only `filesystem_write`,
require `spine.intent_ledger`, and remain `local_guards`.

A narrow package-initialization strangler refreshes the canonical immutable
registry tuple, mapping, and captured function defaults before normal callers
can observe them. Duplicate, partial, or conflicting installation refuses.
Existing import paths remain compatible; no second registry is created.

## Honest result

The scoped promotion inventory remains `closed=false` with exactly four
`registry.not_central:local_guards` blockers: the public promotion callable and
the open, begin, and complete execution surfaces. Missing-row blockers are
resolved, but no row is promoted to `central`.

## Verification specification

- exact row, target, effect, guard, anchor and default-registry tests;
- independent source-level counter-review;
- generic `begin_effect` refusal for all local rows;
- malformed/stale inventory regression coverage;
- four bounded mutations for premature centralization, missing identity, stale
  captured defaults, and partial installation;
- parent typed-manager tests, full suite, isolated wheel;
- Ubuntu/Windows, Python 3.10/3.12, two hash seeds.

GitHub Actions issue #67 currently prevents jobs from recording Step 1. Zero-step
runs are infrastructure observations, not verification evidence.

## Remaining boundary

A dependent packet must compose persisted EffectLease authority, the exact
Runtime Manifest, current RuntimeConformanceReceipt, kill-switch state, and the
selected Docker sandbox before any promotion row can honestly become `central`.

Iron Plan: **ALIGNED BY SCOPE**  
Active gate: **Gate 0**  
OwnerApproval: **not issued**  
Promotion: **not requested**
