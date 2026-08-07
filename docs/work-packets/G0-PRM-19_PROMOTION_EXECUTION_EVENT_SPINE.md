# G0-PRM-19 — Promotion Execution Event Spine

## Objective

Persist the exact start and terminal outcome of an already authorized promotion attempt in the repository's single canonical Event Store. This closes the accounting gap between `PromotionAuthorization` and the live mutation seam without creating a second owner-decision receipt, workflow database, approval issuer, automatic promotion path, or merge authority.

## Authority split

`daedalus.schemas.PromotionReceipt` remains the canonical owner-decision receipt. This packet introduces deliberately distinct mutation-accounting contracts:

- `PromotionExecutionStart`;
- `PromotionExecutionReceipt`;
- `PromotionExecutionLedger`.

The ledger wraps `SpineLedger`, opens writers only through `open_gate0_spine_writer`, verifies the Gate-0 durability profile and appends one `promotion.execution` intent followed by at most one terminal event. It creates no private SQLite lifecycle tables.

## Start binding

Before any later live promotion mutation, `begin()` requires a self-consistent `PromotionAuthorization` and persists:

- promotion identifier;
- authorization digest;
- authenticated approval-consumption digest;
- exact candidate digest;
- exact EvidencePacket digest;
- source revision;
- target ref and authorized target HEAD;
- primary-checkout fingerprint before mutation;
- trusted kernel timestamp and provenance.

A unique partial index over the canonical Event Store enforces one start for each promotion effect key. Exact replay returns the persisted start with `execute=false`; changed start ID, candidate, evidence, authorization, target or checkout identity refuses.

## Terminal binding

`complete()` appends one terminal event and retains:

- the exact persisted start digest and all repeated authorization fields;
- canonical promotion report digest and report bytes;
- outcome `succeeded`, `refused` or `faulted`;
- integration branch and revision where applicable;
- primary-checkout fingerprint after the attempt;
- trusted completion timestamp and provenance.

A successful result requires exactly one promoted row, exact integration identity, exact authorization material and an unchanged primary checkout. A refusal cannot retain integration identity or mutate the primary checkout. A changed primary checkout can only be accounted as `faulted`, with explicit fault evidence. The report is bounded to 4 MiB, retained immutably and revalidated semantically whenever it is read. Non-finite numbers, non-string object keys, unsupported values and canonical round-trip coercion refuse before a terminal Event-Store write.

## Adversarial batch

The focused builder tests cover restart and pending reconciliation, exact terminal replay, changed-subject replay, authorization-digest recomputation, report substitution, integration-revision substitution, primary-checkout mutation, refusal semantics, concurrent starts, corrupted terminal events, malformed contracts, stale kernel time and read-only Event-Store refusal.

The malformed-input batch additionally covers oversized reports, `NaN`, positive and negative infinity, non-string object keys, non-JSON values, completion timestamps before their persisted starts and coherently rehashed reports whose semantics contradict their terminal receipts.

A separate AST/source review checks that this module:

- defines no second class named `PromotionReceipt`;
- creates no private SQLite connection or lifecycle table;
- imports no Git, provider, Kairos, approval-issuance or merge authority;
- commits through `record_intent` and terminates through `mark_completed`;
- retains the Gate-0 writer factory, durability check and unique start invariant;
- freezes, bounds and strictly canonicalizes retained reports;
- revalidates terminal report semantics after restart.

The bounded mutation runner attacks authorization digest verification, timestamp proximity, report authorization binding, primary-checkout preservation, terminal start binding, start-ID replay, completion ordering, strict JSON handling, canonical round-trip equality and the unique start index.

## Deliberate remaining boundary

This packet does **not** wire the live `promote_candidates` seam. It therefore performs no repository mutation and cannot issue a successful production execution receipt yet. The following dependent packet must:

1. register `PromotionExecutionLedger.begin` and `.complete` honestly in the effect inventory;
2. require a persisted start immediately before the first live promotion mutation;
3. always append a terminal receipt or leave an explicit pending reconciliation record after interruption;
4. bind the live integration revision and before/after primary-checkout fingerprints;
5. preserve separate manual OwnerApproval and prohibit automatic promotion.

Gate 0 remains open. This packet does not claim `closed=true`, does not produce OwnerApproval, and does not merge or promote any branch.

## Verification status

The branch carries executable tests, source review, mutation campaign, full-suite job and isolated-wheel job. Results become evidence only when executed on the exact branch head. Repository Actions issue #67 currently prevents jobs from reaching Step 1; a zero-step run is an infrastructure observation, not verification.

Iron Plan: **ALIGNED BY SCOPE**  
Active gate: **Gate 0**  
Promotion: **not requested**
