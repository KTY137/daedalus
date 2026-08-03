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

A small parent process first proves that the kernel-owned cgroup-v2
`/sys/fs/cgroup/memory.events` file is readable and contains both `oom` and
`oom_kill`. It then creates the start marker and forks one allocation child that
repeatedly allocates and touches 8 MiB blocks. The parent retains a bounded
canonical marker only after observing the kernel `oom_kill` counter increase and
reaping the child. The allocation child has no shell, network, voluntary exit,
signal, or self-kill path.

The parent uses return code 70 only as a transport outcome after retaining the
kernel facts. Return code 70 by itself is never accepted as OOM evidence.

If the exact cgroup-v2 counter surface is absent, unreadable or missing either
required counter, the parent writes one exact `supported=false` marker before
any allocation or start marker and returns 72. Only that full combination may be
classified as an external runtime blocker.

## Pass invariant

The scenario passes with observed terminal outcome `failed` only when all of the
following are exact:

1. the canonical scenario ID, digest, authority, executor locator and expected
   outcome match the protected runtime-fault catalog;
2. Docker reports a started-container `completed` receipt rather than a
   pre-start refusal;
3. the parent returns exactly 70 after the observation protocol;
4. the sandbox did not time out and supplied no pre-start error code;
5. the start marker exists;
6. the strict cgroup marker is present, bounded, duplicate-key-free and uses the
   exact marker schema with `supported=true` and `observed=true`;
7. both `oom` and `oom_kill` increased relative to their pre-allocation values;
8. the allocation child was reaped with exit code `-9`, proving SIGKILL;
9. the observation finishes inside the bounded timeout window;
10. no host fallback exists.

A missing Docker CLI is `blocked/docker-cli-unavailable` or
`blocked/docker-cli-unreadable`. Docker daemon, pull, image, or launch refusal is
`blocked/sandbox-unavailable`. Missing cgroup-v2 counters are blocked only for a
started-container receipt with return code 72, no start marker, a strict valid
`supported=false`/`observed=false` marker, zero counters and no child exit code.
Any weakened or recombined unsupported claim fails. Timeout, missing/malformed
marker, unchanged kernel counters, another child terminal state, or any other
parent terminal code is a failed OOM invariant and cannot satisfy the scenario.

## Evidence binding

The executor implementation digest binds:

- exact fixture bytes;
- exact production `daedalus.kernel.sandbox` bytes;
- exact marker protocol schema;
- exact pinned image reference;
- exact memory and timeout limits.

Raw evidence retains scenario, implementation, production-source, Docker CLI,
image and policy identities; bounded timing; start-marker state; the strict
kernel-counter/capability marker and its SHA-256; and the canonical sandbox
receipt with only stdout/stderr digests. It does not retain Docker output text or
the temporary workspace path.

Published files are atomic and output-directory symlinks refuse. Every summary
hard-codes:

- `trusted=false`;
- `attested=false`;
- `gate_closure_claimed=false`.

A separate `RuntimeFaultAttestation` from an admitted Linux-host authority is
still mandatory before the observation may enter the trusted matrix.

## Adversarial review

The independent counter-review checks that:

- the fixture has exactly one production sandbox invocation and no second host
  subprocess or shell path;
- the allocation child cannot self-signal or manufacture the kernel counters;
- the parent reads the cgroup control file, reaps the child and publishes an
  exact marker;
- a pass requires counter increases, child SIGKILL, exact memory policy, start
  marker, launch state and parent terminal code;
- malformed, oversized, duplicate-key and non-finite marker records refuse;
- cgroup capability blocking requires the exact return code, absent start
  marker, strict unsupported marker, zero counters and absent child result;
- pre-start refusal remains blocked rather than becoming an OOM pass;
- implementation identity covers production code, marker schema, image and
  limits;
- plaintext Docker output and temporary paths are absent from retained evidence;
- no exception, trust, attestation or Gate-closure laundering exists.

Focused mutations cover parent return-code substitution, start-marker removal,
`oom`/`oom_kill` counter removal, child-exit substitution, malformed marker,
unsupported-claim recombination, timeout laundering, pre-start-refusal
laundering, scenario drift and production-source identity substitution.

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
while jobs terminate before their first step. A missing Docker daemon, cgroup-v2
memory counter, or image pull is a separate host-runtime blocker and must remain
explicit; it is not permission to weaken the scenario.

## Remaining boundary

This packet does not complete runtime-trust-ledger contention, unauthorized
egress, undeclared-secret access, unknown-outcome reconciliation, either live
runtime-envelope scenario, protected-CAS publication, external host attestation,
provider centralization, or the exact-head Gate-0 release report.

Iron Plan: **ALIGNED by scope; exact-head execution required**  
Active gate: **Gate 0**  
Promotion: **not requested**
