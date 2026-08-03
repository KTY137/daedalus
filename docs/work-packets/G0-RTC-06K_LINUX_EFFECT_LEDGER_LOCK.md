# G0-RTC-06K — Linux Effect-Ledger writer contention

## Objective

Execute the canonical `runtime.effect-ledger.lock-contention` Linux-host fault
against the real `EffectLeaseLedger.begin()` transaction boundary without
introducing another production effectful entrypoint.

This packet is stacked on `g0/linux-sandbox-unavailable-fault`. It does not
resolve the competing production sandbox-policy sibling, trust an observation,
provision an attestation key, merge, promote, or close Gate 0.

## Fault contract

The canonical catalog requires:

- boundary: `effect-ledger`;
- authority: `linux-host`;
- injection: hold the Effect-Ledger writer lock past its configured busy timeout;
- expected outcome: `refused-before-start`;
- invariant: no provider effect starts without a durable start receipt.

## Concrete execution

The test-only executor:

1. creates one signed, scope-bounded Effect Lease for a synthetic `CENTRAL`
   process entrypoint;
2. persists the grant in the production `EffectLeaseLedger` schema;
3. acquires a real SQLite `BEGIN IMMEDIATE` writer lock from a second connection;
4. invokes the production `EffectLeaseLedger.begin()` implementation through a
   fixture subclass that changes only the busy timeout to 150 ms;
5. permits the provider marker write only after `begin()` returns
   `execute=true`;
6. verifies while the writer lock is still held that no execution row exists;
7. releases the lock and verifies that no `STARTED` state or provider marker was
   published.

The shortened timeout is part of the executor identity and is not a production
configuration change. The implementation digest also covers the exact
`daedalus.kernel.effects` module bytes.

## Retained evidence

The raw evidence record retains only bounded structural facts:

- exact scenario and implementation digests;
- production Effect-Lease module digest;
- configured fixture busy timeout and elapsed milliseconds;
- SQLite error type/name/code, without the exception message;
- execution-row count, durable execution state and provider-marker state.

Database paths, temporary-directory names and SQLite exception text are not
retained. The collector still emits an untrusted `LinuxHostFaultEvidence` and
`RuntimeFaultObservation`; a separately authenticated
`RuntimeFaultAttestation` remains mandatory before the observation can enter a
trusted matrix.

## Adversarial review

The separate counter-review test batch checks:

- no subprocess or shell boundary exists in the fixture;
- the provider marker is reachable only after a successful persisted start;
- retained evidence contains no database path or exception message;
- executor identity covers the fixture, production module and timeout;
- no source path can claim trust, attestation or Gate closure;
- mutating `begin()` to return `execute=true` is killed by the marker invariant;
- laundering a `STARTED` state after a lock refusal is killed.

## Requested verification

The dedicated workflow requests:

- Ubuntu and Windows;
- Python 3.10 and 3.12;
- `PYTHONHASHSEED=0` and `123456`;
- Iron Plan verification and `compileall`;
- Effect-Lease, host collector, catalog and attestation regression suites;
- actual Linux execution with retained untrusted artifacts;
- the complete repository suite on Ubuntu/Python 3.12;
- isolated wheel build, install and import outside the checkout.

GitHub Actions issue #67 currently causes jobs to fail before Step 1 with no
logs. No exact-head green claim may be made until jobs record actual steps.

## Remaining blockers

After this packet, the canonical runtime matrix still lacks concrete trusted
execution for:

- runtime-trust ledger contention;
- container OOM;
- unauthorized egress;
- undeclared-secret access;
- unknown-outcome reconciliation;
- two live-runtime envelope scenarios.

External host attestation, protected CAS publication, provider-line
integration, exact-head release reporting, owner closure and the remaining
non-central production entrypoints also remain open.

Iron Plan: **ALIGNED**  
Active gate: **Gate 0**  
Promotion: **not requested**
