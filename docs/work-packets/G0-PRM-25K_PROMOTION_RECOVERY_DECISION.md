# G0-PRM-25K — Authenticated Inert Promotion Recovery Decision

## Scope

This packet defines the signed owner decision required before any future writer
may cancel a retained top-level promotion Effect Lease whose start exists but
whose promotion execution never started. The module verifies owner intent only.
It contains no production issuer, persistence ledger, consumption transition,
terminal writer, Git access, worktree operation or promotion call.

## Exact decision subject

`recovery_expectation(plan, capability)` accepts only a canonically hashed
`effect-only-pending-reconciliation` plan with:

- `owner-decision-before-effect-cancellation` as its sole action;
- automatic external re-execution disabled;
- manual reconciliation and owner decision both required;
- one retained Effect-Lease start digest;
- no effect terminal, promotion start or promotion terminal.

The expectation independently recomputes the plan digest and the complete
`PromotionAuthorization` digest. It binds the recovery plan, promotion
authorization, retained effect-start receipt and source revision.

## Signed inert contract

`PromotionRecoveryDecision` binds the exact expectation plus owner ID, key ID,
nonce, issue/expiry timestamps and provenance. Its operation is fixed to
`cancel-unentered-promotion-effect`. Provenance creation time must equal issue
time and must include every referenced security digest.

`verify_promotion_recovery_decision(...)` authenticates the HMAC using the owner
keyring, enforces a maximum 24-hour validity interval, refuses not-yet-valid and
expired decisions, and compares every exact subject field. The result remains
inert and exposes no execute, cancel, terminalize, consume or promote method.

## Deliberate owner boundary

There is no production decision-issuance helper in this packet. No owner intent
is synthesized by tests or automation as operational authority; test fixtures
independently sign local ephemeral contracts only to verify the parser and
verifier. A later packet must persist and atomically consume a real externally
supplied decision before a separately reviewed cancellation writer can exist.

## Prepared adversarial verification

Behavior tests cover exact expectation derivation, coherently rehashed wrong
states, stale plan digests, changed promotion capabilities, independent signing,
strict round-trip parsing, forged/unknown signatures, re-signed subject and
source-revision substitutions, future/expired/overlong validity and malformed
types. A separate AST/source review rejects issuer, persistence, ledger, Git,
subprocess, lease writer, terminalization and promotion authority. Seven bounded
mutants attack plan hashing, automatic-reexecution refusal, authorization
revalidation, signature verification, plan/source binding and TTL enforcement.

Exact-head compilation, focused tests, mutation execution, full suite,
packaging and the supported platform/Python matrix remain pending. Repository
GitHub Actions issue #67 has repeatedly ended jobs before Step 1 with no logs or
artifacts; those runs are infrastructure observations only.

## Non-claims

No OwnerApproval or owner recovery decision was issued, persisted or consumed.
No Effect Lease was cancelled or terminalized. No merge, promotion, registry
centralization or Gate transition occurred. Gate 0 remains open.
