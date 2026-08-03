# G0-RTC-06O — Runtime-Trust Writer Contention Fault

## Objective

Execute the canonical `runtime.trust-ledger.lock-contention` Linux-host scenario
against the production runtime provider broker, runtime-bound effect authority,
runtime-trust ledger format and effect ledger. The fault proves that a provider
value which has already been computed is withheld when post-invoke trust
verification cannot acquire the trust writer transaction, and that the durable
effect execution becomes `CANCELLED` rather than remaining `STARTED` or becoming
`COMPLETED`.

This packet changes no production provider entrypoint, authority key, trust root,
attestation policy, merge target or promotion path.

## Authenticated setup

The fixture creates two distinct SQLite authorities under one temporary root:

- one bounded `RuntimeTrustLedger` using the production schema, HMAC record
  format, WAL mode, foreign keys and `synchronous=FULL`;
- one unmodified production `EffectLeaseLedger`.

To isolate contention rather than external admission, the fixture seeds exactly
one authenticated `ACTIVE` runtime-trust row through the production record
constructor and insert seam. It does not patch or invoke
`verify_production_runtime_envelope`, does not claim external trust and does not
export the seeded row as trusted evidence.

The fixture then:

1. defines one synthetic runtime-bearing `CENTRAL` entrypoint;
2. creates an exact `EffectLeaseRequest`, `PolicyDecision` and bounded
   `EffectScope`;
3. issues a signed `RuntimeBoundEffectLease` through the production issuance
   function, which re-reads and authenticates the seeded row;
4. constructs a real `RuntimeBoundEffectAuthorization` with separate trust and
   effect ledgers;
5. calls the production `run_runtime_provider()` broker.

The test-only trust-ledger subclass overrides only construction and connection
setup. Its sole semantic change is a 125 ms SQLite busy timeout so the fault is
bounded. All broker, trust verification, effect grant/start/terminal and output
release decisions remain production code.

## Exact injection

The provider callback creates a random opaque return value, opens a second
connection to the trust database, executes `BEGIN IMMEDIATE`, proves
`in_transaction=true`, and returns while retaining that writer transaction.

The production broker has already persisted effect grant and `STARTED` before
calling the provider. Its first post-invoke runtime verification then attempts
the production `RuntimeTrustLedger.require_active()` transaction and reaches the
bounded SQLite busy timeout. The broker's existing trust-loss path persists a
`CANCELLED` effect terminal receipt before re-raising the SQLite failure. The
fixture releases the external writer lock only after the broker has returned or
raised.

## Pass invariant

The observation passes with terminal outcome `cancelled` only when all of the
following are exact:

1. scenario ID, digest, authority, executor locator and expected outcome match
   the protected runtime-fault catalog;
2. the external trust writer transaction is active before the provider returns;
3. the observed exception is a real `sqlite3.OperationalError` classified as
   SQLite `BUSY` or `LOCKED`, including extended error codes reduced to their
   base code;
4. elapsed time reaches the configured busy timeout minus a 25 ms clock
   tolerance and remains below five seconds;
5. the provider callback ran exactly far enough to compute its opaque value;
6. output-digest extraction never ran and no broker result/value was released;
7. the distinct production effect ledger contains the exact execution in state
   `CANCELLED`;
8. its terminal receipt has outcome `CANCELLED`, zero output digests and a
   non-null deterministic trust-loss detail digest;
9. the authenticated runtime-trust record remains unchanged and `ACTIVE` after
   the injected writer transaction is released;
10. canonical raw evidence does not contain the opaque provider value and stays
    below 64 KiB.

An inactive writer lock, unrecognized OperationalError, early return, output
extraction, released value, missing or non-cancelled terminal state, retained
output digest, changed trust row, premature timeout or excessive delay fails the
scenario.

## Evidence binding

The executor implementation digest binds:

- exact fixture bytes;
- exact production `daedalus.runtimes.broker` bytes;
- exact production `daedalus.runtimes.trust_store` bytes;
- exact runtime-bound authority bytes;
- exact production effect-ledger bytes;
- busy timeout and tolerance.

Raw evidence retains only scenario and implementation identities, SHA-256 of the
temporary trust/effect database paths, bounded timing, writer/contention flags,
exception module/type/numeric SQLite code, provider/output-release booleans,
terminal state/outcome/output count/detail presence and authenticated trust-row
state. It retains no provider value, output digest, SQLite exception text,
plaintext path, authority key or secret.

Published summaries hard-code:

- `trusted=false`;
- `attested=false`;
- `gate_closure_claimed=false`.

External `RuntimeFaultAttestation` from an admitted Linux-host authority remains
mandatory before this observation may enter the trusted Gate-0 matrix.

## Adversarial review

The separate review perspective verifies:

- one production broker call and no subprocess, shell, Docker or second provider
  launcher;
- the bounded trust subclass overrides only `__init__` and `_connect`, retains
  production PRAGMAs and closes on PRAGMA failure;
- setup creates one HMAC-authenticated active production record without patching
  the external envelope verifier;
- the provider acquires and proves `BEGIN IMMEDIATE` before returning;
- the competing lock remains held through the broker call;
- only `sqlite3.OperationalError` is classified as the expected host fault;
- extended SQLite codes reduce to `BUSY`/`LOCKED` base codes;
- pass depends on the full busy interval, withheld output, exact `CANCELLED`
  receipt, empty output set and unchanged trust record;
- evidence excludes output value, paths and exception text;
- implementation identity covers every production authority source;
- candidate output cannot claim trust, attestation or Gate closure.

Focused mutations target removal of the writer lock, moving rollback before the
broker call, weakening BUSY/LOCKED classification, shortening the elapsed-time
threshold, allowing output extraction or result release, accepting `STARTED` or
`COMPLETED`, accepting terminal output, dropping trust-record equality, omitting
production-source identity and enabling trust claims.

## Verification request

The dedicated workflow requests:

- Ubuntu and Windows;
- Python 3.10 and 3.12;
- `PYTHONHASHSEED=0` and `123456`;
- Iron Plan and compile-all;
- focused Effect Lease, runtime-bound lease, trust-store, broker, terminal-fence,
  host-runner, catalog and attestation suites;
- one real exact-head Linux SQLite contention execution with retained untrusted
  artifacts;
- the full repository suite;
- isolated wheel build/install/import.

GitHub Actions issue #67 remains an external exact-head verification blocker
while jobs terminate before their first step. Such runs are infrastructure
observations only and cannot establish a builder, package, platform, host-fault
or Gate verdict.

## Remaining boundary

Unknown-outcome reconciliation, both live-runtime envelope scenarios,
protected-CAS publication, external host attestation, remaining production
entrypoint centralization and the exact-head cumulative Gate-0 release report
remain open. This packet does not merge, promote or manufacture OwnerApproval.

Iron Plan: **ALIGNED by scope; exact-head execution required**  
Active gate: **Gate 0**  
Promotion: **not requested**
