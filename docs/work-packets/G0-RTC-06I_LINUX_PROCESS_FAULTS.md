# G0-RTC-06I — Linux process timeout and process-tree kill faults

## Objective

Implement the first two concrete `linux-host` executors from the canonical
Gate-0 runtime fault catalog:

- `runtime.process.timeout`;
- `runtime.process.ignored-sigterm`.

This packet is stacked on `g0/linux-host-fault-runner`. It produces real host
observations from an isolated Linux process group, but those observations remain
explicitly untrusted until the separate runtime-fault attestation boundary
verifies an external issuer signature for the exact observation digest.

No provider, production entrypoint, merge, promotion or Gate closure is invoked.
The effectful process launcher remains under `tests/fixtures`; it is not added as
a production runtime path.

## Fault fixture

The process-tree fixture creates one parent and one child in the new session and
process group supplied by `subprocess.Popen(start_new_session=True)`.

For the ordinary timeout case:

1. parent and child publish readiness;
2. the executor confirms that the parent PID is the process-group ID;
3. the process is allowed to exceed its declared execution timeout;
4. SIGTERM is sent to the whole process group;
5. the parent must terminate with `-SIGTERM` without SIGKILL escalation;
6. `/proc` must contain no live member of the process group.

For the ignored-SIGTERM case, both parent and child install `SIG_IGN` before the
parent publishes readiness. The executor must observe the grace-period timeout,
escalate to SIGKILL, receive `-SIGKILL`, and find no live group member.
Terminated zombie records may temporarily remain until the host init process
reaps them; they are retained separately from live members in the raw evidence.

## Exact implementation and evidence binding

The `LinuxHostExecutorBinding` implementation digest covers both:

- `tests/fixtures/linux_process_fault_executor.py`;
- `tests/fixtures/linux_process_tree_fixture.py`.

Each collector record then additionally binds the canonical scenario digest,
exact source revision, executor locator, start and finish times, raw evidence
digest, terminal outcome and bounded facts through the parent
`G0-RTC-06H` collector contract.

The retained raw evidence contains:

- parent, child and process-group identities;
- exact scenario and implementation digests;
- timeout and signal decisions;
- terminal return code;
- live and zombie group-member lists;
- elapsed time;
- sanitized invariant-failure classification when applicable.

## Fail-closed behavior

- the executor returns `blocked/linux-required` outside Linux;
- readiness is bounded, strict and duplicate-key rejecting;
- parent PID, process-group ID, child count and signal policy must match exactly;
- the executor refuses to target PID 0/1, the collector's own process group, or
  a process that is not a new group leader;
- process commands are argument arrays and never use `shell=True`;
- early exit before timeout is a failed observation;
- a live process after cancellation is a failed observation;
- an ordinary timeout requiring SIGKILL is a failed observation;
- an ignored-SIGTERM tree not requiring escalation is a failed observation;
- a foreign terminal signal is a failed observation;
- cleanup runs after both successful and failed paths;
- malformed fixture readiness is tested against process-tree escape;
- output-directory and destination symlink replacement is refused;
- artifact files are written through temporary files, `fsync` and atomic
  replacement.

## Retained output boundary

The CLI writes separate canonical evidence, observation and raw-evidence files
plus a summary. The summary hard-codes:

- `trusted=false`;
- `attested=false`;
- `gate_closure_claimed=false`.

The workflow artifact is therefore retained execution material, not a trusted
Gate receipt. A later exact-head host collector must publish the bytes to
protected CAS and an authorized external host issuer must sign the complete
observation before the canonical matrix may count it as trusted.

## Independent counter-review

The separate review suite verifies:

1. malformed readiness cannot leave the spawned parent or child live;
2. no shell command parsing is enabled;
3. new-session and process-group cancellation remain present in source;
4. output code cannot claim trust, attestation or Gate closure;
5. executor and fixture bytes both influence implementation identity;
6. published raw bytes, evidence records and observations are mutually
   content-addressed;
7. output-directory symlink substitution refuses without writing through it.

## Requested verification

The dedicated workflow requests:

- Linux and Windows import/contract checks;
- actual Linux execution on Python 3.10 and 3.12;
- `PYTHONHASHSEED=0` and `123456`;
- Iron Plan verification and `compileall`;
- focused collector, process-executor, catalog and attestation suites;
- repository-wide pytest on Linux/Python 3.12;
- isolated wheel build/install/import outside the checkout;
- retained exact-head untrusted process evidence as a pinned workflow artifact.

A workflow run with `steps=null` and no logs remains infrastructure evidence
only and does not validate this packet.

## Deliberate remaining blockers

- seven other Linux-host scenarios remain without concrete executors;
- the two live-runtime scenarios remain without exact live observations;
- raw evidence is not yet published into protected CAS;
- no external host-attestation issuer key or authority policy is provisioned;
- the provider-migration sibling stack is not integrated here;
- the exact-head Gate-0 release report remains open.

Iron Plan: **ALIGNED**  
Active gate: **Gate 0**  
Promotion: **not requested**
