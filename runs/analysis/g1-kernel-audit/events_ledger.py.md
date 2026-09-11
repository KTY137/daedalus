# daedalus/kernel/events/ledger.py  (881 lines)

Base 54f09753. Static read-only. Auditor: parent (W3 slice, subagent cap hit).

## What the file is for

`SpineLedger` is **the** canonical event store — the single sqlite-backed
intent/event spine that Plan §4 invariant 1 requires. It records an intent
before an effect, appends terminal events, and never UPDATEs a recorded intent.
Everything else in the kernel (`AttemptLedger`, promotion, effect leases) is a
facade over this class.

## Axis 1 — docstring truth

This module and `events/envelope.py` are the **honest end** of the repository.
They repeatedly mark their own limits rather than papering over them, and the
audit should say so as clearly as it names defects.

### Checked and TRUE

- `:171` — "picking for a foreign repository can **never** be redirected by
  inherited environment." This is a `never` about a *different* function, so it
  is exactly the kind of cross-module claim that usually rots. It holds:
  `grep -n "DAEDALUS_SPINE_DB" daedalus/spine/picker.py` returns **one** hit,
  `picker.py:486`, and it is inside a docstring explaining the deliberate
  omission — there is no `os.environ` read of that name in the resolver. The
  claim is true *and* correctly attributed: the same docstring openly says
  `default_db_path` itself IS process-global and env-overridable (`:167-168`,
  `:173-174`). Overclaim risk correctly avoided.
- `:322-327` — labelled **"HONEST LIMIT"**: opening a WAL database read-only
  still creates `-wal`/`-shm` sidecars, so "this is not 'touches nothing on
  disk'". Verified against `:329-336`, which opens `mode=ro` and sets
  `query_only=ON`. The module refuses to claim the stronger property it cannot
  deliver. This is the correct handling of the exact hazard that
  `effects.py::_initialize:576-588` documents.
- `:367-372` — a `[MEASURED]` provenance stamp on a concurrency claim: "an
  isolated repro of 4 threads racing `sqlite3.connect(fresh_path)` ->
  `journal_mode=WAL` failed this exact way in **14/40 runs**". A measured number
  with its experiment, not a vibe. Positive evidence.
- `:63` "so it cannot be raced", `:21` "can never be BEHIND reality: every
  effect that happened has a row" — both are scoped to the append-only intent
  discipline and match `record_intent` (`:469-...`) which INSERTs and never
  UPDATEs, and `_txn` (`:454`) which takes `BEGIN IMMEDIATE` up front.

### No overclaims found in this module

I swept for `always|guarantee|never|cannot|impossible|authenticat|verif|enforce|
only|every` (30+ hits) and checked each. Every universal claim I traced is
either true or explicitly scoped/caveated in the same sentence. This module does
not have the defect the audit was commissioned to find.

## Axis 2 — effect surface

| site | effect | registry row | covered |
| --- | --- | --- | --- |
| `:173` `os.environ.get("DAEDALUS_SPINE_DB")` | env read → **determines the DB path** | none | no |
| `:338` `self.path.parent.mkdir(parents=True, exist_ok=True)` | FILESYSTEM_WRITE | none | no |
| `:330` / `:339` `sqlite3.connect(...)` (creates the DB + WAL sidecars) | FILESYSTEM_WRITE | none | no |
| `:342` `_apply_pragmas` → `PRAGMA journal_mode=WAL` (persistent file state) | FILESYSTEM_WRITE | none | no |
| `:343` `_migrate()` → DDL | FILESYSTEM_WRITE | none | no |
| `:454-466` `_txn` → `BEGIN IMMEDIATE`/`COMMIT`, all writes | FILESYSTEM_WRITE | none directly | via facades |

The Effect Registry contains **4** rows targeting `daedalus.kernel.*` out of 108
(`effect_boundary.py:350, 372, 394, 2304`). None targets
`daedalus.kernel.events.ledger`. The registered rows
(`kernel.attempt.begin`/`complete`) declare `guard_contracts=("spine.intent_ledger",)`
and anchor on `record_intent`/`mark_completed` — i.e. the registry treats this
module as the *guard*, not as a guarded entrypoint.

That is a defensible modelling choice for the write methods. It does **not**
cover the constructor: `SpineLedger(path)` creates a directory (`:338`), creates
a database file, and performs a persistent `journal_mode=WAL` transition plus
schema migration (`:342-343`) — durable filesystem effects reachable from any
caller that merely opens the ledger, with no registry row and no guard contract.
Combined with the identical finding for `AttemptLedger.__init__` (see
`attempt_ledger.py.md`), the pattern is: **the kernel's effect inventory covers
methods and misses constructors.**

`os.environ` read at `:173` selects the database path process-globally. It is
documented and intentional (tests/worktrees), but it is an environment-controlled
path with no row in an inventory whose purpose is to enumerate exactly that.

## Axis 3 — unreleased resources

### CONFIRMED — `SpineLedger.__init__` leaks the sqlite connection on a documented, measured failure path

Writable branch, `:338-343`:

```python
self.path.parent.mkdir(parents=True, exist_ok=True)
self._conn = sqlite3.connect(str(self.path), isolation_level=None,
                             check_same_thread=False)   # :339
self._conn.row_factory = sqlite3.Row                    # :341
self._apply_pragmas()                                   # :342
self._migrate()                                         # :343
```

No `try`/`finally`. `_apply_pragmas` (`:345-377`) calls
`_set_journal_mode_wal_with_retry` (`:379-390`), which **re-raises**
`sqlite3.OperationalError` once its deadline passes (`:386-387`). `_migrate`
(`:343`) runs DDL inside `_txn` and can raise `sqlite3.DatabaseError`.

On either raise, `__init__` propagates, the half-built `SpineLedger` is
discarded, and `self._conn` — an **open** sqlite connection — becomes
unreachable garbage. That is precisely the condition
`daedalus/kernel/effects.py::_initialize:576-588` was written to eliminate:
the `-wal`/`-shm` companions exist exactly while a connection is open, so a
GC-finalized connection gives them an indeterminate lifetime, and anything that
stats them (the retention-admission topology scan, per that comment) sees a file
that can vanish between its existence check and its resolve.

Two things make this materially worse than the 13 already-fixed sqlite sites:

1. **The module documents this exact path as measurably reachable.** Its own
   `[MEASURED]` note at `:367-372` records that the `journal_mode=WAL`
   transition on a fresh file failed in **14 of 40 runs** with 4 threads racing
   — "which is exactly what a caller that constructs a fresh
   SpineLedger/Gate-0 writer per concurrent attempt does" (`:363-365`). The
   retry loop reduces that rate but preserves the raise at the deadline. So the
   leak fires under the very concurrency the comment anticipates.
2. **The outer cleanup cannot compensate.**
   `events/durability.py:207-222` wraps construction as
   `ledger = _Gate0OpeningSpineLedger(...)` inside a `try` whose handlers do
   `if "ledger" in locals(): ledger.close()`. When the **constructor** raises,
   the name `ledger` was never bound, `"ledger" in locals()` is `False`, and
   nothing is closed. Both layers miss it.

The fix is the shape already used at `effects.py:588-...`: bind the connection,
then `try: ... except BaseException: self._conn.close(); raise`.

The read-only branch has the same shape at `:330-335`: `sqlite3.connect` at
`:330`, then `PRAGMA busy_timeout` (`:334`) and `PRAGMA query_only=ON` (`:335`)
outside any handler.

### PLAUSIBLE — `_txn` does not roll back a failed COMMIT

`:454-466`:

```python
self._conn.execute("BEGIN IMMEDIATE")
try:
    yield self._conn
except BaseException:
    self._conn.execute("ROLLBACK")
    raise
self._conn.execute("COMMIT")
```

`COMMIT` (`:466`) is outside the `try`. If it raises (disk full, SQLITE_BUSY on
a WAL checkpoint), the transaction stays open on a long-lived connection and
every subsequent `_txn` call starts with `BEGIN IMMEDIATE` inside an already-open
transaction. Secondary: if `ROLLBACK` (`:464`) itself raises, it replaces the
original exception and the caller loses the real cause. Both are low-frequency;
filed PLAUSIBLE.

### Checked and clean

`close()` (`:844-849`) swallows `sqlite3.Error` deliberately, which is correct
for a close path. All read methods hold `self._lock` via `with` (`:442`, `:460`,
`:628`, `:652`, `:686`, `:723`, `:735`, `:775`, `:795`, `:815`, `:828`) —
`with` on an `RLock` does release on the exception path.

## Axis 4 — validator gaps (W4 class)

Not a `_identifier` consumer. The one untrusted-input-to-path flow is
`DAEDALUS_SPINE_DB` → `Path(env)` (`:173-174`), which is unvalidated but is an
operator-controlled environment variable, not candidate-reachable data — out of
the W4 threat class. `_uri_path` (`:154-161`) correctly escapes `?` and `#` and
converts backslashes for the SQLite `file:` URI, with the Windows rationale
stated; that is a *good* sibling of the validator work, not a gap.

`record_intent` uses bound parameters throughout (`:492-...`); no SQL string
interpolation of caller data. The one f-string into SQL is
`f"PRAGMA busy_timeout={self.busy_timeout_ms}"` (`:350`, `:334`), where the
value passed through `int()` at `:308`. Safe.

## Axis 5 — dead / duplicate

No dead code identified. `effect_key` is deliberately **not** unique-constrained
(`:474-477`) — documented as intentional so a retried intent records both
attempts. Worth noting because `AttemptLedger` adds a *partial* unique index over
the same column for its own kind (`attempt_ledger.py:99-104`); the two are
consistent (one general, one kind-scoped) but the interaction is not documented
in either place.

## What I did not cover

`_migrate` / `_add_missing_columns` schema-evolution correctness, and the query
methods `:628-800` beyond their locking discipline.
