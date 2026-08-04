# G0-PRM-20 — Live Promotion Execution Accounting

## Scope

This packet wires the already-authenticated, manual Kairos promotion seam into
the canonical promotion-execution Event-Store lifecycle. It does not merge an
integration branch, create an OwnerApproval, broaden candidate batches, or
close Gate 0.

The retained historical gating implementation remains an exact Git-blob-bound
package resource. Only the public `promote_candidates` strangler is extended.

## Execution order

The live boundary now performs the following sequence:

1. snapshot exactly one clean, non-empty candidate;
2. authenticate the persisted consumed OwnerApproval against candidate,
   evidence, source revision, target ref, and owner-bound expected target;
3. observe a stable source-visible primary-checkout fingerprint;
4. persist `PromotionExecutionStart` in the canonical Event Store;
5. refuse automatic execution when that start is already pending;
6. return the exact retained terminal report when it is already completed;
7. acquire the promotion lock;
8. sample live target HEAD and re-authenticate the same authority;
9. require the live authorization digest to equal the persisted start;
10. require candidate base to equal the authorized live target;
11. mark entry into the retained mutation implementation;
12. invoke the retained integration-worktree implementation;
13. retain any created integration-branch identity before validating the
    returned report or resolving the branch revision;
14. resolve the exact integration branch revision;
15. observe the primary checkout again;
16. persist one success, refusal, or fault receipt and return its retained
    report.

A missing `PromotionExecutionLedger` refuses before capability verification or
repository effects. An unresolved restart never repeats promotion
optimistically; it requires reconciliation.

An exception before mutation entry may be recorded as a refusal. Every known or
unexpected exception after mutation entry is recorded as a fault. This includes
malformed retained reports and failure to resolve the exact revision of an
already-created integration branch.

## Primary-checkout identity

`daedalus.kernel.promotion_fingerprint` is intentionally read-only. It:

- excludes only `.git` and `.daedalus` control roots;
- rejects redirected roots, symlinks, and non-regular entries;
- binds relative path, byte length, raw SHA-256, and executable bit;
- performs two observations and refuses an unstable tree.

A changed primary checkout cannot be represented by a successful or refused
terminal receipt. The live seam attempts to retain it as an explicit fault; if
terminal persistence itself cannot be established, the start remains pending
and the returned report says reconciliation is required.

## Fault-report boundary

A malformed, oversized, non-finite, or otherwise noncanonical report returned
by the retained implementation is untrusted input. The fault terminalizer does
not copy that raw object into the canonical Event Store. It retains only the
known integration branch/revision, authorization, exception type, and a boolean
showing whether a report object was observed. This preserves terminal
accounting without laundering attacker-shaped report material into evidence.

## Adversarial coverage

Focused tests cover:

- missing execution authority before any boundary primitive;
- start persistence before promotion-lock entry;
- exact terminal replay without lock or mutation;
- pending restart without automatic re-execution;
- substituted live authorization;
- stale candidate refusal;
- post-mutation authorization errors classified as faults;
- malformed post-mutation reports terminalized without raw-report copying;
- created branch identity retained when exact revision lookup fails;
- primary-checkout mutation converted to a terminal fault;
- redirected-root and symlink refusal;
- deterministic fingerprints and control-root exclusion.

The bounded mutation runner attacks the mandatory execution ledger, restart
branch, live-authorization equality, stale-candidate fence, post-mutation fault
classification, branch-identity handoff, raw-report copying, after-fingerprint,
redirected root, and control-root exclusion.

## Verification status

The branch contains the focused tests, structural counter-review, mutation
runner, CI matrix, Work Packet status, and packaging checks. Exact-head
execution remains pending because current GitHub Actions runs are affected by
repository issue #67 and record no executable steps. Such a run is not evidence.

## Deliberate remaining boundary

This packet makes execution accounting mandatory at the live seam, but the
canonical effect inventory still needs its own small dependent update for the
new `PromotionExecutionLedger.begin` and `.complete` writes and the strengthened
promotion anchors. EffectLease, RuntimeConformanceReceipt, and Docker sandbox
composition also remain required before the promotion row can become
`central` and before Gate 0 can report `closed=true`.
