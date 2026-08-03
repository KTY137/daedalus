# G0-RTC-06O — Runtime Trust Ledger Contention Fault

## Objective

Execute the canonical `runtime.runtime-trust.lock-contention` scenario against
the production runtime provider broker and production HMAC-authenticated
`RuntimeTrustLedger`.

The packet closes one fail-closed defect in the terminal runtime-trust fence:
SQLite BUSY/LOCKED failures during the post-provider fence previously escaped as
raw `sqlite3.OperationalError`. That path could withhold the Python return value
but leave the effect without the required persisted `CANCELLED` terminal state.
The broker now classifies SQLite failures at the trust-fence boundary as
`RuntimeProviderTrustFenceError`; the existing broker cancellation path then
persists `CANCELLED` before re-raising.

This packet does not create external runtime admission, attest the fault,
provision authority keys, merge, promote, or close Gate 0.

## Production change

`daedalus.runtimes.broker._finish_completed_under_runtime_fence()` now:

1. classifies SQLite errors while opening the trust authority as
   `RuntimeProviderTrustFenceError`;
2. classifies SQLite errors during `BEGIN IMMEDIATE`, authenticated row lookup,
   or trust-fence reads as `RuntimeProviderTrustFenceError`;
3. performs best-effort rollback without replacing the original failure;
4. leaves `RuntimeProviderStateError` and non-SQLite programming failures on
   their existing distinct paths.

`run_runtime_provider()` already catches only
`RuntimeProviderTrustFenceError`, writes a deterministic cancellation detail
digest, persists terminal outcome `CANCELLED`, and re-raises. Provider output is
therefore not returned.

The production `RuntimeTrustLedger` timeout remains 30 seconds. No production
configuration or lock semantics are weakened.

## Exact fault injection

The Linux-host fixture uses:

- the production broker;
- the production `RuntimeTrustLedger` record format, HMAC authentication,
  schema, `require_active()` lookup and SQLite transactions;
- one test-only `BoundedRuntimeTrustLedger` subclass that overrides only
  `__init__` and `_connect()` to preserve all production PRAGMAs while reducing
  the busy timeout to 125 ms;
- a separate raw SQLite writer connection that acquires `BEGIN IMMEDIATE` only
  after the broker's second successful production `require_active()` call and
  immediately before the terminal fence;
- distinct trust and effect-ledger paths.

The fixture seeds one locally HMAC-authenticated active row through the
production private row constructor and insert helper. This is test setup needed
to reach the lock boundary. It is explicitly not external runtime admission,
attestation, or Gate evidence.

The provider callback runs and output evidence is built before the lock fault.
The external writer stays active until the terminal fence exhausts the bounded
busy timeout. The broker must then:

- raise `RuntimeProviderTrustFenceError` whose cause is SQLite
  `OperationalError` with BUSY/LOCKED classification;
- persist exactly one `CANCELLED` terminal with no output digests and a detail
  digest;
- return no provider value;
- leave the authenticated runtime-trust row unchanged and `ACTIVE` after the
  external writer releases.

Python 3.11+ uses `sqlite_errorcode`. Python 3.10 compatibility classifies the
standard BUSY/LOCKED `OperationalError` text internally; exception text is never
retained in evidence.

## Pass invariant

The scenario passes with observed outcome `cancelled` only when all of the
following are exact:

1. scenario ID, digest, authority, executor locator and expected outcome match
   the protected runtime fault catalog;
2. the production provider callback ran and output evidence was constructed;
3. the second production runtime-trust verification succeeded before the
   external writer acquired its lock;
4. the external writer was active before release;
5. the terminal fence waited at least 100 ms but less than 5 seconds;
6. the surfaced exception is `RuntimeProviderTrustFenceError` caused by SQLite
   `OperationalError` classified as BUSY or LOCKED;
7. no invocation result or provider value was returned;
8. exactly one terminal row was retained with outcome `cancelled`, zero output
   digests and a non-null detail digest;
9. after releasing the external writer, production `require_active()` authenticates
   the same record SHA and state `ACTIVE`;
10. no provider value or exception message appears in retained evidence.

Any successful completion, missing cancellation, output digest on cancellation,
raw SQLite escape, absent writer, unbounded wait, altered trust row, unexpected
terminal multiplicity or returned provider value fails the scenario.

## Evidence binding

The executor implementation digest binds:

- exact executor bytes;
- exact production broker bytes;
- exact production trust-store bytes;
- busy timeout and elapsed-time bounds.

Raw evidence retains only source/scenario/implementation identities, a hash of
the temporary database path, bounded timing, writer/provider/evidence booleans,
exception class identities, SQLite numeric/name classification where available,
terminal counts/digests, and durable trust state/record SHA. It does not retain
provider output, exception text, database contents, integrity key, temporary
path, runtime record payload, stdout, or stderr.

Published files use file fsync and atomic replace. Directory fsync remains where
the operating system supports directory descriptors. Output-directory symlinks
refuse. Every summary hard-codes:

- `trusted=false`;
- `attested=false`;
- `gate_closure_claimed=false`.

An external `RuntimeFaultAttestation` from an admitted Linux-host authority is
still mandatory before this observation may enter the trusted matrix.

## Adversarial review

The independent review perspective verifies:

- SQLite errors are converted at the production terminal-fence boundary before
  any provider value can be returned;
- only `RuntimeProviderTrustFenceError` enters the existing cancellation path;
- rollback swallowing is restricted to preserving the original fence failure;
- the test ledger subclass changes only timeout/connect behavior and retains the
  production PRAGMAs;
- the fixture calls the real broker, real `require_active()` and a real SQLite
  writer lock;
- the local seed is not represented as external admission or attestation;
- pass requires cancelled terminal, zero output digests and authenticated row
  survival;
- provider output and exception text are absent from evidence;
- implementation identity covers production broker/store bytes and timing
  bounds;
- no trust, attestation or Gate-closure laundering exists.

Focused mutations cover removing the broker SQLite conversion, converting the
wrong exception class, omitting cancellation, accepting `COMPLETED`, allowing
output digests on cancellation, acquiring the writer before verification,
removing the real `require_active()` lookup, shortening/removing the busy wait,
allowing returned output, skipping durable-row authentication, changing the
production source identity and scenario drift.

## Verification request

The dedicated workflow requests:

- Ubuntu and Windows;
- Python 3.10 and 3.12;
- `PYTHONHASHSEED=0` and `123456`;
- Iron Plan and compile-all;
- runtime trust-store, terminal-fence, executor and independent review suites;
- malformed/stale binding and fault-attestation suites;
- one retained exact-head Linux contention run;
- the full repository suite;
- isolated wheel build/install/import.

GitHub Actions issue #67 remains an external exact-head verification blocker
while jobs terminate before their first step. This is not permission to accept a
raw SQLite escape or simulated replacement authority.

## Remaining boundary

This packet does not complete unknown-outcome reconciliation, live-runtime
envelope faults, protected-CAS publication, external host attestation, declared
secret delivery, bounded egress proxying, remaining provider centralization or
the exact-head Gate-0 release report.

Iron Plan: **ALIGNED by scope; exact-head execution required**  
Active gate: **Gate 0**  
Promotion: **not requested**
