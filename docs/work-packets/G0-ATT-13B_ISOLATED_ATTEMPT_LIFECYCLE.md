# G0-ATT-13B — Persisted Isolated Attempt Lifecycle

## Purpose

This packet extends the repository's **single canonical Event Store** with the
start/terminal lifecycle for checkout-external Attempts. It consumes the bounded
source-tree CAS from G0-ATT-13A and prepares an external workspace, but invokes
no provider, runtime, Docker process, Effect Lease, evaluator or promotion path.

## Canonical authority

The pre-review implementation introduced an independent `attempt_starts` /
`attempt_terminals` SQLite database. A context-separated adversarial
counter-review rejected that shape because Gate 0 requires one event spine and
forbids a new state store outside the canonical kernel.

The corrected implementation is a facade over `SpineLedger`:

- one canonical `attempt.lifecycle` intent stores `AttemptStartRecord`;
- one terminal spine event stores `AttemptTerminalReceipt`;
- a partial unique index on the existing `intents` table serializes the one
  start winner for each namespaced Attempt effect key;
- no Attempt-specific table or second SQLite authority exists;
- callers may pass an existing writable `SpineLedger` instance, and the facade
  retains that exact object;
- a read-only `SpineLedger` is refused rather than silently bypassed for schema
  installation or lifecycle writes;
- source trees, reports and candidate trees remain authoritative only when they
  are re-read from the selected `SourceTreeStore`.

The implementation is split strangler-style along real responsibilities:

- `attempt_contracts.py` owns canonical records and shared invariants;
- `attempt_spine_reader.py` owns the strict raw Event-Store projection;
- `attempt_ledger.py` owns lifecycle transitions through `SpineLedger`;
- `attempt_workspace.py` owns checkout-external materialization;
- `attempts.py` remains a thin compatible import surface.

## Raw Event-Store integrity

A second context-separated adversarial pass found that reading terminal state
only through the ordinary `SpineLedger` projection would parse event detail
before this packet could reject duplicate JSON keys or noncanonical bytes. The
lifecycle now reads the same canonical spine tables through a query-only strict
projection while `SpineLedger` remains the sole writer and transition authority.

The projection rejects:

- malformed or duplicate-key intent payloads and event detail;
- noncanonical JSON bytes;
- payload-digest substitution;
- missing start events;
- more than one terminal event;
- unknown terminal states;
- wrong terminal detail shapes;
- terminal `effect_id` values that do not bind the receipt digest.

## Ordering

For one canonical `AttemptContract`, the coordinator performs this order:

1. verify the input manifest from the selected CAS;
2. verify exact base-revision equality;
3. commit the canonical start intent to the Event Store;
4. return without effects on terminal or pending replay;
5. materialize the exact input tree into a new external workspace only for the
   single fresh winner.

The lifecycle never writes candidate bytes into the primary checkout. Workspace
parent, primary checkout and CAS root must be pairwise disjoint where relevant.

## Restart and replay semantics

- Exactly one concurrent `begin` returns `execute=true`.
- A persisted start without a terminal receipt is an unknown outcome and returns
  `pending_reconciliation`; it is never materialized or executed again.
- A terminal replay returns the first persisted receipt and does not expose a
  workspace.
- Replay comparison ignores a newly supplied observation timestamp but requires
  identical start/receipt identifiers and all immutable subject material.
- A failed or cancelled Attempt can only be retried under a new canonical
  `attempt_id`; the old Attempt remains terminal.
- `KeyboardInterrupt` and `SystemExit` are not converted into known failures;
  the durable start remains pending.

## Terminal evidence

`AttemptTerminalReceipt` binds the exact start digest, Attempt identity, input
tree, outcome, CAS-backed report, optional candidate source tree, source
revision and provenance. A successful outcome requires a candidate tree.
Terminal replay re-reads report and candidate objects from the selected CAS and
checks that the spine event's `effect_id` equals the receipt digest.

## Materialization failure

A normal materialization exception becomes a deterministic, CAS-backed
`faulted` terminal receipt before the coordinator raises
`AttemptWorkspaceError`. A process-level abort remains pending because the
system cannot prove whether effects occurred.

## Adversarial review

Behavioral and context-separated review cover:

- start-before-materialization order;
- pending and terminal replay without rematerialization;
- timestamp-independent idempotency;
- concurrent start serialization;
- stale input and candidate revisions;
- primary-checkout immutability and root disjointness;
- foreign CAS input, report and candidate refusal;
- selected-store and event-spine substitution;
- read-only spine refusal;
- duplicate-key, noncanonical and payload-digest tampering;
- multiple or unknown terminal events;
- terminal `effect_id` substitution;
- terminal artifact corruption on replay;
- constructor-shaped authority bypasses;
- normal materialization faults versus process aborts;
- stable compatibility imports after the responsibility split;
- static refusal of a second Attempt-specific state store.

The bounded mutation campaign attacks pending re-execution, store substitution,
changed replay material, success without a candidate, process-abort
terminalization, skipped CAS checks, event-spine removal, extra terminal events,
read-only spine misuse and terminal digest binding.

These passes were performed from separate review contexts within the same
builder session. They are useful builder/adversarial evidence but do **not**
satisfy the Master Plan's required independent reviewer step. That step remains
open until a genuinely separate reviewer examines the exact diff and executable
evidence.

## Deliberate remaining Gate-0 boundary

This packet does not execute the Attempt. The next dependent packet must bind a
persisted Effect Lease, Runtime Manifest and current Conformance Receipt to the
fresh `AttemptStartRecord`, run only inside the prepared workspace through the
selected sandbox boundary, capture the candidate tree and complete the same
Event Store record. Pending reconciliation remains an explicit recovery path,
not an automatic retry.

GitHub Actions issue #67 remains an external exact-head execution blocker while
hosted jobs terminate before Step 1 without logs or artifacts. Such runs are not
represented as test, mutation, platform, packaging or Gate evidence.

Iron Plan: **ALIGNED BY SCOPE; EXECUTION PENDING**  
Iron Gate: **0**  
Promotion: **not requested**
