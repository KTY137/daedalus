# G0-RTC-06J — Docker sandbox pre-start refusal and unavailable fault

## Objective

Make sandbox launch failure mechanically distinguishable from an attempt result
and execute the canonical `runtime.sandbox.daemon-unavailable` Linux-host fault.

This packet is stacked on `g0/linux-process-fault-executors`. It changes no
production caller to fall back to the host, adds no automatic trust, and does
not merge, promote or close Gate 0.

## Sandbox receipt classification

`SandboxExecutionReceipt` now carries a digest-bound launch state:

- `completed`: Docker started the container command and returned its terminal
  code;
- `timed-out`: the Docker invocation exceeded the policy timeout;
- `refused-before-start`: the sandbox runtime could not start the attempt.

Pre-start refusal is returned for:

- missing Docker executable;
- non-executable Docker binary;
- other operating-system launch errors;
- Docker CLI return code 125.

Docker exit code 125 belongs to the Docker CLI rather than the requested
container command. It is therefore intrinsically classified as
`refused-before-start`. A legacy receipt constructed with return code 125 and no
explicit launch state is upgraded conservatively to that classification;
explicitly repacking 125 as `completed` refuses.

Container command return code 127 remains a completed attempt because Docker may
have started the container and the command inside it was missing. Timeouts are
not mislabeled as daemon unavailability.

The receipt digest now includes launch state and bounded error code in addition
to argv, stdout, stderr, return code and timeout identity. OS exception messages
are not retained.

## Real unavailable-runtime fault

The host fixture forces an unavailable Docker endpoint with a unique nonexistent
Unix socket and clears context/TLS environment variables for the duration of the
probe. It invokes the real `run_in_docker_sandbox` boundary with:

- a digest-pinned image reference;
- network disabled;
- one temporary candidate workspace;
- a command that would create `/workspace/fallback-marker` if a container or
  host fallback actually executed it.

The fault passes only when:

- the receipt is `refused-before-start`;
- the workspace marker does not exist;
- no host fallback is observed.

The environment is restored after the probe. The executor implementation digest
binds both its own bytes and the exact production sandbox module bytes.

## Fail-closed and adversarial checks

- Docker commands remain argv arrays with no shell parsing;
- no host fallback dispatch exists in the sandbox module;
- return code 125 cannot be represented as a completed attempt;
- missing binary, permission and generic OS launch errors produce distinct
  bounded error codes;
- timeout remains a separate launch state;
- exception messages, which may contain credentials or endpoint details, are
  excluded from receipts;
- output-directory symlink substitution refuses;
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

The receipt digest changes because launch classification is now part of the
security-relevant identity. Gate-0 receipts from an older source revision must
therefore remain stale rather than being silently reused.

## Requested verification

The dedicated workflow requests:

- Linux and Windows contract checks;
- Python 3.10 and 3.12;
- `PYTHONHASHSEED=0` and `123456`;
- Iron Plan and `compileall`;
- original sandbox policy tests plus launch-state and independent counter-review
  suites;
- real unavailable-Docker fault execution on Linux;
- retained exact-head untrusted raw/evidence/observation artifacts;
- full repository pytest on Linux/Python 3.12;
- isolated wheel build/install/import outside the checkout.

A workflow run that ends with `steps=null` and no logs is infrastructure evidence
only and does not verify this packet.

## Deliberate remaining blockers

- six additional Linux-host scenarios remain without concrete executors;
- two live-runtime scenarios remain without live observations;
- the sandbox production entrypoint is not yet centrally Effect-Lease guarded;
- raw fault evidence is not published into protected CAS;
- no external host-attestation issuer key or authority policy is provisioned;
- the exact-head Gate-0 release report remains open.

Iron Plan: **ALIGNED**  
Active gate: **Gate 0**  
Promotion: **not requested**
