# G0-PRM-22 — Promotion Manager Audit

## Objective

Close the remaining post-mutation identity gap in `G0-PRM-20` without rewriting the retained live promotion function. The packet records the exact integration-worktree allocation, cleanup and branch-reaper outcomes, binds that immutable audit into the canonical promotion-execution report, and refuses terminal accounting whenever the surviving branch identity cannot be proven.

## Strangler boundary

The exact parent `daedalus/kairos/gated_writes.py` blob is retained as `_gated_writes_execution_accounting.py.src`. The public module becomes a short compatibility loader that:

1. verifies the retained Git-blob digest;
2. executes the exact parent implementation under the historic import path;
3. replaces only the `GitWorktreeManager` and `PromotionExecutionLedger` constructor seams;
4. preserves the public `promote_candidates` call surface.

No Big-Bang rename, duplicate promotion implementation, new Git command path or new workflow database is introduced.

## Manager audit

`AuditedWorktreeManager` delegates each effect before recording its outcome. It retains:

- exact base revision and allocated branch;
- returned worktree path or allocation failure identity;
- exact cleanup target and success/failure;
- exact branch-reaper result or failure identity;
- bounded exception type, message prefix and full-message digest;
- deterministic audit digest.

Exceptions are recorded and re-raised unchanged. The adapter does not suppress, retry or translate manager effects.

## Terminal decision rules

The execution-ledger proxy injects the audit snapshot and digest before delegating to the existing `PromotionExecutionLedger.complete` authority.

- A successful promotion must bind the one allocated branch, its current live revision and a `retained` reaper action.
- A refusal can omit integration identity only when cleanup succeeded and the reaper explicitly reports `deleted` or `absent` for the allocated branch.
- A surviving `pending` or `retained` branch after refusal becomes an exact fault with current branch revision.
- Cleanup or reaper failure becomes an exact fault when the surviving branch can be resolved.
- Allocation failure or any other post-mutation ambiguity remains a pending-reconciliation intent unless either a live branch revision or a proven deleted/absent outcome is available.
- Pre-mutation refusal remains valid without manager allocation evidence.

This prevents the retained internal reaper exception handler from silently converting a failed cleanup lifecycle into an optimistic success or refusal.

## Adversarial verification prepared

The focused tests cover successful retained branches, proven deleted refusals, refused-but-surviving pending branches, swallowed reaper failure, unresolved post-mutation identity, fault re-binding to the current branch revision, pre-mutation refusal, allocation/cleanup/reaper failures, immutable snapshots and opaque non-JSON reaper results.

A separate source review proves that:

- the wrapper executes the exact parent blob before installing the adapter;
- no promotion algorithm is reimplemented in the wrapper;
- only constructor and public-call seams are replaced;
- the adapter delegates before recording success and re-raises every failure;
- no mutating Git, filesystem, OwnerApproval or merge authority enters the boundary;
- audit data is injected before terminal delegation;
- unknown identity uses pending reconciliation rather than optimistic terminalization.

A bounded mutation campaign attacks failure recording, reaper-row ambiguity, audit digest binding, refusal deletion proof, success revision/reaper checks, report binding, completion assessment and ledger installation.

## Deliberate remaining boundary

This packet does not issue OwnerApproval, create a promotion authorization, merge a branch or automatically promote. It does not change the owner-decision receipt authority. It remains dependent on successful exact-head verification of the Core Event-Spine and Live Promotion Execution Accounting packets.

Gate 0 remains open. The following work still includes canonical effect-inventory registration for all final live seams, complete release evidence, runtime/sandbox closure and the remaining fault matrix.

## Verification status

Executable tests, mutation checks, Python/platform matrix, full-suite and isolated-wheel checks are prepared on the branch. They become evidence only when the exact head executes. Repository Actions issue #67 currently terminates jobs before Step 1; such runs are infrastructure observations only.

Iron Plan: **ALIGNED BY SCOPE**  
Active gate: **Gate 0**  
Promotion: **not requested**
