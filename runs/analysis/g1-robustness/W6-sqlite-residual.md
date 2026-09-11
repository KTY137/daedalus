# W6 — SQLite residual defect sweep (post 13-site fix)

- **Scope**: `daedalus/` and `tools/` only (Python). `tests/` is explicitly
  out of scope (owned by a parallel packet covering 39 test-side sqlite
  sites) and was not read for this report. `apps/` out of scope.
- **Repo**: `C:/Users/Administrator/daedalus`
- **Commit measured against**: `2233a148b6423bd5085ab189e1bc9b3f97613191`
  (local `main`, per the SubagentStart banner; the task brief cited
  `54f09753` as the branch-start commit — both are on the same history,
  no sqlite-relevant files differ between them for this sweep).
- **Method**: static read only. Grepped `sqlite3\.connect\(`, `with
  sqlite3\.connect`, `\._connect\(\)`, `executescript`, `\.cursor\(\)`,
  `journal_mode`, `synchronous`, `busy_timeout`, `foreign_keys`,
  `isolation_level`, `check_same_thread`, `finally`, `\.close\(\)` across
  `daedalus/` and `tools/`, then read every hit's enclosing function and,
  where a file exposes a private `_connect()`/`_open_sqlite()` helper
  called from multiple methods, read **every** call site of that helper
  (not just the one the grep for the literal `sqlite3.connect(` landed
  on), plus external cross-module callers of a private `_connect()`.
- **Patterns searched**: raw connect-site enumeration; deterministic
  close (with/try-finally/explicit) vs GC-dependent; open cursors kept
  across a boundary; `executescript()` inside a transaction; pragma
  presence/absence per connect site; `isolation_level=None` multi-statement
  atomicity; `check_same_thread=False` / cross-thread connections; WAL
  companion (`-wal`/`-shm`) lifetime and who stats them.

## Connect-site enumeration (raw `sqlite3.connect(` occurrences)

20 raw call sites total: 19 in `daedalus/`, 1 in `tools/`. Five of them are
private `_connect()`/`_open_sqlite()` **factories** called from multiple
methods in the same file (or, in one case, from another module) — each of
those call sites was individually verified below the table, not just the
factory definition.

| # | File:line | DB / purpose | Closed deterministically? | Notes |
|---|---|---|---|---|
| 1 | `daedalus/health.py:812` | `vector_index.db`, ro probe | **Yes** — `try/finally: con.close()` | part of health surface, not one of the 13 |
| 2 | `daedalus/eval/mutate.py:130` | `.coverage` (coverage.py's own db), ro | **No on the exception path** | see Finding A |
| 3 | `daedalus/memory/projection_worker.py:293` (`_ro_connect`) | `vector_index.db`, ro | **Yes** — sole caller wraps in `try/finally: conn.close()` (line 682-684) | |
| 4 | `daedalus/memory/embeddings.py:693` | `vector_index.db`, persistent `self._conn` | **Yes, by discipline** — `EventVectorStore.close()` exists and all 5 production constructors (`context_plan.py:326`, `gui_catalogue.py:791`, `interfaces/http/read.py:351`, `memory/__init__.py:125`, `memory/projection_worker.py:656`) wrap use in `try/finally: store.close()` | long-lived handle by design, not a leak |
| 5 | `daedalus/kernel/approvals.py:443` (`_connect`, 4 call sites: 465, 535, 653, 738) | owner-approval consumptions ledger | **Yes**, all 4 | one of the fixed 13's siblings — re-verified independently, all 4 call sites close |
| 6 | `daedalus/kernel/attempt_spine_reader.py:89` | spine ledger, ro | **Yes** — `connection: ... = None` + `finally: connection.close()` (line 240-242) | |
| 7 | `daedalus/kernel/effect_recovery.py:523` (`_persisted_terminal`) | effect-lease ledger, ro | **Yes** — `try/finally: connection.close()` | fixed site; close is fine — **but see Finding B (pragmas)** |
| 8 | `daedalus/kernel/effects.py:568` (`_connect`, 6 call sites: 588, 654, 707, 764, 896, 942) | effect-lease ledger, rw | **Yes**, all 6 | fixed site — re-verified independently, all 6 close |
| 9 | `daedalus/kernel/effect_replay.py:366` | effect-lease ledger, ro | **Yes** — `finally: connection.close()` (line 573-575) | |
| 10 | `daedalus/kernel/offload_lease.py:2204` | attempt/intent ledger, ro | **Yes** — `with contextlib.closing(...)` | already closes; note the `timeout=5` pragma choice (Finding C) |
| 11 | `daedalus/kernel/events/ledger.py:330` and `:339` (`SpineLedger.__init__`, persistent `self._conn`) | `spine.sqlite3`, ro/rw | **Yes, by discipline** — `close()`, `__enter__`/`__exit__`; every production caller checked (`health.py`, `web_api.py`, `token_monitor.py`, `spine/picker.py`, `conversation.py`, `progress_sources.py` x2, `tools/bootstrap_receipt.py`, `kernel/events/durability.py`'s `open_gate0_spine_writer`) closes on both success and error paths | |
| 12 | `daedalus/kernel/promotion_execution_reader.py:152` | promotion-execution ledger, ro | **Yes** — `finally: connection.close()` (line 298-300) | |
| 13 | `daedalus/structcore/cache.py:269` | per-repo `idx-*.sqlite` cache | **Yes** — explicit `close()` called both in the constructor's except-handler and by the sole production caller (`structcore/index.py:500`, `finally: cache.close()`) | already carries its own close-vs-discard comment |
| 14 | `daedalus/runtimes/provider_target_receipt_ledger.py:293` (`_read_intent`) | canonical spine, ro | **Yes** — `finally: connection.close()` (line 403-405) | |
| 15 | `daedalus/runtimes/provider_observation_store.py:294` (`_open_sqlite`, 4 call sites: 477, 523, 657, 681) | provider-observation binding store | **Yes**, all 4 | includes a class (`PreprovisionedProviderObservationBindingLedger`) whose sole `self._connect()`/`self._connect_read_only()` external use (`load()`, line 711) closes in `finally` |
| 16 | `daedalus/runtimes/provider_observation.py:553` (`_connect`, 3 call sites: 573, 807, 857) | provider-observation bindings (legacy/preprovisioned), rw, no WAL | **Yes**, all 3 | fixed site — re-verified; **one external caller**, `daedalus/runtimes/broker.py:373` (`ledger._connect()`), also closes in `finally` (line 456-457) |
| 17 | `daedalus/runtimes/trust_store.py:253` (`_connect`, 5 call sites: 275, 472, 537, 606, 643) | runtime-trust ledger | **Yes**, all 5 | fixed site — re-verified independently, all 5 close |
| 18 | `tools/system_check.py:236` (`read_intents`) | harness temp `spine.sqlite3`, ro | **No on the exception path** | see Finding A |

**No `with sqlite3.connect(...)` survives in `daedalus/` or `tools/`.** A
targeted grep for the literal pattern across the whole repo returns matches
only under `tests/` (38 hits, out of scope per the brief) and inside
docstrings/comments/`scripts/*.py` code-generation string literals that
*describe* the mutation harness, not live production code. **The 13-site
fix was exhaustive for this pattern in the product tree** — this is a
positive universal claim, so the full 20-site enumerated set above is the
evidence for it, not a recollection.

**GC-dependent survivors: 2 of 20** (`eval/mutate.py`, `tools/system_check.py`
— both share the identical shape: close on the happy path, never closed
if an exception fires between `connect()` and the pre-planned `close()`
call). Everything else closes deterministically on every exit path,
including exception paths, including 15 call sites (approvals.py x4,
effects.py x6, provider_observation.py x3, trust_store.py x5,
provider_observation_store.py x4 via its factory) that were **not** named
in the 13-site citation but sit behind the exact same `_connect()` helper
pattern — all independently verified clean.

## Cursors held open (finding class #2)

**No matches.** There are zero `.cursor()` calls anywhere in `daedalus/`
or `tools/` — every read goes through `connection.execute(...)` directly.
The one place that iterates a query result lazily instead of calling
`.fetchall()` — `eval/mutate.py:133`, `for fid, numbits in
con.execute(...)` — consumes the iterator to exhaustion inside the same
function before `close()`, so it is not "held open" in the WAL-blocking
sense; its only defect is the exception-path leak already captured in
Finding A. No generator function anywhere yields rows from a live cursor
across a call boundary (checked: no `Iterator`/`Generator`-typed function
in `daedalus/` wraps a `sqlite3` read).

## `executescript` inside a transaction (finding class #3)

**No matches.** `executescript()` is not called anywhere in `daedalus/`
or `tools/`. Finding class #3 does not apply to this scope.

## Pragma table (per connect site)

| Store (file) | journal_mode | synchronous | busy_timeout | foreign_keys | isolation_level | connect `timeout=` |
|---|---|---|---|---|---|---|
| spine ledger writer (`kernel/events/ledger.py`, rw branch) | WAL (with retry loop) | NORMAL | 30000 (set first) | ON | None | default (5.0, superseded by pragma) |
| spine ledger reader (`kernel/events/ledger.py`, `read_only=True`) | (inherits WAL from file) | *unset* | 30000 | *unset* | None | default |
| Gate-0 writer (`kernel/events/durability.py::_Gate0OpeningSpineLedger`) | WAL | **FULL** (override) | 30000 | ON | None | default |
| spine reader (`kernel/attempt_spine_reader.py`) | (inherits) | *unset* | 30000 | *unset* | None | 30.0 |
| spine reader (`kernel/promotion_execution_reader.py`) | (inherits) | *unset* | 30000 | *unset* | None | 30.0 |
| spine reader (`kernel/offload_lease.py:2204`, issuer guard) | (inherits) | *unset* | **unset — relies only on `timeout=5`** | *unset* | default (not None) | **5** |
| spine reader (`tools/bootstrap_receipt.py` → writer, not reader) | n/a — full `SpineLedger()` | NORMAL | 30000 | ON | None | default |
| harness spine reader (`tools/system_check.py:236`) | (inherits) | *unset* | **unset — relies only on default `timeout=5.0`** | *unset* | default (not None) | default (5.0) |
| effect-lease ledger writer (`kernel/effects.py::_connect`) | WAL | FULL | 30000 | ON | None | 30 |
| effect-lease ledger reader A (`kernel/effect_replay.py`) | (inherits) | *unset* | 30000 | *unset* | None | 30.0 |
| effect-lease ledger reader B (`kernel/effect_recovery.py::_persisted_terminal`) | (inherits) | *unset* | **unset — relies only on default `timeout=5.0`** | *unset* | default (not None) | default (5.0) |
| owner-approval ledger (`kernel/approvals.py::_connect`) | WAL | FULL | 30000 | ON | None | 30 |
| runtime-trust ledger (`runtimes/trust_store.py::_connect`) | WAL | FULL | 30000 | ON | None | 30 |
| provider-target-receipt reader (`runtimes/provider_target_receipt_ledger.py::_read_intent`) | (inherits) | *unset* | 30000 | *unset* | None | 30.0 |
| provider-observation bindings, legacy (`runtimes/provider_observation.py::_connect`) | **default (rollback journal, not WAL — deliberate, documented)** | default | *unset* | *unset* | default (not None) | default (5.0) |
| provider-observation store (`runtimes/provider_observation_store.py::_open_sqlite`) | default (rollback journal, not WAL) | default | *unset* | *unset* | **None** | 30 |
| vector index (`memory/embeddings.py`, `EventVectorStore.__init__`) | **default (rollback journal, not WAL — undocumented)** | default | *unset* | ON | default (not None) | default (5.0) |
| vector index reader (`health.py:812`, `memory/projection_worker.py:293`) | (inherits) | *unset* | *unset* | *unset* | default (not None) | default (5.0) |
| structcore cache (`structcore/cache.py`) | default | default | *unset* | *unset* | default (not None) | default (5.0) |
| `.coverage` reader (`eval/mutate.py`) | n/a, foreign file | n/a | n/a | n/a | n/a | default (5.0) |

### Pragma disagreements found

**Finding B (the significant one) — same database, 6x busy-wait gap
between sibling readers.**
`kernel/effect_recovery.py::_persisted_terminal` (line 509-535) and
`kernel/effect_replay.py::_project_persisted_execution` (line 351-410)
both read the identical file — `EffectLeaseLedger.path`, the same db
`kernel/effects.py::EffectLeaseLedger._connect()` writes with
`busy_timeout=30000` (30s) and `journal_mode=WAL`. `effect_replay.py`'s
reader matches that discipline explicitly: `timeout=30.0` at connect PLUS
`PRAGMA busy_timeout=30000` redundantly. `effect_recovery.py`'s reader
sets **no pragmas at all** — no `PRAGMA busy_timeout`, no `PRAGMA
query_only`, no `isolation_level=None`, and no `timeout=` override, so it
falls back to Python's `sqlite3.connect` default of `timeout=5.0`. Under
write contention on the effect-lease ledger — which is exactly the
condition `effect_recovery` exists to run under, since it is the crash-
/unknown-outcome reconciliation path — this reader gives up and raises
`sqlite3.OperationalError: database is locked` roughly 6x sooner than its
sibling reader on the same file, and that error surfaces as
`EffectReplayProjectionError`/similar rather than the caller getting the
same wait discipline everywhere else in this ledger family enjoys. This
is a live, in-scope, un-annotated inconsistency, not a hypothetical.

**Finding C (weaker, likely-intentional) — deliberately short timeout at
an issuance guard.**
`kernel/offload_lease.py:2204` reads the same attempt/spine ledger the
canonical `SpineLedger` writes with `busy_timeout=30000`, but connects
with an explicit `timeout=5`. The surrounding docstring frames this as a
capability-issuance guard decision ("READ-ONLY BY CONSTRUCTION"), and a
5s cap on a synchronous issuance check is plausibly deliberate (fail fast
rather than block the issuer for 30s). Flagging it because it is a
concrete, measured disagreement on the same DB family, but it reads as
designed rather than an oversight — lower severity than Finding B.

**Finding D (hygiene gap, no WAL) — `EventVectorStore` sets none of
journal_mode/synchronous/busy_timeout.**
`memory/embeddings.py`'s `EventVectorStore.__init__` (line 693-696) opens
`vector_index.db` with bare `sqlite3.connect(self.db_path)` and only ever
sets `PRAGMA foreign_keys = ON`. It never requests WAL, never sets
`synchronous`, never sets `busy_timeout` — it relies solely on the Python
default 5-second connect timeout. Every reader of the same file
(`health.py:812`, `memory/projection_worker.py:293`) inherits that
default-rollback-journal posture, so there's no reader/writer *pragma*
mismatch here (both sides agree on "nothing set"), but it means the
vector index — read concurrently by the HTTP search endpoint
(`interfaces/http/read.py`), the GUI catalogue, `context_plan.py`, and
written by the projection worker and `memory/__init__.py`'s best-effort
ingest bridge — has no WAL reader/writer concurrency story at all: a
writer holds an exclusive rollback-journal lock for the duration of its
transaction and any concurrent reader/writer past the 5s default waits
gets "database is locked". This is a design gap relative to every other
store in the family (all of which chose WAL deliberately, with comments
explaining why), not a regression from the 13-site fix — this file was
never part of that patch and its rollback-journal choice long predates it.

**No other same-DB, different-connection pragma disagreements found.**
The owner-approval, runtime-trust, effect-lease-writer and canonical-spine
families are internally consistent (identical `_connect()`/`_apply_pragmas`
bodies reused by every write path in the same file); their read-only
siblings that DO set pragmas (`attempt_spine_reader.py`,
`promotion_execution_reader.py`, `provider_target_receipt_ledger.py`,
`effect_replay.py`) all agree on `busy_timeout=30000` +
`PRAGMA query_only=ON` + `isolation_level=None` + `timeout=30.0`. Only
`effect_recovery.py`'s reader (Finding B) and `offload_lease.py`'s guard
reader (Finding C) and the two harness-adjacent readers
(`tools/system_check.py`, and by extension `eval/mutate.py` against a
foreign coverage.py file) deviate.

## `isolation_level=None` multi-statement atomicity (finding class #5)

Every `isolation_level=None` (autocommit) connection in scope drives its
own transaction **by hand** with explicit `BEGIN IMMEDIATE` / `COMMIT` /
`ROLLBACK` around every multi-statement logical unit — this was exactly
the discipline the 13-site fix's comments call out repeatedly ("this DDL
already autocommits", "every exit path below commits or rolls back by
hand"). Checked every `BEGIN IMMEDIATE` site in `effects.py`,
`approvals.py`, `trust_store.py`, `provider_observation.py`,
`kernel/events/ledger.py::_txn`, `provider_observation_store.py`'s
`initialize_provider_observation_binding_store` (line 524 `BEGIN
IMMEDIATE` ... line 534 `commit()`) — all bracket their multi-statement
work with an explicit transaction boundary and roll back on every raised
exception. **No finding here**: no multi-statement logical unit under
`isolation_level=None` was found running without an explicit `BEGIN`.

## Cross-process/thread (finding class #6)

`check_same_thread=False` appears in exactly one place:
`kernel/events/ledger.py:331` and `:339` (`SpineLedger`'s read-only and
read-write branches). Both are documented and guarded: "One connection per
instance ... plus an internal lock lets a single instance be shared across
threads ... without two statements interleaving on one connection." Every
public method that touches `self._conn` on this class takes `self._lock`
first (`pragmas()`, `_txn()`, etc.) — confirmed by reading those methods.
No other file sets `check_same_thread=False`, and no connection anywhere
in scope is stored on `self` and then handed to a thread pool without an
owning lock. **No finding here.**

## What a kill leaves (finding class #7)

| DB | WAL? | On SIGKILL mid-transaction | Anything stats the WAL companions? |
|---|---|---|---|
| `spine.sqlite3` (canonical Event Store, `kernel/events/ledger.py`) | Yes | Hot `-wal`, replayed automatically on next open (SQLite's own recovery); `BEGIN IMMEDIATE`/explicit commit-or-rollback means no half-written row is ever visible before COMMIT | Yes — this is exactly the retention-admission topology scan the 13-site fix was written to protect (per the fix's own comments in `effects.py`/`approvals.py`/`trust_store.py`) |
| effect-lease ledger (`kernel/effects.py`) | Yes | Same as above | Yes, same scan family |
| owner-approval ledger (`kernel/approvals.py`) | Yes | Same as above | Yes, same scan family |
| runtime-trust ledger (`runtimes/trust_store.py`) | Yes | Same as above | Yes, same scan family |
| provider-observation bindings, legacy (`runtimes/provider_observation.py`) | **No** (deliberate, documented) | Hot rollback journal (`-journal`), replayed on next open; no `-wal` marker ever exists | Not applicable — no WAL sidecar to stat |
| provider-observation store (`runtimes/provider_observation_store.py`) | No | Same — rollback journal; this store additionally uses a temp-file + `os.link()` atomic-publish pattern (`initialize_provider_observation_binding_store`), so a kill before the `os.link()` leaves only an orphaned temp file beside the real store, never a half-published store | Not applicable |
| vector index (`memory/embeddings.py`) | No (Finding D) | Hot rollback journal | Not applicable, but see Finding D for the concurrency gap this choice creates independent of kill safety |
| structcore per-repo cache (`structcore/cache.py`) | No | Hot rollback journal; this cache is explicitly an optimization layer ("degrading to recompute is the intended behavior") so a corrupt/half-written cache is self-healing by design — a corrupt DB just misses on next run | Not applicable |

No dedicated WAL-checkpoint or WAL-truncation call was found anywhere in
`daedalus/` or `tools/` (no `PRAGMA wal_checkpoint` grep hit) — WAL growth
is left entirely to SQLite's automatic checkpoint (default: after ~1000
pages written), which is standard and not itself a defect, but it means
nothing in this repo actively bounds `-wal` size; the only guard against
unbounded growth is that every WAL-mode store here also closes its
connections deterministically (confirmed above), so the auto-checkpoint
that fires on close/every-Nth-commit is not starved by a leaked reader.

## Findings

### Finding A — `eval/mutate.py:130` and `tools/system_check.py:236`: connection leaks on the non-declared exception path

`path/daedalus/eval/mutate.py:130-148`:
```python
try:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    files = {r[0]: r[1] for r in con.execute("select id, path from file")}
    out: dict = {}
    for fid, numbits in con.execute("select file_id, numbits from line_bits"):
        ...
    con.close()
    return out
except (sqlite3.Error, OSError):
    continue
return {}
```
`path/tools/system_check.py:230-244`:
```python
def read_intents(db: Path) -> list:
    if not Path(db).exists():
        return []
    import sqlite3
    try:
        uri = "file:" + str(db).replace("\\", "/") + "?mode=ro"
        con = sqlite3.connect(uri, uri=True)
        rows = con.execute(...).fetchall()
        con.close()
        return rows
    except Exception:
        return []
```
**Failure enabled**: `con.close()` is reachable only on the happy path,
immediately before `return`. Any exception raised between `connect()` and
that `close()` call — in `mutate.py`, anything that is *not*
`sqlite3.Error`/`OSError` (e.g. a `TypeError`/`KeyError` in the byte-bit
decoding loop) propagates uncaught past the `except` clause with the
connection never closed; in `system_check.py`, the `except Exception`
clause is broad enough to catch the failure, but the `except` body itself
never calls `con.close()`, so the connection is still leaked — the broad
catch changes what the caller sees (a silent `[]`) but not whether the
connection closes. Both are the exact "unreachable garbage in a reference
cycle, finalized by the generational GC at an unpredictable moment" shape
the 13-site fix targeted, just on the *error* path where the equivalent
`with sqlite3.connect(...) as conn:` pattern had already been avoided on
the *success* path.
**On mid-operation kill**: not applicable to a kill (both DBs are
read-only opens against files these functions don't write); the exposure
is process-internal — a leaked read handle keeps the underlying db file
locked/open on the process until GC runs, which on Windows can keep the
file locked against a concurrent writer or deletion for an indeterminate
window, which is the same "stat sees a moving target" hazard as the
original bug class, just triggered by a query bug instead of a `with`
misunderstanding.
**Severity**: Low-Medium. Both are tooling/eval-harness code (not on the
mission/attempt/evidence trust-boundary path); `mutate.py`'s DB is a
foreign `coverage.py` file with no schema control on our side (a
malformed byte in `numbits` is plausible on a corrupt coverage db);
`system_check.py`'s function is used by the harness's own smoke/self-test
tooling.
**Confidence**: High — verified by direct code reading, not inference.

### Finding B — `kernel/effect_recovery.py:523`: reader of the effect-lease ledger omits every pragma its sibling reader sets

Already detailed above (pragma table + "Finding B"). Restated as a
finding-card:
**Failure enabled**: a reader on the crash-recovery/reconciliation path
(`_persisted_terminal`, called during unknown-outcome resolution — exactly
when a concurrent writer transaction is plausible) waits only the Python
`sqlite3` default 5.0s for the WAL lock instead of the 30s every other
reader/writer of this same file agrees on, raising `sqlite3.
OperationalError: database is locked` under contention where its sibling
`effect_replay.py` reader would have waited it out.
**On mid-operation kill**: not kill-triggered; triggered by ordinary
concurrent access timing. Kill-safety of the underlying WAL file itself is
fine (see kill table).
**Severity**: Medium. This is a real, silent behavioral asymmetry on a
correctness-adjacent path (effect-outcome reconciliation after a crash is
precisely a "was there an in-flight writer" scenario), but its blast
radius is an extra, well-typed exception (`EffectReplayProjectionError`-
style wrapping via `except (EffectLeaseError, sqlite3.DatabaseError)` — 
worth checking whether `effect_recovery.py` wraps `sqlite3.OperationalError`
the same defensive way; it should be checked as part of any fix).
**Confidence**: High.

### Finding C — `kernel/offload_lease.py:2204`: 5s vs 30s busy-wait on the same ledger, likely deliberate

Restated as a finding-card for completeness. **Severity**: Low (reads as
intentional fail-fast at an issuance guard, per its own docstring).
**Confidence**: Medium (intent inferred from docstring, not confirmed with
the author).

### Finding D — `memory/embeddings.py`: `EventVectorStore` never sets journal_mode/synchronous/busy_timeout

Restated as a finding-card. **Severity**: Low-Medium — no correctness bug
observed (all production callers close deterministically, so no leak), but
under concurrent access (search endpoint + projection worker + best-effort
ingest bridge, all real production call sites) this store has strictly
weaker lock-wait behavior than every WAL-mode store in the codebase, and
it's the only store family with no comment explaining the choice.
**Confidence**: High that the pragmas are absent; Medium on real-world
impact since no incident evidence was available to check (static sweep
only).

## NOT findings (explicitly excluded)

- **13 already-fixed `with sqlite3.connect(...) as conn:` sites** (today's
  fix, not re-reported): `kernel/approvals.py:455`, `kernel/effects.py:940`
  (`_initialize`/`execution_state` family, 6 call sites total),
  `kernel/effect_recovery.py:515` (`_persisted_terminal`'s *close*
  behavior — re-verified clean; only its *pragmas* are a new finding, see
  Finding B), `runtimes/provider_observation.py:560` (`_initialize`/
  `store`/`load` family, 3 call sites total), `runtimes/trust_store.py:263`
  and `:465` (`_initialize`/`lookup`/`quarantine`/`records` family, 5 call
  sites total). All 19 individual call sites behind these 5 factories were
  independently re-verified in this sweep (not merely trusted) and all
  close deterministically.
- **No `with sqlite3.connect(...)` survives anywhere in `daedalus/` or
  `tools/`** — confirmed by full-repo grep; only `tests/` (38 hits, out of
  scope) and code-generation string literals in `scripts/*.py` (which
  describe/replay the mutation, not execute it) remain.
- **No `.cursor()` calls** anywhere in scope — finding class #2 does not
  apply.
- **No `executescript()` calls** anywhere in scope — finding class #3
  does not apply.
- **No multi-statement logical unit under `isolation_level=None` without
  an explicit `BEGIN`** — every autocommit connection in scope drives its
  own `BEGIN IMMEDIATE`/`COMMIT`/`ROLLBACK` by hand.
- **No unguarded `check_same_thread=False`** — the one user
  (`kernel/events/ledger.py`'s `SpineLedger`) pairs it with an internal
  `RLock` taken by every method that touches the shared connection.
- **`kernel/offload_lease.py:2204`'s `contextlib.closing(...)`** — already
  deterministic; only its pragma choice is flagged (Finding C).
- **`structcore/cache.py`** — already carries its own close-vs-discard
  fix and comment predating this sweep; re-verified clean, not re-reported
  as new.
- **`memory/embeddings.py`'s persistent `self._conn`** — not a leak; all
  5 production constructors close deterministically. Only its pragma
  posture is flagged (Finding D), not its lifecycle.

## Answers to the specific questions asked

- **Total connect sites**: 20 raw `sqlite3.connect(` occurrences (19 in
  `daedalus/`, 1 in `tools/`); counting every individual call site behind
  the 5 multi-caller `_connect()`/`_open_sqlite()` factories, there are
  **34 distinct places a connection is opened** in scope.
- **Still GC-dependent**: **2 of the 34** — `eval/mutate.py:130` and
  `tools/system_check.py:236`, both only on their non-happy-path exception
  branch (Finding A). Every other site closes deterministically on every
  observed exit path, including exception paths.
- **`with sqlite3.connect(...)` the 13-site fix missed**: **none** — full
  re-sweep confirms zero surviving instances in `daedalus/`/`tools/`.
- **Top pragma disagreements**: (1) `kernel/effect_recovery.py` vs
  `kernel/effect_replay.py` on the identical effect-lease ledger file — 5s
  vs 30s busy-wait, Finding B, the one that looks like an oversight rather
  than a design choice; (2) `kernel/offload_lease.py:2204`'s explicit 5s
  vs the ledger's 30s, Finding C, reads as intentional; (3)
  `memory/embeddings.py`'s `EventVectorStore` never adopting WAL/
  busy_timeout at all, Finding D, a hygiene gap rather than a disagreement
  between two connections (both sides of that store agree on "nothing
  set").
- **Ranked finding list**: Finding B (Medium) > Finding D (Low-Medium) >
  Finding A (Low-Medium, tooling-only) > Finding C (Low, likely
  intentional).
- **Which deserve their own fix packet**: Finding B is the strongest
  candidate — it is a one-line fix (`connection.execute("PRAGMA
  busy_timeout=30000")` plus `timeout=30.0`/`isolation_level=None`/
  `PRAGMA query_only=ON` to match its sibling reader exactly) on a
  genuine crash-recovery path, cheap to verify with a contention test
  mirroring the one the 13-site fix presumably already has for its own
  siblings. Finding A is a reasonable second candidate (also a one-line
  `try/finally` fix in each of the two functions) but is confined to
  tooling, not the trust-boundary kernel. Findings C and D are worth a
  one-line owner note each (confirm C is intentional; decide whether
  `EventVectorStore` should adopt WAL) rather than an urgent fix packet.
