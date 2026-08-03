# G1-PREP-03 — Deterministic Renovation Replay Planning

## Status

Gate 0 remains the active authoritative gate. This packet is non-executing
Gate-1 preparation stacked on `G1-PREP-02`. It must be replayed and fully
reverified against the final accepted Gate-0 head before Gate 1 can activate.

## Objective

Classify the only safe next action for each of the exactly two canonical
Renovation Attempts from caller-supplied event-spine receipt identities, without
creating a second lifecycle authority.

The packet introduces:

- `AttemptLifecycleObservation`, which binds one exact Attempt, replay key,
  sequence, source revision, lifecycle state, and content-addressed start and
  terminal receipt identities;
- `RenovationReplayDecision`, which derives one of `execute`,
  `blocked-dependency`, `reconcile`, `return-terminal`, or `restart-required`;
- `RenovationReplayPlan`, which binds exactly two ordered decisions to the exact
  canonical `RenovationAttemptPlan`;
- strict canonical mapping/file parsing with recursive duplicate-key refusal;
- consumer verification that revalidates the complete WorkItem, mission,
  Fourfold, runtime-manifest, policy, Attempt, observation, and decision chain.

## Fail-closed lifecycle semantics

The planner does not infer success from an absent row and does not permit an
in-flight Attempt to execute again:

- `not-started` has no receipts and may execute only when dependencies permit;
- `started` and `unknown` require a start receipt and produce `reconcile`;
- `succeeded` requires start and terminal receipts and returns the retained
  terminal identity;
- `failed` and `cancelled` require start and terminal receipts and produce
  `restart-required`, never another execution of the same Attempt identity;
- sequence 1 cannot have any lifecycle state before sequence 0 succeeds;
- sequence 1 remains `blocked-dependency` while sequence 0 is incomplete.

`restart-required` is deliberately not a restart implementation. A later active
Gate-1 packet must create a new canonical Attempt through the existing event
spine, persist it, and prove crash/restart behavior with a real isolated
workspace and Effect-Lease-authorized runtime.

## Authority boundary

This packet contains no:

- SQLite or alternative lifecycle/event ledger;
- worktree, CAS candidate materialization, or source mutation;
- Effect Lease issuance, runtime invocation, provider callback, or network call;
- EvidencePacket, nomination, OwnerApproval, PromotionReceipt, merge, or
  promotion;
- automatic action dispatch.

The replay plan is a recomputable read-only decision artifact. Consumers must
supply current authoritative observations and cannot trust a candidate-authored
plan by itself.

## Adversarial verification request

Builder and separate source-review tests cover:

- fresh, successful, in-flight, unknown, failed, and cancelled states;
- dependency ordering and dependent early-start refusal;
- foreign Attempt, replay-key, and stale-revision substitution;
- contradictory receipt shapes;
- forged but structurally valid action repackaging;
- nested noncanonical arrays and recursive duplicate JSON keys;
- absence of execution, persistence, effect, approval, and promotion authority.

The bounded mutation campaign attacks:

1. removal of the dependency-success fence;
2. conversion of reconciliation into duplicate execution;
3. removal of consumer-side recomputation equality.

Dedicated CI requests Ubuntu and Windows, Python 3.10 and 3.12, two hash seeds,
parent WorkItem/Attempt/Fourfold/kernel tests, compile-all, Iron Plan, mutations,
the full suite, and isolated-wheel imports.

GitHub Actions issue #67 remains an external exact-head blocker while hosted jobs
terminate before Step 1 with no logs or artifacts. Such runs are infrastructure
observations only and cannot be represented as product or Gate evidence.

Promotion: **not requested**
