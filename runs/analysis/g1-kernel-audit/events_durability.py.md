# daedalus/kernel/events/durability.py  (234 lines)

Base 54f09753. Static read-only. Auditor: parent (W3 slice, subagent cap hit).

## What the file is for

Applies and *reads back* the Gate-0 durability profile (`journal_mode=wal`,
`synchronous=FULL`, `busy_timeout>=30000`, `foreign_keys=ON`) on the canonical
`SpineLedger` connection, and owns `open_gate0_spine_writer`, the factory that
opens a writer already at `synchronous=FULL` before the generic schema migration
runs.

## Axis 1 — docstring truth

### Checked and TRUE

- `:6-8` "This module does not introduce another ledger or another state
  authority. It hardens the exact existing writable `SpineLedger` connection and
  reads the settings back from SQLite." Verified: `enforce_gate0_durability`
  reaches into `ledger._conn` / `ledger._lock` (`:153-154`) rather than opening
  anything, and `_Gate0OpeningSpineLedger` (`:52`) is a subclass overriding only
  `_apply_pragmas` (`:60-62`). No second connection, no second file. Consistent
  with Plan §4 invariant 1.
- `:135-141` "`journal_mode` is intentionally not changed here… This profile
  **refuses** a non-WAL file instead of silently rewriting it." Verified at
  `:162-166`: reads status, and if `before.journal_mode != "wal"` raises rather
  than issuing a `PRAGMA journal_mode` write. The refusal is real, and refusing
  rather than silently upgrading is the correct fail-closed choice.
- `:139-141` "Apply and readback happen **atomically** under the ledger's exact
  connection lock; no nested public-lock call or replacement connection is
  used." Verified: `with lock:` at `:161` brackets both the three `PRAGMA` writes
  (`:167-172`) and the `_read_connection_status` readback (`:173`), and the lock
  is the ledger's own `_lock` (`:154`), an `RLock`. Claim holds.
- The readback discipline itself is the strongest property here: `_status`
  (`:65-95`) computes `satisfied` from values **read back out of SQLite**
  (`:97-110`), not from what was requested. `ledger.pragmas()` carries the
  matching note ("not echoed from what we asked for. A pragma that silently
  failed to apply is exactly the failure worth surfacing",
  `events/ledger.py:809-812`). This is a genuine instrument-trust design and
  deserves to be named as positive evidence.

### No overclaims found

No `always` / `guaranteed` / `authenticated` in this module. The one `cannot`
(`:28`, "The canonical Event Store cannot satisfy the Gate-0 writer profile") is
an exception docstring describing a refusal, not a promise.

## Axis 2 — effect surface

| site | effect | registry row | covered |
| --- | --- | --- | --- |
| `:207` `_Gate0OpeningSpineLedger(...)` → `SpineLedger.__init__` → mkdir + connect + WAL + migrate | FILESYSTEM_WRITE | none | **no** |
| `:167-172` `PRAGMA synchronous/busy_timeout/foreign_keys` | connection-local | n/a | n/a |
| `:61` `PRAGMA synchronous=FULL` | connection-local | n/a | n/a |

`import os` (`:14`) is used only for the `os.PathLike` annotation at `:190`; no
`os.environ` read in this module. No subprocess, no network.

`open_gate0_spine_writer` is the Gate-0 *production writer factory* — the
function whose whole purpose is to be the admitted door to the canonical event
store — and it has no Effect Registry row. See `events_ledger.py.md` Axis 2 for
the general finding (the kernel's effect inventory covers methods and misses
constructors/factories).

## Axis 3 — unreleased resources

### Checked and clean — and this module is why a sibling finding was refuted

`open_gate0_spine_writer` (`:188-224`) closes its own ledger on **every** failure
path: `except Gate0DurabilityError:` → `ledger.close()` (`:216-218`), and
`except (SpineError, sqlite3.Error, OSError, ValueError, TypeError)` →
`ledger.close()` (`:219-223`). It also normalises that whole error set into
`Gate0DurabilityError`, which is what makes the narrow handler in
`AttemptLedger.__init__:74` sufficient — I initially filed that as a CONFIRMED
leak and had to retract it after reading this file. Recorded in
`attempt_ledger.py.md`.

`enforce_gate0_durability` acquires no resource of its own; it borrows the
ledger's lock via `with` (`:161`), which releases on the exception path.

### CONFIRMED — the `"ledger" in locals()` guard cannot fire for a constructor failure

`:216-218` and `:220-222` both read:

```python
if "ledger" in locals():
    ledger.close()
```

The only statement that can bind `ledger` is the assignment at `:207`. If
`_Gate0OpeningSpineLedger(...)` — i.e. `SpineLedger.__init__` — raises, the
assignment never completes, `ledger` is unbound, `"ledger" in locals()` is
`False`, and nothing is closed.

That matters because `SpineLedger.__init__` **does** leak an open connection when
it raises: it calls `sqlite3.connect` at `events/ledger.py:339` and then
`_apply_pragmas()` / `_migrate()` at `:342-343` with no `try`/`finally` — and the
module's own `[MEASURED]` note (`events/ledger.py:367-372`) records the
`journal_mode=WAL` transition failing in 14/40 runs under 4-way contention on a
fresh path. So the two layers compose into an unclosed connection with
indeterminate-lifetime `-wal`/`-shm` companions.

This is the *same defect* as the primary `events_ledger.py` finding, seen from
the caller's side. I am recording it here because the `locals()` idiom reads as
if it covers construction failure and does not — a reviewer checking only this
file would conclude the factory is leak-safe. The correct fix is in
`SpineLedger.__init__`; a defensive fix here is not possible, since there is no
object to close.

## Axis 4 — validator gaps (W4 class)

Not applicable. No `_identifier` use, no path construction; `path` is passed
straight through to `SpineLedger` (`:206`). `busy_timeout_ms` is coerced through
`int()` inside a `try` at `:198-201` before reaching an f-string PRAGMA in the
parent class — correct.

## Axis 5 — dead / duplicate

- `inspect_gate0_durability` (`:110-131`) vs `_read_connection_status` (`:97-108`):
  two readback paths for the same four pragmas. They are **not** redundant —
  the public one goes through `ledger.pragmas()` (taking the ledger's public
  lock), the private one reads the raw connection while the caller already holds
  that lock (`:161-173`). Taking the public lock there would be the "nested
  public-lock call" the docstring at `:139-140` says it avoids. Deliberate and
  correctly explained; **not** a duplicate-code finding. Recording it because it
  looks like one on a fast read.
- `_Gate0OpeningSpineLedger` (`:52`) is private and used once (`:207`). Not dead.

## What I did not cover

Whether `synchronous=FULL` is actually preserved across the generic migration in
`SpineLedger._migrate` — the factory's stated reason for existing (`:8-10`) is
that it must be, and `open_gate0_spine_writer` does re-check via
`inspect_gate0_durability` at `:209`, but I did not read `_migrate`.
