# G0-APR-11 — Authenticated Approval Consumption

## Scope

This Work Packet ports the hardened approval-consumption authority from the
reviewed sibling `g0/approval-consumption` onto the selected linear Gate-0 head
`59f1c476b2d2bccb1ee568f8b7cdd38220a61693`.

It remains deliberately narrower than sealed promotion. It authenticates one
signed `OwnerApproval` again inside the SQLite transaction and persists a
binding-complete, canonical consumption receipt. It does not issue an owner
approval, create a human decision, mutate a checkout, create a promotion
receipt, or promote a candidate.

## Authority boundary

`ApprovalLedger.consume` accepts the original signed `OwnerApproval`, the
owner keyring, the exact `ApprovalExpectation`, and one promotion identifier.
A caller-constructed `VerifiedOwnerApproval` cannot cross the boundary.

The ledger:

- owns the consumption clock and refuses naive or backwards time;
- verifies signature, TTL, candidate, evidence, nomination, base revision,
  target ref, and expected target HEAD before and inside `BEGIN IMMEDIATE`;
- rechecks expiry immediately before persistence;
- stores canonical approval, expectation, and consumption JSON plus all binding
  columns under WAL, `synchronous=FULL`, foreign keys, and busy timeout;
- enforces uniqueness for approval digest, approval id, owner/key/nonce,
  promotion id, and consumption digest;
- refuses non-empty legacy ledgers without an explicit migration;
- re-authenticates persisted approval bytes and requires exact canonical receipt
  equality through `verify_consumption`.

The existing sealed-promotion fixture is migrated to the authenticated API and
verifies its persisted receipt before presenting it to the promotion
authorization layer. The production promotion boundary still needs a separate
packet that makes this persisted verification mandatory at the live mutation
seam.

## Adversarial coverage

Focused tests cover malformed identifiers and digests, forged verified records,
tampered signatures, wrong expectations, stale target revisions, expiry between
preflight and persistence, backwards clocks, replay and nonce repackaging,
concurrent consumption, corrupt SQLite, corrupt canonical JSON, row/receipt
mismatch, unknown keys, non-empty legacy authority, CLI signature injection,
and persisted-receipt reauthentication.

The packet also reruns the real Fourfold-to-OwnerApproval integration, sealed
promotion authorization, effect leases, gate reporting, kernel contracts, the
full suite, and an isolated wheel import across Ubuntu/Windows, Python 3.10 and
3.12, and two hash seeds.

## Independent review statement

The port preserves the sibling packet's deterministic tests but does not treat
its model-assisted review text as evidence. Exact-head CI and packaging results
must be produced by GitHub Actions. At creation time repository issue #67 still
causes new jobs to terminate before Step 1; such runs are infrastructure
observations and cannot satisfy this packet's verification requirements.

## Exit

This packet is ready for dependent work only when its exact-head workflow has
executed all focused, full-suite, platform, hash-seed, and isolated-wheel jobs
successfully. It does not close Gate 0 and requests no merge or promotion.
