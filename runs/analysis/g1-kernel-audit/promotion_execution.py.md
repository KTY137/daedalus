# daedalus/kernel/promotion_execution.py  (1100 lines)

Base 54f09753. Static read-only.

## What the file is for

Persisted mutation-accounting layer sitting between `PromotionAuthorization`
(from `promotion.py`) and the actual worktree/Git mutation the caller
performs. `PromotionExecutionLedger` wraps the single canonical `SpineLedger`
Event Store, recording exactly one `promotion.execution` intent
(`PromotionExecutionStart`) per promotion identity and at most one terminal
event (`PromotionExecutionReceipt` + a bounded, canonicalized JSON report).
It defines no second workflow database, invokes no Git, applies no
candidates, and issues no `OwnerApproval` — by design (per its own docstring
and per the deliberate-boundary note in
`docs/work-packets/G0-PRM-19_PROMOTION_EXECUTION_EVENT_SPINE.md`).

## Axis 1 — docstring truth

### CONFIRMED
None.

### PLAUSIBLE
None.

### Checked and honest
- `:1-9` "It extends the repository's single `SpineLedger` Event Store; it
  does not create a second workflow database, issue OwnerApproval, apply
  candidates, invoke Git, merge branches, or promote automatically." —
  confirmed by scoped grep for `subprocess\.|Popen|git |merge|OwnerApproval`
  in this file: zero hits. The only writer is `SpineLedger` via
  `open_gate0_spine_writer` (`:632-635`), and the only SQL this file issues
  directly is a `CREATE UNIQUE INDEX IF NOT EXISTS` on `SpineLedger`'s own
  `intents` table (`:680-688`), not a second table/database.
- `:213-215` / `:318-322` "Persisted intent committed before the first
  promotion mutation" (`PromotionExecutionStart` docstring) — this file
  itself never mutates a checkout; the claim describes intended usage by a
  caller (see Axis 5: that caller does not currently exist in production).
- `:640-654` constructor: any exception during `open_gate0_spine_writer`,
  `enforce_gate0_durability`, or `_install_single_start_invariant` closes an
  owned spine before re-raising (`except Gate0DurabilityError` at `:645-650`
  and a catch-all `except BaseException` at `:651-654`), so "requires
  Gate-0 Event-Store durability" (`:648-649`) is enforced fail-closed with no
  leaked handle — see Axis 3.
- `:502-513` (docstring quoting the historical B8 bug, MEASURED 2026-08-23:
  13 red tests) — a retrospective note about a fixed defect, not a live
  claim; the fields it says were "widened" (`owner_approval_ref`, `trust`)
  are present in `PromotionExecutionStart.__post_init__` (`:240-296`) and are
  compared in `_validate_report`'s `expected_authorization` dict (`:544-549`,
  explicitly commented "ALL TEN, not eight") — confirmed the code matches the
  claimed fix.
- `:1-9`/`:213` distinct-names claim: grep confirms no second class named
  `PromotionReceipt` anywhere in this file (only `PromotionExecutionReceipt`
  and `PromotionExecutionStart`), matching the module docstring's explicit
  "deliberately uses the distinct names" and the G0-PRM-19 work packet's own
  review checklist item ("defines no second class named `PromotionReceipt`").

## Axis 2 — effect surface

| site (file:line) | effect | registry row | covered? |
|---|---|---|---|
| `SpineLedger.record_intent` (`:934-940`, via `self._require_spine()`) | FILESYSTEM_WRITE (sqlite, via `SpineLedger`) | none targets `daedalus.kernel.promotion_execution....` | **no** |
| `SpineLedger.mark_completed` (`:1051-1055`) | FILESYSTEM_WRITE (sqlite) | none | **no** |
| `CREATE UNIQUE INDEX IF NOT EXISTS ...` (`:682-688`, via `self._require_spine()._txn()`) | FILESYSTEM_WRITE (sqlite DDL) | none | **no** |
| `read_promotion_execution_intents(...)` (`:696-699`, delegates to `promotion_execution_reader.py`) | FILESYSTEM read (sqlite, `mode=ro`) | none | **no** |

### Notes
This file performs no *direct* subprocess/socket/open()/tempfile calls
itself (confirmed by scoped grep: zero hits for
`subprocess\.|Popen|socket\.|urllib|requests\.|open\(.*[wax]|tempfile\.|
os\.environ|os\.getenv|shutil\.` in this file); every effect is mediated
through `SpineLedger` (owned by `daedalus/spine/ledger.py`, out of my slice)
via `open_gate0_spine_writer`/`record_intent`/`mark_completed`/`_txn`. Per
the brief's measured fact, only 4 rows in `effect_boundary.py` target
`daedalus.kernel....` and none of them is this file or targets
`PromotionExecutionLedger.begin`/`.complete` by name or by anchor — I
grepped `effect_boundary.py` for `promotion_execution` and
`PromotionExecutionLedger` and got zero hits. This is not a silent gap: the
G0-PRM-19 work packet that introduced this file explicitly names the missing
registration as **deliberate, unfinished, future work** — "Deliberate
remaining boundary... The following dependent packet must: 1. register
`PromotionExecutionLedger.begin` and `.complete` honestly in the effect
inventory..." (`docs/work-packets/G0-PRM-19_PROMOTION_EXECUTION_EVENT_SPINE.md`).
That dependent packet has not landed (see Axis 5: zero production callers of
this class anywhere). So today every effect this file can perform is
genuinely unregistered *and* genuinely unreachable from production code —
consistent, not contradictory, with the module's own honest claim not to
invoke Git or apply candidates.

## Axis 3 — unreleased resources

No findings.
- `__init__` (`:621-654`): `self.spine` starts `None`; it is only assigned
  after `open_gate0_spine_writer`/`path` succeeds. Both `except
  Gate0DurabilityError` (`:645-650`) and the catch-all `except BaseException`
  (`:651-654`) close an *owned* spine (`self._owns_spine and self.spine is
  not None`) before re-raising, covering every failure point in the try body
  (durability enforcement, single-start-invariant DDL). If `path` is already
  a `SpineLedger` instance (`self._owns_spine = False`), `close()` correctly
  never touches it (`:656-658`) — the caller owns that lifecycle, matching
  this file's own "does not own the spine unless it opened it" contract.
  This is the exact shape the brief's canonical leak example
  (`events/ledger.py:338-343`) is missing — here it is present and correct.
- `_install_single_start_invariant` (`:680-688`) uses
  `with self._require_spine()._txn() as connection:` — a context manager
  from `SpineLedger` (out of slice); no bare connection is opened in this
  file.
- No `open()`, `tempfile`, `Popen`, `threading.Lock`, or `socket` anywhere in
  this file.

## Axis 4 — validator gaps (W4 class)

No findings reachable within this file.
- Every canonical identifier/digest/revision field on `PromotionExecutionStart`
  and `PromotionExecutionReceipt` is validated through the canonical
  `_identifier`/`_sha256`/`_revision`/`_utc_timestamp` helpers imported from
  `daedalus.kernel.contracts.base` (`:27-35`) — not a local weak-regex copy.
- None of `start_id`, `promotion_id`, `target_ref`, `receipt_id` is used to
  construct a filesystem path, SQL identifier, or shell argument in this
  file. `target_ref`/`promotion_id` reach `_effect_key(promotion_id)`
  (`:85-86`, `f"promotion.execution:{_identifier(promotion_id, ...)}"`),
  which becomes a SQLite **parameter value** (`effect_key=?`, always bound,
  never interpolated into SQL text — confirmed via `record_intent`'s
  signature usage at `:934-940` and the reader's parameterized queries in
  `promotion_execution_reader.py:163-175`), not a path or identifier
  construction site. Per the brief's own carve-out: "a value that is only
  ever used as a dict key or logged is not a finding" — this is the SQL
  analog (a bound parameter, not string-built SQL or a path) and is
  similarly not a finding.
- `receipt.report_sha256`, `start.digest`, and all `*_sha256` fields are
  validated by the strict `_sha256`/`_SHA256_RE` (`^[0-9a-f]{64}$`) before
  use and never reach path construction in this file.

## Axis 5 — dead / duplicate

### CONFIRMED
- **`PromotionExecutionLedger` (`:618-1087`) has ZERO production callers
  anywhere in the repository — not even the one-hop-down kind found for
  `promotion.py`'s functions.** `grep -rn "PromotionExecutionLedger"
  --include=*.py daedalus/ tests/ scripts/ tools/ docs/` matches only: this
  file's own definition and `__all__` (`:618,1095`); the lazy-facade export
  list in `daedalus/kernel/__init__.py:80`; and roughly 40 hits confined to
  `tests/kernel/test_promotion_execution*.py` (5 files). I additionally
  traced the one production call site that *does* exercise the authorization
  half of the promotion pipeline —
  `daedalus/kairos/gated_writes.py:promote_candidates` — end to end
  (`:144-330`) and confirmed it **never imports or calls
  `PromotionExecutionLedger`, `.begin`, or `.complete`** (scoped grep for
  `PromotionExecutionLedger|promotion_execution|fingerprint_primary_checkout|
  primary_checkout` in `daedalus/kairos/gated_writes.py` returns zero hits).
  So this is not merely "unreachable because its caller's caller is
  unreachable" (the `promotion.py` situation) — it is unreachable because
  the one production function whose docstring/work-packet names it as the
  intended reader (`promote_candidates`) was never actually wired to call it,
  even though that function *is* production code that calls `promotion.py`'s
  authorization primitives one hop away.
- **This is a documented, promised-but-undelivered seam, not silent dead
  code.** `docs/work-packets/G0-PRM-19_PROMOTION_EXECUTION_EVENT_SPINE.md`
  ("Deliberate remaining boundary") explicitly states: "This packet does
  **not** wire the live `promote_candidates` seam. It therefore performs no
  repository mutation and cannot issue a successful production execution
  receipt yet. The following dependent packet must: 1. register
  `PromotionExecutionLedger.begin` and `.complete` honestly in the effect
  inventory; 2. require a persisted start immediately before the first live
  promotion mutation; 3. always append a terminal receipt or leave an
  explicit pending reconciliation record after interruption; 4. bind the
  live integration revision and before/after primary-checkout fingerprints;
  5. preserve separate manual OwnerApproval and prohibit automatic
  promotion." None of those five items has landed in `gated_writes.py` as of
  this base revision. This is a textbook Axis-5 seam: an unwired producer
  whose own project documentation names its intended consumer and lists
  exactly what remains — not dead code, but a genuinely incomplete wiring
  step that both this file's `pending()` reconciliation method (`:1076-1087`)
  and the whole `PromotionExecutionCompletion`/report-binding machinery
  currently have no way to be exercised by.
- This also means `fingerprint_primary_checkout` (from the sibling
  `promotion_fingerprint.py`, see that dossier) is doubly unreachable: even
  if `PromotionExecutionLedger` were called, this file's own `begin()`/
  `complete()` signatures take `primary_checkout_before_sha256`/
  `primary_checkout_after_sha256` as **plain string parameters** (`:876-878,
  966-967`) — this file does not import or call `fingerprint_primary_checkout`
  itself (confirmed: no import of `daedalus.kernel.promotion_fingerprint`
  anywhere in this file). The intended caller would have to call the
  fingerprint helper *and* this ledger *and* wire both into
  `gated_writes.py` — three separate unfinished wiring steps, not one.

### PLAUSIBLE
None beyond the above.

## OWNED-FLAG

Not applicable — this file is not `offload_lease.py`, the flagged
`attempt_execution.py` string-evidence sites, or `effects.py`.

## What I did not cover

Did not execute or import any code (static read-only). Did not audit
`daedalus/spine/ledger.py` (`SpineLedger`, `record_intent`, `mark_completed`,
`_txn`) or `daedalus/spine/durability.py`
(`open_gate0_spine_writer`/`enforce_gate0_durability`) beyond confirming they
are called as context managers/factories — both are out of my assigned
slice. Did not verify whether any *non-production* (e.g. CLI/manual-ops)
script calls `PromotionExecutionLedger` outside the `daedalus/`, `tests/`,
`scripts/`, `tools/`, `docs/` search roots I was told to scope to.
