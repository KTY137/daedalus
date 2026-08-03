# G0-PRM-12D — Live Promotion Receipt Integration

## Purpose

This packet connects the persisted `PromotionLedger` from G0-PRM-12C to the
already sealed Kairos promotion seam. It remains an explicit owner operation,
creates only an integration branch, and never merges or promotes automatically.

## Ordering and authority

While holding the existing cross-process promotion lock, the live seam now:

1. re-reads the target ref;
2. re-authenticates the exact persisted `OwnerApproval` consumption;
3. refuses stale candidate bases;
4. fingerprints and requires a clean primary checkout;
5. commits `PromotionStartRecord` before retained integration-worktree code;
6. executes at most once;
7. fingerprints the primary checkout again;
8. resolves the integration branch revision when one exists;
9. commits and reads back one terminal `PromotionReceipt`.

A canonical `PromotionLedger` is mandatory. Compatibility callers that omit it
retain the old call shape but can only receive a structured refusal.

## Replay and recovery boundary

An exact terminal replay returns the persisted report and receipt without
calling the retained mutation path. A persisted start without a terminal record
is an unknown outcome. It is marked `promotion_pending_reconciliation` and is
never automatically retried.

This packet deliberately does not invent reconciliation policy. A later fault
and recovery packet must inspect pending starts and integration refs under an
operator-controlled procedure.

## Primary checkout fence

The primary checkout observation binds the exact HEAD and SHA-256 of Git's
NUL-delimited porcelain status with optional locks disabled. Promotion refuses
a dirty checkout before the start record. A changed or dirty post-execution
observation forces a `faulted` receipt; it cannot be reported as success.

## Adversarial evidence specified by this packet

The focused tests cover:

- start persistence before the retained mutation seam;
- terminal persistence and exact read-back after execution;
- terminal replay without integration re-entry;
- pending-start replay refusal;
- dirty pre-state refusal;
- changed primary identity forcing a fault;
- execution exceptions terminalized without leaking exception details;
- refused integration retained as a non-success receipt;
- rejection of noncanonical promotion-ledger substitutes.

The mutation runner attacks the canonical-ledger check, replay fence,
pre-execution cleanliness check, post-execution identity comparison and terminal
read-back.

## Independent review finding corrected

An earlier intermediate implementation copied the retained `_promote_locked`
algorithm but invoked `_promote_one` with an incompatible signature. That path
would have converted every real candidate into a refusal. The reviewed version
does not duplicate that algorithm: it keeps the exact retained implementation
and places the persisted start/terminal boundary around it.

## Verification status

Source, tests, mutation runner, workflow and isolated-wheel smoke are included in
this Work Packet. GitHub-hosted verification remains externally blocked by the
repository-wide Actions failure tracked in issue #67: affected jobs terminate
before Step 1 and expose no logs or artifacts. No green CI claim is made until
an exact-head run executes these commands.

## Deliberate remaining Gate-0 boundary

This packet does not close Gate 0. Pending-start reconciliation, isolated
attempt/CAS wiring, runtime conformance, Docker sandboxing, complete effect-entry
coverage and the full fault-injection matrix remain separate dependent packets.
