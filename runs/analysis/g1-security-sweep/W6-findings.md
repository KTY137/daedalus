# W6 — OwnerApproval path (`daedalus/kernel/approvals.py`) vs the sealed-promotion invariant

Base: local main `851ff43c`. Static reading only. No test was run, nothing
executed, no approval issued or consumed.

## Verdict up front

**No security finding.** The one-use binding and replay refusal match the
plan's sealed-promotion invariant (§4 invariant 5 and Revision 3 clause 1) as
far as static reading can establish. This file is the strongest security code I
read in this sweep. The rest of this document is the evidence for that claim,
recorded so the negative result is auditable rather than merely asserted — and
so a future change that weakens one of these five properties is visibly a
regression.

I actively looked for eight specific defeats and found none. They are listed
under "Attacks I tried and could not land", with the exact code that stops each.

## Enumeration

- `daedalus/kernel/approvals.py`, 855 lines; read in full at the decision points
  (lines 285-300, 345-424, 440-648, 750-805) and structurally mapped elsewhere.
- `daedalus/kernel/contracts/security.py:110-140` (OwnerApproval signing) and
  `:320-328` (EffectLease signing) read.
- `grep -rn "keyring=" --include=*.py daedalus/kernel/` -> 15 call sites across
  approvals, authorization, effects, effect_recovery, effect_replay,
  offload_lease. I verified the *contract* of the shared verifier, not each of
  the 15 callers (see "What I did not cover").
- Binding dimensions compared: **7** (`operation`,
  `nomination_receipt_sha256`, `candidate_artifact_sha256`,
  `evidence_packet_sha256`, `base_revision`, `target_ref`,
  `expected_target_revision`).
- Database uniqueness constraints enforcing one-use: **4**.

## Attacks I tried and could not land

### 1. Replay the same approval twice — BLOCKED
Uniqueness is enforced by the database inside the transaction, not by a
read-then-write check in Python (which would be a TOCTOU race). Four separate
UNIQUE constraints (`approvals.py:469-494`):

```sql
    approval_sha256 TEXT PRIMARY KEY,
    approval_id TEXT NOT NULL UNIQUE,
    ...
    promotion_id TEXT NOT NULL UNIQUE,
    ...
    consumption_sha256 TEXT NOT NULL UNIQUE,
    UNIQUE(owner_id, key_id, nonce)
```

and the integrity violation is translated into an explicit refusal rather than
being swallowed (`approvals.py:625-632`):

```python
        except sqlite3.IntegrityError as exc:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise ApprovalReplay(
                "owner approval, nonce, or promotion identity was already consumed"
            ) from exc
```

Note this is genuinely one-use along **four independent axes** — the approval
digest, the approval id, the promotion id, and the (owner, key, nonce) triple.
Defeating replay requires defeating all four.

### 2. Race two concurrent consumptions — BLOCKED
`connection.execute("BEGIN IMMEDIATE")` (`approvals.py:537`) takes the write
lock at transaction start, not at first write, so two racers serialize and the
loser hits the UNIQUE constraint above. `busy_timeout=30000` and
`synchronous=FULL` (`approvals.py:448-450`) back this up.

### 3. Verify against one expectation, consume against another — BLOCKED
The approval is verified **twice**, and the second verification happens *inside*
the transaction, with the results required to be identical
(`approvals.py:543-552`):

```python
            verified = verify_owner_approval(
                approval, keyring=keyring, expectation=expectation,
                now=transaction_at,
            )
            if verified != preflight:
                raise ApprovalStateError(
                    "approval verification changed before consumption"
                )
```

This is the check most systems omit. Its presence is why a preflight/commit
divergence cannot be engineered.

### 4. Roll the clock back to un-expire an approval — BLOCKED
Three monotonicity assertions across the three timestamps taken
(`approvals.py:539-542`, `554-557`, and expiry re-checked at persistence time
`559-566`):

```python
            if transaction_at < preflight_at:
                raise ApprovalStateError(
                    "approval ledger clock moved backwards before consumption"
                )
```

Expiry is re-evaluated at *persistence* time, not only at verification time, so
an approval cannot expire mid-transaction and still land.

### 5. Forge a signature with an empty or weak secret — BLOCKED
`_secret_bytes` (`approvals.py:285-289`) refuses anything under 32 bytes:

```python
def _secret_bytes(secret: bytes | str) -> bytes:
    value = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
    if len(value) < 32:
        raise ValueError("owner approval secret must contain at least 32 bytes")
    return value
```

An unset env var is a hard error, not a default (`approvals.py:754-758`). So the
common "HMAC with an empty key" forge is unavailable. An unknown `(owner_id,
key_id)` raises rather than returning a falsy secret (`approvals.py:358-360`).

### 6. Tamper with a bound field without breaking the signature — BLOCKED
The HMAC covers **every** field except the signature itself
(`contracts/security.py:126-133`):

```python
    def signing_dict(self) -> dict[str, Any]:
        body = self.to_dict()
        body.pop("signature_sha256")
        return body
```

This is the correct construction (sign-all-but-the-signature over a canonical
serialization), not a hand-picked field list that a later field addition would
silently leave unsigned.

### 7. Timing-attack the signature comparison — BLOCKED
`hmac.compare_digest` at both comparison sites (`approvals.py:362`, `:693`), not
`==`.

### 8. Bypass binding by omitting a dimension — BLOCKED
All seven dimensions are compared and **all** mismatches are reported together
(`approvals.py:375-404`), including `expected_target_revision` against
`expectation.current_target_revision` — which is the "freshly resolved target
revision" the plan's Revision 3 clause 1 specifically requires. Collecting all
mismatches rather than short-circuiting also means an attacker probing one field
at a time learns nothing extra.

Additionally `_MAX_APPROVAL_TTL = timedelta(hours=24)` (`approvals.py:32`) is
enforced against the *approval's own* issued/expires span
(`approvals.py:368-369`), so a self-issued 10-year approval is refused at
verification, not merely discouraged.

## Two observations (not defects)

### O-W6-01 Legacy table migration fails closed — good, worth preserving
`approvals.py:497-508`: if a legacy `owner_approval_consumptions` table exists
*and is non-empty*, `_initialize` raises `ApprovalStateError` rather than
silently starting a fresh v2 table. That is the right call: silently ignoring
the legacy table would reset the one-use ledger and make every historical
approval replayable. Flagging it only so it is not "simplified away" later.

### O-W6-02 The plan says "ordered candidate batch"; the schema binds one candidate
Plan Revision 3 clause 1 requires the approval to bind "the ordered candidate
**batch**". The contract binds a single `candidate_artifact_sha256`
(`approvals.py:381-384`, `:477`). This is not a weakness — a single
content-addressed digest over an ordered batch is a perfectly sound encoding,
and one-candidate-per-approval is *stricter* than a batch. I could not confirm
from this file alone which of the two it is, because that depends on how the
caller computes the digest. Recorded as a documentation/precision question for
the owner, explicitly **not** as a security finding.

## What I did not cover

- **The 15 `keyring=` call sites.** I verified the shared verifier's contract,
  not that every caller passes a correctly-populated keyring. A caller supplying
  an attacker-influenced keyring would defeat everything above; that is the
  natural next question and it is outside W6's file scope.
- **Where the signing secret is stored at rest** and who can read it. W3
  (secrets) covers that surface. The 32-byte floor is enforced; the *provenance*
  of the secret is not W6's to judge.
- **The callers of `consume()`** — specifically whether `promotion.py` /
  `promotion_trust_root.py` actually call it before creating the integration
  worktree, and whether any promotion path reaches Git mutation *without* it.
  This is the single most important follow-up: approvals.py is sound in
  isolation, and an unguarded caller would make that irrelevant. Files to read:
  `daedalus/kernel/promotion.py` (which mentions a re-authenticated "demoted
  second factor" at line 16) and `daedalus/kernel/promotion_trust_root.py`.
- `verify_consumption()` (`approvals.py:642-735`) was read only structurally.
- No dynamic verification: I did not run the test suite, so "these constraints
  hold" is a statement about the source, not an executed proof. In particular I
  did not mutation-test the guards to confirm a test notices if one is removed.
