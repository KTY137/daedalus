# G0-RTC-06H — Linux-host fault runner boundary

## Objective

Add the collector-side execution boundary for the nine canonical `linux-host`
runtime fault scenarios without treating a candidate-authored result as trusted
evidence and without pretending that the concrete host executors already exist.

This packet is stacked on `g0/runtime-fault-attestations`. It does not merge,
promote, close Gate 0, invoke a live provider, or provision an attestation key.

## Canonical bindings

One `LinuxHostFaultRun` retains and cross-checks:

- the exact canonical scenario ID and scenario digest;
- the exact source revision;
- the catalog-declared executor locator;
- a SHA-256 identity for the selected executor implementation;
- collector-owned start and finish timestamps;
- status, observed terminal outcome and bounded detail code;
- the SHA-256 digest of the retained raw evidence bytes;
- bounded structured facts;
- the complete `LinuxHostFaultEvidence` digest inside the canonical
  `RuntimeFaultObservation` provenance.

The raw bytes remain available to the caller for content-addressed publication.
Replacing them after execution invalidates the run before it can be returned.

## Fail-closed execution semantics

- only scenarios whose authority is exactly `linux-host` may enter this runner;
- executor registry keys must match both the canonical catalog locator and the
  bound executor record;
- foreign executor registrations refuse the whole run;
- missing executors generate explicit `blocked/executor-unavailable`
  observations;
- executor exceptions generate sanitized `failed/executor-error` observations;
- arbitrary return objects generate `failed/executor-contract` observations;
- a reported pass whose outcome differs from the catalog is downgraded to
  `failed/outcome-mismatch`;
- backwards or timezone-naive collector clocks refuse;
- raw evidence is non-empty and bounded to one MiB;
- structured facts are typed, unique and bounded;
- untrusted evidence JSON rejects duplicate keys, unknown fields, string-as-array
  repackaging, non-finite numbers and oversized documents.

`KeyboardInterrupt`, `SystemExit` and other `BaseException` control flow is not
laundered into ordinary evidence by this boundary.

## Trust boundary

A host run is still not proof. The resulting observation must be authenticated
by the separate `RuntimeFaultAttestation` boundary using an externally supplied
issuer key and authority policy. Even an authenticated observation remains a
Gate blocker when its status is `failed` or `blocked`, its outcome is wrong, its
revision is stale, or its scenario digest has drifted.

The packet intentionally contains no built-in passing host executor. Running the
canonical catalog with an empty registry produces nine explicit blockers and
cannot close the canonical matrix even when those blocked records are otherwise
content-addressed.

## Adversarial review findings addressed

1. The first collector draft discarded raw evidence after hashing it. The final
   run retains the bytes and checks them against the evidence digest.
2. A logical executor locator alone did not bind the implementation that ran.
   `LinuxHostExecutorBinding` now requires an exact implementation SHA-256.
3. A normal `json.loads` path could silently accept duplicate object keys.
   The untrusted wire loader now rejects duplicate keys and non-finite values.
4. A hostile executor could report `passed` with the wrong terminal outcome.
   The collector downgrades that result before constructing the observation.
5. Exception messages could contain credentials or provider output. Only the
   exception class is retained by the collector-owned failure path.
6. Foreign registry entries and key/binding-locator recombination now refuse
   before any scenario executes.

## Requested verification

The dedicated workflow requests:

- Linux and Windows contract checks;
- Python 3.10 and 3.12;
- `PYTHONHASHSEED=0` and `123456`;
- Iron Plan verification and `compileall`;
- focused host-runner, catalog and attestation suites;
- the repository-wide pytest suite on Linux/Python 3.12;
- isolated wheel build, installation and imports outside the checkout.

A workflow run that fails before Step 1 supplies infrastructure evidence only
and is not interpreted as product verification.

## Deliberate remaining blockers

- none of the nine canonical Linux-host fault executors is implemented here;
- no host collector publishes raw evidence to protected CAS;
- no external host-attestation issuer key or issuer policy is provisioned;
- live-runtime envelope expiry and binary-drift scenarios remain separate;
- the provider entrypoint migration stack is not integrated by this packet;
- the complete exact-head Gate-0 release report therefore remains open.

Iron Plan: **ALIGNED**  
Active gate: **Gate 0**  
Promotion: **not requested**
