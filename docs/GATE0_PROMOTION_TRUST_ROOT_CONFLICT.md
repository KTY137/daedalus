# Two trust roots for one seal — a decision the owner has to make

Status: **RESOLVED.** [MEASURED 2026-08-25] `daedalus/kernel/promotion_trust_root.py`
implements recommendation (2) below — git-signed tags (Option B) as the trust
root, hybrid with the trunk's ledger. Kept as historical record of the
analysis; not current architecture.
Author: Athena, 2026-08-17
Invariant: 4.5 sealed promotion, 4.1 one kernel
Gate: 0

## The situation

Sealed promotion is implemented twice, on two branches, with two incompatible
trust roots. Both are real, tested code. Neither knows about the other.

| | consolidated trunk | checkpoint branch |
| --- | --- | --- |
| module | `daedalus/kernel/approvals.py` + `kernel/promotion.py` | `daedalus/spine/promotion_approval.py` |
| trust root | HMAC over a canonical body | git-signed tag `promote/<candidate_sha256>` |
| verification | recompute the HMAC and compare | `git verify-tag` exit code vs an allowed-signers file read from the committed tree |
| key material | shared secret from an environment variable (`approvals.py:732,767`) | owner's private signing key, never in the repository |
| symmetry | **symmetric** — whatever can verify can also forge | **asymmetric** — verifying proves nothing about forging |
| persistence | one-use consumption receipt in a SQLite approval ledger, 24h TTL | the tag is its own durable audit artifact |
| maturity | substantially more built out: ledger, re-read of live HEAD before mutation, binding-complete receipts | verifier only; no ledger, no live-HEAD re-read |

## Why this is a conflict and not a duplicate

`docs/GATE0_SEALED_OWNER_APPROVAL.md` is present on **both** branches. It
analyses the options and section 5 records the recommendation:

> **B, with A as the upgrade path.** Git-signed tags give a real cryptographic
> trust root at low cost, produce their own audit artifact, and need no key
> distribution beyond an allowed-signers file the repository already can hold.

The trunk implements neither B nor A. It implements a shared-secret HMAC, which
that same document analyses and does not recommend. The checkpoint branch
implements exactly what the document recommends, and cites it in its module
docstring.

So the repository contains a recorded governance decision and an implementation
that diverges from it, on the same branch, with no amendment record explaining
the divergence. That is the thing worth flagging — not which scheme is nicer.

## What is actually at risk `[MEASURED, bounded]`

`approvals.py:292`

```python
def _signature(signing_digest: str, secret: bytes | str) -> str:
    return hmac.new(...)
```

`verify_owner_approval` recomputes this with the same secret and compares
(`approvals.py:361-363`). The secret is read from an environment variable in the
CLI paths (`approvals.py:732`, `:767`).

Consequence, stated precisely: **any code that can read the environment of a
process holding that secret can mint an owner approval that verifies.**
Invariant 4.3 requires candidate execution to be capability-bounded and unable to
modify its promotion mechanism. Whether this is reachable in practice depends on
whether a candidate ever executes with that variable in its environment — that
depends on `daedalus/kernel/sandbox.py` and is **not established here**. I did
not test it, so I am not claiming an exploit. I am claiming the trust root is
symmetric where the repository's own recommendation calls for asymmetric, which
removes a defence that the design document explicitly asked for.

Fail-closed behaviour is intact either way: `gated_writes.py:202` refuses
promotion when no approval ledger or keyring is supplied.

## One thing the checkpoint verifier knows that is worth keeping regardless

`git verify-tag` prints

```
Good "git" signature with ED25519 key SHA256:...
No principal matched.
```

on stderr for a signature by a key that is **not** in the allowed-signers file.
A verifier that greps for `Good` accepts an untrusted key. Only the exit code is
authoritative. This is measured and it is a trap any future implementation of
option B will walk into.

## Recommendation

Do not merge the checkpoint module into the trunk as a second promotion path —
that would create exactly the parallel authority invariant 4.1 forbids, and it is
the weaker implementation of the two in every respect except the trust root.

Two coherent ways forward, both requiring an owner decision:

1. **Keep the trunk implementation, amend the decision document.** If HMAC with
   an env-var secret is acceptable under the real threat model, say so in
   `GATE0_SEALED_OWNER_APPROVAL.md` with the reasoning, so the divergence stops
   being silent. Cheapest, and honest.
2. **Keep the trunk's ledger and live-HEAD re-read, swap the trust root.**
   Replace `_signature`/`verify_owner_approval` with the signed-tag verifier from
   the checkpoint branch, keeping everything else. This is what the recorded
   recommendation asks for, and it is a contained change: one function pair.

I lean to (2), because the trunk's genuinely valuable parts — the ledger, the
one-use consumption receipt, the re-read of live HEAD immediately before mutation
— are orthogonal to the trust root and survive the swap untouched. But the threat
model is the owner's call, and (1) is a legitimate answer if candidates provably
never see that environment.

Until it is decided, the checkpoint module stays on its branch and is not merged.
