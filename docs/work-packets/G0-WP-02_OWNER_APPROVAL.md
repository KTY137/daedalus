# G0-WP-02 — Authenticated Owner Approval

## Scope

This Work Packet adds an inert, authenticated owner-approval capability. It does
not promote a candidate and does not mark `promotion.owner_approval` implemented
in the effect registry. The later sealed-promotion packet must accept only an
atomically consumed capability and must re-check the live target HEAD directly
before repository mutation.

## Contract

`OwnerApproval` binds exactly:

- approval, owner and key identities;
- operation `promote-candidate`;
- nomination receipt digest;
- candidate artifact digest;
- evidence packet digest;
- candidate base revision;
- target ref and expected target HEAD;
- one-use nonce;
- issue and expiry timestamps;
- canonical provenance;
- an HMAC-SHA256 signature from an external owner key.

The repository never stores the owner secret. The CLI reads the named secret
environment variable and emits signed or verified JSON to stdout only.

## Replay boundary

`ApprovalLedger` uses SQLite with `BEGIN IMMEDIATE`, `WAL`, `synchronous=FULL`,
and unique constraints over approval digest, approval ID, promotion ID,
consumption digest, and `(owner_id, key_id, nonce)`. Verification and consumption
both enforce the validity window. A consumed capability retains the exact target
HEAD and an independently persisted consumption digest.

## Adversarial review

The following mutations were applied to isolated repository copies and each was
killed by the focused tests:

1. bypass `hmac.compare_digest`;
2. remove the live target-HEAD comparison;
3. remove nonce uniqueness from the consumption ledger.

Additional negative coverage includes candidate/evidence/nomination/base/ref/
operation mismatches, future and expired approvals, signature tampering, unknown
keys, concurrent replay, approval repackaging under the same nonce, corrupt
SQLite input, expiry between verification and consumption, and malformed
promotion IDs.

## Verification

Local builder evidence on the branch parent plus this packet:

- Iron Plan verification: passed;
- focused owner-approval tests: 19 passed;
- relevant Gate/Trust batch after final transaction cleanup: 211 passed, 4 subtests passed;
- isolated wheel build and imports of `daedalus.kernel`, `daedalus.gates`,
  `daedalus.twin`, and `OwnerApproval`: passed;
- full-suite first failure reproduced unchanged on the frozen parent export:
  `tests/test_agent_env.py::DaedalusTests::test_infers_existing_paths` under the
  Linux/Python 3.13 runner.

## Deliberate remaining blocker

`GUARD_CONTRACT_IMPLEMENTED["promotion.owner_approval"]` remains `False`, and
`python.promote_candidates` remains `UNGUARDED`. This is intentional: a contract
and verifier are not an enforced promotion boundary. The next dependent packet
must wire the consumed capability into sealed promotion before the Gate report
may set `owner_approval_enforced=true`.
