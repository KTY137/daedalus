# Gate 0: the sealed owner approval

Status: **analysis and design options. Nothing implemented.** The choice of
trust root is the owner's, not an implementer's, and it is the reason this note
stops short of code.

Iron Plan: ALIGNED · Iron Gate: 0 · touches invariant §4.5 (sealed promotion),
§4.3 (isolation), §4.8 (bounded effects).

---

## 1. What is actually false today

`daedalus/spine/effect_boundary.py:150`

```python
"promotion.owner_approval": False,
```

This is not a switch someone left off. It is a measurement, and it is accurate.
Three facts establish it:

**The contract exists and is complete.** `PromotionReceipt`
(`daedalus/schemas.py:1523`) already models the whole decision:
`promotion_status ∈ {pending-owner, approved, rejected}`, `owner_approval_ref`,
and `approval_assurance ∈ {not-applicable, authenticated}`. It enforces the
coupling in `__post_init__`: an `approved` receipt without an
`owner_approval_ref` raises, and so does one whose assurance is not
`authenticated`. Its own docstring states the boundary it does not cross:

> This schema does not authenticate the owner; the guarded promotion boundary
> must resolve and authenticate the approval locator before any merge/deploy.

**Nothing constructs it.** `grep -rn "PromotionReceipt(" --include=*.py .`
returns exactly one hit: the class definition. No production path builds one.

**The callable that mutates the repository cannot see it.**

```python
def promote_candidates(repo_root, candidates, *, project, availability,
                       ledger_path=None, lock_timeout_s=120.0,
                       gate_timeout_s=900.0, cancel=None) -> dict:
```

There is no approval parameter. `promote_candidates` takes gated candidates and
an availability map, acquires a lock, and writes an integration worktree. It
never asks who authorised this.

So the honest reading of the `False` is: **a well-formed vocabulary for
authenticated approval exists, and no code can produce, verify, or require
one.** Anyone writing `approval_assurance="authenticated"` today would be
asserting something no mechanism checked.

`effect_boundary.py:142` makes the consequence structural — "A missing contract
can be required by an UNGUARDED row but can never be used to open a CENTRAL
row." So `python.promote_candidates` is pinned at `UNGUARDED` by construction,
and Gate 0 cannot exit while it is. That is the design working, not failing.

## 2. Why this cannot be "wired"

Wiring means connecting an existing mechanism to an existing call site. Here the
mechanism does not exist, and building it requires answering a question that
belongs to the owner:

> **What proves that a promotion was authorised by you and not by something
> running as you?**

Every option below is a different answer to that, with a different trust root
and a different failure mode. Picking one is a governance decision. Picking one
*silently* would be exactly the drift §4.10 forbids — and flipping the boolean
without building the mechanism would violate §4.9 (honest claims) in the one
inventory whose entire value is that it does not lie about what is guarded.

## 3. What the approval has to be bound to

The migration note already on the row:

> Require an owner-issued, candidate/evidence/HEAD-bound approval capability at
> `promote_candidates()` before creating the integration worktree.

Three bindings, each closing a distinct replay:

| bound to | replay it prevents |
|---|---|
| candidate artifact sha256 | approving candidate A, promoting candidate B |
| evidence packet sha256 | approving on evidence E, promoting on weaker evidence E′ |
| source revision (HEAD) | approving against one base, promoting onto a moved tree |

A fourth is needed and is not obvious from the note: **expiry**, or a
single-use marker. An approval that stays valid indefinitely is a standing
authorisation, which is what §4.5 exists to prevent.

### The regeneration problem

`_promote_locked` (`gated_writes.py:774`) can regenerate a candidate mid-flight:
when the base has moved, `_reattempt()` runs a fresh `TaskAttempt` and the
promoted artifact is **not** the artifact that was approved. Its sha changes; so
does the evidence it was gated on.

Any approval bound to the candidate sha is therefore invalidated by a mechanism
that already exists and runs inside the very call the approval is supposed to
authorise. Two acceptable resolutions, and one that is not:

- **Void on regeneration** — a staleness retry cancels the approval and the
  candidate returns to `pending-owner`. Safe, and costs the owner a second look
  in exactly the case where the tree moved underneath them.
- **Re-approve inline** — regeneration triggers a fresh approval request.
  Correct but turns a batch promotion into an interactive session.
- **Approve the task rather than the artifact** — rejected. It reduces the
  approval to "I trust whatever this task produces", which is a standing
  authorisation wearing a receipt's clothes.

This has to be settled before the capability is designed, not after: it changes
what the approval names.

## 4. Trust-root options

Ordered by assurance. Each would let `approval_assurance="authenticated"` be
truthful; they differ in what an attacker must control to forge one.

### A. Detached signature over a canonical approval body

The owner signs `{candidate_sha, evidence_sha, source_revision, expiry, nonce}`
with a key that never touches the repository. The public key is committed;
`promote_candidates` verifies before taking the lock.

- Forgery requires the private key.
- Survives a fully compromised agent process — the strongest property here, and
  the only option that satisfies §4.3 against a candidate that can run code.
- Cost: key management, and the owner needs a signing step in the loop.

### B. Git-signed tag or commit on the nomination

The owner signs a tag naming the nomination receipt; verification is
`git verify-tag` against a committed allowed-signers file.

- Reuses infrastructure that exists, and the audit trail is the tag itself.
- Trust root is the git signing key — same class as A, weaker only in that
  git's verification surface is larger than one signature check.
- Cost: low. Probably the cheapest honest option.

### C. Approval file in a location the candidate cannot write

A structured file under a path outside every candidate write root, checked
against the write policy that already exists.

- Trust root is the filesystem boundary. Holds only as strongly as the write
  policy, which §1 already says is not a security boundary against a direct
  filesystem writer.
- Adequate for a single-operator machine; do not describe it as authenticated
  against a hostile candidate.

### D. Environment token, in the style of `DAEDALUS_IRON_PLAN_AMENDMENT`

- Consistent with the existing amendment unlock, and immediately available.
- Weakest: an environment variable is readable by every child process, so a
  candidate that spawns anything inherits the capability. §4.8 explicitly puts
  effects at boundaries "not entrusted to prompts", and an inherited env var is
  barely stronger than one.
- Acceptable only as an explicitly labelled interim with the assurance field
  reading something other than `authenticated`.

### E. Interactive TTY confirmation

- Rejected as the *sole* mechanism. It authenticates presence at a terminal, not
  the owner, and it cannot be replayed into a receipt. Useful as a second factor
  on top of A or B; never alone.

## 5. Recommendation

**B, with A as the upgrade path.** Git-signed tags give a real cryptographic
trust root at low cost, produce their own audit artifact, and need no key
distribution beyond an allowed-signers file the repository already can hold. If
the threat model later includes a candidate that executes arbitrary code with
the owner's git config, A is the migration and the receipt shape does not change.

**Void the approval on regeneration.** It is the conservative reading of §4.5,
and the alternative quietly promotes an artifact nobody approved.

## 6. What it would take, once the trust root is chosen

Not an estimate of difficulty — a list of what must be true before the boolean
may become `True`:

1. An approval body with a canonical serialisation, bound to candidate sha,
   evidence sha, source revision, expiry, and nonce.
2. A verifier that resolves `owner_approval_ref` and returns a boolean, living
   where no candidate can write to it.
3. `promote_candidates()` requiring a verified approval **before** acquiring the
   promotion lock and before the integration worktree exists — refusing, not
   raising, in the module's established style.
4. Regeneration voiding the approval and returning the candidate to
   `pending-owner`.
5. The first production construction of `PromotionReceipt`, with
   `approval_assurance="authenticated"` set only by the verifier and never by a
   caller.
6. Fault-injection coverage: absent approval, expired approval, approval for a
   different candidate, for different evidence, against a moved HEAD, replayed
   twice, and forged. Each must fail closed.
7. Only then: `"promotion.owner_approval": True`, and the
   `python.promote_candidates` row moves off `UNGUARDED` — with the tests as the
   evidence, not the flag as the claim.

Until then the inventory is correct as written, and the correct thing to do with
it is to leave it alone.
