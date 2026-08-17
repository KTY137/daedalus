# Gate 0 — first driven Linux-host fault run

Status: STATUS (revision-bound measurement, not a timeless claim)
Date: 2026-08-17
Revision: `0d281c0316d74af7aceae2dc5b126945ec252c2d`
Evidence: `runs/gate0-linux-container-fault/`
Driver: `daedalus/runtimes/container_fault_driver.py`

## What was missing

The canonical catalog declares nine `linux-host` scenarios and names an exact
fixture executor for each. The collector seam, the evidence schema
(`daedalus-linux-host-fault-evidence/1`), the attestation boundary and all eight
fixture executors already existed. Nothing connected them, so on a Windows
workstation every `linux-host` row stayed unobserved and each executor
short-circuited to `blocked / linux-required` before touching the fault.

## How the run is wired

The driver does not invoke Docker. It goes through
`daedalus.kernel.sandbox.run_in_docker_sandbox`, so each container inherits the
canonical bounded-effect policy — pinned image, read-only root filesystem,
`--network none`, `--cap-drop ALL`, non-root user, repository mounted read-only
at `/repo`, one writable workspace. Evidence is produced by
`run_linux_host_fault_catalog`, not by a second path.

Image: `python:3.10-slim@sha256:a78e4529630cfe8c5199cafd6e0c28ee1579a13f86274396d8b6b2d80367aa3a`
Host: Docker Desktop 29.6.1, `docker info` → OSType `linux`.

## Result [MEASURED]

Nine of nine scenarios observed in 19.3 s wall clock. Every one reached
`sandbox-launch-state: completed`, so every container really started.

| Status | Count | Scenarios |
| --- | --- | --- |
| passed | 3 | `runtime.process.timeout`, `runtime.process.ignored-sigterm`, `runtime.effect.unknown-outcome-replay` |
| failed | 2 | `runtime.effect-ledger.lock-contention`, `runtime.trust-ledger.lock-contention` |
| blocked | 4 | `runtime.process.oom`, `runtime.sandbox.daemon-unavailable`, `runtime.egress.unauthorized-endpoint`, `runtime.secrets.undeclared-access` |

This is the first time any `linux-host` row of the canonical catalog has been
executed rather than assumed.

### The three passes

Real Linux process-tree and ledger-recovery faults reproduced with the declared
outcome: escalated kill of an ignored `SIGTERM`, timeout cancellation of a
process tree, and reconciliation of an unknown outcome after a crash between
external acknowledgement and terminal persistence.

### The two failures are stale fixtures, not flaky infrastructure

Both executors raise before they can inject their fault, and both were invisible
on Windows because the platform gate refused first. The container's own
collector caught each one and failed closed; neither was upgraded.

- `runtime.effect-ledger.lock-contention` — recorded `TypeError`.
  `tests/fixtures/effect_ledger_contention_fault_executor.py:171` constructs
  `EffectLeaseRequest` without `runtime_manifest_sha256` and
  `runtime_conformance_sha256`, which the production dataclass now requires.
- `runtime.trust-ledger.lock-contention` — recorded
  `RuntimeProviderBindingMismatch`.
  `tests/fixtures/runtime_trust_contention_fault_executor.py:449` calls
  `run_runtime_provider`, and `daedalus/runtimes/broker.py:449` rejects the
  authorization it passes: "authorization must be an exact
  `RuntimeBoundEffectAuthorization`".

Both are fixture drift against contracts that moved. Repairing them is a
separate labor and is deliberately not attempted here.

### The four blocked rows need a container runtime inside the container

`container_oom`, `unauthorized_egress`, `undeclared_secret` and
`sandbox_unavailable` each look for a Docker CLI and record
`blocked / docker-cli-unavailable` when it is absent. A plain `python:3.10-slim`
container has none, and mounting the host Docker socket is forbidden by
`daedalus/kernel/sandbox.py` — correctly, since it would hand the sandbox
control of its own runtime. These four need a Linux host with a daemon, not a
nested socket.

## Does the attestation boundary accept this run? No — and that is correct.

Both answers are measured against `verify_runtime_fault_matrix`:

- With no trusted digests — the real state — all nine observations are
  `fault.untrusted-observation` blockers. The driver holds no signing key by
  design, so nothing it produces is trusted.
- Hypothetically, if every observation from this run were trusted, 21 blockers
  would remain: the 4 `fault.blocked`, the 2 `fault.failed`, and 15
  `fault.missing` rows for the `deterministic-fixture` and `live-runtime`
  scenarios, which this driver does not produce.

What the run does establish is that the records are structurally well formed:
no `fault.scenario-drift`, `fault.authority-mismatch`, `fault.stale-revision`
or `fault.outcome-mismatch` blocker appears, and the three passes match their
declared expected outcomes.

## Open ends

1. No attestation issuer is wired up. Until an independent issuer signs these
   observations, the `linux-host` column cannot contribute to Gate 0 exit.
   Self-attestation by the driver would prove nothing and is not implemented.
2. Two fixture executors are stale against current kernel contracts (above).
3. Four scenarios need a Linux host with a reachable Docker daemon.
4. The 15 non-`linux-host` rows come from pytest and live probes and are outside
   this driver's scope.
5. `daedalus/kairos/_gated_writes_legacy.py.src` fails its raw-byte integrity
   pin on any Windows checkout that lands CRLF: the check hashes raw bytes while
   Git stores the file LF-normalized. The working copy was normalized locally to
   run the guard; the durable fix is an attribute pinning `eol=lf`, or
   normalizing before hashing. Not attempted here — the file is protected.
