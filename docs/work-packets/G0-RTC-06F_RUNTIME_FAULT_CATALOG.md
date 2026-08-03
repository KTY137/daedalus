# G0-RTC-06F — Runtime fault catalog and trusted observation matrix

## Objective

Turn the runtime portion of the Gate-0 fault campaign into a stable,
machine-readable requirement set without manufacturing execution evidence.

This packet is stacked on `G0-RTC-06E`. It does not run a live provider, create
a trusted observation, close the full fault matrix, migrate a provider, or close
Gate 0.

The canonical implementation lives in `daedalus.runtimes.fault_matrix`.
`daedalus.runtimes.faults` remains a compatibility import while the repository
is migrated strangler-style along explicit runtime responsibilities.

## Catalog boundary

`RUNTIME_FAULT_CATALOG` contains 24 required Gate-0 scenarios:

- 13 deterministic fixture scenarios covering broker replay, authority binding,
  provider failure/cancellation, output evidence, trust-loss windows, terminal
  serialization, shared-ledger refusal and terminal persistence failure;
- 9 Linux-host scenarios covering SQLite contention, timeout, process-tree kill,
  OOM, sandbox unavailability, egress, secret isolation and unknown-outcome
  reconciliation; and
- 2 live-runtime scenarios covering envelope expiry and binary/image drift.

Every scenario has a stable ID, boundary, required execution authority,
injection, expected outcome, invariant and executor locator. The catalog digest
is independent of input ordering.

## Observation boundary

A `RuntimeFaultObservation` binds:

- one exact scenario ID and scenario digest;
- one exact source revision;
- the scenario's required authority class;
- passed, failed or blocked status;
- the actual observed terminal outcome when an outcome was observed;
- content-addressed raw evidence; and
- provenance over the scenario and evidence digests.

A passing observation must contain an `observed_outcome`. The verifier compares
it with the scenario's `expected_outcome`. This prevents a trusted harness from
reducing both "the test runner exited zero" and "the system reached the required
terminal state" to one undifferentiated pass bit. A blocked observation may not
invent an observed outcome.

Observations are immutable records, not self-authenticating proof. A candidate
can construct a structurally valid record and can claim `status="passed"`; that
claim alone satisfies nothing.

## External trust boundary

`verify_runtime_fault_matrix` requires an independently obtained set of trusted
**observation-record digests**. A required observation remains blocked when its
record digest is absent from that set, even when the embedded status says
`passed`.

Consequently:

- an empty trust set fails closed;
- trusting a raw JUnit payload but not the complete observation record is
  insufficient;
- changing scenario, authority, revision, status, observed outcome, timestamp
  or provenance changes the observation digest and invalidates prior trust;
- a candidate-local catalog shrink produces a catalog mismatch and missing
  canonical scenarios; and
- model opinion cannot be inserted as an execution authority.

A future exact-head collector must build the trust set from authenticated CI,
host-fixture and live-runtime evidence. This packet does not implement that
collector.

## Derived blockers

The verifier derives blockers for:

- catalog mismatch;
- matrix or observation revision staleness;
- missing or foreign scenarios;
- scenario-digest drift;
- authority mismatch;
- untrusted observation records;
- passed observations with a terminal-outcome mismatch; and
- failed or externally blocked observations.

There is no writable `closed` field on the matrix. The verification projection
reports `closed=true` only when every canonical required scenario has one exact,
trusted, passing observation with the required terminal outcome. That projection
is runtime-fault completeness only; it is not the Gate-0 release decision.

## Adversarial review findings fixed

1. **Candidate pass claims.** The first draft accepted structurally valid
   `status="passed"` observations without requiring external trust. Verification
   now requires the complete observation digest in an externally supplied trust
   set.
2. **Outcome erasure.** A trusted pass record originally had no structured field
   for what actually happened. Observations now bind `observed_outcome`, and a
   passing outcome must equal the catalog requirement.
3. **Requirement shrink.** Matrix provenance may bind a candidate-local catalog,
   but verification always compares it with the externally selected canonical
   catalog and names the mismatch plus missing scenarios.
4. **Record repackaging.** Trust applies to the full observation digest rather
   than only the raw evidence digest, so metadata and binding changes invalidate
   trust.
5. **String-as-array input.** Strict loaders reject strings for scenario arrays,
   observation arrays and trust sets.
6. **JUnit output path.** The first workflow draft wrote JUnit XML below
   `reports/` before creating the directory. The workflow now creates it before
   pytest starts.

## Verification contract

The dedicated workflow requests:

- Python 3.10 and 3.12;
- `PYTHONHASHSEED=0` and `123456`;
- Iron Plan verification and compile-all;
- catalog contract tests plus every currently mapped deterministic broker/fence
  test;
- JUnit XML; and
- an isolated wheel smoke that imports both the canonical module and the legacy
  compatibility path.

The workflow emits the deterministic required-scenario catalog with
`security_boundary_claimed=false` and `execution_evidence_claimed=false`.

Exact-head CI remains subject to the repository-wide zero-step Actions blocker.
A job with no steps and no logs is infrastructure evidence only.

## Deliberate remaining blockers

- Linux-host and live-runtime executors are not implemented in this packet.
- No trusted observation collector or exact-head trust-set assembler exists yet.
- The catalog covers the runtime campaign, not every Gate-0 promotion, checkout,
  filesystem, crash-journal or release-report fault.
- Provider public entrypoints remain non-central.
- Gate 0 remains open.

Iron Plan: **ALIGNED**  
Active gate: **Gate 0**  
Promotion: **not requested**
