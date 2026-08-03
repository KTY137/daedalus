# G0-RTC-06J — Linux sandbox-unavailable fault

## Objective

Execute the canonical `runtime.sandbox.daemon-unavailable` Linux-host scenario
against the production Docker sandbox boundary without adding a production
entrypoint or claiming that the resulting observation is trusted.

## Injection

The executor requires a readable Docker CLI and replaces the inherited Docker
endpoint with an exact nonexistent Unix socket for the duration of one
sandbox call. `DOCKER_CONTEXT`, TLS verification, and certificate-path
overrides are removed only inside that bounded environment and restored on
every ordinary, failed, and control-flow exit.

The sandbox command would create a marker in the candidate workspace if it
ever ran. A valid observation requires all of the following:

- the sandbox invocation returns non-zero before the configured timeout;
- the host-fallback marker remains absent;
- no shell or second subprocess launcher exists in the fixture;
- the production sandbox receipt retains argv/stdout/stderr identities only;
- daemon error text and the temporary socket path are not retained.

A missing Docker CLI is a `blocked/docker-cli-unavailable` observation, not a
fabricated pass for the daemon-unavailable injection.

## Exact implementation binding

The `LinuxHostExecutorBinding` digest covers:

1. the complete executor fixture bytes;
2. the complete `daedalus.kernel.sandbox` module bytes.

The collector then binds the canonical scenario digest, exact source revision,
executor locator, implementation digest, collector timestamps, retained raw
evidence digest, terminal outcome, and typed facts. The output files are
atomic and output-directory symlinks fail closed.

## Adversarial review

The separate review test checks that:

- the test fixture has no `subprocess`, `os.system`, or shell escape;
- the production sandbox retains one explicit `subprocess.run` boundary and
  no host fallback;
- only output digests, never Docker stderr/stdout text, enter evidence;
- the nonexistent socket path is retained only by SHA-256;
- candidate code cannot set `trusted`, `attested`, or
  `gate_closure_claimed` to true;
- `BaseException` control flow is not laundered into an ordinary failed
  observation;
- every mutated Docker environment key is restored.

## Verification requested

The dedicated workflow requests:

- Linux and Windows contract coverage;
- Python 3.10 and 3.12;
- `PYTHONHASHSEED=0` and `123456`;
- Iron Plan and compile-all;
- sandbox policy, host collector, attestation, malformed-input, and
  independent review tests;
- exact-head Linux execution with retained untrusted artifacts;
- full repository pytest;
- isolated wheel build/install/import outside the checkout.

## Deliberate remaining blockers

This packet does not authenticate the host observation, publish it to protected
CAS, provision an external host-attestation key, or close Gate 0. Six canonical
Linux-host scenarios remain without concrete executors:

- runtime trust-ledger lock contention;
- effect-ledger lock contention;
- container OOM;
- unauthorized egress;
- undeclared secret access;
- unknown-outcome reconciliation.

The two live-runtime scenarios also remain without externally trusted live
observations. GitHub Actions execution must be evaluated on the exact head; a
job that fails before Step 1 supplies infrastructure evidence only.

Iron Plan: **ALIGNED**

Active gate: **Gate 0**

Promotion: **not requested**
