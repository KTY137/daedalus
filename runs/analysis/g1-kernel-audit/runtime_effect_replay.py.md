# daedalus/kernel/runtime_effect_replay.py  (154 lines)

Base 54f09753. Static read-only.

## What the file is for

Composes `effect_replay.py`'s read-only persisted-execution projection with
`runtime_effects.py`'s runtime-trust verification, so a runtime-bound
execution's replay state can be inspected without granting, starting,
finishing, or re-executing anything, and without the current live runtime
trust record replacing what was true at the original start instant.

## Axis 1 — docstring truth

### CONFIRMED
- none.

### PLAUSIBLE
- none.

### Checked and honest
- Module docstring: "This module composes both authorities at the retained
  start instant without granting, starting, finishing, revoking, or
  re-executing an effect." (:11-13). Verified: the only writes anywhere in
  this file are zero — no `INSERT`/`UPDATE`/ledger-mutating call exists here.
  `verify_runtime_bound_effect_lease` is called with
  `now=start_instant` (:118-129), where `start_instant` is parsed from
  `effect_snapshot.start_receipt.started_at` (:114-117) — the retained
  historical instant, not the current wall clock. Confirmed true.
- "The current runtime trust record must still be active and authenticated
  when the projection is requested. This conservative rule intentionally
  refuses historical runtime capability replay after trust expiry or
  quarantine until an authenticated append-only runtime trust history
  exists." (:10-13). This is an honest, explicit statement of a *conservative
  limitation*, not an overclaim — it says what does NOT work yet (replaying
  after trust expiry) rather than claiming full historical replay. I checked
  it is accurate: `verify_runtime_bound_effect_lease` (called at :118) goes
  through `_require_runtime_record` -> `ledger.require_active(...)`
  (`runtime_effects.py:245-267`), which by name and by the
  `RuntimeTrustLedgerPort` contract requires the record to be *currently*
  active, not merely to have been active at `start_instant`. So a trust
  record that has since expired or been quarantined will fail this call even
  though the effect's original start was legitimate at the time — matches
  the docstring's disclosed limitation exactly.
- "neither result grants authority to execute" (`inspect_runtime_effect_execution`
  docstring, :77-79). Confirmed: return type is a frozen dataclass
  (`RuntimeEffectExecutionReplaySnapshot`, :42-67) with no method that calls
  into `EffectLeaseLedger.grant/begin/finish`.
- Inline comment: "a runtime-bearing lease must never be rewrapped as a
  NonRuntimeEffectAuthorization, because that facade exists precisely to
  refuse runtime leases." (:91-93). Verified structurally: this function
  builds a `PersistedEffectLeaseSubject` (from `effect_replay.py`) directly
  from `authorization.capability.lease` (:96-103), never touching
  `NonRuntimeEffectAuthorization` at all — the type simply never appears in
  this file's runtime path, so the claimed refusal is enforced by absence of
  a code path rather than an explicit runtime check. That is a slightly
  weaker guarantee than "refuses" implies (there is no active refusal to
  test), but I did not find a way to actually construct the described
  bypass from this file alone, so this is not a finding, just a note that
  the guarantee is structural/by-construction rather than defensively
  checked here.

## Axis 2 — effect surface

No subprocess/network/filesystem-write/env-read sites in this file (grepped;
zero hits). The only I/O is delegated entirely to
`effect_replay.py::_project_persisted_execution` (reused, not reimplemented —
see Axis 5), which is the same read-only `mode=ro` / `query_only=ON` sqlite
read already covered in that file's dossier. No local table entry.

## Axis 3 — unreleased resources

No findings. No resource acquisition of any kind in this file — it holds no
sqlite connection, file handle, lock, or subprocess itself; it only calls
`_project_persisted_execution`, which already closes its own connection in a
`finally` block (see `effect_replay.py` dossier, Axis 3).

## Axis 4 — validator gaps (W4 class)

No findings. This file constructs no filesystem path, git ref, or URL
segment from any value at all — it only compares digests
(`trust_record.record_sha256`, `runtime_id`, :135-142) and constructs a
frozen dataclass. No `_identifier`-validated value reaches path construction
here because no path construction happens here.

## Axis 5 — dead / duplicate

- Not dead: `inspect_runtime_effect_execution` is called from
  `daedalus/runtimes/recovery.py:22-26` and covered by
  `tests/kernel/test_runtime_effect_replay_projection*.py`. Grep:
  `grep -rn "inspect_runtime_effect_execution" --include=*.py daedalus/ tests/` → 1 production caller (`daedalus/runtimes/recovery.py`) + dedicated test files.
- **Genuine composition, not duplication** — this is the clean half of the
  Axis-5 question posed by the brief. `inspect_runtime_effect_execution`
  (:70-147) directly imports and calls `_project_persisted_execution` from
  `effect_replay.py` (:24-29, call at :105) instead of reimplementing the
  sqlite read; it adds only the runtime-trust verification layer on top
  (:113-142). `effect_replay.py` is the authoritative reader of "what was
  persisted"; this file is the authoritative reader of "was the runtime trust
  behind it valid at that instant" — two distinct, composed responsibilities,
  matching the two-authority split documented in `runtime_effects.py:1-8`.
  No parallel control plane, no re-derivation of the ledger-reading logic.
  This file also correctly imports `_parse_utc` from `effects.py` (:30)
  rather than redefining it — unlike `runtime_effects.py` and
  `effect_recovery.py` in this same slice (see those dossiers for the
  triplicated-helper finding this file avoids).

## OWNED-FLAG

N/A — this file is not owned by another running packet.

## What I did not cover

- Did not re-verify `RuntimeTrustLedgerPort.require_active` implementations
  outside this slice.
- Did not re-verify `effects.py::_parse_utc`/`verify_effect_lease` internals
  (OWNED-FLAG).
