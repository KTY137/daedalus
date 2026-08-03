# G0-RTC-06O — Runtime-Trust Terminal-Fence Contention

## Objective

Execute the canonical `runtime.trust-ledger.lock-contention` Linux-host fault
against the production runtime broker, runtime-bound Effect Lease authority,
HMAC-authenticated runtime-trust ledger and persisted Effect Lease ledger.

The critical ordering is:

1. grant and `STARTED` are durable;
2. the provider returns an opaque value;
3. output evidence is materialized;
4. the last ordinary runtime verification succeeds;
5. a competing trust writer is acquired;
6. the production terminal trust fence reaches SQLite BUSY/LOCKED;
7. the provider value is withheld and the real effect execution becomes
   `CANCELLED`;
8. exact replay is inert.

No provider entrypoint, trust root, attestation, merge, promotion or Gate closure
is introduced.

## Production defect fixed

Previously a SQLite failure while opening or entering the terminal runtime-trust
fence could escape as raw `sqlite3.OperationalError`. The value was not returned,
but the already-started effect could miss its durable terminal receipt.

The broker now converts SQLite errors at this exact fence into
`RuntimeProviderTrustFenceError`, rolls back best-effort without replacing the
original fence failure, and leaves non-SQLite programming and effect-ledger
failures on their existing distinct paths. The broker's existing trust-loss
handler then persists `CANCELLED` with zero output digests before re-raising.

## Authenticated setup

The fixture creates distinct trust and effect SQLite files. It seeds exactly one
HMAC-authenticated `ACTIVE` runtime record using the production record format,
then issues a signed `RuntimeBoundEffectLease` and constructs a real
`RuntimeBoundEffectAuthorization` with real guard decisions and registry wiring.
The seeded record is fixture setup only; it is never represented as external
runtime admission or attestation.

A test-only trust-ledger subclass changes only SQLite connection timeout to
125 ms while retaining foreign keys, WAL, `synchronous=FULL` and busy timeout.
A test-only authorization wrapper delegates `grant`, `begin_effect`,
`finish_effect` and every verification to the real authority. After its second
broker-level ordinary verification succeeds, it acquires a separate
`BEGIN IMMEDIATE` writer immediately before the terminal fence.

The runtime record and lease are bound to the exact source revision supplied to
the host collector.

## Pass invariant

The observation passes as `cancelled` only when:

- catalog scenario, digest, authority, executor and expected outcome are exact;
- both ordinary broker verifications completed and the writer was active before
  terminal-fence acquisition;
- provider and output-evidence callbacks both ran;
- the observed error is `RuntimeProviderTrustFenceError` caused by a real SQLite
  BUSY/LOCKED `OperationalError`, including extended codes;
- essentially the full busy timeout elapsed, but the run remained below five
  seconds;
- no provider value or successful broker result escaped;
- the real effect ledger contains `CANCELLED`, terminal outcome `CANCELLED`, zero
  output digests and a non-null detail digest;
- the authenticated runtime record remains byte-identical and `ACTIVE` after
  writer release;
- replay of the exact execution invokes neither callback, returns
  `executed=false`, and leaves the terminal row unchanged;
- raw evidence contains no provider value and remains below 64 KiB.

Early injection, inactive lock, output not materialized, unrecognized error,
`STARTED`/`COMPLETED`, terminal output, missing detail, trust drift, active replay,
premature timeout or excessive delay fails.

## Evidence discipline

The implementation digest binds exact fixture, broker, trust-store,
runtime-effect and effect-ledger bytes plus timeout and tolerance. Raw evidence
retains only source identities, hashed temporary database paths, bounded timing,
class/numeric SQLite classification, callback/release flags, terminal metadata,
trust-row survival and replay state. It excludes provider output, output digest,
SQLite exception text, plaintext paths, keys, database contents, stdout and
stderr.

Published summaries hard-code `trusted=false`, `attested=false` and
`gate_closure_claimed=false`. External `RuntimeFaultAttestation` remains
mandatory.

## Independent counter-review

The separate AST/evidence perspective verifies:

- production SQLite errors are converted only at the terminal fence;
- cleanup rollback cannot replace the original failure;
- the timeout subclass changes only connection behavior;
- the wrapper delegates the real effect authority and injects after the second
  ordinary verification;
- real lease issuance, effect persistence and runtime-trust authentication are
  present;
- pass requires output evidence before injection, durable cancellation, empty
  terminal outputs, unchanged trust state and inert exact replay;
- provider output, exception text and plaintext paths cannot enter evidence;
- candidate material cannot claim trust, attestation or Gate closure.

Focused mutations target removal or broadening of SQLite conversion, injection
before output evidence, fake/in-memory terminal state, accepting completion or
terminal outputs, dropping runtime-row equality, allowing active replay,
returning provider output and omitting production-source identity.

## Verification request and blocker

The dedicated workflow requests Ubuntu and Windows, Python 3.10 and 3.12, two
hash seeds, Iron Plan, compile-all, focused broker/trust/effect/fence/collector
and attestation suites, one real Linux SQLite execution with retained untrusted
evidence, full pytest and isolated-wheel import.

GitHub Actions issue #67 remains an external exact-head blocker while jobs fail
before Step 1 with `steps=null` and no logs. Such runs are infrastructure
observations only and cannot establish a product, package, platform, host-fault
or Gate verdict.

Unknown-outcome reconciliation, live-runtime envelope faults, protected-CAS
publication, external host attestation, remaining provider centralization and
the exact-head cumulative Gate-0 release report remain open.

Iron Plan: **ALIGNED by scope; exact-head execution required**  
Active gate: **Gate 0**  
Promotion: **not requested**
