# G0-PRM-12A — Persisted Promotion Authorization

## Gate and parent

- Active gate: Gate 0
- Exact parent: `bcf464b17c2b01f8213349d53e141b51a41251f6`
- Parent branch: `g0/authenticated-approval-consumption-linear`
- Promotion: not requested

## Acceptance claim

A self-consistent `ConsumedOwnerApproval` is not promotion authority. Before
candidate/evidence/HEAD binding can yield a `PromotionAuthorization`, the exact
consumption receipt must be re-authenticated against the persisted
`ApprovalLedger` using an independently supplied owner keyring.

This packet adds the pure, non-effectful composition boundary
`authorize_persisted_promotion`. It:

1. requires an actual `ApprovalLedger` and a non-empty owner keyring;
2. calls `ApprovalLedger.verify_consumption` before candidate authorization;
3. therefore re-authenticates the retained signed `OwnerApproval` and requires
   exact canonical persisted receipt/row equality;
4. rejects a receipt from a foreign or empty ledger;
5. rejects an unknown or incorrect owner key;
6. rejects a ledger that substitutes a different consumption capability;
7. preserves every existing candidate, EvidencePacket, source-revision and
   live-target-HEAD binding in `authorize_promotion`;
8. performs no Git, worktree, provider, network or repository mutation.

## Deliberate boundary

This packet does **not** yet modify
`daedalus.kairos.gated_writes.promote_candidates`. The current live seam still
calls the pure `authorize_promotion` primitive directly. A dependent packet
must make `authorize_persisted_promotion` mandatory while the promotion lock is
held, re-read the target ref inside that lock immediately before worktree
creation, and start the integration branch from that authorized target
revision rather than from an ambient candidate base.

No `PromotionReceipt` is issued here. Receipt construction and durable CAS
persistence remain a separate batch after the live mutation seam is sealed.

## Adversarial verification

The focused suite covers:

- exact persisted and authenticated success;
- a valid-looking consumption presented to a different ledger;
- wrong owner-key re-authentication;
- stale candidate binding after successful persistence verification;
- missing ledger and empty keyring;
- a malicious `ApprovalLedger` subclass/instance substituting another valid
  capability;
- source-order review proving persistence verification precedes the pure
  binding call and the new function contains no effectful imports or calls.

The bounded mutation runner attacks three non-equivalent seams:

1. bypass persisted-consumption verification;
2. accept a different capability returned by the ledger;
3. allow an empty owner keyring.

The workflow requests the focused Trust/Gate batch, the complete repository
suite, Ubuntu and Windows on Python 3.10/3.12 with two hash seeds, the bounded
mutation campaign and isolated-wheel import verification.

## Verification status

Repository-wide GitHub Actions issue #67 currently causes exact-head jobs to
finish before Step 1 with no step records or logs. Consequently no workflow
result can be treated as execution evidence until the infrastructure issue is
resolved. This packet must remain a draft and must not be described as green
solely because its workflow was scheduled.

Builder review is source-complete. Exact-head test, mutation, full-suite,
platform and wheel evidence remain pending external CI execution.
