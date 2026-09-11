# daedalus/kernel/attempt_spine_reader.py  (245 lines)

Base 54f09753. Static read-only.

## What the file is for

A strict, read-only projection of Attempt lifecycle rows out of the canonical
Event-Store SQLite tables (`intents`/`intent_events`). `read_attempt_intents`
opens the database `mode=ro`, re-derives and checks payload digests, enforces
a strict two-event (`intended` → `completed`/`failed`) lifecycle shape, and
binds record timestamps to their Event-Store transition timestamps within a
skew bound, raising `AttemptStateError` on any deviation instead of returning
partial or best-effort data.

## Axis 1 — docstring truth

### Checked and honest
- `:78` "`SpineLedger` remains the only writer and state-transition
  authority" — this file contains no `INSERT`/`UPDATE`/`execute` of a write
  statement anywhere; every `connection.execute(...)` call (:96-111, :129-135)
  is a `PRAGMA` or `SELECT`. True as a claim about *this file's* behavior.
- `:83-84` "opened with `mode=ro` so inspection cannot create or modify the
  Event Store, even when a caller supplies a missing path" — confirmed at
  `:89-94`: `sqlite3.connect(f"file:{_uri_path(database)}?mode=ro", uri=True,
  ...)`. SQLite's `mode=ro` URI parameter fails to open (raises
  `sqlite3.OperationalError`, a subclass of the caught `sqlite3.DatabaseError`
  at :236) rather than creating a file when the target path is missing —
  this matches the "even when... missing path" clause exactly, and `PRAGMA
  query_only=ON` (:97) is a second, redundant enforcement of the same
  no-write property at the connection level.
- Class-level docstring is absent (no classes in this module); no
  `authenticated`/`guaranteed`/`always`/`never`/`all `/`every`/`cannot`/
  `impossible` claims elsewhere in the file beyond the ones above.

No overclaim found on Axis 1 for this file.

## Axis 2 — effect surface

| site (file:line) | effect | registry row | covered? |
| --- | --- | --- | --- |
| `sqlite3.connect(..., mode=ro, ...)` (`attempt_spine_reader.py:89-94`) | none of the six `Effect` values apply — this is an explicitly read-only connection (`mode=ro` + `PRAGMA query_only=ON`), not `FILESYSTEM_WRITE` | n/a | n/a — no registry row is expected for a read-only site; the brief's effect list (process spawn, network, filesystem *write*, environment reads) does not include read-only SQLite access as an effect requiring a row |

### Notes
- This file performs no filesystem write, no process spawn, no network call,
  and no `os.environ`/`os.getenv` read. The only filesystem interaction is
  the read-only SQLite open. Axis 2 is clean by construction — there is
  nothing here to check against the Effect Registry.

## Axis 3 — unreleased resources

### Checked and honest
- `sqlite3.connect(...)` at `:89` is bound to `connection`, initialized to
  `None` at `:86` before the `try:` at `:87`, and released in
  `finally: if connection is not None: connection.close()` (`:240-242`).
  This is exactly the canonical fixed shape named in the brief
  (`conn = self._connect()` / `try:` / `finally: conn.close()`), and unlike
  the pre-fix sqlite sites elsewhere in the kernel, it does **not** rely on
  a bare `with sqlite3.Connection` (which the brief notes commits but does
  not close). The `finally` covers every exception path inside the `try`
  block, including the re-raised `AttemptStateError` on malformed rows
  (:118-234) and the caught-and-reraised `sqlite3.DatabaseError` (:236-239).
  No leak found; this is the pattern other sites should match, not deviate
  from.

## Axis 4 — validator gaps (W4 class)

### Checked and honest
- The only path-shaped value in this file is the `path` parameter itself
  (`:72`, `str | os.PathLike[str]`), resolved via `Path(path).resolve()`
  (`:88`) and passed straight into the SQLite URI builder `_uri_path`
  (imported from `daedalus.spine.ledger`, not defined here). It is not
  validated by `_identifier` or any weak regex in this file — it is a
  caller-supplied filesystem path used directly, not an identifier that gets
  concatenated into one. `_uri_path` itself is out of my assigned slice
  (`daedalus/spine/ledger.py`), so I did not re-audit its own escaping.
- `effect_key` (`:74`) is used only as a bound SQL parameter (`:109-111`),
  never string-interpolated into a path or query — not a finding per the
  brief's own carve-out ("only ever used as a dict key or logged is not a
  finding"; here it's a bound parameter, an even stronger case).
- No local copy of `_ID_RE`/`_identifier` exists in this file.

## Axis 5 — dead / duplicate

### CONFIRMED
- **Single consumer, exactly as expected — no seam defect.**
  `read_attempt_intents` (`:71`, exported at `:245` via `__all__`) is
  imported and called only by `daedalus/kernel/attempt_ledger.py` — at
  `attempt_ledger.py:46` (import), `:148` (call with `effect_key`), and
  `:423` (call without). Confirmed via
  `grep -rn "read_attempt_intents" daedalus/ tests/ scripts/ tools/ docs/
  apps/`: production hits are exactly those three lines in
  `attempt_ledger.py`, plus stale duplicate copies under
  `apps/web/src-tauri/backend/_internal/daedalus/...` and
  `apps/web/src-tauri/target/{debug,release}/...` (grep-hygiene duplicates
  per the brief, not real additional callers). Test-only references appear
  in `tests/kernel/test_isolated_attempt_lifecycle_review.py`,
  `tests/kernel/test_isolated_attempt_spine_wire_review.py`, and
  `tests/contracts/test_attempt_event_time_mutation_transport.py`
  (import-only). This matches the brief's own statement of the expected
  fact ("used by attempt_ledger.py:46,148,423") — I found no additional
  production consumer and no promised-but-missing reader in the module
  docstring (which names no consumer at all, just "a strict read projection").
- No duplicate regex/validator/digest helper found in this file — it imports
  `_strict_json`, `_timestamp_value`, `_ATTEMPT_EFFECT_PREFIX`,
  `_ATTEMPT_INTENT_KIND` from `attempt_contracts.py` rather than
  reimplementing them, and imports `_uri_path`, `STATE_COMPLETED`,
  `STATE_FAILED`, `STATE_INTENDED`, `Intent` from `daedalus.spine.ledger`
  rather than redefining the state machine.

## What I did not cover

- Did not audit `daedalus/spine/ledger.py::_uri_path` or the `Intent`
  dataclass it constructs (`:209-234`) — both out of my assigned slice.
- Did not audit `attempt_ledger.py`'s own use of the returned `Intent` list
  (out of my slice; it is covered by another worker's dossier).
- Did not run the test suite; consumer/caller counts are static grep results
  only.
