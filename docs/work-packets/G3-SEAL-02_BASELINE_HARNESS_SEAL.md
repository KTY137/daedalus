# G3-SEAL-02 - the kernel binding that makes a Gate-3 baseline harness sealable

Packet ID: `G3-SEAL-02`
Artifact role: `primary`
Status: `built; acceptance matrix green; NOT reviewed by an independent reviewer; nothing sealed`
Active gate: `1`
Classification: `ALIGNED`
Owner: `repository owner`
Base revision: `0a75ede8cad82dcb43bd510fd516a979e2a7b00d`
Dependencies: `G3-BASE-01, G1-EVAL-CORPUS-01`
Master-plan authority: `Revision 13`
Promotion: not requested; automatic merge, promotion, and Gate transition are
forbidden. This packet removes one Gate-3 blocker; it cannot open, enter, or
satisfy Gate 3.
Supersedes: the empty `packet/g3-seal-01` branch (no commits).

## Primary acceptance claim

> A `RunManifest` reports `sealed=True` **if and only if** an owner-signed,
> one-use, unexpired `BaselineHarnessSeal` has been authenticated by the kernel
> and bound to exactly that manifest's digest and each of its six freeze
> obligations. No builder-supplied string, no unverified record and no
> promotion approval can produce that answer.

## Why this packet exists

`G3-BASE-01` §F4 is the last structural blocker between this repository and
Gate 3's first sentence ("First freeze public tasks, evaluator versions,
budgets, model/hardware reporting, seed policy, and statistical reporting" —
plan §11, followed by "Only after that baseline harness is sealed").

Today `RunManifest.sealed` is hard-wired `False` with an honest docstring: an
earlier version returned `bool(owner_seal_ref)` and an independent reviewer
sealed a run with the literal string `"i am definitely the owner trust me"`.
Fail-closed was the correct interim answer. It is not a terminal answer — an
eternally-false flag means no Gate-3 evidence can ever be produced.

## The decision this packet makes, and the one it refuses to make

### Rejected: widen `OwnerApproval.operation`

The obvious implementation is to add a second operation tag —
`"seal-baseline-harness"` — to the existing `OwnerApproval`, whose
`__post_init__` today asserts `operation == "promote-candidate"` in **two**
places (`daedalus/kernel/contracts/security.py`, `daedalus/kernel/approvals.py`
`VerifiedOwnerApproval`).

This is rejected. It widens the single contract that guards Invariant 5
(sealed promotion) so that a *second*, much cheaper-to-obtain artifact shares
its type, its ledger table, its keyring and its verification path. Every
future reader of the promotion path would have to re-derive that a
`VerifiedOwnerApproval` in hand is not necessarily a promotion authority.
`docs/GATE0_PROMOTION_TRUST_ROOT_FINDING.md` already records two constructed
attacks against this trust root; making it polymorphic is the wrong direction.

### Chosen: a separate, attestation-only contract that authorizes nothing

`BaselineHarnessSeal` is its own `CanonicalContract` with its own contract
type, its own replay table and its own domain-separated signature. It grants
**no effect authority at all**: it cannot promote, cannot merge, cannot widen a
write root, cannot admit egress, cannot mint a lease. Its entire semantic
content is *"the owner attests that this exact frozen harness is the one that
counts"*. A capability that authorizes nothing cannot be a trust-root widening.

Three mechanical separations make the two artifacts non-interchangeable:

1. **Type separation.** `signing_dict()` includes `contract_type`, so a seal
   signature is not a valid signature over any `daedalus.owner-approval` body
   and vice versa. This holds today, before any of the below.
2. **Domain separation.** Seals sign `SEAL_SIGNING_DOMAIN + signing_digest`,
   not the bare digest. Belt and braces on top of (1), and it costs nothing.
3. **Ledger separation.** Seals consume against
   `baseline_harness_seal_consumptions_v1`, a table `ApprovalLedger` never
   reads or writes. A consumed seal cannot retire a promotion nonce and a
   consumed promotion cannot retire a seal nonce.

## Extend, never duplicate

Reused unchanged: `CanonicalContract` serialization and digests,
`ContractProvenance`, the `_identifier` / `_sha256` / `_revision` /
`_utc_timestamp` validators, `canonical_sha`, the `_secret_bytes` 32-byte
minimum, the HMAC-SHA256 primitive, the SQLite WAL/`synchronous=FULL`/
`busy_timeout` connection discipline, and the error taxonomy
(`SignatureError` / `Expired` / `BindingMismatch` / `Replay`).

Not duplicated: no second canonical serializer, no second digest authority, no
second keyring format, no second clock convention.

## Contracts and behavior

### `BaselineHarnessSeal` (`daedalus.baseline-harness-seal`)

Binds the manifest digest **and every freeze obligation separately**, so
swapping any single obligation after sealing invalidates the seal rather than
silently carrying it:

`seal_id`, `owner_id`, `key_id`, `operation` (fixed
`seal-baseline-harness`), `manifest_sha256`, `task_set_sha256`,
`evaluator_sha256`, `budget_sha256`, `environment_sha256`,
`seed_policy_sha256`, `base_revision`, `plan_digest`, `nonce`, `issued_at`,
`expires_at`, `signature_sha256`, `provenance`.

`expires_at - issued_at` is capped at 24 h, matching the Gate-0 approval TTL.

### `VerifiedBaselineSeal`

The authenticated result. Constructible in practice only by
`verify_baseline_seal`, because `__post_init__` recomputes
`seal_sha256` from the bound fields and refuses a mismatch — a hand-built
instance has to already know the digest of a body it does not possess.

### `ConsumedBaselineSeal`

Persisted evidence of one atomic consumption: the verified seal, the
expectation digest, a `seal_use_id`, `consumed_at`, and a self-verifying
`consumption_sha256`.

### `SealExpectation`

What the *caller* independently believes it is sealing — manifest digest, the
six obligation digests, base revision and plan digest. Verification refuses
unless the expectation and the signed seal agree field by field, so a seal
issued for one harness cannot be pointed at another.

## The `RunManifest` change

`owner_seal_ref: str | None` stays (it remains an unverified *claim*, and
`seal_claim` / `evidence_status` keep reporting it as such). One field is
added:

```python
verified_seal: VerifiedBaselineSeal | None = None
```

`__post_init__` gains a real `isinstance` check against `VerifiedBaselineSeal`
(via a deferred import, so this package keeps a stdlib-only module-level import
graph). Structural checking was rejected: all eight bound digests are publicly
computable from the manifest, so duck typing would have reproduced the
`G3-BASE-01` string forgery one layer down. Presenting a non-seal is a
`FreezeError`, not a quiet `sealed=False`, because a silent `False` would let a
forgery attempt sit in a report looking like ordinary prework.

`sealed` then becomes:

```python
seal = self.verified_seal
if seal is None:
    return False
return (
    seal.manifest_sha256 == self.digest
    and seal.task_set_sha256 == self.task_set.digest
    ... one comparison per obligation, plus base_revision and plan_digest ...
)
```

Budgets are bound as ONE digest over the whole equal-budget mapping
(`_budget_digest`), not per arm: `require_equal_budgets` already forces them
equal, and per-arm binding would let an arm be *added* after sealing without
changing any bound value (acceptance row 10b).

`verified_seal` stays **outside** `RunManifest.digest`, exactly as
`owner_seal_ref` does today and for the same recorded reason: sealing an
existing run must not change the identity of what was measured.

`evidence_status()` gains a third branch for the sealed case and keeps both
existing unsealed branches verbatim.

## Acceptance matrix

### 5a. Positive path
1. `issue_baseline_seal` → `verify_baseline_seal` → `SealLedger.consume`
   returns a `ConsumedBaselineSeal` whose `consumption_sha256` verifies.
2. A `RunManifest` carrying that verified seal reports `sealed=True` and an
   `evidence_status()` that names the seal, the owner and the key id.

### 5b. Refusal path — each must raise, none may pass
3. Wrong secret → `SealSignatureError`.
4. Bare-digest signature (no domain prefix) → `SealSignatureError`.
   *This is the regression test for domain separation.*
5. `now >= expires_at` → `SealExpired`; `now < issued_at` → `SealExpired`.
6. TTL > 24 h at issue → `ValueError`.
7. Second consumption of the same seal → `SealReplay`.
8. Same `(owner_id, key_id, nonce)` under a new `seal_id` → `SealReplay`.
9. Expectation disagreeing on **any one** of the eight bound digests →
   `SealBindingMismatch`. Parameterised over all eight.
10. A manifest whose `budgets` differ from the sealed `budget_sha256` reports
    `sealed=False` even while holding a genuinely verified seal.

### 5c. The forgery tests, kept and extended
11. The historical forgery — `owner_seal_ref="i am definitely the owner trust
    me"` — still yields `sealed=False`. Kept verbatim from `G3-BASE-01`.
12. A `RunManifest` constructed with `verified_seal=None` reports
    `sealed=False` no matter what `owner_seal_ref` says.
13. **Cross-artifact forgery:** a genuine, currently-valid
    `VerifiedOwnerApproval` cannot be passed as `verified_seal` (type refusal),
    and its signature does not verify as a seal signature.
14. **Ledger non-interference:** consuming a seal does not mark any promotion
    approval consumed, and `ApprovalLedger.consumed()` is unaffected. Asserted
    against one SQLite file holding both tables.

### 5d. Fault injection
15. Ledger file unwritable → refusal before the seal is treated as consumed.
16. Concurrent double-consume from two connections → exactly one succeeds.
17. Malformed / truncated JSON seal payload → `ValueError`, never a pass.

## Scope

**In scope**
- `daedalus/kernel/contracts/security.py` (add the three seal contracts)
- `daedalus/kernel/seals.py` (new: issue / verify / `SealLedger`)
- `daedalus/eval/gate3/contracts.py` (`RunManifest.verified_seal`, `sealed`,
  `evidence_status`)
- `tests/kernel/test_baseline_harness_seal.py` (new)
- `tests/eval/gate3/test_contracts.py` (extend, do not rewrite)
- this document

**Forbidden paths** — a diff touching these fails the packet
- `daedalus/kernel/approvals.py` (the promotion path stays byte-identical)
- `daedalus/kernel/policy/**`, `daedalus/spine/**`
- `docs/IKARUS_ARIADNE_MASTER_PLAN.md`, its amendment chain, `AGENTS.md`
- anything under `daedalus/gates/`

## Migration and rollback

There is no migration. `RunManifest.verified_seal` defaults to `None`, which is
exactly the pre-packet behaviour, so every manifest already constructed anywhere
in the tree keeps reporting `sealed=False` and every existing
`evidence_status()` string is produced by an unchanged branch. No stored record
is rewritten, no run is backfilled, and no run recorded before this packet
becomes sealed.

Rollback is the reverse-apply of this diff: delete `daedalus/kernel/seals.py`,
drop `BaselineHarnessSeal` from `daedalus/kernel/contracts/security.py` and its
two export names, restore `RunManifest.sealed` to `return False`, and restore
the two census pins to 514 / 2009. Nothing outside those files depends on the
seal, and `daedalus/kernel/approvals.py` is byte-identical either way, so the
promotion path cannot be disturbed by rolling this back.

The one persistent artifact is the ledger table
`baseline_harness_seal_consumptions_v1`. It is created lazily by
`SealLedger.__init__` and is disjoint from `owner_approval_consumptions_v2`;
after a rollback it is simply an unread table, and dropping it destroys only
seal-consumption history, never approval history.

## What this packet explicitly does NOT claim

- It does **not** close Gate 3, open it, or produce baseline evidence. It
  removes one blocker; `G3-BASE-01` §F6 ("what is NOT proven") stands.
- It does **not** make any existing run sealed. Every run recorded to date
  stays `sealed=False`; there is no backfill and no grandfathering.
- It does **not** give the seal any effect authority, and the acceptance
  matrix (13, 14) is what keeps that true under future edits.
- It is **not** a security boundary claim. Plan §1: no local hook or contract
  in this repository covers an external client or a direct filesystem writer.
- The type plane still carries 0 corpus tasks. Kill criterion 14.4 stays
  untestable and no seal changes that.

## Evidence, expected failures and review

- The 24-hour TTL will be too short for a human owner sealing a harness on a
  different day than the run. Recorded, not fixed: matching the Gate-0 cap is
  the conservative choice, and lengthening it is an owner decision with its own
  evidence, not a convenience edit inside this packet.
- `RunManifest` gains a non-`None`-able field with a default, so every existing
  positional construction keeps working. If any caller constructs it by
  `dataclasses.replace` with a stale field set, that surfaces as a `TypeError`
  at import of the test suite, not as a silent unsealed run.
