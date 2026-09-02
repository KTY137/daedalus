# daedalus/kernel/effect_replay.py  (614 lines)

Base 54f09753. Static read-only.

## What the file is for

Strict read-only projection over a persisted `EffectLease`/execution row in
the Effect-Lease SQLite ledger. It re-derives and re-validates the exact lease,
start receipt, and (if present) terminal receipt from the database, comparing
every field against the caller-supplied authorization and execution objects.
It exists so a restart can distinguish "still pending" from "already
terminal" without the generic ledger's `execute=False` replay signal alone
(module docstring, :1-14), and it grants no authority to execute, start, or
finish anything itself.

## Recovery robustness: crash mid-replay, idempotency

This module performs no writes at all (confirmed: no `INSERT`/`UPDATE`/
`DELETE`/`with sqlite3` write-transaction anywhere; only `SELECT` at :376-385
and :440-454, plus two `PRAGMA` statements at :373-374). A crash during a call
to `inspect_effect_execution`/`_project_persisted_execution` therefore cannot
leave the ledger in a worse state than before the call — the function either
returns a fully-validated snapshot, returns `None`, or raises before any
externally-visible side effect. Repeated calls are trivially idempotent
because there is nothing to repeat. This directly supports the
crash-then-recover flow in `effect_recovery.py` (this slice): recovery code
calls into this file first (via `daedalus/runtimes/recovery.py` and callers
like `chip_design/cli.py:427`) to learn whether an execution is
`pending_reconciliation` before doing anything effectful.

## Axis 1 — docstring truth

### CONFIRMED
- none — see "Checked and honest" below.

### PLAUSIBLE
- none.

### Checked and honest
- Module docstring: "This module opens the selected Effect-Lease SQLite file
  with `mode=ro` and `query_only=ON`... It neither grants nor starts a lease
  and exposes no re-execution authority." (`effect_replay.py:9-13`). Verified
  at the one connection site (:366-374): `mode=ro` in the URI and
  `PRAGMA query_only=ON` are both present, and the only SQL executed against
  that connection is two `SELECT`s (:376-385, :440-454). No `grant`, `begin`,
  or `finish` method or call exists in this file. Confirmed true.
- `PersistedEffectLeaseSubject` docstring: "This is deliberately *not* a
  capability. It carries no guard decisions, no kill-switch authority and no
  grant/begin/finish methods, so holding one can never authorize an effect."
  (:313-317). Verified: the dataclass fields are `lease, request,
  policy_decision, effect_ledger, lease_keyring, registry` (:321-329) — no
  guard-decision field, no method beyond `__post_init__`. Confirmed true.
- `_project_persisted_execution` docstring: "Shared read-only reader behind
  every replay projection. It opens the ledger read-only, never writes, and
  grants no execute authority" (:357-359). Confirmed by the same evidence as
  above; this is also the exact function `runtime_effect_replay.py` reuses
  directly (imported at `runtime_effect_replay.py:28`) rather than
  reimplementing — see Axis 5.
- `inspect_effect_execution` docstring: "`None` means the signed lease is
  persisted but the exact execution has no start... Historical signature and
  scope verification is evaluated at the retained start instant; no stale
  lease or kill switch can thereby regain authority to execute." (:583-588).
  Verified: `verify_effect_lease` is called with
  `now=_parse_utc(start.started_at, "started_at")` (:506-514) — the retained
  start time, not the caller's current wall clock — so a lease that expired
  or a kill-switch generation that advanced *after* the original start cannot
  make historical verification fail differently than it did at start time.
  Confirmed true for this file; whether `verify_effect_lease` itself is
  correct is `effects.py`, OWNED-FLAG, not re-verified here.

## Axis 2 — effect surface

| site (file:line) | effect | registry row | covered? |
|---|---|---|---|
| `effect_replay.py:366-371` `sqlite3.connect(..., mode=ro)` | filesystem/sqlite read | none under `daedalus.kernel.*` | not directly; read-only, see Notes |

### Notes
- Zero `target="daedalus.kernel.effect_replay...."` rows in the 108-row
  registry (grepped). Expected per the brief's measured fact.
- The read is strictly read-only (`mode=ro` + `PRAGMA query_only=ON`,
  :367,374) — it cannot itself constitute one of the write/spawn/network
  effect classes the registry exists to gate (subprocess, network egress,
  filesystem write, secret/env read). It is a query over an already-existing
  ledger file. I judge this file's absence from the registry as *expected and
  benign* rather than a gap, distinct from `effect_recovery.py`'s
  `ledger.finish` write path (see that dossier), because Effect Registry rows
  gate effects, and there is no effect here to gate.

## Axis 3 — unreleased resources

Checked and honest: `_project_persisted_execution` (:351-575) is the only
resource acquisition in this file. `connection = sqlite3.connect(...)`
(:366-371) is initialized to `None` first (:364) and released in a
`try/finally` (:573-575: `if connection is not None: connection.close()`),
which also correctly covers the case where `sqlite3.connect` itself raises
before `connection` is assigned. This matches the canonical fixed shape from
`effects.py::_initialize`. No open file handles, tempfiles, locks, sockets,
or subprocesses anywhere else in the module. No findings.

## Axis 4 — validator gaps (W4 class)

Checked and honest: `_identifier` is applied to values coming out of
persisted JSON (`execution_id`, `idempotency_key`, `lease_sha256`, etc. in
`_start_receipt` :132-166 and `_terminal_receipt` :208-258) and to the
`execution` argument's own fields. None of these validated values are used to
build a filesystem path, git ref, or URL segment in this file — they are used
exclusively as sqlite bound parameters (`?` placeholders at :384-385, :450-453)
and as dict/dataclass field values compared for equality. The one path built
in this file, `f"file:{_uri_path(ledger.path.resolve())}?mode=ro"` (:367),
comes from `ledger.path` (trusted configuration), not from any
`_identifier`-validated request field. No findings.

## Axis 5 — dead / duplicate

- Not dead. `inspect_effect_execution` has extensive production callers:
  `daedalus/build_exec.py:969-972`, `daedalus/chip_design/cli.py:427,2381`,
  `daedalus/chip_design/publication_verifier.py:89`,
  `daedalus/gates/repository_write_effect_lease.py:742`,
  `daedalus/kernel/offload_lease.py:1099,1181` (which also documents it in
  prose as "the ONLY" reader, :1023 there — a promised-consumer pattern
  confirmed real), plus
  `daedalus/runtimes/provider_target_receipt_retention_*.py`. Grep:
  `grep -rn "inspect_effect_execution" --include=*.py daedalus/ tests/` → dozens of hits across 9+ production modules.
- **Good reuse, not duplication**: `_project_persisted_execution` (:351-575,
  the actual sqlite-reading logic) is imported directly by
  `runtime_effect_replay.py` (`from daedalus.kernel.effect_replay import ...
  _project_persisted_execution`, that file's :24-29) rather than being
  reimplemented. `runtime_effect_replay.py::inspect_runtime_effect_execution`
  composes this file's projection with an additional runtime-trust check; it
  does not fork or duplicate the sqlite-reading code. This is the correct
  answer to the brief's Axis 5 duplication question for the replay pair:
  `effect_replay.py` is authoritative for "what is persisted for this
  execution", `runtime_effect_replay.py` is authoritative for "is the runtime
  trust that produced it still valid" — genuinely distinct responsibilities,
  composed rather than parallel. Also imports `_parse_utc` directly from
  `effects.py` (:27-37 here) rather than redefining it, unlike
  `effect_recovery.py` and `runtime_effects.py` (see those dossiers for the
  triplicated `_secret_bytes`/`_signature`/`_parse_utc` finding — this file is
  not part of that duplication).

## OWNED-FLAG

N/A — this file is not owned by another running packet.

## What I did not cover

- Did not re-verify `verify_effect_lease` or `EffectLeaseLedger` internals
  (`effects.py`, OWNED-FLAG, just received a fix) — trusted as a dependency.
- Did not trace the full production call chain from `chip_design/cli.py` or
  `build_exec.py` down to a real network/process boundary; confirmed only
  that they import and call this file's public function.
