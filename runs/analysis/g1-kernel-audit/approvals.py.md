# daedalus/kernel/approvals.py  (855 lines)

Base 54f09753. Static read-only.

## What the file is for

Defines the HMAC-signed `OwnerApproval` issue/verify primitives
(`issue_owner_approval`, `verify_owner_approval`), the frozen
`ApprovalExpectation` / `VerifiedOwnerApproval` / `ConsumedOwnerApproval`
binding dataclasses, and `ApprovalLedger` — a SQLite-backed, single-use,
atomically-consuming ledger that persists this file's approval consumption as
the *demoted second factor* consumed by `daedalus.kernel.promotion_trust_root`.
Also exposes a `main()` CLI (`issue`/`verify` subcommands) — the sole
kernel-target row (`daedalus.kernel.approvals:main`) in the Effect Registry.

## Axis 1 — docstring truth

### CONFIRMED
None.

### PLAUSIBLE
None.

### Checked and honest
- `:1` "Authenticated, one-use owner approval capabilities." — **authenticated**:
  `hmac.compare_digest` (constant-time, not `==`) at `:362` (fresh verify) and
  `:693-699` (persisted re-verify in `verify_consumption`). **one-use**: enforced
  by real SQLite `UNIQUE` constraints (`approval_id`, `promotion_id`,
  `consumption_sha256`, and `UNIQUE(owner_id, key_id, nonce)`, `:469-494`)
  inside a `BEGIN IMMEDIATE` transaction (`:537`) — two concurrent `consume()`
  calls serialize on SQLite's write lock; the loser gets `sqlite3.IntegrityError`
  → `ApprovalReplay` (`:625-632`), not a silently-accepted second use. This is
  atomic at the DB layer, not a check-then-act race.
- `:352` "Authenticate and validate every bounded approval dimension" —
  confirmed: `verify_owner_approval` checks signature (`:361-363`), TTL/expiry
  window three ways (`:368-373`), and all seven binding fields via the
  `comparisons` dict (`:375-400`) before returning a verdict; any mismatch
  raises `ApprovalBindingMismatch` naming every mismatched field, not just the
  first.
- `:426` "SQLite authority for authenticated, atomic approval consumption" —
  confirmed atomic per above; `consume()` also re-verifies *inside* the
  transaction (`:543-548`) and refuses if the re-verify disagrees with the
  preflight verify (`:549-552`, `ApprovalStateError`) or if the ledger clock
  moved backwards (`:539-542,554-557`).
- `:813` (in `main()`'s comment) "It writes no file, spawns nothing... its only
  effect is SECRETS" — confirmed: `_cli_issue`/`_cli_verify` only call
  `os.environ.get(secret_env)` (`:754,789`), `Path.read_text` (`:751,781-784`,
  reads not writes), `issue_owner_approval`/`verify_owner_approval` (pure), and
  `print(...)` (`:774,801`, stdout). Neither constructs an `ApprovalLedger`, so
  `main()` never reaches the sqlite write path documented below.
- **Secret-absent behavior (brief's specific question)**: `_secret_bytes`
  (`:285-289`) raises `ValueError` if the secret is `< 32 bytes`, called from
  `_signature` (`:292-295`) on every issue and verify path; `verify_owner_approval`
  additionally raises `ApprovalSignatureError` if `keyring.get((owner_id,
  key_id))` is `None` (`:358-360`) and `_cli_issue`/`_cli_verify` raise
  `ValueError` if the named env var is unset (`:754-758,789-793`). Fails
  closed in every direction checked — an absent/short/unknown key never
  authenticates.
- Sqlite resource handling: this file is the brief's *calibration example* for
  the Axis-3 fixed shape (`:453-464`'s own comment names the bug and the fix).
  I verified all four `_connect()` use sites — `_initialize` (`:465-510`),
  `consume` (`:535-640`), `verify_consumption` (`:653-666`), `consumed`
  (`:738-746`) — each wraps in `try/finally: connection.close()`. This file is
  the fixed reference shape, not a leak site.

## Axis 2 — effect surface

| site (file:line) | effect | registry row | covered? |
|---|---|---|---|
| `sqlite3.connect` via `_connect` (`:443-451`), called from `_initialize`/`consume`/`verify_consumption`/`consumed` | FILESYSTEM_WRITE (WAL) | none named specifically | not covered — see note |
| `os.environ.get(secret_env)` `:754,789` | ENV_READ / SECRETS | `cli.approvals` (`daedalus/spine/effect_boundary.py:2301-2308`, `target="daedalus.kernel.approvals:main"`, `effects=(Effect.SECRETS,)`) | yes, via `main()` |
| `input_path.read_text` / `expectation_path.read_text` `:751,781-784` | filesystem read | same `cli.approvals` row | yes (read-only, not separately classed) |
| `print(...)` `:774,801` | stdout | n/a | not a classed effect per brief's list |

### Notes
- The `cli.approvals` row's own notes (`effect_boundary.py:2314-2316`) cite
  `os.environ.get(secret_env)` at `approvals.py:732` (`_cli_issue`) and `:767`
  (`_cli_verify`). In this revision those calls are at `:754` and `:789` — a
  consistent +22-line offset, i.e. the registry note's line citations are
  **stale** (the file grew by 22 lines since the note was written). Not a
  security defect — the row still covers the right function by name — but a
  minor documentation-drift finding worth another worker's note if
  `effect_boundary.py` line-citation freshness is in scope elsewhere.
- The sqlite write effect inside `ApprovalLedger.consume()`/`_initialize()` has
  no dedicated registry row. This is consistent with Axis 5 below: since
  `ApprovalLedger.consume(` has zero production callers today, there is
  currently no live gap — but when this path is wired, `promote_candidates`'s
  own row (`python.promote_candidates`, `guard_contracts=(...,
  "promotion.owner_approval")`) is the most plausible place for that coverage
  to land, since `promotion.owner_approval` reads as exactly this guard's name.

## Axis 3 — unreleased resources

No findings — see Axis 1's "Sqlite resource handling" note above; this file is
the already-fixed reference shape the brief's calibration example points to.

## Axis 4 — validator gaps (W4 class)

No findings. `_identifier`/`_revision`/`_sha256`/`_utc_timestamp` (imported
`:22-29` from `daedalus.kernel.contracts.base`, itself a re-export of
`daedalus.kernel.contracts.canonical`'s weak-regex validators — confirmed via
`contracts/base.py:10,17`) validate `approval_id`, `owner_id`, `key_id`,
`nonce`, `promotion_id`, `target_ref`, `base_revision`, etc. throughout this
file's dataclasses. None of these validated values are ever used to build a
filesystem path, sqlite path, git ref, or URL segment **inside this file** —
they are only stored as dataclass fields, SQL column bind parameters
(parameterized, `:592-621`), or canonical-JSON payload content. A value used
only as a dict key, SQL parameter, or logged/printed string is explicitly not
a finding per the brief.

Flag for cross-file awareness (not a finding in *this* file): `target_ref` and
`promotion_id` leave this module as plain strings into
`daedalus.kernel.promotion` and `daedalus.kairos.gated_writes` (outside my
slice), where `target_ref` eventually becomes a `git rev-parse --verify <ref>`
argument (`daedalus/kernel/promotion.py:308-324`) — an argument-injection
surface distinct from path traversal, and not a `Path(...)` join. Worth
another worker's attention if `promotion.py`/`gated_writes.py` are in scope
elsewhere; not claimed here.

## Axis 5 — dead / duplicate

### CONFIRMED
- `ApprovalLedger` (the class) and its `.consume(` method are referenced in
  production code only as a type import / `isinstance` check —
  `promotion_trust_root.py:1002` (`isinstance(approval_ledger, ApprovalLedger)`),
  `promotion.py:30` (type import), `kairos/gated_writes.py` (parameter type
  hint, not instantiation). The constructor `ApprovalLedger(` and the method
  call `.consume(` are **never invoked** anywhere under `daedalus/`.
  Exact greps run: `grep -rn "ApprovalLedger\(" --include=*.py daedalus/` →
  0 matches; `grep -rn "\.consume\(" --include=*.py daedalus/` → 0 matches.
  `.consume(` appears only in `tests/kernel/test_owner_approval.py`,
  `tests/kernel/test_sealed_promotion.py`,
  `tests/kernel/test_persisted_promotion_authorization.py`. This is the other
  half of the joint finding filed in `promotion_trust_root.py.md`: the entire
  D5 sealed-promotion consumption chain is built and heavily tested but has no
  live production caller in this revision. `daedalus/loop.py:12-15` documents
  that the scheduling loop deliberately never calls `promote_candidates` (by
  design, so it cannot auto-promote) — but no *other* caller (CLI, API, UI)
  exists either as of this revision, so the omission is broader than the
  loop's own documented abstention.
- `issue_owner_approval` / `verify_owner_approval` (module-level pure
  functions, `:298-422`) ARE reachable in production, via `main()`'s
  `_cli_issue`/`_cli_verify` (`:750-802`), which is itself covered by the
  `cli.approvals` registry row. These two are wired; the ledger-consumption
  path is not.

### PLAUSIBLE
None beyond the above.

## OWNED-FLAG

Not applicable — this file is not one of the three flagged files
(`offload_lease.py`, the flagged `attempt_execution.py` string-evidence sites,
`effects.py`).

## What I did not cover

Did not trace whether any non-Python surface (e.g. `apps/web/src-tauri`'s Rust
code) shells out to `python -m daedalus.kernel.approvals` as production
wiring for `issue`/`verify` — I checked only Python-level callers per the
audit's grep-hygiene guidance and did not read the Tauri Rust sources. Did not
audit `daedalus.kernel.contracts` (`OwnerApproval`, `ContractProvenance`) or
`daedalus.spine.envelope` (`canonical_json`/`canonical_sha`) internals — both
imported but out of my assigned slice.
