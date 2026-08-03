# G0-PRM-12C — Persisted Promotion Receipts

## Gate and parent

- Active gate: Gate 0
- Exact parent: `dae260ee475819289bc81cdeaa76a9e948ae1dae`
- Parent branch: `g0/live-promotion-seam-linear`
- Promotion: not requested

## Purpose

This packet adds the inert persistence authority required around the sealed
promotion seam. It records one exact promotion start before any repository
mutation and one immutable terminal `PromotionReceipt` afterward. It does not
create worktrees, apply candidates, resolve Git refs, merge branches, consume an
Effect Lease, or issue OwnerApproval.

## Start authority

`PromotionLedger.begin` accepts a canonical `PromotionAuthorization`, a stable
start ID, and an externally measured primary-checkout fingerprint. Before
persistence it recomputes the authorization digest over promotion ID, candidate,
evidence, source revision, target ref, authorized live target revision and
approval-consumption digest.

The start record binds:

- promotion and start IDs;
- authorization and approval-consumption digests;
- candidate and EvidencePacket digests;
- source revision, target ref and authorized target revision;
- the primary-checkout fingerprint measured before mutation;
- the first persisted start time.

A `BEGIN IMMEDIATE` transaction commits this record before returning
`execute=true`.

## Restart and replay semantics

The first exact start returns `PromotionBeginResult(execute=true)`. Every exact
replay returns `execute=false`:

- without a terminal receipt it is `pending_reconciliation=true` and must never
  automatically re-run the promotion;
- with a terminal receipt it returns that exact persisted completion.

Retry wall-clock time is not part of the replay identity. A restarted process
may present the same stable authority and start ID at a later time and receives
the original start record. Changed authorization, start ID, primary fingerprint,
promotion ID or approval consumption is refused.

## Terminal receipt

The canonical `daedalus.promotion-receipt/1.0.0` contract binds:

- the exact persisted start and authorization;
- approval consumption, candidate and EvidencePacket;
- source revision, target ref and authorized target revision;
- terminal report digest;
- integration branch and revision when successful;
- primary-checkout fingerprints before and after;
- start/completion timestamps and complete provenance.

Allowed outcomes are `succeeded`, `refused`, and `faulted`.

A successful receipt requires exactly one successful promoted result, no refusal
or ungated result, no cleanup error, and an integration branch plus exact
revision. A refusal cannot contain a promoted result. If the primary checkout
fingerprint changes, the outcome must be `faulted`; a fault with an unchanged
primary checkout still requires explicit fault or cleanup evidence.

One terminal receipt is permitted per promotion/start. Canonical receipt JSON,
report JSON, SQLite columns, receipt digest, report digest and semantic outcome
are all revalidated when read. Exact terminal replay returns the prior record;
a changed receipt ID, report or outcome is refused.

## Persistence boundary

The ledger uses:

- SQLite WAL;
- `synchronous=FULL`;
- foreign keys and busy timeout;
- `BEGIN IMMEDIATE` for starts and completions;
- uniqueness over promotion/start/authorization/approval consumption and
  terminal receipt identity;
- explicit pending-start enumeration for crash reconciliation.

Corrupt SQLite, malformed JSON, noncanonical bytes, column/JSON disagreement,
forged authorization digest and receipt/report digest tampering fail closed.

## Independent review and mutations

Builder tests cover canonical round trips, start/terminal replay, changed
identity refusal, forged authorization, restart recovery, immutable report
snapshots, malformed timestamps, primary-checkout mutation, terminal report
semantics, database corruption and concurrent starts/completions.

A separate review checks schema parity, no repository/provider effect imports,
SQLite durability primitives, replay source decisions and mandatory binding
fences.

The bounded mutation campaign attacks:

1. forged authorization acceptance;
2. `execute=true` on start replay;
3. primary-checkout mutation acceptance;
4. omission of persisted receipt-digest verification;
5. success without integration identity;
6. an empty or contradictory success report.

## Dedicated verification request

The packet requests:

- compile-all and Iron Plan verification;
- focused receipt, promotion, approval, evidence, effect-lease and gate-report
  tests;
- bounded mutation execution;
- full repository suite;
- Ubuntu and Windows on Python 3.10 and 3.12 with two hash seeds;
- isolated-wheel import, schema and minimal persistence smoke.

GitHub Actions issue #67 may still terminate hosted jobs before Step 1. A run
without executed steps, logs and artifacts is not evidence and cannot close this
packet.

## Deliberate remaining boundary

The live promotion seam is not wired to this ledger in this packet. A dependent
packet must:

1. measure a deterministic primary-checkout fingerprint under the promotion
   lock;
2. persist `begin` before entering the integration mutation helper;
3. refuse automatic execution when `execute=false`;
4. reconcile pending starts after crashes;
5. resolve the exact integration revision and persist the terminal receipt;
6. expose the receipt without merging or automatically promoting anything.

Effect-Lease consumption and central effect-registry wiring remain separate
Gate-0 migrations. No OwnerApproval is generated here.
