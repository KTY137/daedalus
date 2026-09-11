# daedalus/kernel/promotion_execution_reader.py  (303 lines)

Base 54f09753. Static read-only.

## What the file is for

Strict, read-only SQLite projection of the `promotion.execution` slice of the
canonical `intents`/`intent_events` tables that `SpineLedger` owns. It opens
its own `mode=ro` connection (never the writer), verifies the retained
unique-partial-index definition has not been weakened or substituted, and
rejects duplicate JSON keys, non-finite constants, noncanonical byte
sequences, digest mismatches, and malformed event sequences before handing
rows back as `Intent` objects to `promotion_execution.py`.

## Axis 1 — docstring truth

### CONFIRMED
None.

### PLAUSIBLE
None.

### Checked and honest
- `:1-6` "`SpineLedger` remains the sole writer and transition authority.
  This reader keeps raw SQLite text long enough to reject duplicate JSON
  keys, non-finite constants, noncanonical bytes, payload-digest
  substitution, schema substitution and invalid event sequences before
  higher-level contracts are hydrated." — verified each clause against code:
  - duplicate JSON keys: `_reject_duplicate_pairs` used as
    `object_pairs_hook` (`:41-47,70`).
  - non-finite constants: `_reject_constant` used as `parse_constant`
    (`:50-51,71`) — rejects `NaN`/`Infinity`/`-Infinity` before they become
    Python floats.
  - noncanonical bytes: `canonical_json(value)` round-trip equality check,
    `if rendered != raw: raise` (`:77-82`).
  - payload-digest substitution: `expected_payload_sha =
    hashlib.sha256(raw_payload...)`; `if str(row["payload_sha"]) !=
    expected_payload_sha: raise` (`:184-190`).
  - schema substitution: this refers to the **SQLite index schema**, not a
    JSON `"schema"` field — `_verify_index_shape` (`:94-134`) compares the
    live `sqlite_master.sql` text for the named index against the exact
    expected DDL (`_normalized_sql` equality, `:104-107`), and separately
    checks `PRAGMA index_list`/`PRAGMA index_info` for uniqueness,
    partial-ness, origin `'c'` (explicit `CREATE INDEX`, not an
    autoindex), and that it binds exactly the `effect_key` column
    (`:109-134`) — refusing "a same-named but weaker or differently scoped
    index," per its own docstring (`:94-95`). Called first, before any row
    is read (`:161`), matching "before higher-level contracts are hydrated."
  - invalid event sequences: `if not events: raise` (`:199-202`); `if
    len(events) > 2 or ...state != STATE_INTENDED: raise` (`:203-206`);
    exhaustive state-shape checks for `STATE_COMPLETED`/`STATE_FAILED`
    (`:234-263`) with an `else: raise` for any other state (`:260-263`).
  All six sub-claims hold.
- `:142-148` "An exact `effect_key` query still returns a foreign-kind
  collision so the caller can refuse it. An unscoped query includes both the
  canonical kind and the reserved effect-key prefix, preventing a malformed
  row from hiding from pending reconciliation merely by changing one of
  those columns." — confirmed: the effect-key-scoped branch (`:172-175`)
  selects by `effect_key = ?` alone (no `kind` filter), so a row with a
  matching `effect_key` but a different `kind` is still returned (and
  `promotion_execution.py:_intent_for` then raises on the kind mismatch,
  `:708-711` in that file); the unscoped branch (`:162-170`) selects `WHERE
  kind = ? OR effect_key LIKE ?`, an OR of both conditions, so a row that
  spoofed one column but not the other is still caught by the `OR`.

## Axis 2 — effect surface

| site (file:line) | effect | registry row | covered? |
|---|---|---|---|
| `sqlite3.connect(f"file:{...}?mode=ro", uri=True, ...)` `:152-160` | FILESYSTEM read (real path, URI-form, explicit `mode=ro` + `PRAGMA query_only=ON` at `:159-160`) | none targets `daedalus.kernel.promotion_execution_reader....` | **no** |

### Notes
This is the one sqlite site in my slice that is genuinely read-only in
intent and in enforcement: the connection URI forces `mode=ro` and the code
additionally sets `PRAGMA query_only=ON` immediately after connecting,
before any query runs (`:159-160`), which makes even an accidental write
statement fail at the SQLite layer rather than relying on `mode=ro` alone.
No row in `effect_boundary.py` targets this file or `promotion_execution.py`
(scoped grep for `promotion_execution` in that file returns zero hits, and
the brief's measured fact confirms only 4 kernel rows exist, none here). Per
Axis 5, this file's only caller (`promotion_execution.py`) also has zero
production callers, so the gap is unregistered *and* currently unreachable —
consistent, not a live unguarded write surface.

## Axis 3 — unreleased resources

No findings — this is the exemplary, brief-cited-correct shape.
```python
connection: sqlite3.Connection | None = None
try:
    ...
    connection = sqlite3.connect(...)
    ...
    return projected
except PromotionExecutionReadError:
    raise
except sqlite3.DatabaseError as exc:
    raise PromotionExecutionReadError(...) from exc
finally:
    if connection is not None:
        connection.close()
```
(`:149-300`). The connection variable is declared `None` before the `try`,
assigned only on success, and `finally` closes it whenever it is non-`None`
— on the success path, on a caught `PromotionExecutionReadError` raised from
inside the function body (e.g. from `_verify_index_shape` or a strict-JSON
helper), on a caught `sqlite3.DatabaseError`, and on any other exception that
propagates uncaught (the `finally` still runs). This is precisely the "the
fixed shape is `conn = self._connect()` / `try:` / `finally: conn.close()`"
pattern the brief names as canonical — no gap.

## Axis 4 — validator gaps (W4 class)

No findings.
- `path` (the database file path argument) is resolved via
  `Path(path).resolve()` (`:151`) and passed through `_uri_path` (imported
  from `daedalus.spine.ledger`, out of my slice) to build the `sqlite3`
  connection URI — this is an operator-supplied database location, not a
  value derived from `_identifier`/a weak regex, so it is out of the W4
  threat shape this axis targets (same carve-out the sibling
  `promotion_trust_root.py.md` dossier applied to its own `repo_root`
  parameter).
- No other value in this file reaches path construction. `effect_key` is
  used only as a bound SQL parameter (`:163-175`), never string-built into
  SQL text or a filesystem path.

## Axis 5 — dead / duplicate

### CONFIRMED
- **`read_promotion_execution_intents` (`:137-303`) has exactly one
  production caller, and that caller has zero production callers of its
  own.** `grep -rn "read_promotion_execution_intents(" --include=*.py
  daedalus/ tests/ scripts/ tools/ docs/` shows: this file's own `def`
  (`:137`); one production call from `daedalus/kernel/promotion_execution.py:
  696-699` (`PromotionExecutionLedger._read_intents`); and one test
  reference confirming the call exists via source inspection
  (`tests/kernel/test_promotion_execution_reader_review.py:66`). Per the
  `promotion_execution.py.md` dossier, `PromotionExecutionLedger` itself has
  zero production callers anywhere. So this reader is correctly wired to its
  one intended reader (not an unwired producer — the seam is one level up,
  at `PromotionExecutionLedger`'s own callers, not here).
- No duplicate regex/validator/digest helper found in this file: `_strict_json`,
  `_verify_index_shape`, and `_normalized_sql` are all specific to this
  file's SQLite-projection concern and have no equivalent elsewhere in the
  four files I audited (`promotion.py`, `promotion_execution.py`,
  `promotion_fingerprint.py`) — checked, not found.

### PLAUSIBLE
None.

## OWNED-FLAG

Not applicable — this file is not `offload_lease.py`, the flagged
`attempt_execution.py` string-evidence sites, or `effects.py`.

## What I did not cover

Did not execute or import any code (static read-only). Did not audit
`daedalus/spine/ledger.py`'s `Intent`/`_uri_path` definitions beyond
confirming they are imported and used as declared — out of my assigned
slice. Did not independently verify SQLite's actual runtime behavior for
`PRAGMA query_only=ON` against a crafted malicious statement (no code
execution permitted under the hard rules).
