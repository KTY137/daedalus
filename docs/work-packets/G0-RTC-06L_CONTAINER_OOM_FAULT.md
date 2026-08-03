# G0-RTC-06L — Container OOM Host Fault

## Objective

Execute the canonical `runtime.process.oom` Linux-host scenario through the
production Docker sandbox boundary. This packet contributes one untrusted
observation to the Gate-0 runtime fault campaign. It does not attest the
observation, provision authority keys, merge, promote, or close Gate 0.

## Exact host injection

The fixture requires Linux and a discoverable, readable, executable Docker CLI.
It runs the production `DockerSandboxPolicy` and `run_in_docker_sandbox()` path
with:

- `python:3.12-alpine` pinned to the exact multi-platform image digest
  `sha256:6d43704baacd1bfbe7c295d7f13079d5d8104ed33568873133f8fc69980419df`;
- network disabled;
- read-only container root;
- one bounded candidate workspace;
- non-root user;
- `64m` memory and memory-swap limit;
- one CPU, 32 processes, 16 MiB temporary filesystem, and 30-second timeout.

The candidate command first creates `/workspace/oom-started` and then
continuously allocates and touches 16 MiB blocks. It has no shell, subprocess,
network, voluntary exit, signal, or self-kill path.

## Pass invariant

The scenario passes with observed terminal outcome `failed` only when all of the
following are exact:

1. the canonical scenario ID, digest, authority, executor locator and expected
   outcome match the protected runtime-fault catalog;
2. Docker reports a started-container `completed` receipt rather than a
   pre-start refusal;
3. the terminal return code is exactly 137;
4. the sandbox did not time out and supplied no pre-start error code;
5. the start marker exists, proving that the pinned candidate command entered
   the container before termination;
6. the observation finishes inside the bounded timeout window;
7. no host fallback exists.

A missing Docker CLI is `blocked/docker-cli-unavailable` or
`blocked/docker-cli-unreadable`. Docker daemon, pull, image, or launch refusal is
`blocked/sandbox-unavailable`. Timeout, missing marker, or any other terminal
code is a failed OOM invariant and cannot satisfy the scenario.

## Evidence binding

The executor implementation digest binds:

- exact fixture bytes;
- exact production `daedalus.kernel.sandbox` bytes;
- exact pinned image reference;
- exact memory and timeout limits.

Raw evidence retains scenario, implementation, production-source, Docker CLI,
image and policy identities; bounded timing; start-marker state; and the
canonical sandbox receipt with only stdout/stderr digests. It does not retain
Docker output text or the temporary workspace path.

Published files are atomic and output-directory symlinks refuse. Every summary
hard-codes:

- `trusted=false`;
- `attested=false`;
- `gate_closure_claimed=false`.

A separate `RuntimeFaultAttestation` from an admitted Linux-host authority is
still mandatory before the observation may enter the trusted matrix.

## Adversarial review

The independent counter-review checks that:

- the fixture has exactly one production sandbox invocation and no second
  subprocess or shell path;
- the allocation program cannot self-signal or manufacture return code 137;
- a pass requires the exact memory policy, started marker, launch state and
  terminal code;
- pre-start refusal remains blocked rather than becoming an OOM pass;
- implementation identity covers production code, image and limits;
- plaintext Docker output and temporary paths are absent from retained evidence;
- no exception, trust, attestation or Gate-closure laundering exists.

Focused mutations cover return-code substitution, marker removal, timeout
laundering, pre-start-refusal laundering, scenario drift and production-source
identity substitution.

## Verification request

The dedicated workflow requests:

- Ubuntu and Windows;
- Python 3.10 and 3.12;
- `PYTHONHASHSEED=0` and `123456`;
- Iron Plan and compile-all;
- focused sandbox, executor, host collector, fault-catalog and attestation tests;
- an exact-head real Linux/Docker OOM run with retained untrusted artifacts;
- the full repository suite;
- isolated wheel build/install/import.

GitHub Actions issue #67 remains an external exact-head verification blocker
while jobs terminate before their first step. A missing Docker daemon or image
pull is a separate host-runtime blocker and must remain explicit; it is not
permission to weaken the scenario.

## Remaining boundary

This packet does not complete runtime-trust-ledger contention, unauthorized
egress, undeclared-secret access, unknown-outcome reconciliation, either live
runtime-envelope scenario, protected-CAS publication, external host attestation,
provider centralization, or the exact-head Gate-0 release report.

Iron Plan: **ALIGNED by scope; exact-head execution required**  
Active gate: **Gate 0**  
Promotion: **not requested**
