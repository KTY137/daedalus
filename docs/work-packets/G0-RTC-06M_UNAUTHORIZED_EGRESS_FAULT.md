# G0-RTC-06M — Unauthorized Egress Host Fault

## Objective

Execute the canonical `runtime.egress.unauthorized-endpoint` Linux-host
scenario through the production Docker sandbox boundary. The packet proves the
empty-endpoint lease case: an endpoint outside the declared set is unreachable
when the sandbox is configured with network mode `none`.

This packet contributes one untrusted host observation only. It does not attest
the observation, provision an authority key, merge, promote, centralize a
provider, or close Gate 0.

## Exact injection

The executor requires Linux and a readable, executable Docker CLI. It uses:

- `python:3.12-alpine` pinned to index digest
  `sha256:6d43704baacd1bfbe7c295d7f13079d5d8104ed33568873133f8fc69980419df`;
- production `DockerSandboxPolicy` and `run_in_docker_sandbox()`;
- network mode exactly `none`, representing an empty leased endpoint set;
- read-only root, non-root user and one bounded candidate workspace;
- 128 MiB memory, one CPU, 32 PIDs, 16 MiB tmpfs and 20-second host timeout;
- one fixed IPv4 TEST-NET-2 destination, `198.51.100.1:443`, so no DNS lookup or
  external service behavior enters the oracle.

Inside the container, the probe first inspects `/sys/class/net` and
`/proc/net/route`, creates a start marker, and attempts one AF_INET TCP
connection with a two-second socket timeout. It retains a bounded canonical
marker and returns code 73 only when:

- the only interface is `lo`;
- no active default route exists;
- the connection did not succeed;
- the exact error is Linux `ENETUNREACH` (`errno=101`).

Code 73 is transport only. It cannot pass without the strict namespace and
connection marker.

## Pass invariant

The host observation passes with terminal outcome `failed` only when all of the
following are exact:

1. scenario ID, digest, authority, executor locator and expected outcome match
   the protected runtime-fault catalog;
2. the production sandbox policy is image-pinned and uses network mode `none`;
3. Docker reports a started-container `completed` receipt, not a pre-start
   refusal;
4. the parent returns 73, did not time out and carries no pre-start error code;
5. the start marker exists;
6. the strict marker is valid, duplicate-key-free and uses the exact schema;
7. `supported=true`, interfaces are exactly `["lo"]`, and no default route
   exists;
8. endpoint host and port equal the fixed protected values;
9. the connection failed with exact `errno=101`;
10. the run finishes inside the bounded window and no host fallback exists.

A missing Docker CLI is blocked as `docker-cli-unavailable` or
`docker-cli-unreadable`. Docker daemon, image pull or launch refusal is blocked
as `sandbox-unavailable`.

If `/sys/class/net` or `/proc/net/route` is absent, unreadable or malformed, the
container may return 75 with one strict `supported=false` marker before creating
the start marker. Only the full exact combination—completed receipt, code 75,
no timeout/error, no start marker, empty interfaces, no route, no connection and
no errno—is blocked as `network-namespace-inspection-unavailable`. Any
recombination fails.

A timeout, successful connection, extra interface, default route, another errno,
wrong endpoint, missing/malformed marker or any other terminal code fails the
fault invariant.

## Evidence binding

The executor implementation digest binds:

- exact executor bytes;
- exact production sandbox bytes;
- marker schema;
- pinned image;
- network mode;
- endpoint host and port;
- required errno;
- timeout.

Retained raw evidence contains only scenario, source, implementation, Docker CLI
and image identities; exact policy/endpoint facts; bounded timing; marker and
receipt digests; interface names, route boolean, connection boolean and errno.
No socket exception text, Docker stdout/stderr text, DNS result or temporary
workspace path is retained.

Published files use file fsync and atomic replace. Directory fsync is retained
where the operating system supports directory descriptors. Output-directory
symlinks refuse. Every summary hard-codes:

- `trusted=false`;
- `attested=false`;
- `gate_closure_claimed=false`.

External `RuntimeFaultAttestation` from an admitted Linux-host authority remains
mandatory before this observation may enter the trusted matrix.

## Adversarial review

The independent review perspective checks:

- exactly one production sandbox call and no host subprocess, shell or network
  fallback;
- a fixed numeric endpoint and no DNS path;
- namespace inspection, loopback-only interface set, absent default route,
  failed connection and exact `ENETUNREACH`;
- strict transport-code and capability-block classifications;
- bounded duplicate-rejecting marker parsing;
- implementation identity over production bytes and all oracle parameters;
- absence of plaintext exception/output material and temporary paths;
- absence of trust, attestation, Gate-closure or exception laundering.

Focused mutations cover network-mode substitution, endpoint substitution,
interface/default-route weakening, successful-connect laundering, errno
substitution, missing start marker, malformed marker, timeout/pre-start
laundering, unsupported-claim recombination, scenario drift and production-source
identity substitution.

## Verification request

The dedicated workflow requests:

- Ubuntu and Windows;
- Python 3.10 and 3.12;
- `PYTHONHASHSEED=0` and `123456`;
- Iron Plan and compile-all;
- focused sandbox, executor, host-runner, catalog and attestation suites;
- one exact-head real Linux/Docker network-none run with retained untrusted
  artifacts;
- the full repository suite;
- isolated wheel build/install/import.

GitHub Actions issue #67 remains an external exact-head verification blocker
while jobs terminate before their first step. A missing Docker daemon, pinned
image pull or network-namespace inspection surface remains an explicit external
runtime blocker and is not permission to weaken the oracle.

## Remaining boundary

This packet covers only the empty-endpoint network-none case. Bounded proxy
allowlists, runtime-trust-ledger contention, undeclared-secret access,
unknown-outcome reconciliation, live-runtime envelope scenarios, protected-CAS
publication, external host attestation, remaining provider centralization and
the exact-head Gate-0 release report remain separate work.

Iron Plan: **ALIGNED by scope; exact-head execution required**  
Active gate: **Gate 0**  
Promotion: **not requested**
