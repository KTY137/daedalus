# G0-ATT-13B — Persisted Isolated Attempt Lifecycle

## Purpose

This packet adds the single Gate-0 start/terminal authority for isolated
Attempts. It consumes the bounded source-tree CAS from G0-ATT-13A and prepares a
checkout-external workspace, but deliberately invokes no provider, runtime,
Docker process, Effect Lease, evaluator or promotion path.

## Authority and ordering

`AttemptLedger` is bound at construction to one exact `SourceTreeStore` object.
It re-reads every input tree, report and candidate tree from that store. Typed or
digest-shaped objects are not sufficient evidence that an artifact exists.

For one canonical `AttemptContract`, the coordinator performs this order:

1. verify the input manifest from the selected CAS;
2. verify exact base-revision equality;
3. commit `AttemptStartRecord` with `BEGIN IMMEDIATE`;
4. return without effects on terminal or pending replay;
5. materialize the exact input tree into a new external workspace only for the
   single fresh winner.

The lifecycle never writes into the primary checkout. Workspace parent, primary
checkout and CAS root must be pairwise disjoint where relevant.

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

`AttemptTerminalReceipt` binds:

- the exact start digest;
- canonical Attempt and input-tree identities;
- outcome;
- a report artifact present in the selected CAS;
- an optional candidate source-tree manifest present in the same CAS;
- exact source revision and provenance.

A successful outcome requires a candidate source tree. Candidate and persisted
terminal artifacts are re-read on every replay, so later CAS corruption fails
closed rather than becoming trusted historical evidence.

## Materialization failure

A normal materialization exception is recorded as a deterministic, CAS-backed
`faulted` terminal receipt before the coordinator raises
`AttemptWorkspaceError`. A process-level abort remains pending because the
system cannot prove whether effects occurred.

## Adversarial review

The behavioral and context-separated review suites cover:

- start-before-materialization order;
- pending and terminal replay without rematerialization;
- timestamp-independent idempotency;
- concurrent start serialization;
- stale input and candidate revisions;
- primary-checkout immutability;
- pairwise root disjointness;
- foreign CAS input, report and candidate refusal;
- selected-store substitution;
- strict persisted-wire reparsing and SQLite tampering;
- terminal artifact corruption on replay;
- constructor-shaped authority bypasses;
- normal materialization faults versus process aborts.

The mutation campaign attacks pending re-execution, store substitution, changed
start replay, success without a candidate, process-abort terminalization,
terminal report verification and input-tree CAS verification.

## Deliberate remaining Gate-0 boundary

This packet does not execute the Attempt. The next dependent packet must bind a
persisted Effect Lease, Runtime Manifest and current Conformance Receipt to the
fresh `AttemptStartRecord`, run only inside the prepared workspace through the
selected sandbox boundary, capture the resulting candidate tree and complete
this ledger. Pending reconciliation remains an explicit operator/recovery
packet, not an automatic retry.

GitHub Actions issue #67 remains an external exact-head execution blocker while
hosted jobs terminate before Step 1 without logs or artifacts. Such runs are not
represented as test, mutation, platform, packaging or Gate evidence.

Iron Plan: **ALIGNED BY SCOPE; EXECUTION PENDING**  
Iron Gate: **0**  
Promotion: **not requested**
