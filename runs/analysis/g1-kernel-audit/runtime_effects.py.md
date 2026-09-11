# daedalus/kernel/runtime_effects.py  (569 lines)

Base 54f09753. Static read-only.

## What the file is for

Wraps `effects.py`'s generic `EffectLease` with a second, independent
authority: a `RuntimeTrustLedgerPort`-backed `RuntimeTrustRecord` that must be
active both when the runtime-bound lease is issued and again immediately
before grant/begin. `RuntimeBoundEffectAuthorization` is the production
facade a runtime-bearing entrypoint actually holds; it owns its own clock so
callers cannot backdate verification, and it composes `EffectLeaseLedger`
methods from `effects.py` rather than reimplementing ledger persistence.

## Axis 1 — docstring truth

### CONFIRMED
- none.

### PLAUSIBLE
- **Narrow race between `_verify_at(pre_start)` and `effect_ledger.begin(...)`
  in `begin_effect`** (`runtime_effects.py:512-525`). The module docstring
  promises the capability "rechecks that record before both grant and
  execution start" (:5-7). The recheck (`self._verify_at(pre_start)`, :514)
  and the durable `begin` call (:515-525) are two separate calls, not one
  atomic operation — if runtime trust is revoked in the gap between them, the
  effect still starts durably before the post-start recheck (:527-538) has a
  chance to cancel it. The code narrows this window by also rechecking
  immediately after `begin` (:530) and calling `effect_ledger.finish(...,
  outcome="cancelled", ...)` if that second check fails (:532-538), so a
  revoked-mid-window trust record does get the execution cancelled rather
  than left silently STARTED forever — but there is still a real, if narrow,
  window where the effect is durably STARTED while trust is actually invalid.
  PLAUSIBLE, not CONFIRMED: I did not establish whether the caller is allowed
  to treat "cancelled after the fact" as equivalent to "never started" for
  every consumer of `begin_effect`'s result, i.e. whether an external effect
  could already have been dispatched by the caller in that same window before
  it observes the cancellation exception.

### Checked and honest
- "it binds the signed lease to one exact, authenticated and active
  RuntimeTrustRecord and rechecks that record before both grant and execution
  start" (:5-7): `grant()` (:499-510) calls `self._verify_at(instant)` (:501)
  before `self.effect_ledger.grant(...)` (:502-510); `begin_effect()` (:512-539)
  calls `self._verify_at(pre_start)` (:514) before `self.effect_ledger.begin(...)`
  (:515-525). Both call sites recheck before the ledger call, as claimed,
  modulo the narrow gap above.
- "The capability performs no provider call and grants no effect by itself."
  (:7-8): confirmed — no subprocess/network/file-write call anywhere in this
  file (grepped; zero hits for any Axis-2 effect class).
- `RuntimeBoundEffectAuthorization` docstring: "This production facade owns
  its clock so callers cannot backdate trust verification after lease or
  runtime-evidence expiry." (:443-445). Confirmed: `verify()`, `grant()`, and
  `begin_effect()` all call `_utc_now()` internally (:497, :500, :513) and
  none of the three public methods accepts a caller-supplied `now`. Only the
  lower-level module function `verify_runtime_bound_effect_lease` exposes an
  explicit `now` parameter (:363-372), and the docstring explicitly
  distinguishes that "low-level verifier" from "this production facade" —
  honest about the split.
- `_require_runtime_trust_ledger_port` docstring: "`@runtime_checkable`
  proves only that the member NAME resolves... Require the member to be
  callable so the refusal happens at this boundary." (:221-234). Confirmed:
  the check is `not isinstance(value, RuntimeTrustLedgerPort) or not
  callable(getattr(value, "require_active", None))` (:236-238) — both the
  protocol check and an explicit `callable()` check are present, exactly as
  documented, with an honestly scoped caveat: "The check deliberately stops
  at callability... a guard that blocks a valid ledger rather than an
  invalid one" (:232-234) — the docstring does not overclaim full signature
  validation.

## Axis 2 — effect surface

No subprocess/network/filesystem-write/env-read sites in this file (grepped
for all Axis-2 categories: zero hits). This module is pure in-memory
composition and verification logic over dataclasses; the actual sqlite
writes happen inside `effect_ledger.grant/begin/finish`, which live in
`effects.py` (OWNED-FLAG) and are only *called from* this file at
`runtime_effects.py:502, 515, 532, 553`. No table entry — there is no local
effect to enumerate.

## Axis 3 — unreleased resources

No findings. No sqlite/file/tempfile/lock/socket/subprocess acquisition
anywhere in this file (grepped; zero hits).

## Axis 4 — validator gaps (W4 class)

Checked and honest: `_identifier` is applied to `runtime_id` and
`issuer_key_id` (`RuntimeBoundEffectLease.__post_init__`, :121-124). Neither
value is used to build a filesystem path, git ref, or URL segment anywhere in
this file — both are used only as dict/dataclass fields and in digest/HMAC
computation. No findings.

## Axis 5 — dead / duplicate

- Not dead: `RuntimeBoundEffectAuthorization`, `issue_runtime_bound_effect_lease`,
  and `verify_runtime_bound_effect_lease` all have real production callers —
  `daedalus/runtimes/admission/authorization.py`,
  `daedalus/runtimes/recovery.py:27`, `daedalus/build_exec.py`,
  `daedalus/chip_design/cli.py`, `daedalus/gates/repository_write_effect_lease.py`
  (grep: `grep -rn "RuntimeBoundEffectAuthorization\|issue_runtime_bound_effect_lease\|verify_runtime_bound_effect_lease" --include=*.py daedalus/ tests/` → 41 files, non-test hits in at least 8 production modules).
- **CONFIRMED duplicate helpers with a behavioral divergence.** `_as_utc`,
  `_parse_utc`, `_secret_bytes`, `_signature` (:68-96) are independent
  reimplementations of the same-named functions in `effects.py:223-253`,
  rather than imports (contrast with `effect_replay.py` and
  `runtime_effect_replay.py`, which both import `_parse_utc` directly from
  `effects.py`). The `_secret_bytes`/`_signature` pair is functionally
  identical to `effects.py`'s (same >=32-byte check, same HMAC-SHA256
  construction, only the error message text differs) — a third copy of the
  same pair also exists in `effect_recovery.py:205-217` (see that dossier).
  `_parse_utc` here (:78-83) additionally catches `(AttributeError,
  ValueError)` on `datetime.fromisoformat(value.replace(...))`, while
  `effects.py:223-227`'s original and `effect_recovery.py:226-230`'s copy
  both catch only `ValueError`. This means: if `value` were ever a non-string
  (e.g. `None`), `effects.py::_parse_utc` and `effect_recovery.py::_parse_utc`
  would raise an unhandled `AttributeError` instead of the intended
  fail-closed `EffectLeaseBindingMismatch`/`EffectRecoveryBindingError`,
  whereas this file's copy would correctly raise
  `RuntimeLeaseBindingMismatch`. I did not find a call site in this file, in
  `effects.py`, or in `effect_recovery.py` that passes a non-`_utc_timestamp`-
  validated value into `_parse_utc` (every observed call site pre-validates
  the value is a string first), so I could not confirm this divergence is
  reachable — PLAUSIBLE robustness gap in `effects.py`/`effect_recovery.py`,
  not CONFIRMED exploitable, and out of scope to fix here since `effects.py`
  is OWNED-FLAG. Reported because it is the clearest evidence in this slice
  that the un-imported duplication has already started silently drifting
  between copies.

## OWNED-FLAG

N/A — this file is not owned by another running packet. (It imports several
names from `daedalus/kernel/effects.py`, which *is* owned — see the
duplicate-helper finding above for where that boundary matters.)

## What I did not cover

- Did not re-verify `EffectLeaseLedger.grant/begin/finish` or
  `verify_effect_lease` internals (`effects.py`, OWNED-FLAG) — trusted as a
  dependency for the race-window analysis above.
- Did not verify `RuntimeTrustLedgerPort.require_active` implementations
  (outside this slice) for how promptly they observe revocation.
