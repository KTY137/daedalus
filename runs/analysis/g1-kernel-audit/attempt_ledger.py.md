# daedalus/kernel/attempt_ledger.py  (429 lines)

Base 54f09753. Static read-only. Auditor: parent (W6 slice, subagent cap hit).

## What the file is for

`AttemptLedger` is a facade over the single canonical `SpineLedger` event store.
It persists exactly one start intent per `attempt_id` (`begin`), persists exactly
one terminal receipt against that start (`complete`), and decodes/revalidates
persisted rows on every read. It owns no second store — it installs a unique
index on the spine's own `intents` table and uses the spine's transaction seam.

## Axis 1 — docstring truth

### Checked and honest

- `:50` "facade over the repository's single canonical event spine." Verified:
  the only persistence calls are `self.spine.record_intent` (`:287`),
  `self.spine.mark_completed` (`:400`), and one DDL through `self.spine._txn()`
  (`:98`). No second connection, no second file. Matches Plan §4 invariant 1.
- `:90-96` `_install_single_start_invariant` — "A second SQLite connection would
  have its own per-connection durability settings and could silently fall back
  to `synchronous=NORMAL`. The index is therefore installed through the exact
  already-admitted `SpineLedger` transaction seam." Verified: `:98` uses
  `self.spine._txn()`, not `sqlite3.connect`. The stated reason is real and the
  code matches it.
- `:232-237` `begin` — "``started_at`` is retained only as a source-compatibility
  adapter... Its value is deliberately ignored and never enters a security
  record." Verified: `:238` `del started_at`; the record at `:257-281` uses
  `trusted_started_at` from `self._clock.now()` (`:256`) for both `started_at`
  and `provenance.created_at`. The universal "never" holds — I enumerated every
  use of the name in the method and there is exactly one, the `del`.
- `:322-327` `complete` — same claim for `completed_at`. Verified: `:328` `del`,
  `:350` `trusted_completed_at = self._clock.now(minimum=start.started_at)`.
  The `minimum=` is the persisted start, not caller input. Honest.

### PLAUSIBLE — "one attempt start" is enforced by an index that a caller can skip

`:106-108` raises "canonical event spine cannot enforce one attempt start" if
the `CREATE UNIQUE INDEX` fails, so the invariant is real when the constructor
runs. But the index is `CREATE UNIQUE INDEX IF NOT EXISTS ... WHERE kind =
'attempt.lifecycle'` (`:100-103`) — a *partial* index installed at
`AttemptLedger.__init__` time. Any other writer that opens the same spine file
without going through `AttemptLedger` (the spine is the shared canonical store,
so other subsystems do open it) still gets the index if a ledger was ever
constructed against that file, because a partial index is persistent file state.
So the invariant is durable once installed. The residual risk is a spine file
that has never had an `AttemptLedger` constructed against it being written by a
different attempt-lifecycle producer. I found no such producer, so this stays
PLAUSIBLE and low.

## Axis 2 — effect surface

| site | effect | registry row | covered |
| --- | --- | --- | --- |
| `:63` `open_gate0_spine_writer(path)` — creates/opens the sqlite DB file | FILESYSTEM_WRITE | **none** | **NO** |
| `:98-104` `self.spine._txn()` → `CREATE UNIQUE INDEX` (DDL, durable schema write) | FILESYSTEM_WRITE | **none** | **NO** |
| `:287` `self.spine.record_intent(...)` | FILESYSTEM_WRITE | `effect_boundary.py:348` `kernel.attempt.begin` | yes |
| `:400` `self.spine.mark_completed(...)` | FILESYSTEM_WRITE | `effect_boundary.py:370` `kernel.attempt.complete` | yes |
| `:213`, `:333` `source_store.read_bytes`; `:215`, `:243`, `:340` `load_tree` | read | n/a | n/a |

### CONFIRMED — `AttemptLedger.__init__` performs an unregistered durable write

The Effect Registry has exactly **4** rows targeting `daedalus.kernel.*` out of
108 total (`effect_boundary.py:350, 372, 394, 2304` — verified by
`grep -c 'target="daedalus.kernel'`). Two of them cover this file: `begin` and
`complete`. Neither covers `__init__`, yet constructing an `AttemptLedger`:

- opens or **creates** the canonical event-store sqlite file (`:63`), and
- executes DDL that permanently alters that file's schema (`:99-104`).

`CREATE UNIQUE INDEX` on a shared canonical store is a durable, cross-process,
schema-level filesystem effect. The registry's own `Effect.FILESYSTEM_WRITE` row
class exists for exactly this. The two anchors the registry does declare
(`record_intent` at `:357`, `mark_completed` at `:379`) are both *method-body*
anchors, so a mechanical anchor check on this file would pass while the
constructor's write goes uninventoried.

Severity: this is an inventory/coverage defect, not an exploit — the write is
benign and intentional. But Gate-0's exit criterion is a *complete* central
start/guard path for effectful entrypoints, and an unregistered constructor-side
schema write is precisely the kind of row the fault matrix cannot exercise
because it does not know it exists.

No subprocess, no network, no `os.environ` read in this file. `import os` (`:5`)
is used only for the `os.PathLike` type annotation at `:54`.

## Axis 3 — unreleased resources

### Investigated and REFUTED — the narrow-except shape here is not a leak

`__init__` `:61-87` looks like the classic finding: a `try` whose body can raise
`AttemptStateError` (`:68`, the `read_only` check) wrapped in
`except Gate0DurabilityError` (`:74`) — a narrower except than the try can
raise, with `self.spine` already assigned at `:62`. I filed this as CONFIRMED,
then read the callees and **it does not hold**:

- `open_gate0_spine_writer` (`events/durability.py:188-224`) converts
  `SpineError`/`sqlite3.Error`/`OSError`/`ValueError`/`TypeError` into
  `Gate0DurabilityError` **and closes its own ledger** (`:216`, `:220`) before
  re-raising. A failed open leaks nothing and never assigns `self.spine`.
- `enforce_gate0_durability` (`durability.py:133-184`) likewise converts
  `sqlite3.Error`/`TypeError`/`AttributeError` to `Gate0DurabilityError`
  (`:174-178`), and raises `Gate0DurabilityError` — not `AttemptStateError` —
  for the read-only case at `:146-149`.
- Therefore the `AttemptStateError` at `:68` is reachable **only** when the
  caller passed its own `SpineLedger` (`_owns_spine` False, set at `:60`). In
  that case the caller owns the object and *not* closing it is correct — which
  is exactly what the `if self._owns_spine and ...` guard at `:75` encodes.

Recording the refutation because the shape is a tempting false positive and the
next auditor will meet it again.

### PLAUSIBLE — the same constructor uses two different cleanup breadths

`:74` `except Gate0DurabilityError:` vs `:84` `except BaseException:`. The
second handler protects `_install_single_start_invariant`; the first protects
the open + durability enforcement. Given the conversion discipline in
`durability.py` the narrow form is currently sufficient, but it is sufficient
only *because of a property of a different module*. If `enforce_gate0_durability`
ever raises outside its declared conversion set (e.g. a lock error from
`with lock` at `:161`, `MemoryError`, `KeyboardInterrupt`), the owned writer
leaks — the WAL-companion lifetime problem documented in
`effects.py::_initialize:576-588`. Making `:74` `except BaseException` to match
`:84` costs nothing and removes the cross-module dependency. Low severity,
filed as consistency.

### Checked and clean

`complete` and `begin` acquire no resources of their own; all persistence goes
through `SpineLedger`, which owns its connection and lock.

## Axis 4 — validator gaps (W4 class)

Weak-`_identifier` values in this file: `attempt.attempt_id` (`:259`, `:279`,
`:282`, `:290`, `:291`), `start_id` (`:258`), `receipt_id` (`:352`).

**None of them reach path construction in this file.** Traced every use:

- `_effect_key(attempt_id)` (`:150`, `:290`) → a SQL bound parameter via
  `read_attempt_intents(effect_key=...)` and `record_intent(effect_key=...)`.
  Parameterized, not interpolated.
- `trace_id=attempt.attempt_id` (`:279`, `:291`, `:381`) → a record field.
- `start_id` / `receipt_id` → record fields only.
- `workspace_relative_path` (`:264`) → passed into `AttemptStartRecord`, where
  `_repo_path` validates it (`attempt_contracts.py:135`). This is the guard that
  blocks the W4 chain; see `attempt_workspace.py.md`.

So this file is a **negative result** for Axis 4, and a useful one: it is the
seam where the weak identifier is correctly confined to parameterized SQL.

## Axis 5 — dead / duplicate

### CONFIRMED — `pending()` is a restart-reconciliation producer with no consumer

`pending()` (`:420-426`) returns the persisted starts that are still
`STATE_INTENDED` — i.e. the attempts a crash left mid-flight. It is the
restart-reconciliation surface of the Attempt lifecycle.

Grep run: `grep -rn "\.pending()" --include=*.py daedalus/ tests/ scripts/ tools/`
→ **20 call sites, 0 of them under `daedalus/`.** All 20 are tests
(`tests/kernel/test_isolated_attempt_lifecycle*.py`,
`test_promotion_execution*.py`, `test_isolated_attempt_time_*.py`).
`grep -rn "\.pending()" --include=*.py daedalus/ | wc -l` → `0`.

The companion signal has the same shape.
`AttemptBeginResult.pending_reconciliation` (`attempt_contracts.py:323`) is one
of **four** independent definitions of that property in the kernel
(`attempt_contracts.py:323`, `effect_replay.py:88`,
`promotion_execution.py:502`, `runtime_effect_replay.py:66`). There are 13
production consumers of the property name across `daedalus/`
(`chip_design/cli.py:434,2384`, `chip_design/publication_verifier.py:90`,
`gates/repository_write_effect_lease.py:599,722`,
`kernel/offload_lease.py:1106,1184`, `runtimes/recovery.py:167`, …) — but every
one of them consumes the *effect-lease / promotion / runtime* variants. The
`AttemptBeginResult` variant is read only by
`tests/kernel/test_isolated_attempt_lifecycle.py:139`.

I also checked the one plausible in-kernel consumer:
`grep -n "pending()\|pending_reconciliation\|AttemptLedger\|IsolatedAttemptCoordinator"
daedalus/kernel/attempt_execution.py` returns **zero hits** — that module does
not touch this lifecycle at all.

Per the brief this is a **seam defect, not dead code**: the producer is correct
and tested, and the docstring-level promise of the surrounding subsystem
(Gate 1 requires "restart/replay works" for the Renovation slice) names a reader
that does not exist in production. Nothing in `daedalus/` reconciles a pending
Attempt after a crash. Deleting `pending()` would be the wrong fix; wiring it is
the work.

### Other

- No duplicate validators or digest helpers in this file; `_sha256`,
  `_strict_json`, `_timestamp_value` are all imported, not re-implemented.

## OWNED-FLAG — a second Attempt lifecycle sits in the same package

`daedalus/kernel/attempt_execution.py` (2724 lines, owned by the running
chip-refusal packet — flagged, not audited) opens with:

> "Kernel-owned TaskAttempt lifecycle core… **ONE way to attempt a task.** The
> loop needs **exactly one seam** between 'we decided to try this' and 'here is a
> patch a human may promote'… This module is that seam." (`:1-11`)

That is a universal module-level claim of exactly the kind this audit hunts, and
it coexists with the lifecycle documented here: `AttemptContract` →
`AttemptStartRecord` → `AttemptTerminalReceipt`, with its own three Effect
Registry rows. The two share no code (grep above: zero cross-references) and use
different identities (`effect_key` is `"attempt-lifecycle:" + attempt_id` here,
versus the candidate git BRANCH NAME there, `attempt_execution.py:18-20`).

Mitigating fact I confirmed before filing: both commit intents to the **same**
canonical `SpineLedger`, so this is *not* a second event store and Plan §4
invariant 1 is not breached on that axis. What is open is whether two Attempt
*contracts* in one kernel is the "one canonical contract" the invariant
requires, and whether "ONE way to attempt a task" is true.

**PLAUSIBLE, OWNED-FLAG, not deep-audited.** Whoever owns the chip-refusal
packet should be told this claim is load-bearing and contested.

## What I did not cover

- `SpineLedger` internals (`daedalus/spine/ledger.py`) — outside the kernel slice.
- `attempt_execution.py` beyond the flag above — owned by a running packet.
