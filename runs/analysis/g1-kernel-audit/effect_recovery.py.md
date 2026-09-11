# daedalus/kernel/effect_recovery.py  (619 lines)

Base 54f09753. Static read-only.

## What the file is for

`reconcile_unknown_effect` finishes an `EffectLeaseLedger` execution that is
stuck in `STARTED` (crash / unknown outcome mid-effect) using an
externally-observed, HMAC-signed `ExternalEffectObservation`. It never issues
a new lease and never starts a new execution — it only transitions an
already-durable `STARTED` row to `COMPLETED`, or, if the row is already
terminal, checks that the terminal receipt matches the observation. The
signature over `ExternalEffectObservation` (`_signature`/`_secret_bytes`,
:205-217) is the authentication gate before any ledger write.

## Recovery robustness: crash mid-reconciliation, idempotency, double-spend

Traced `reconcile_unknown_effect` (:554-606) against interruption at every
point:

- **Crash before `ledger.finish` is called** (during `verify_external_effect_observation`,
  :565-573, or the `state is None` / `state == "STARTED"` checks, :574-577):
  no side effect occurred; a retry re-enters the function from scratch. Safe.
- **Crash during/after `ledger.finish`** (:579-585): `ledger.finish` is a
  single sqlite write (in `effects.py`, OWNED-FLAG, trusted as durable/atomic
  here). If it crashes before committing, the row stays `STARTED` and a retry
  takes the same branch again — safe. If it crashes after committing but
  before this function returns to its caller, the row is now terminal
  (`COMPLETED`). A retry re-enters, sees `state != "STARTED"` (:577), falls to
  `_persisted_terminal` (:593) and `_matches` (:594-598), which compares the
  new observation's `output_digests`/`detail_sha256` against what is already
  persisted. If the same observation is retried, `_matches` is true and the
  function returns `reconciled=False` (already-applied) rather than calling
  `finish` again — **CONFIRMED idempotent for identical retries**, no
  double-finish.
- **Double-spend via a second, different observation**: if a second,
  differently-signed `ExternalEffectObservation` (different `output_digests`
  or `detail_sha256`) arrives after the first reconciliation already
  completed the execution, `state` is no longer `STARTED`, so `ledger.finish`
  is never called again; `_matches` (:544-551) compares the new observation
  against the already-persisted receipt field-by-field and fails, so the
  function raises `EffectRecoveryStateError("execution is terminal under
  different recovery evidence")` (:604-606) instead of silently accepting the
  second observation. **CONFIRMED**: no double-write, no silent overwrite.
- **Race between two concurrent reconciliation attempts for the same STARTED
  execution**: both read `state == "STARTED"` and both call `ledger.finish`.
  This file does not itself serialize that; whether the second `finish` call
  is rejected or raises depends on `EffectLeaseLedger.finish`'s own
  concurrency handling (`effects.py`, OWNED-FLAG — not re-verified here, but
  the `except EffectLeaseStateError: pass` at :591-592 shows the author
  anticipated exactly this race and treats a losing `finish` call as
  equivalent to "already terminal, go read and match" rather than propagating
  the error). PLAUSIBLE that this is race-safe; CONFIRMED that the code is
  structured to treat a lost race as the terminal-read path, not as a crash.

## Axis 1 — docstring truth

### CONFIRMED
- none.

### PLAUSIBLE
- none.

### Checked and honest
- Module docstring "Authenticated reconciliation for externally acknowledged
  unknown effects" (`effect_recovery.py:1`) — `reconcile_unknown_effect`
  (:554) always calls `verify_external_effect_observation` (:565) first,
  which HMAC-verifies the observation signature (:373-377) before any ledger
  mutation. Confirmed: no code path reaches `ledger.finish` without passing
  verification first.
- `ExternalEffectObservation.__post_init__` requires `status == "acknowledged"`
  (:102-104) — enforced unconditionally, not just documented.
- The inline comment at :514-522 describing the sqlite `with`-does-not-close
  pitfall is descriptive, not a functional claim, and the code below it
  (:523-532) implements the corrected `try`/`finally` shape it describes.

## Axis 2 — effect surface

| site (file:line) | effect | registry row | covered? |
|---|---|---|---|
| `effect_recovery.py:523` `sqlite3.connect(uri, uri=True)` | filesystem/sqlite read (`mode=ro`) | none under `daedalus.kernel.*` | not directly; see Notes |
| `effect_recovery.py:579` `ledger.finish(...)` (via `reconcile_unknown_effect`) | sqlite write (transitions STARTED->terminal) | none under `daedalus.kernel.*` | not directly; see Notes |

### Notes
- Grep of the 108 `EntrypointSpec(` rows in `daedalus/spine/effect_boundary.py`
  for `target="daedalus.kernel.effect_recovery...."` returns zero matches —
  consistent with the brief's measured fact that only 4 kernel rows exist and
  none target this file.
- `reconcile_unknown_effect` itself does **not** take a registry or
  `EntrypointSpec` and does not check one (:554-606) — it only requires a raw
  `EffectLeaseLedger`, an `EffectExecutionRequest`, a `LeasedEffectStartReceipt`
  and a signed `ExternalEffectObservation`. The registry check for the
  underlying effect happened earlier, at the original `ledger.begin()` call
  that created the `STARTED` row this function finishes (in `effects.py`,
  OWNED-FLAG, not re-verified here).
- The only production (non-test) caller found repo-wide is
  `daedalus/runtimes/recovery.py::reconcile_runtime_provider_unknown` (:224-259),
  which requires a `RuntimeBoundEffectAuthorization` constructed via
  `runtime_effects.verify_runtime_bound_effect_lease` — that verification path
  (in `runtime_effects.py`, this same slice) does check the entrypoint
  registry through `verify_effect_lease(..., registry=...)`. So the effect
  surface here is plausibly covered transitively by whichever non-kernel
  `EntrypointSpec` row issued the original runtime-bound lease (e.g. a
  provider CLI target), not by a row naming this file. This is PLAUSIBLE, not
  CONFIRMED: I did not trace which specific one of the 108 rows corresponds to
  the runtime that calls into `daedalus/runtimes/recovery.py` in production.
- `reconcile_unknown_effect` is exported in `__all__` (:609-618) and is a
  plain importable function; a hypothetical second caller could invoke it
  directly with a raw `EffectLeaseLedger` and bypass
  `daedalus/runtimes/recovery.py`'s additional `_validate_runtime_binding` /
  `_load_provider_binding` checks (:180-221 there). No such second production
  caller was found (grep, see Axis 5) — flagged as PLAUSIBLE surface, not
  CONFIRMED reachable misuse.

## Axis 3 — unreleased resources

Checked and honest: `_persisted_terminal` (:509-535) is the only resource
acquisition in this file. `connection = sqlite3.connect(uri, uri=True)` (:523)
is followed by `try: ... finally: connection.close()` (:531-532) — the
canonical fixed shape from `effects.py::_initialize`, already applied here.
No open file handles, tempfiles, locks, sockets, or subprocesses anywhere in
this module (grepped for all Axis-3 resource classes: zero hits besides the
one sqlite connect above). No findings.

## Axis 4 — validator gaps (W4 class)

Checked and honest: `_identifier` is applied to `observation_id`,
`provider_id`, `execution_id`, `idempotency_key`, `issuer_key_id`
(`ExternalEffectObservation.__post_init__`, :76-124). None of these values
reach `Path(...)`, `os.path.join`, or an f-string building a filesystem path
in this file — they are used only as sqlite bound parameters (`?`
placeholders, e.g. :529) and as dict/dataclass fields. The one path built in
this file, `uri = f"file:{Path(ledger.path).resolve().as_posix()}?mode=ro"`
(:513), is built from `ledger.path` (a trusted, configuration-supplied path),
not from any `_identifier`-validated value. No findings.

## Axis 5 — dead / duplicate

- Not dead: `reconcile_unknown_effect` and `issue_external_effect_observation`
  have a real production caller,
  `daedalus/runtimes/recovery.py:16-19,251` (`reconcile_runtime_provider_unknown`),
  plus extensive test coverage (`tests/kernel/test_effect_recovery*.py`).
  Grep: `grep -rn "reconcile_unknown_effect\|issue_external_effect_observation" --include=*.py daedalus/ tests/` → 1 production + several test hits.
- **CONFIRMED duplicate helper triplication.** `_secret_bytes` and `_signature`
  (:205-217) are byte-for-byte reimplementations of `daedalus/kernel/effects.py`'s
  `_secret_bytes`/`_signature` (`effects.py:243-253`) — same >=32-byte minimum,
  same HMAC-SHA256 construction, only the `ValueError` message text differs
  ("recovery issuer secret..." vs "effect lease issuer secret..."). A third
  independent copy exists in `runtime_effects.py:86-96` (this slice). Neither
  `effect_recovery.py` nor `runtime_effects.py` imports these from
  `effects.py`, even though `effect_replay.py` and `runtime_effect_replay.py`
  correctly import `_parse_utc` directly from `effects.py`
  (`effect_replay.py:35`, `runtime_effect_replay.py:30`). This is an
  inconsistent reuse pattern within the same package, not a hard defect, but
  it is the exact "same digest/signature helper implemented twice" shape
  Axis 5 asks for. `effects.py` is the stricter/canonical site since it is
  the module the other two demonstrably could import from.
- **CONFIRMED duplicate `_parse_utc`/`_as_utc`.** `effect_recovery.py:220-233`
  reimplements `effects.py:223-236` exactly, including the same narrow
  `except ValueError` (not `AttributeError`) on `datetime.fromisoformat`. This
  copy is behaviorally identical to the original (unlike `runtime_effects.py`'s
  copy — see that dossier for the divergence). No exploitable gap found here:
  every call site passes an already-`_utc_timestamp`-validated string before
  `_parse_utc` runs (:266-269, :303, :378-379), so the untyped-input branch is
  not reachable through this file's own call graph.

## OWNED-FLAG

N/A — this file is not owned by another running packet.

## What I did not cover

- Did not trace which exact `EntrypointSpec` row (of the 108) issues the
  runtime-bound lease that reaches `daedalus/runtimes/recovery.py` in
  production; the Axis 2 "covered transitively" claim is PLAUSIBLE only.
- Did not re-verify `effects.py::EffectLeaseLedger.finish`/`execution_state`
  internals (OWNED-FLAG file, just landed a fix) — treated as a trusted
  dependency for the idempotency analysis above.
- Did not check callers of `daedalus/runtimes/recovery.py` beyond confirming
  it exists and is imported; full upstream reachability to a real
  network/process boundary was out of scope for a 5-file slice.
