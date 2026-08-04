# G0-PRM-25K — Authenticated Inert Promotion Recovery Decision

## Scope

This packet defines the signed owner decision required before any future writer
may cancel a retained top-level promotion Effect Lease whose start exists but
whose promotion execution never started. The module verifies owner intent only.
It contains no production issuer, persistence ledger, consumption transition,
terminal writer, Git access, worktree operation or promotion call.

## Exact current decision subject

`recovery_expectation(capability, promotion_ledger)` does not accept a caller-
supplied plan or expectation. It derives a fresh read-only recovery plan from the
strict persisted Effect-Lease and promotion-execution projections and accepts
only `effect-only-pending-reconciliation` with:

- `owner-decision-before-effect-cancellation` as its sole action;
- automatic external re-execution disabled;
- manual reconciliation and owner decision both required;
- one retained Effect-Lease start digest;
- no effect terminal, promotion start or promotion terminal.

The expectation independently recomputes the returned plan digest and the
complete `PromotionAuthorization` digest. It binds the current recovery plan,
promotion authorization, retained effect-start receipt and source revision.

## Signed inert contract

`PromotionRecoveryDecision` binds the exact expectation plus owner ID, key ID,
nonce, issue/expiry timestamps and provenance. Its operation is fixed to
`cancel-unentered-promotion-effect`. Provenance creation time must equal issue
time and must include every referenced security digest.

`verify_promotion_recovery_decision(...)` first authenticates the HMAC using the
owner keyring, then enforces a maximum 24-hour validity interval. Only after
signature and time validation does it reproject the current cross-ledger state
and compare every exact subject field. A changed effect-start receipt, changed
plan or no-longer-effect-only state invalidates a previously signed decision.
The result remains inert and exposes no execute, cancel, terminalize, consume or
promote method.

## Deliberate owner boundary

There is no production decision-issuance helper in this packet. No owner intent
is synthesized by tests or automation as operational authority; test fixtures
independently sign local ephemeral contracts only to verify the parser and
verifier. A later packet must persist and atomically consume a real externally
supplied decision and must reproject state again inside the separately reviewed
cancellation writer transaction.

## Prepared adversarial verification

Behavior tests cover fresh strict-state derivation, coherently rehashed wrong
states, stale plan digests, changed promotion capabilities, independent signing,
strict round-trip parsing, forged/unknown signatures before ledger access,
re-signed subject and source-revision substitutions, changed retained effect
starts, future/expired/overlong validity before ledger access and malformed
types. A separate AST/source review rejects issuer, persistence, Git, subprocess,
lease writer, terminalization and promotion authority, forbids a caller-supplied
expectation, and verifies signature/time/state-check ordering. Eight bounded
mutants attack plan hashing, automatic-reexecution refusal, authorization
revalidation, signature verification, stale-state projection bypass,
plan/source binding and TTL enforcement.

Exact-head compilation, focused tests, mutation execution, full suite,
packaging and the supported platform/Python matrix remain pending. Repository
GitHub Actions issue #67 has repeatedly ended jobs before Step 1 with no logs or
artifacts; those runs are infrastructure observations only.

## Non-claims

No OwnerApproval or owner recovery decision was issued, persisted or consumed.
No Effect Lease was cancelled or terminalized. No merge, promotion, registry
centralization or Gate transition occurred. Gate 0 remains open.
