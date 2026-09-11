# daedalus/kernel/contracts/security.py  (334 lines)

Base 54f09753. Static read-only. Auditor: parent (W2 slice, subagent cap hit).

## What the file is for

Defines the three trust contracts the kernel's security spine is built on —
`OwnerApproval`, `EffectLeaseRequest`, `EffectLease` — plus the two neutral
`Protocol` ports (`RuntimeTrustRecordPort`, `RuntimeTrustLedgerPort`) and their
error type. They inherit `CanonicalContract` and reuse `canonical.py`'s
validators; they add no second serialization or digest authority.

## Axis 1 — docstring truth

This file uses the word "Authenticated" twice, in a module whose contracts
underwrite Plan §4 invariant 5 (sealed promotion). Both were checked.

### Checked — headline overstates, body corrects (acceptable, but note the shape)

`:63-67` `OwnerApproval`:

> "**Authenticated**, bounded and single-candidate owner authorization.
>
> The contract remains **inert** until a verifier authenticates the signature
> and a replay ledger consumes its nonce. It never applies a candidate."

The summary line calls the record "Authenticated"; the very next sentence says
it is inert until *something else* authenticates it. The class itself performs
no authentication — `__post_init__` (`:87-124`) only validates field shapes, and
`signature_sha256` is validated by `_sha256` (`:92-98`), i.e. checked to be
64 hex characters, not verified as a signature. `signing_dict` (`:126-129`) and
`signing_digest` (`:131-133`) compute what a verifier *would* sign; they do not
compare anything.

Verdict: **not an overclaim**, because the qualification is in the same
docstring and is accurate. But it is the shape that becomes one when quoted:
a reader citing only the summary line would state something false. The
verification that makes the word true lives in `approvals.py` — and a sibling
worker confirmed it is real there (`hmac.compare_digest`, constant-time, at
approvals.py:362 and :693; absent or <32-byte key fails closed; one-use enforced
by SQLite UNIQUE inside `BEGIN IMMEDIATE` at :469-494,537, genuinely atomic
rather than check-then-act). So the claim is discharged elsewhere, correctly.

`:34` `RuntimeTrustRecordPort`: "**Authenticated** runtime-trust record fields
consumed by the kernel." Same reading: the adjective describes the provenance
the *supplier* must guarantee, not anything this Protocol enforces.

### PLAUSIBLE — `@runtime_checkable` gives a much weaker check than the word "Authenticated" suggests

Both ports are `@runtime_checkable` (`:32`, `:45`). A `runtime_checkable`
Protocol's `isinstance` verifies **attribute presence only** — not types, not
values, not authenticity. For `RuntimeTrustRecordPort` (`:36-42`, seven `str`
attributes) an `isinstance` check passes for any object that happens to have
seven attributes with those names and arbitrary contents.

Live `isinstance` sites, enumerated:

- `daedalus/kernel/runtime_effects.py:236` — `isinstance(value, RuntimeTrustLedgerPort)`
- `daedalus/kernel/runtime_effects.py:263` — `isinstance(record, RuntimeTrustRecordPort)`
- `daedalus/kernel/runtime_effect_replay.py:53` — `isinstance(self.runtime_trust_record, RuntimeTrustRecordPort)`

**Mitigation found, and it is good:** `runtime_effects.py:224` carries an
explicit docstring acknowledging exactly this hazard —
"``isinstance(x, RuntimeTrustLedgerPort)`` is therefore True for an object…" —
and `:236` compensates with an additional `callable(...)` check on the required
method. So the primary consumer already knows.

I am filing PLAUSIBLE rather than CONFIRMED because the two consumers of
`RuntimeTrustRecordPort` (`runtime_effects.py:263`,
`runtime_effect_replay.py:53`) check presence only, and I did not trace whether
their callers independently validate the seven field *values* before use. The
finding worth carrying is narrower and certain: **the word "Authenticated" at
`:34` describes a property no `isinstance` against this Protocol can establish**,
and the one module that says so out loud had to write its own warning.

### Checked and honest

- `:144-147` `EffectLeaseRequest` — "The request **grants nothing by itself** and
  is safe to persist or inspect." Correct: the class carries scope and digests,
  with no authority-bearing field and no method that authorizes.
- `:163-165` — the comment explaining why `operation_sha256` is optional
  ("Omitted values retain the historical wire bytes and digests") is a precise
  statement of a canonicalisation compatibility constraint. Honest.
- `:3-6` module docstring — "they do not create a second serialization or digest
  authority." Verified: every digest goes through `canonical_sha` imported from
  `daedalus.spine.envelope` (`:25`) and the validators are all imported from
  `contracts/canonical.py` (`:14-24`). No local regex, no local hasher. This is
  the correct pattern and the direct counter-example to the 9 files that *do*
  duplicate `_ID_RE` (measured by W1).

## Axis 2 — effect surface

None. No filesystem, subprocess, network, or `os.environ` access — this is a
pure contract module. Correctly absent from the Effect Registry.

## Axis 3 — unreleased resources

None. No resources acquired.

## Axis 4 — validator gaps (W4 class)

### CONFIRMED — `target_ref`, a git ref, is validated only by the weak `_identifier`

`:107`:

```python
object.__setattr__(self, "target_ref", _identifier(self.target_ref, "target_ref"))
```

`_ID_RE` is `^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$` (`canonical.py:27`). For a
value that will be handed to git, that permits:

- `..` sequences (git's own `check-ref-format` rejects these, so we may be
  relying on git to refuse rather than refusing ourselves);
- `:` anywhere after the first character — meaningful in a refspec (`src:dst`).

It does **not** permit a leading `-`, because the first character must be
alphanumeric, so argv option-injection (`--upload-pack=…`) is blocked at
character one. I checked the regex rather than assuming.

The value flows out of this file: re-validated the same weak way at
`approvals.py:84` and `:139`, then into
`promotion.py:308-310` / `:355` (`resolve_live_target_revision` →
`_canonical_identifier(target_ref, ...)`), with the live call at
`kairos/gated_writes.py:287`.

I have **not** established the impact — that requires reading the git invocation
in `promotion.py`, which is another worker's file. Handed off to the promotion
worker with the specific questions (is `_canonical_identifier` a stricter
validator or a local copy of the weak regex; is the ref an argv element or
string-interpolated; does anything call `git check-ref-format`). Recording it
here as a CONFIRMED *validator choice* with **impact unresolved**, explicitly not
as a CONFIRMED vulnerability.

### Other `_identifier`-validated fields — none reach a path in this file

`approval_id`, `owner_id`, `key_id`, `nonce` (`:88-89`); `request_id`,
`mission_id`, `attempt_id`, `entrypoint_id`, `idempotency_namespace` (`:169-176`).
All are record fields here. `attempt_id` is the field whose downstream path use
was the subject of W4's F-W4-01 — that chain is **blocked** downstream by
`_repo_path` (independently confirmed twice; see `attempt_workspace.py.md`).

## Axis 5 — dead / duplicate

### Checked and refuted — this file is NOT unused

My first scoped grep for importers of `contracts.security` returned only two
test files, which looked like a 334-line unused security module. That was a
**false alarm from the grep pattern**: consumption goes through the package's
lazy facade, `contracts/__init__.py:31-41`, which maps all six names to owner
`"security"` and resolves them in `__getattr__` (`:71-81`). So callers write
`from daedalus.kernel.contracts import OwnerApproval` and never name the module.

Symbol-level counts (scoped to real source, copy directories excluded):

| symbol | refs in `daedalus/` | refs in `tests/` |
| --- | --- | --- |
| `EffectLease` | 54 | 33 |
| `EffectLeaseRequest` | 44 | 63 |
| `OwnerApproval` | 25 | 47 |
| `RuntimeTrustRecordPort` | 13 | 3 |
| `RuntimeTrustLedgerPort` | 11 | 10 |
| `RuntimeTrustPortError` | 6 | 2 |

Heavily used. Recording the false alarm because the same grep shape would
mislead the next auditor: **in a lazy-facade package, module-level import greps
undercount; grep the symbols.**

No duplicated validators or digest helpers in this file (see Axis 1, last item).

## What I did not cover

The `EffectLease` body (`:236-334`) beyond its docstring and validator imports —
the lease *ledger* semantics are another worker's slice.
