# G0-RTC-06N — Undeclared Secret Isolation Host Fault

## Objective

Execute the canonical `runtime.secrets.undeclared-access` Linux-host scenario
through the production Docker sandbox boundary. This packet proves the current
empty-secret-lease case only:

- one random host environment canary is inherited by the Docker CLI process;
- the production sandbox receives no environment injection and no reference or
  secret mounts;
- the container cannot enumerate or read the canary by its undeclared name;
- standard secret mount roots contain no secret artifacts;
- no secret value is retained in evidence.

This packet does not introduce a secret broker, a declared-secret mount API, an
authority key, attestation, merge, promotion or Gate-closure claim.

## Exact injection

The executor requires Linux and a readable, executable Docker CLI. It uses:

- `python:3.12-alpine` pinned to index digest
  `sha256:6d43704baacd1bfbe7c295d7f13079d5d8104ed33568873133f8fc69980419df`;
- production `DockerSandboxPolicy` and `run_in_docker_sandbox()`;
- network mode `none` and `reference_mounts=()`;
- read-only root, non-root user and one bounded candidate workspace;
- 128 MiB memory, one CPU, 32 PIDs, 16 MiB tmpfs and 20-second timeout;
- one process-local lock around the fixed probe name
  `DAEDALUS_UNDECLARED_SECRET_PROBE`.

If the fixed name already exists in the host environment, the run blocks before
launch rather than overwriting an unknown value. Otherwise the executor creates
a random 256-bit canary and places it in the inherited Docker CLI environment.
In the `finally` block it deletes the variable only when the value is still the
exact canary. A missing or changed value is an explicit failed invariant, and a
foreign replacement is preserved rather than deleted.

The canary itself is never included in the container command, Docker arguments,
marker, facts, summary or raw retained evidence. Only its SHA-256 is retained.
The marker parser additionally rejects any marker bytes containing the canary.

## Container observation

Before the access attempt, the pinned probe requires a readable
`/proc/self/mountinfo`. It then creates a start marker and:

1. hashes only the sorted environment variable names; it never serializes names
   or values;
2. attempts to read the exact undeclared variable and retains booleans only;
3. hashes mountinfo without retaining its text;
4. detects mounts at `/run/secrets`, `/var/run/secrets` and
   `/run/credentials`;
5. counts files and symlinks below those fixed roots without reading contents;
6. caps the artifact scan at 1,024 entries.

The probe returns transport code 76 only when the undeclared name is absent and
unreadable, no secret mount exists, no secret artifact exists and the scan
remained bounded. Code 76 alone is never sufficient.

## Pass invariant

The host observation passes with terminal outcome `failed` only when all of the
following are exact:

1. scenario ID, digest, authority, executor locator and expected outcome match
   the protected runtime-fault catalog;
2. the exact production sandbox has no reference mounts and network mode
   `none`;
3. the host canary existed for the Docker CLI call and remained unchanged until
   exact removal afterward;
4. Docker reports a started-container `completed` receipt, not a pre-start
   refusal;
5. the parent returns 76 without timeout or pre-start error;
6. the start marker exists;
7. the strict marker is valid, duplicate-key-free and contains no canary bytes;
8. `supported=true`, the secret name is absent and the read attempt failed;
9. environment-name and mountinfo digests are nonzero;
10. no secret mount or artifact exists and the artifact scan is bounded;
11. canonical raw evidence contains no canary bytes;
12. the run completes inside the bounded window and no host fallback exists.

A missing Docker CLI is blocked as `docker-cli-unavailable` or
`docker-cli-unreadable`. Docker daemon, image pull or launch refusal is blocked
as `sandbox-unavailable`. A pre-existing probe-name collision blocks without
overwrite.

If mountinfo is absent, unreadable or malformed, the container may return 78
before the start marker with one strict `supported=false` marker containing zero
digests, no access, no mount, zero artifacts and a bounded scan. Only that exact
combination is blocked as `secret-namespace-inspection-unavailable`; recombined
unsupported claims fail.

Any observed name/value, secret mount, artifact, unbounded scan, malformed or
canary-bearing marker, wrong return code, timeout, missing start marker or host
environment mutation fails the scenario. A foreign value observed during
cleanup remains in the host environment and is never mistaken for successful
restoration.

## Evidence binding

The executor implementation digest binds:

- exact fixture bytes;
- exact production sandbox bytes;
- marker schema;
- pinned image;
- fixed secret probe name;
- fixed secret roots;
- timeout and artifact bound.

Retained raw evidence contains identities, policy facts, bounded timing, canary
SHA-256, environment-name and mountinfo SHA-256 values, access/mount booleans,
artifact count, marker/receipt digests and host-restoration state. It contains no
secret value, environment-name list, mountinfo text, secret file name/content,
Docker stdout/stderr text or temporary workspace path.

Published files use file fsync and atomic replace. Directory fsync remains where
the operating system supports directory descriptors. Output-directory symlinks
refuse. Every summary hard-codes:

- `trusted=false`;
- `attested=false`;
- `gate_closure_claimed=false`.

External `RuntimeFaultAttestation` from an admitted Linux-host authority remains
mandatory before this observation may enter the trusted matrix.

## Adversarial review

The independent review perspective checks:

- exactly one production sandbox call and no second launcher;
- a locked host-canary lifecycle with collision refusal, conditional exact
  cleanup and preservation of foreign replacements;
- absence of the canary from Docker arguments;
- compilation of the embedded probe;
- environment names only, never values;
- fixed secret roots, bounded artifact enumeration and mountinfo inspection;
- exact empty-secret pass and exact unsupported capability block;
- strict bounded duplicate-rejecting marker parsing and canary-byte rejection;
- implementation identity over production bytes and all isolation parameters;
- no plaintext environment, mount, output, trust, attestation, Gate-closure or
  exception laundering.

Focused mutations cover environment injection, reference-mount substitution,
canary argument leakage, unconditional or missing cleanup, foreign-value
deletion, secret-name/value acceptance, mount/artifact acceptance, scan-bound
removal, canary-marker acceptance, unsupported-claim recombination,
timeout/pre-start laundering, scenario drift and production-source identity
substitution.

## Verification request

The dedicated workflow requests:

- Ubuntu and Windows;
- Python 3.10 and 3.12;
- `PYTHONHASHSEED=0` and `123456`;
- Iron Plan and compile-all;
- focused sandbox, executor, host-runner, catalog and attestation suites;
- one exact-head real Linux/Docker isolation run with retained untrusted
  artifacts;
- the full repository suite;
- isolated wheel build/install/import.

GitHub Actions issue #67 remains an external exact-head verification blocker
while jobs terminate before their first step. Missing Docker, pinned-image pull
or mountinfo support remains an explicit external runtime blocker and is not
permission to weaken the oracle.

## Remaining boundary

This packet proves only the empty-secret-lease and inherited-host-environment
case. A production secret broker, declared secret allowlist, tmpfs/FD injection,
redaction across application logs and provider-specific credential delivery
remain separate Gate-0 work. Runtime-trust-ledger contention, unknown-outcome
reconciliation, live-runtime envelope scenarios, protected-CAS publication,
external host attestation, remaining provider centralization and the exact-head
Gate-0 release report also remain open.

Iron Plan: **ALIGNED by scope; exact-head execution required**  
Active gate: **Gate 0**  
Promotion: **not requested**
