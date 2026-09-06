# G1-IKARUS-27 — Crash reconciliation for the two-rename file replacement

Packet ID: G1-IKARUS-27
Artifact role: primary
Active gate: 1
Classification: ALIGNED
Owner: repository owner
Base revision: 585b7ea4e141332928ad6c9578b9c9997e55f247
Dependencies: G1-IKARUS-24 (adapter, HOLD) and G1-IKARUS-25 (fence lift, landed);
G1-IKARUS-COMPUTER-01 lease/receipt contracts; G1-IKARUS-21 continuation recovery
Plan revision 12, SHA-256 `126594137ebf1854458e625b64831c431c64b4a9f3dd8ca2b03c7867e0e8d8fb` (verified)
Status: **DRAFT — for Codex and owner review, not started**

`Iron Plan: ALIGNED` — §7.2 "explicit reconciliation of interrupted effects"
through the existing kernel and scheduler; §4 invariants 3, 7 and 8.

## Recommendation

**Keep `file.write` with `expected_sha256` fenced; land the two cheap pieces first.**
An independent design review (Momus, 2026-09-05) rejected the reconciler as first
sketched with five CRITICAL, four high, two medium and one low finding; all
twelve are answered below, and one CRITICAL (**Q2**) is not solvable inside this
packet's axis at all. The two cheap, independently useful pieces are **D1** (derived
reserved names) and **D2** (the pre-effect intent bound to the START receipt);
both are pure improvements to the fenced path and neither lifts the fence.
Cerberus F3 is already largely closed in the tree by
`ComputerService._store_failure_record` (**D5**), which this packet reads rather
than re-proposes. Everything downstream depends on an unresolved kernel question
(**Q2**).

## Primary acceptance claim

After a crash anywhere in the two-rename replacement, a restart can either prove
the final host state and settle it with a receipt, or refuse visibly with
`reconciliation_required` — and in no case guess, and in no case let a later
unfenced `file.write` destroy the only remaining copy of the owner's bytes.
Only when the whole matrix below is green does `RELEASE_REPLACE_FENCED`
(`daedalus/kernel/policy/computer.py:55`) flip to `False`.

## Scope

In scope: `daedalus/runtimes/computer_files.py` (reserved-name derivation only:
`_replace`, `computer_files.py:897-1054`), `daedalus/runtimes/computer.py`
(intent record before `_dispatch`, failure record on the exception path, the
reconciler call site, the projection at `computer.py:72-83`),
`daedalus/kernel/policy/computer.py` (the fence flag and an unreconciled-target
refusal), `daedalus/orchestration/ikarus/computer_schedule.py` (call the
reconciler from the existing `_recover_continuations` seam, `computer_schedule.py:484`),
`tests/runtimes/test_computer_files.py`, `tests/runtimes/test_computer_service_files.py`,
`tests/kernel/test_computer_policy.py`, `docs/IKARUS_COMPUTER.md`, this packet.

Forbidden: any new scheduler, effect authority or event store (§13, §7.2); any
new terminal outcome in `daedalus/kernel/effects.py:45`; any bespoke reader over
`control/computer-effect-evidence` outside `effect_replay`; `computer_context.py`;
`apps/web`; the master plan, the amendment chain, `AGENTS.md`, `CLAUDE.md`;
the adapter's boundary/traversal logic (owned by G1-IKARUS-24).

## Crash points of the two-rename protocol

`_replace` (`computer_files.py:897`) opens a `hold` handle on the original
(`:906`), re-hashes it under that handle (`:913-914`), creates the temporary
(`:916`), writes and `fsync`s the file data (`:930-931`), renames
original→backup with `replace=False` (`:936`), then temporary→public with
`replace=False` (`:940`), then unlinks the backup through the hold handle
(`:992`). Reserved names are `.daedalus-internal-<16 hex>.daedalus-tmp` and
`….daedalus-backup` (`computer_files.py:55-57`, `:907-908`).

| # | Crash point | Host state left behind |
| --- | --- | --- |
| C0 | before `:916` | nothing; original intact |
| C1 | after `:916`, before `:936` | original intact **plus** an orphan temporary (possibly short) |
| C2 | between `:936` and `:940` | **public name missing**; original bytes live only under the backup; temporary present |
| C3 | after `:940`, before `:992` | new bytes public; original bytes still under the backup; temporary consumed |
| C4 | after `:992`, before the receipt at `computer.py:292` | correct final state, no terminal receipt — execution stays `STARTED` |
| C5 | during post-effect verification (`computer_files.py:1149`) | same as C4; the adapter's own report is lost |

In-process, C1–C3 are resolved from the two still-open handles
(`computer_files.py:946-986`) and reported as `ComputerFileEffectUncertain` /
`ComputerFileInterrupted` with `recovery_paths` (`:1007`, `:1037-1054`). **After
process death those handles are gone and the reserved names are unrecoverable**:
they were minted by `secrets.token_hex(8)` into local variables only.

Open adapter item (G1-IKARUS-24's lane, blocks A3/A7). `_verify` and `_absent`
now report a host `OSError` instead of letting it escape
(`computer_files.py:816-833`), but `_replace`'s rollback verification still calls
`self._matches` under `except ComputerRefused` alone
(`computer_files.py:1017-1019`), so an `OSError` there propagates untyped past
`_replace` — `_write` converts only `KeyboardInterrupt` — and the service then
classifies a real, ambiguous host state through the generic branch. The
reconciler's C2 evidence is only as good as this typing.

## Contracts and behavior

**D1 — derived, not random, reserved names.** Replace `secrets.token_hex(8)`
(`computer_files.py:907-908`) with a keyed derivation over identity the canonical
store already holds: `HMAC(k, execution_id ‖ operation_sha256 ‖ "tmp"|"backup")`,
truncated to 16 hex. `execution_id` is deterministic —
`f"{lease.lease_id}-exec-{key}"` (`daedalus/kernel/offload_lease.py:2288`) over
`lease_id = "computer-" + canonical_sha({"mission","attempt"})[:32]`
(`computer.py:243,254`) — and `operation_sha256` (`computer.py:242`) binds tool,
arguments (target path, `expected_sha256`) and policy digest. A reconciler
holding the persisted start receipt recomputes both names with **no new state**.
Keying (not a plain digest) stops a concurrent in-workspace writer precomputing
and squatting a reserved name; squatting is fail-closed either way (both renames
use `replace=False`), so an unkeyed digest is a fallback — see **Q1**.

**D2 — the START receipt is the intent record.** `begin_effect`
(`computer.py:267`) already writes a durable start receipt before `_dispatch`
(`computer.py:274`). Bind the replacement tuple to it: `{target,
expected_sha256, new_content_sha256, temporary_name, backup_name,
workspace_identity, policy_sha256}`. A receipt carries only `detail_sha256`
(`daedalus/kernel/effects.py:864-890` stores the digest, never the payload), so
the tuple goes to `store_canonical_json` (`daedalus/kernel/artifacts.py:63`)
under `control/computer-artifacts` — the CAS the COMPLETED path already uses at
`computer.py:291-292` — and its digest binds into the start receipt. No second
store.

**D3 — restart reconciliation on the existing seams.** The only permitted reader
is `inspect_effect_execution(authorization, execution)`
(`daedalus/kernel/effect_replay.py:578`), a strict read-only projection returning
`EffectExecutionReplaySnapshot.pending_reconciliation` (`effect_replay.py:88`,
true iff `STARTED`). There is no enumeration API (the only `STARTED` query is
embedded at `effects.py:810`), so the reconciler re-derives the execution
identity per known mission/attempt instead of scanning the ledger. It is invoked
from the existing restart scan `_recover_continuations`
(`daedalus/orchestration/ikarus/computer_schedule.py:484`), which already runs
first inside `dispatch_due_computer` (`computer_schedule.py:507-510`) and already
emits `reconciliation_required` (`computer_schedule.py:501`) — never from
`ComputerService.__init__`, which sits outside the kill switch (**D6**, **Q4**).

Order per pending execution, all under `ExclusiveFileLock` (`computer.py:247`),
all through the handle-anchored parent:

1. hash the public name, the derived temporary and the derived backup;
2. `{public == new_content_sha256, backup == expected_sha256, temp absent}` →
   **completed**: the effect finished (C4/C5); settle, delete nothing;
3. `{public absent, backup == expected_sha256}` (C2) → **restore**: rename
   backup→public with `replace=False`; then re-verify and settle as *restored*;
4. `{public == new_content_sha256, backup == expected_sha256, temp present}`
   (C3) → **completed after backup cleanup**, only if the public hash matched
   first;
5. `{public == expected_sha256, temp present}` (C1) → remove the temporary,
   settle as *restored*;
6. **anything else** — a hash that matches neither, a missing backup, an
   ambiguous pair, a workspace whose identity changed — stops with
   `reconciliation_required`, touches nothing, and names the reserved paths.

**A reserved name on disk is never a write primitive.** Restore is gated on
`sha256(backup) == expected_sha256` *from the start receipt*; *completed* may be
claimed only when the public name hashes to `new_content_sha256` **and** the
backup still hashes to `expected_sha256`. Nothing is deleted before the
surviving copy has been proven by hash.

**D4 — outcome vocabulary.** The kernel's terminal states are exactly
`{COMPLETED, FAILED, CANCELLED}` (`daedalus/kernel/effects.py:45`); this packet
mints none. *restored* settles as `CANCELLED`, *completed* as `COMPLETED`,
*uncertain* stays `STARTED` and is surfaced to the owner as
`reconciliation_required` — the vocabulary lives in the CAS detail record, not
in the ledger's outcome column.

**D5 — F3 is already partly closed; this packet reads that seam, it does not
re-propose it.** Measured 2026-09-05: `ComputerService._store_failure_record`
(`computer.py:355-379`) persists a `daedalus-computer-failure/1` record —
`error_type`, bounded message, `effect_state`, the adapter's `recovery_paths`
(`computer_files.py:1007`, `:1037-1054`), `external_started`, `dispatched`,
`provably_no_effect`, `policy_sha256` — into `control/computer-artifacts` through
`store_canonical_json`, secret-floor filtered, whenever a start receipt exists
(`computer.py:326-336`). The CANCELLED terminal binds it as `detail_sha256`
(`computer.py:339-341`, falling back to the old class-name digest only when the
store failed) and the response carries `evidence.failure_record`
(`computer.py:348-349`). Cerberus F3 is therefore closed for **in-process**
failures.

What it does not close, and what this packet must add: the record is written by
the dying process. On C2–C5 there is no record at all, and on the
`reconciliation_required` path the record is bound to no terminal receipt — it
reaches the caller only in the in-memory response. The reconciler therefore
cannot depend on it; it depends on **D2**, the *pre-effect* intent bound to the
START receipt (target, `expected_sha256`, new-content digest, backup and
temporary names). D5's remaining work is to read the failure record when one
exists and to reconcile the two when they disagree.

**D6 — the unreconciled-target write fence.** `file.write` *without*
`expected_sha256` is unfenced today (`daedalus/kernel/policy/computer.py:92-93`)
and would create a new file at a path whose only surviving copy sits in an
orphan backup. Every write to a path with an unreconciled open effect must be
refused, and **that refusal must be derivable without the reconciler having
run** — the reconciler cannot run when the kill switch is engaged, on a
non-Windows host (`computer_files.py:685`), or after a policy change
(`computer.py:220-221`). The fence therefore reads the pending start receipt
via `effect_replay`, not the reconciler's output.

**D7 — durability model, stated honestly.** `os.fsync(fd)`
(`computer_files.py:931`) syncs the temporary's *data*; the two renames (`:936`,
`:940`) and the parent directory are **never** synced. Under power loss the
directory entries can be lost independently of the file data, so the reachable
states include *public name, backup and temporary all absent* — the owner's bytes
are gone and no reconciler recovers them. This packet claims reconciliation
against **process** death only. Directory-fsync is a separate measurement.

**D8 — policy drift across a restart.** Reconciling under the *current* policy
executes an effect the owner never authorized; under the *stored* policy it
resurrects a possibly revoked grant. This packet picks **refuse**: if
`load_policy(...).digest != start_receipt.policy_sha256`, the reconciler reports
`reconciliation_required` with a policy-drift reason and performs no host effect.
A restore after a revoked grant is an owner action, not an automatic one.

**D9 — telling the owner.** Reserved names are refused as request paths
(`computer_files.py:708-709`) and excluded from `file.list`
(`computer_files.py:1073-1076`, counted only in `withheld`). After a crash the
owner's bytes are unreachable through every Ikarus surface with a bare
`withheld: 1` as the sole hint. The `reconciliation_required` result must name
the target path, the reserved paths and the two hashes, and must reach the
autonomy/inspection surface (G1-IKARUS-23), not only the schedule return value.

## Acceptance matrix

Each row is a deterministic test; fault injection uses an injected failure at
the exact named line, followed by a fresh service over the same authority root.

| # | Row | Acceptance |
| --- | --- | --- |
| A1 | C0 fault (before `:916`) + restart | no reserved name exists; original hash unchanged; execution settles `CANCELLED`; no host effect |
| A2 | C1 fault (after `:916`) + restart | temporary removed; public hash `== expected_sha256`; outcome *restored* |
| A3 | C2 fault (between `:936` and `:940`) + restart | public restored from backup by hash; backup gone; outcome *restored* |
| A4 | C3 fault (after `:940`) + restart | public `== new_content_sha256`, backup removed only after both hashes proven; outcome *completed* |
| A5 | C4/C5 fault (after `:992`) + restart | no host effect at all; terminal receipt written; outcome *completed* |
| A6 | Workspace changed meanwhile | parent/workspace identity differs from the start receipt → `reconciliation_required`, zero effect |
| A7 | Hash mismatch at reconciliation | backup hashes to neither `expected_sha256` nor `new_content_sha256` → `reconciliation_required`, nothing deleted, nothing renamed |
| A8 | Reconciliation refused by policy | stored `policy_sha256` ≠ current (D8) → `reconciliation_required`; also when the tool grant was revoked |
| A9 | Kill switch during reconciliation | switch engaged before/at the lease checkpoint (`computer.py:249-256`) → no rename, no delete, execution stays `STARTED` |
| A10 | Idempotent double reconciliation | running the reconciler twice over the same root produces the same terminal receipt digest and no second host effect (`begin_effect` already returns `execute=False`, `computer.py:268-269`) |
| A11 | D6 fence | an unfenced `file.write` (no `expected_sha256`) to a path with an unreconciled open effect is refused — with the kill switch engaged, on a non-Windows host, and after a policy change |
| A12 | D1 derivation | reserved names recomputed from a persisted start receipt alone equal the names the adapter used; two different operations never collide |
| A13 | D2 intent | the START receipt's `detail_sha256` resolves in CAS to the replacement tuple; a reconciler given only that record reproduces both reserved names and both hashes |
| A14 | D5 regression | the landed failure record (`computer.py:355-379`) keeps carrying `effect_state` and `recovery_paths`, and the reconciler prefers the START intent when the two disagree |
| A15 | Adapter typing | an injected host `OSError` at `computer_files.py:1017-1019` is reported as a typed uncertain outcome, not propagated untyped (G1-IKARUS-24 lane) |
| A16 | Baseline preserved | the G1-IKARUS-25 measurement (153 passed) still passes with the fence still up |

**Refusal tests.** Reserved name squatted by a third party before `:936` →
refusal before any effect, original intact. Reserved name supplied as a request
path → `computer_files.py:708-709` refusal. Reconciler on a non-Windows host →
refusal, no effect. Reconciler given a start receipt whose signature or scope
fails at the retained start instant → `effect_replay` refusal, no effect.
Reconciler concurrent with a live operation → `ExclusiveFileLock`
(`computer.py:247`) serializes and the second reports `reconciliation_required`.

## Evidence, expected failures and review

Baseline to reproduce before building: the G1-IKARUS-25 measurement
(`tests/kernel/test_computer_policy.py`, `tests/runtimes/test_computer_service.py`,
`tests/runtimes/test_computer_service_files.py`, the fence-inventory assertion,
`tests/test_council_vendors.py` — 153 passed) plus a RED run proving each A-row
fails before the change. **Nothing in this packet has been built or measured.**

Provenance of the two tree facts folded in on 2026-09-05: `_store_failure_record`
and the `computer_files.py:1017-1019` typing gap were READ AND VERIFIED here at
`585b7ea4` with the working tree dirty; the reported adapter suite result (86
passed, adapter hash `22af4d6c…`, typed `_mkdir` interruption and `OSError`
reporting in `_verify`/`_absent`) is INHERITED from the concurrent G1-IKARUS-24
session and was not re-run by this packet's author. Every line reference above
was re-verified against the dirty tree after that session's edits landed; they
will move again if it edits further.

Expected failures, accepted and not fixed here: power loss (D7); POSIX in every
form — the adapter refuses effects off Windows (`computer_files.py:685`) and
its private move is `link`+`unlink`, so a crash there can leave `st_nlink == 2`
residue; network volumes, mount-point traversal and non-local filesystems remain
unmeasured (G1-IKARUS-24); a workspace an owner edits by hand between crash and
restart lands in A7 and stays uncertain by design.

Review chain: this draft goes to Codex as an independent vendor before any
build, then to the owner. A model verdict is advisory and promotes nothing.

## Migration and rollback

`RELEASE_REPLACE_FENCED = True` (`daedalus/kernel/policy/computer.py:55`) and
the projection that drops `expected_sha256` from the offered schema
(`computer.py:72-83`) stay exactly as they are until the whole matrix is green;
D1 and D5 land under the standing fence and change no admitted shape. Rollback
is re-raising the flag; the derived names and the failure record are inert
without it. No completed effect, lease, receipt or evidence record is ever
rewritten — including the ones a crash left `STARTED`.

## Review questions for the independent reviewer

Momus's three decisive questions, verbatim:

1. What persisted artifact written before the first rename binds the tuple, and
   can it be the START receipt?
2. Can the kernel settle a start receipt whose lease and process are gone?
3. What stops the next unfenced `file.write` from destroying the orphaned backup
   when the switch is engaged or the host is not Windows?

Also:

- **Q1** — is there a durable key for D1's HMAC that is not a new store, or does
  the design fall back to an unkeyed digest and accept reserved-name squatting as
  a fail-closed denial of service?
- **Q2 (blocking)** — `finish_effect` (`daedalus/kernel/runtime_effects.py:541`)
  verifies `start_receipt.lease_sha256` against a **live** `capability.lease`,
  which is gone after a crash. Either the reconciler acquires a *fresh* lease
  (leaving the crashed execution `STARTED` forever, so `pending_reconciliation`
  never clears and A5/A10 cannot be satisfied as written), or the kernel grows a
  settlement path for an orphaned start receipt — a different architectural axis
  belonging in its own packet (§10). **Which?** This packet cannot be built until
  it is answered.
- **Q3** — is C3's ordering safe against an adversary who rewrites the public
  name between hashing it and deleting the backup?
- **Q4** — does routing the reconciler through `_recover_continuations`
  (`computer_schedule.py:484`) — which today reports `metadata_only: True` —
  misrepresent an operation that performs a real host rename?

## What this packet does NOT claim

No POSIX effects: the adapter refuses them (`computer_files.py:685`) and
this design is Windows-only. No promotion, no merge, no gate closure; a green
matrix authorizes flipping one release flag and nothing else. No security
guarantee: the adapter is a trusted host seam, not a sandbox, and a
reconciliation receipt is evidence of what was observed, not proof that no
other process interfered. No crash-consistency against power loss (D7). No
claim that the Iron Plan §7.2 reconciliation obligation is discharged for any
capability other than `file.write` replacement.
