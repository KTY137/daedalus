# G0-RTC-06J — Docker sandbox pre-start refusal and unavailable fault

## Objective

Make sandbox launch failure mechanically distinguishable from an attempt result
and execute the canonical `runtime.sandbox.daemon-unavailable` Linux-host fault.

This packet is stacked on `g0/linux-process-fault-executors`. It changes no
production caller to fall back to the host, adds no automatic trust, and does
not merge, promote or close Gate 0.

## Sandbox receipt classification

`SandboxExecutionReceipt` carries a digest-bound launch state:

- `completed`: Docker started the container command and returned its terminal
  code;
- `timed-out`: the Docker invocation exceeded the policy timeout;
- `refused-before-start`: the sandbox runtime could not start the attempt.

Pre-start refusal is returned for:

- missing Docker executable;
- non-executable Docker binary;
- other operating-system launch errors;
- Docker CLI return code 125.

These categories are not interchangeable. Missing/non-executable/runtime-launch
errors prove only that this host could not invoke the sandbox boundary. They do
**not** prove that a present Docker daemon was unavailable. Only Docker CLI
return code 125, represented as `refused-before-start` with
`error_code=docker-cli-refused`, is eligible for the canonical daemon-unavailable
fault.

Docker exit code 125 belongs to the Docker CLI rather than the requested
container command. It is therefore intrinsically classified as
`refused-before-start`. A legacy receipt constructed with return code 125 and no
explicit launch state is upgraded conservatively to that classification;
explicitly repacking 125 as `completed` refuses.

Container command return code 127 remains a completed attempt because Docker may
have started the container and the command inside it was missing. Timeouts are
not mislabeled as daemon unavailability.

The receipt digest includes launch state and bounded error code in addition to
argv, stdout, stderr, return code and timeout identity. OS exception messages are
not retained.

## Exact unavailable-runtime fault

The host fixture first establishes its prerequisites:

- Linux host;
- a Docker CLI discoverable through the active environment;
- the resolved Docker CLI is a readable executable regular file;
- the Docker CLI bytes are SHA-256 bound into the raw evidence.

A missing or unreadable Docker CLI produces a canonical `blocked` observation
with `docker-cli-unavailable` or `docker-cli-unreadable`. It can never be
repackaged as a passed daemon-unavailable fault.

The fixture then forces an unavailable Docker endpoint with a unique nonexistent
Unix socket and clears context/TLS environment variables for the duration of the
probe. It invokes the real `run_in_docker_sandbox` boundary with:

- a digest-pinned image reference;
- network disabled;
- one temporary candidate workspace;
- a command that would create `/workspace/fallback-marker` if a container or
  host fallback actually executed it.

The fault passes only when all of these are exact:

- `launch_state == refused-before-start`;
- `error_code == docker-cli-refused`;
- `returncode == 125`;
- `timed_out == false`;
- the workspace marker does not exist;
- no host fallback is observed.

Any other nonzero completed result, timeout, missing runtime, permission failure
or generic OS launch refusal fails or blocks instead of satisfying the scenario.
The Docker environment is restored after every exit. The executor implementation
digest binds both its own bytes and the exact production sandbox module bytes.
The nonexistent socket path is retained only by digest, never in plaintext.

## Sibling consolidation

Two sibling drafts originally implemented complementary halves of this fault:

- the production launch-state authority and return-code-125 classification;
- Linux/Docker prerequisites, CLI digest binding, scenario binding and
  independent fixture review.

This packet is the selected consolidation target because the fault cannot be
sound without the production receipt classification. The additional host
preconditions and counter-review checks have been ported here. The sibling must
not be closed until exact-head diff review confirms that all unique behavior and
evidence constraints are retained.

## Fail-closed and adversarial checks

- Docker commands remain argv arrays with no shell parsing;
- no host fallback dispatch exists in the sandbox module or fixture;
- return code 125 cannot be represented as a completed attempt;
- missing binary, permission and generic OS launch errors produce distinct
  bounded error codes but cannot pass daemon unavailability;
- arbitrary nonzero completed results cannot pass;
- timeout remains a separate launch state;
- exception messages, which may contain credentials or endpoint details, are
  excluded from receipts;
- raw evidence retains Docker CLI, argv, stdout, stderr and socket-path digests,
  not daemon output or the socket path itself;
- output-directory symlink substitution refuses;
- `BaseException` control flow is not laundered into evidence;
- raw evidence, canonical evidence and observation digests are cross-checked;
- published summaries hard-code `trusted=false`, `attested=false` and
  `gate_closure_claimed=false`.

## Compatibility boundary

Legacy code constructing `SandboxExecutionReceipt` without `launch_state`
continues to work:

- `timed_out=true` infers `timed-out`;
- return code 125 infers `refused-before-start` and
  `docker-cli-refused`;
- other terminal return codes infer `completed`.

The receipt digest changes because launch classification is part of the
security-relevant identity. Gate-0 receipts from an older source revision remain
stale rather than being silently reused.

## Requested verification

The dedicated workflow requests:

- Linux and Windows contract checks;
- Python 3.10 and 3.12;
- `PYTHONHASHSEED=0` and `123456`;
- Iron Plan and `compileall`;
- original sandbox policy tests, launch-state tests, deterministic fixture tests
  and an independent AST/evidence counter-review;
- exact-head unavailable-Docker fault execution on Linux;
- retained exact-head untrusted raw/evidence/observation artifacts;
- full repository pytest on Linux/Python 3.12;
- isolated wheel build/install/import outside the checkout.

The retained host-evidence job intentionally fails when Docker CLI prerequisites
are absent or the exact 125 classification is not observed. That failure is a
runtime/infrastructure blocker, not permission to downgrade the fault. A workflow
run that ends with `steps=null` and no logs is infrastructure evidence only and
does not verify this packet.

## Deliberate remaining blockers

- six additional Linux-host scenarios remain without concrete executors;
- two live-runtime scenarios remain without live observations;
- the sandbox production entrypoint is not yet centrally Effect-Lease guarded;
- raw fault evidence is not published into protected CAS;
- no external host-attestation issuer key or authority policy is provisioned;
- the exact-head Gate-0 release report remains open.

Iron Plan: **ALIGNED by scope; exact-head execution blocked by #67**  
Active gate: **Gate 0**  
Promotion: **not requested**
