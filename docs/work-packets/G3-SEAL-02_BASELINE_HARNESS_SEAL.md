# G3-SEAL-02 - the kernel binding that makes a Gate-3 baseline harness sealable

Packet ID: `G3-SEAL-02`
Artifact role: `primary`
Status: `built; independently reviewed; primary claim REFUTED at revision 1 and repaired; 47-row matrix green; nothing sealed`
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

> A `RunManifest` reports `sealed=True` **if and only if** a `SealAuthority`
> has re-read a persisted one-use consumption from the `SealLedger`, re-run the
> owner HMAC over the signed `BaselineHarnessSeal` it stores, and that seal
> binds exactly this manifest's digest and each of its six freeze obligations.
>
> No builder-supplied string, no hand-built value of any seal class, no
> serialization route (`from_dict`, subclass, pickle, deepcopy), no unpersisted
> receipt and no promotion approval can produce that answer.
>
> Revision 1 of this packet claimed the first paragraph while implementing only
> the digest comparison, and an independent reviewer forged a seal in one
> script. The second paragraph exists because of that.

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

The authenticated result of one verification. **It is a value, not a
capability, and nothing may treat holding one as proof of anything.**

A first revision of this packet claimed here that it was "constructible in
practice only by `verify_baseline_seal`". That was false, and an adversarial
reviewer refuted it in one script: the class is a frozen dataclass, every field
it carries is publicly computable from the manifest via
`seal_expectation_digests()`, and `__post_init__` validates only *formats*. The
reviewer built one with `owner_id="attacker"` and `signature_sha256="0"*64` and
sealed a run with it — plus four more routes (`from_dict`, subclass, pickle,
deepcopy). See "Evidence, expected failures and review".

### `SealAuthority`

The thing that actually answers "is this sealed?". It holds a `SealLedger` and
the owner keyring, and `reauthenticate(receipt)` re-reads the persisted row,
re-parses the **signed** seal, re-runs the HMAC, and cross-checks every
denormalized column against it. It returns a `VerifiedBaselineSeal` or raises;
it never returns a bool.

It also refuses a receipt consumed through a ledger **clock seam** unless the
caller passes `allow_clock_seam=True`, mirroring
`promotion.authorize_persisted_promotion`'s refusal of a decision whose
`seams_used` is non-empty. A rewound clock can consume an expired seal, so a
seam-built receipt must not seal anything by default.

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
`seal_claim` / `evidence_status` keep reporting it as such). Two public fields
are added, and they are **all-or-nothing** — a receipt without an authority
cannot be authenticated, and an authority without a receipt has nothing to
authenticate:

```python
consumed_seal:  ConsumedBaselineSeal | None = None
seal_authority: SealAuthority        | None = None
_authenticated_seal: VerifiedBaselineSeal | None = field(init=False, ...)
```

`__post_init__` type-checks both (deferred import, so this package keeps a
stdlib-only module-level import graph) and then calls
`seal_authority.reauthenticate(consumed_seal)`, which **re-reads the ledger row
and re-runs the owner HMAC**. Its result is stored in `_authenticated_seal`,
which is `init=False` so no caller can supply it and `dataclasses.replace`
forces a fresh ledger round trip.

Authentication happens once, at construction, so `sealed` stays a cheap
property reporting an answer an authority already gave — and a forged receipt
fails **loudly** there instead of quietly reporting `False` inside a report.

`sealed` then becomes:

```python
seal = self._authenticated_seal        # half 1: did an owner sign this?
if seal is None:
    return False
return (                               # half 2: sign WHAT?
    seal.manifest_sha256 == self.digest
    and seal.task_set_sha256 == self.task_set.digest
    ... one comparison per obligation, plus base_revision and plan_digest ...
)
```

Neither half is sufficient alone. Half 1 without half 2 seals any manifest with
any genuine seal; half 2 without half 1 is the forgery the reviewer executed.

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

### 5b. Refusal path, continued — the review's findings as rows
20. A receipt consumed through a ledger **clock seam** does not seal unless the
    caller passes `allow_clock_seam=True` → `SealStateError`.
21. A clock that advances past `expires_at` between the preflight sample and
    the persistence sample → `SealExpired`, and **nothing is persisted**.
22. A ledger clock that moves backwards mid-consume → `SealStateError`.

### 5c. Forgery, continued
16. A hand-built `VerifiedBaselineSeal` **of the real class**, unsigned, no
    ledger → refused. *This is the row the first revision was missing, and the
    forgery that worked.*
16b. A hand-built `ConsumedBaselineSeal` with a self-consistent digest →
    `SealStateError` ("not persisted"): the receipt validates itself, the
    ledger is what refuses it.
16c. `from_dict` / subclass / pickle / deepcopy of a forged seal → all refused
    (parameterised).
17. A receipt without an authority, or an authority without a receipt →
    `FreezeError`.
18. A genuine receipt re-authenticated against the **wrong keyring** →
    `SealSignatureError`.
19. A ledger row edited in place (`UPDATE ... SET owner_id='attacker'`) no
    longer authenticates → `SealStateError`.

### 5d. Fault injection
16. Concurrent double-consume from two connections → exactly one succeeds.
17. Malformed / truncated JSON seal payload → `ValueError`, never a pass.

*Row 15 of the first revision ("ledger file unwritable") is WITHDRAWN: it was
listed and never tested. See the review section.*

## Scope

**In scope**
- `daedalus/kernel/contracts/security.py` (add `BaselineHarnessSeal`)
- `daedalus/kernel/seals.py` (new: issue / verify / `SealLedger` /
  `SealAuthority`)
- `daedalus/eval/gate3/contracts.py` (`RunManifest.consumed_seal`,
  `seal_authority`, `sealed`, `evidence_status`, plus the pre-existing
  `FrozenTaskSet.task_ids` / `SeedPolicy.seeds` freeze gap the review found)
- `tests/kernel/test_baseline_harness_seal.py` (new)
- `tests/contracts/test_import_scc_hierarchy.py`,
  `tests/contracts/test_work_packet_index.py` (moving census pins only)
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

### Independent adversarial review (2026-09-09) — the first revision FAILED

A reviewer with no sight of this document attacked commit `8f2cd807` and
**refuted its primary acceptance claim in one script**. Retained in full,
because the plan requires negative evidence to survive, and because the shape
of the mistake is more instructive than the fix.

| # | Finding | Disposition |
| --- | --- | --- |
| CRITICAL-1 | `sealed` returned `True` for a hand-built, unsigned `VerifiedBaselineSeal` (`owner_id="attacker"`, `signature_sha256="0"*64`, no ledger). Also via `from_dict`, subclass, pickle, deepcopy, and `object.__setattr__`. | **FIXED.** `RunManifest` now takes a `ConsumedBaselineSeal` + `SealAuthority` and re-authenticates against the ledger. Rows 5c16, 5c16b, 5c16c. |
| HIGH-2 | "one-use" and "unexpired" never reached `sealed`: one genuine consumed seal sealed unlimited manifests forever. | **FIXED** by the same change — the authority re-reads the persisted consumption. |
| HIGH-3 | `consume` sampled the clock once *before* `BEGIN IMMEDIATE`; under real lock contention (`busy_timeout` 30 s) an **expired** seal was persisted with a pre-expiry `consumed_at`. `ApprovalLedger` has always re-checked. | **FIXED.** Three clock samples, monotonicity guards, in-transaction re-verify, expiry-at-persistence check, `except Exception: ROLLBACK`. Rows 5b21, 5b22. |
| MEDIUM-4 | `verify_consumption` compared a self-consistent digest to itself — a hand-edited row verified. | **FIXED, and beyond the approval path**: it now re-parses the signed seal, re-runs the HMAC, and cross-checks *every* denormalized column (the approval version checks four), refusing loudly if a future column is added unchecked. Row 5c19. |
| MEDIUM-5 | The injectable clock seam is identical to `ApprovalLedger`'s (accepted), but nothing downstream refused a seam-built receipt the way `authorize_persisted_promotion` refuses `seams_used`. | **FIXED.** `SealAuthority.allow_clock_seam` defaults to `False`. Row 5b20. |
| LOW-6 | `seals._as_utc` checked `tzinfo is None` but not `utcoffset() is None`; approvals checks both. Measured a 1 h silent shift. | **FIXED.** |
| MEDIUM-7 | Pre-existing: `FrozenTaskSet.task_ids` and `SeedPolicy.seeds` were not defensively copied, so an object could hold a state its own validator refuses and its digest could move. Direction was fail-closed for `sealed`. | **FIXED** (`tuple()` before validation), though it predates this packet. |
| INFO-8 | The sealed branch of `evidence_status()` dropped `owner_seal_ref` from the rendered line. | **FIXED** — the sealed line now names any unverified claim as well. |

The reviewer also **refuted six of my own worries**: seal and approval
signatures cannot cross-verify, consuming one cannot retire the other's nonce,
a `ConsumedBaselineSeal` is refused by `authorize_persisted_promotion`, the
`UNIQUE` constraints hold, an injected `MemoryError` mid-`INSERT` rolls back
cleanly, and `approvals.py` is untouched. **The type/domain/ledger separation
was never the weak part.** Trusting a value type was.

Mutation testing killed 7/7 (including all three the packet asked for), so the
suite was strong on every guard that existed — the gap was a *missing* guard.
§5c tested three forgeries: the historical string, a promotion approval, and a
structural impostor of a **different class**. It never tried the real class,
hand-built. That is exactly the one that worked, and it is now row 5c16.

**Corrections to the first revision's own claims**, since it made three the
reviewer had to check by hand: the acceptance matrix contained **35** tests,
not the 36 the commit message reported; `bound_digests` returns **seven**
digests, not "eight"; acceptance row 15 (unwritable ledger file) had **no
test** and still does not — it is withdrawn rather than left as an unearned
row, because a portable unwritable-SQLite fixture on Windows is its own piece
of work and inventing a passing test for it would be worse than admitting the
gap.

### Expected failures, recorded before the build

- The 24-hour TTL will be too short for a human owner sealing a harness on a
  different day than the run. Recorded, not fixed: matching the Gate-0 cap is
  the conservative choice, and lengthening it is an owner decision with its own
  evidence, not a convenience edit inside this packet.
- Sealing now needs a live `SealLedger` and the owner keyring at manifest
  construction. That is deliberate — it is the whole finding — but it means a
  report renderer that only has JSON cannot construct a sealed manifest. It
  must carry the receipt and be given an authority, or render UNSEALED.
