# G0-PRM-22 — Promotion Manager Audit

## Objective

Close the remaining post-mutation identity gap in `G0-PRM-20` without rewriting the retained live promotion function. The packet records exact integration-worktree allocation, cleanup and branch-reaper outcomes, binds that immutable audit into the canonical promotion-execution report, and refuses terminal accounting whenever the surviving branch identity cannot be proven.

## Corrected strangler boundary

Adversarial review found that the first draft described a retained-source loader and production installation that were not present in the final tree. It also replaced the public `PromotionExecutionLedger` class with a factory even though the sealed promotion callable performs an `isinstance` check against that global. Installing the draft literally would therefore raise `TypeError` before any promotion work.

The corrected boundary is narrower and honest:

1. `AuditedWorktreeManager` remains a pure delegate/audit adapter;
2. the public `PromotionExecutionLedger` class is never replaced;
3. one already-open, correctly typed ledger instance is wrapped only for the duration of a public promotion call;
4. both audit and replay proxies subclass the canonical ledger type, while an arbitrary duck-typed object is deliberately left unwrapped so the sealed parent rejects it;
5. a `ContextVar` scopes the one audited manager to one call and rejects a second manager allocation;
6. the manager and replay installers remain **unwired** until the dependent production-wiring packet.

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

The typed execution-ledger proxy injects the audit snapshot and digest before delegating to the existing `PromotionExecutionLedger.complete` authority.

- A successful promotion must bind the one allocated branch, its current live revision and a `retained` reaper action.
- A refusal can omit integration identity only when cleanup succeeded and the reaper explicitly reports `deleted` or `absent` for the allocated branch.
- A surviving `pending` or `retained` branch after refusal becomes an exact fault with current branch revision.
- Cleanup or reaper failure becomes an exact fault when the surviving branch can be resolved.
- Allocation failure or any other post-mutation ambiguity remains a pending-reconciliation intent unless either a live branch revision or a proven deleted/absent outcome is available.
- Pre-mutation refusal remains valid without manager allocation evidence.

Replay reconstructs the exact audit schema and digest and refuses a persisted terminal completion whose report/receipt identity or lifecycle evidence is contradictory.

## Adversarial verification prepared

Focused tests cover successful retained branches, proven deleted refusals, refused-but-surviving pending branches, swallowed reaper failure, unresolved post-mutation identity, fault re-binding, pre-mutation refusal, allocation/cleanup/reaper failures, immutable snapshots and opaque non-JSON reaper results.

The corrected installation tests prove that:

- the public ledger class remains the canonical class;
- a real typed ledger becomes an audit proxy that still passes the sealed type check;
- replay selects a typed replay proxy without replacing the class;
- an arbitrary object is not laundered into a valid ledger;
- duplicate and out-of-order installer calls refuse;
- the live public module does not yet claim either installer call.

Separate source reviews prove delegation order, no mutating authority in the adapters, audit binding before terminal delegation, semantic replay validation and pending reconciliation for unknown identity. Bounded mutation campaigns now use unique source seams and attack failure recording, reaper ambiguity, digest/report binding, stale revision, deletion proof, completion assessment, ledger laundering, class replacement and replay-selector bypass.

## Deliberate remaining boundary

This packet is not production wiring. It does not issue OwnerApproval, consume an EffectLease, create promotion authorization, merge a branch or automatically promote. A dependent packet must install the manager and replay adapters in `daedalus.kairos.gated_writes`; another dependent packet must compose EffectLease, runtime conformance and Docker containment before the promotion surface can become `central`.

Gate 0 remains open. The following work still includes canonical effect-inventory registration, complete release evidence, runtime/sandbox closure and the remaining fault matrix.

## Verification status

Executable tests, mutation checks, Python/platform matrix, full-suite and isolated-wheel checks are prepared. They become evidence only when the exact head executes. GitHub Actions issue #67 currently terminates jobs before Step 1; zero-step runs are infrastructure observations only.

Iron Plan: **ALIGNED BY CORRECTED SCOPE**  
Active gate: **Gate 0**  
Production wiring: **not claimed**  
Promotion: **not requested**
