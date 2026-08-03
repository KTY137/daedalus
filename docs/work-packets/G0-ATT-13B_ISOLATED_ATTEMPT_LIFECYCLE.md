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

- `attempt_clock.py` owns trusted monotonic lifecycle observation time;
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
The projection opens SQLite with URI `mode=ro`; read-only inspection cannot
create a missing Event Store as a side effect.

The projection rejects:

- malformed or duplicate-key intent payloads and event detail;
- noncanonical JSON bytes;
- payload-digest substitution;
- missing start events;
- more than one terminal event;
- unknown terminal states;
- wrong terminal detail shapes;
- terminal `effect_id` values that do not bind the receipt digest.

## Trusted lifecycle time

The predecessor API accepted `started_at` and `completed_at` from callers. That
made security-relevant lifecycle chronology caller-authored. The compatibility
keywords remain accepted so dependent source does not break, but their values
are explicitly discarded and never enter a contract or provenance record.

`AttemptLifecycleClock` samples trusted UTC wall time once and advances it from
`time.monotonic_ns`. It maintains a strict nondecreasing floor and can floor a
terminal observation above a persisted start after restart. Start and terminal
provenance timestamps must exactly equal their corresponding trusted lifecycle
timestamps. The strict Event-Store projection additionally refuses a start time
that follows its `INTENDED` event or a completion time that follows its terminal
event. A terminal receipt must be strictly later than its bound start.

Adversarial tests pass far-future and far-past compatibility timestamps and
prove they have no authority. Repacked records that consistently change both the
embedded lifecycle time and provenance time are still refused against the
canonical Event-Store event time.

## Workspace preflight and ordering

The original constructor created `workspace_parent` before checking whether it
was nested under the primary checkout or CAS. A malformed path could therefore
mutate a protected tree before being refused.

The corrected constructor:

1. resolves and validates the primary checkout and CAS roots read-only;
2. rejects a leaf symlink, broken symlink or non-directory workspace target;
3. resolves the prospective workspace path without creating it;
4. checks prospective disjointness from primary checkout and CAS;
5. creates the workspace parent only after those checks;
6. resolves and checks the created directory again to catch redirected parent
   symlinks or topology changes.

For one canonical `AttemptContract`, preparation then performs this order:

1. verify the input manifest from the selected CAS;
2. verify exact base-revision equality;
3. commit the canonical start intent to the Event Store;
4. return without effects on terminal or pending replay;
5. materialize the exact input tree into a new external workspace only for the
   single fresh winner.

Tests prove refused primary-nested and CAS-nested paths are not created, the
primary tree digest is unchanged, parent-symlink redirects are refused before
child creation, and broken workspace symlinks remain untouched.

## Restart and replay semantics

- Exactly one concurrent `begin` returns `execute=true`.
- A persisted start without a terminal receipt is an unknown outcome and returns
  `pending_reconciliation`; it is never materialized or executed again.
- A terminal replay returns the first persisted receipt and does not expose a
  workspace.
- Replay comparison ignores newly observed trusted time but requires identical
  start/receipt identifiers and all immutable subject material.
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

## Effect inventory blocker

The stable kernel API now exposes three effectful methods:

- `AttemptLedger.begin` commits the start intent;
- `AttemptLedger.complete` commits the terminal receipt;
- `IsolatedAttemptCoordinator.prepare` commits a start and materializes the CAS
  tree into an external workspace.

The canonical effect registry and static discovery classifier do not yet contain
these exact class methods. They therefore remain a Gate-0 blocker rather than
being silently treated as read-only internals. The machine-readable
`G0-ATT-13B_EFFECT_INVENTORY.json` records their exact targets, effects, guard
contracts, anchors and required migration. A dedicated test requires each target
to have exactly one canonical registry row or one explicit open blocker.

The honest minimum registry state is `local_guards`; these methods must not be
marked `central` until a dependent packet mechanically composes the persisted
Effect Lease, Runtime Manifest, current Conformance Receipt and selected sandbox
boundary. The blocker artifact may be removed only when the canonical Gate
report itself emits equivalent rows and no unregistered finding remains.

## Adversarial review

Behavioral and context-separated review cover:

- start-before-materialization order;
- pending and terminal replay without rematerialization;
- trusted monotonic time and caller-time rejection;
- provenance-time and Event-Store-time causal binding;
- concurrent start serialization;
- stale input and candidate revisions;
- protected-tree preflight before workspace creation;
- primary-checkout immutability and root disjointness;
- parent and leaf symlink redirection;
- foreign CAS input, report and candidate refusal;
- selected-store and event-spine substitution;
- read-only spine refusal and no-create inspection;
- duplicate-key, noncanonical and payload-digest tampering;
- multiple or unknown terminal events;
- terminal `effect_id` substitution;
- terminal artifact corruption on replay;
- constructor-shaped authority bypasses;
- normal materialization faults versus process aborts;
- stable compatibility imports after the responsibility split;
- static refusal of a second Attempt-specific state store;
- explicit inventory of newly exposed effectful kernel methods.

The bounded mutation campaign attacks pending re-execution, store substitution,
changed replay material, success without a candidate, process-abort
terminalization, skipped CAS checks, event-spine removal, extra terminal events,
read-only spine misuse, read-inspection database creation, forged lifecycle
time, detached provenance time, removed event-time causality, protected-tree
creation before refusal, symlink acceptance, monotonic-floor removal and
terminal digest binding.

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

The new lifecycle methods must also be added to the canonical effect registry
and static discovery classifier before this packet can be considered structurally
complete. They remain explicitly unregistered in the machine-readable blocker
artifact; no security boundary is claimed.

GitHub Actions issue #67 remains an external exact-head execution blocker while
hosted jobs terminate before Step 1 without logs or artifacts. Such runs are not
represented as test, mutation, platform, packaging or Gate evidence.

Iron Plan: **ALIGNED BY SCOPE; EFFECT INVENTORY AND EXECUTION OPEN**  
Iron Gate: **0**  
Promotion: **not requested**
