# G0-RTC-06M — Unauthorized egress host fault

## Purpose

Execute the canonical `runtime.egress.unauthorized-endpoint` Linux-host scenario through the production Docker sandbox. This packet adds no production entrypoint, trust root, attestation, merge, promotion, or Gate-closure claim.

## Exact injection

The executor runs the digest-pinned `python:3.12-alpine` image through `DockerSandboxPolicy` with `network="none"`, a read-only root, non-root user, dropped capabilities, `no-new-privileges`, one bounded writable workspace, 128 MiB memory, one CPU, 32 PIDs, 16 MiB tmpfs, and a 20-second timeout.

Inside the container, a bounded probe inspects `/sys/class/net` and `/proc/net/route`, then attempts a numeric TCP connection to the IANA documentation address `198.51.100.1:443`. It performs no DNS lookup and requires no provider credential or repository secret.

## Pass invariant

The observation passes with terminal outcome `failed` only when all of the following are exact:

1. Docker reports a started-container result rather than pre-start refusal or timeout;
2. the dedicated transport code is `73`;
3. a start marker proves the probe executed;
4. the namespace exposes only loopback;
5. no active default route exists;
6. the exact numeric endpoint did not connect;
7. the retained error is Linux `ENETUNREACH` (`101`);
8. the strict marker is bounded, duplicate-key-free, internally typed and bound to the exact endpoint;
9. execution remains inside the bounded host interval.

Missing namespace inspection is retained as `blocked/network-namespace-inspection-unavailable`. Docker pre-start refusal is retained as `blocked/sandbox-unavailable`. A changed return code, endpoint, topology, marker, connection result, errno, timeout, or host fallback fails.

## Evidence discipline

The implementation digest binds the exact executor bytes, production sandbox bytes, image digest, marker schema, network mode, endpoint, expected errno, and timeout. Raw evidence retains only scenario/source/implementation identities, content digests, bounded policy/timing facts, the strict marker, and the sandbox receipt. It does not retain Docker stdout/stderr plaintext, temporary paths, credentials, environment values, or secret material.

Published summaries hard-code `trusted=false`, `attested=false`, and `gate_closure_claimed=false`. External `RuntimeFaultAttestation` remains mandatory before this observation can enter the trusted Gate-0 matrix.

## Adversarial counter-review

The separate review perspective checks:

- exactly one production sandbox call and no fixture-side subprocess or shell launcher;
- exact network-none, image, endpoint and timeout bindings;
- real numeric socket execution plus route/interface inspection;
- pass dependence on the exact transport, start marker, loopback-only namespace, absent default route, failed connection and exact errno;
- malformed, duplicate-key, non-finite and endpoint-substituted marker refusal;
- production sandbox source identity in the implementation digest;
- no plaintext-output, trust, attestation or Gate-closure laundering.

Focused mutation targets are the network policy, transport code, start marker, route check, interface set, endpoint, errno and production-source identity.

## Verification request

The dedicated workflow requests Ubuntu and Windows, Python 3.10 and 3.12, two hash seeds, Iron Plan verification, compileall, focused builder and counter-review tests, one real exact-head Docker run with retained untrusted artifacts, the full repository suite, and isolated-wheel build/install/import.

GitHub Actions issue #67 remains an external verification blocker while jobs fail before Step 1 with `steps=null` and no logs. A missing Docker daemon, image pull, network namespace inspection facility, or incompatible kernel errno is a separate explicit host-runtime blocker and is not permission to weaken the fault.

## Remaining boundary

This packet does not implement undeclared-secret isolation, unknown-outcome reconciliation, runtime-trust-ledger contention, live-runtime envelope observations, protected-CAS publication, external host attestation, provider-line consolidation, or the exact-head Gate-0 release report.

Iron Plan: **ALIGNED by scope; exact-head execution required**  
Active gate: **Gate 0**  
Promotion: **not requested**
