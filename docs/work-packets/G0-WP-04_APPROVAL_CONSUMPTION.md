# G0-WP-04 — Authenticated Approval Consumption

## Position in the Gate-0 chain

Parent: `G0-WP-03 — Persisted Effect Leases`  
Branch: `g0/approval-consumption`  
Promotion: not implemented and not requested

This packet repairs the authority gap discovered during the independent review of `G0-WP-02`. It does not apply candidates, update refs, mutate a primary checkout or issue an owner decision.

## Problem statement

The previous replay ledger consumed a publicly constructible `VerifiedOwnerApproval` record. That record also discarded the nomination, candidate, evidence and base-revision bindings from the signed approval. A future promotion boundary could therefore neither prove that the consumed capability was owner-authenticated nor recover all of the fields it was required to enforce.

## Scope

- validate `ApprovalExpectation` as an exact bounded record;
- retain every signed promotion binding in `VerifiedOwnerApproval`;
- require `ApprovalLedger.consume` to receive the original signed `OwnerApproval`;
- authenticate and compare the signed approval before and again inside `BEGIN IMMEDIATE`;
- use a ledger-owned timezone-aware clock rather than a caller-supplied consumption timestamp;
- persist full approval, expectation and consumption bytes in a new v2 table;
- return a self-digesting, binding-complete `ConsumedOwnerApproval`;
- require exact persisted equality through `verify_consumption` before any later promotion can trust the receipt;
- preserve the old signed OwnerApproval wire contract and package import paths.

## Explicit non-goals

- no `PromotionReceipt`;
- no Git ref or working-tree mutation;
- no owner key generation or repository-stored secret;
- no automatic approval, merge or promotion;
- no claim that Gate 0 is closed.

## Adversarial acceptance cases

1. A directly constructed `VerifiedOwnerApproval` cannot be consumed.
2. A changed signature or wrong expectation leaves no ledger row.
3. Candidate, evidence, nomination and base bindings survive verification and consumption.
4. The same approval, nonce or promotion identifier cannot be consumed twice.
5. Concurrent attempts yield exactly one winner.
6. Expiry between preflight verification and transaction persistence is refused.
7. A modified receipt fails its self-digest.
8. An unpersisted but self-consistent receipt is refused.
9. Corrupt or row-mismatched persisted receipt bytes fail closed.
10. Naive clocks, malformed digests and overlong approval TTLs are refused.

## Verification state

The implementation and deterministic test matrix are committed, but the current GitHub Actions environment is failing jobs before the first workflow step. Therefore this packet remains builder-prepared and unverified. Its PR must remain draft until executable CI, packaging and independent review evidence are available.
