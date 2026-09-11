# daedalus/kernel/sandbox.py  (346 lines)

Base 54f09753. Static read-only.

## What the file is for

Builds a locked-down `docker run` argv from an explicit, self-validating
`DockerSandboxPolicy` (pinned-digest image, read-only root, one writable
candidate-workspace bind mount, read-only reference mounts, no privileges,
`network=none` by default) and runs it via `run_in_docker_sandbox`, which
classifies the outcome into a `SandboxExecutionReceipt` with an explicit
`launch_state` (`completed` / `timed-out` / `refused-before-start`) so a
Docker-CLI or engine failure is never mistaken for an attempted candidate run.

## Axis 1 — docstring truth

### CONFIRMED
- none.

### PLAUSIBLE
- none — every checked claim held.

### Checked and honest
- Module docstring (:5-6): "grants one bounded candidate workspace as the
  only writable bind mount" — `argv()` (:93-118) mounts exactly
  `self.candidate_workspace` without `,ro` (:107) and every entry in
  `reference_mounts` is forced read-only in `__post_init__`
  (:83-85: `writable = [... if not mount.read_only]; if writable: raise`).
  True for *bind* mounts specifically; the `--tmpfs /tmp:rw,...` (:108) is
  also writable but is a tmpfs, not a bind mount, so the literal claim holds.
- Module docstring (:6): "keeps network access off unless an explicit
  internal proxy network is selected" — enforced at
  `DockerSandboxPolicy.__post_init__` (:77-78): `network != "none"` requires
  `startswith("daedalus-egress-")`, and `argv()` passes `--network
  self.network` (:99) with no other path to set it. True.
- Module docstring (:3-4): "rejects privileged or host-coupled
  configurations" — `user in {"0","0:0","root"}` is rejected (:79-80),
  `/var/run/docker.sock` and `/run/docker.sock` are rejected as mount targets
  or sources (:86-89), `--cap-drop ALL` and
  `--security-opt no-new-privileges:true` are unconditional in `argv()`
  (:105-106). True.
- Module docstring (:8-11): "A Docker CLI failure is not treated as an
  attempt result... This module contains no host fallback path." —
  `run_in_docker_sandbox` (:238-337) has exactly one `subprocess.run` call
  (:251-257, the Docker CLI itself); every failure branch
  (`TimeoutExpired` :258, `FileNotFoundError` :268, `PermissionError` :278,
  `OSError` :288, exit code 125 :298, engine-unreachable stderr match :308)
  returns a `refused-before-start` or `timed-out` receipt — none of them
  falls back to running the raw `command` outside Docker. Confirmed no
  second `subprocess` call exists anywhere in this file
  (`grep -n "subprocess\." daedalus/kernel/sandbox.py` → only :17 import,
  :251 the one call, :258 the one exception type). True, and this is the
  answer to the brief's specific question: **the sandbox fails closed; it
  never silently degrades to unsandboxed execution.**
- `SandboxExecutionReceipt.__post_init__` "refused receipt must not represent
  an attempt result" / "completed receipt requires a terminal returncode"
  (:163, :168 error messages) are actively enforced by the dataclass
  invariants immediately above each message (:156-172), not just asserted in
  prose.
- Comment at :308-320 documents a *previously fixed* bug (case A9c1: engine
  pipe absent produced CLI exit 1, which used to be misclassified as
  `completed`) — the current code (`_engine_unreachable` :230-235, called at
  :308) demonstrably closes that gap by string-matching the documented
  marker list against stderr before falling through to the `completed`
  branch at :329.

## Axis 2 — effect surface

| site (file:line) | effect | registry row | covered? |
| --- | --- | --- | --- |
| `subprocess.run(argv, ...)` (`sandbox.py:251-257`) | PROCESS_SPAWN (spawns `docker`, which itself spawns the containerized candidate) | none under `daedalus.kernel.*` — the four kernel rows (:350, :372, :394, :2304) declare only `Effect.FILESYSTEM_WRITE` | **not covered under any `daedalus.kernel` target**, but a covering row exists under a non-kernel target: `runtimes.container_fault_driver` (`daedalus/spine/effect_boundary.py`, target `daedalus.runtimes.container_fault_driver:main`, declares `FILESYSTEM_WRITE, PROCESS_SPAWN, PROCESS_CONTROL`, `Wiring.CENTRAL`). Its note explicitly names this exact function: "the spawn and the bounded-effect policy ... both live in `daedalus.kernel.sandbox.run_in_docker_sandbox`", and its `GuardAnchor` pins the call name `run_in_docker_sandbox` so the row cannot silently rot into a raw, unaudited spawn elsewhere in that module. |

### Notes
- This confirms the brief's measured fact exactly: `sandbox.py` does spawn a
  process, and none of the 4 kernel-targeted `EntrypointSpec` rows declares
  `PROCESS_SPAWN` (all four are `FILESYSTEM_WRITE`-only). The covering row is
  real, but it lives entirely outside `daedalus/kernel/` — at
  `daedalus/runtimes/container_fault_driver.py:main`.
- **Reachability gap worth flagging explicitly**: `grep -rn
  "run_in_docker_sandbox\|DockerSandboxPolicy" daedalus/ tests/` shows the
  *only* production caller of `run_in_docker_sandbox` is
  `daedalus/runtimes/container_fault_driver.py` (the fault-injection driver)
  plus test fixtures under `tests/fixtures/*_fault_executor.py`. Neither
  `daedalus/kernel/attempt_execution.py` nor
  `daedalus/kernel/attempt_workspace.py`/`attempt_ledger.py` import
  `sandbox.py` at all. That means the live TaskAttempt lifecycle paths in
  this kernel package do **not** currently route candidate execution through
  the Docker sandbox described here — the sandbox is wired only into the
  fault-matrix rehearsal driver, not (as far as this file and its callers
  show) into ordinary attempt execution. This is a scope/wiring observation,
  not a defect in `sandbox.py` itself, which makes no claim about being
  invoked from any particular caller.

## Axis 3 — unreleased resources

### Checked and honest
- `subprocess.run(...)` (:251-257) is a single blocking call with
  `capture_output=True` and an explicit `timeout=policy.timeout_s`; Python's
  `subprocess.run` owns the child's full lifecycle (including killing and
  reaping it on `TimeoutExpired`), so there is no unmanaged `Popen` here and
  no acquire/release pair for this module to get wrong. No finding.
- No file handles, tempdirs, locks, or sockets are opened anywhere in this
  file — it only builds argv and inspects a completed/failed
  `subprocess.run` result.

## Axis 4 — validator gaps (W4 class)

### Checked and honest
- No use of `_identifier` or any locally duplicated weak regex in this file.
  Path-shaped values are `SandboxMount.target` (validated at :52:
  `not self.target.startswith("/") or ".." in Path(self.target).parts` —
  rejects both non-absolute and `..`-containing targets) and
  `DockerSandboxPolicy.candidate_workspace`
  (resolved via `Path(...).resolve()` at :73 and required to be an existing
  directory at :74-75). Neither goes through `_identifier`/`_ID_RE`, so this
  file has no sibling of the W4 weak-regex chain.
- `image` is checked for `"latest" in self.image` and `"@sha256:" not in
  self.image` (:71) — a content/format check, not a path-traversal
  validator, and it is never used to build a filesystem path (only passed as
  a Docker image argument at :116). Not an Axis-4 finding.

## Axis 5 — dead / duplicate

### Checked and honest
- All five exported names (`DockerSandboxPolicy`, `SandboxExecutionReceipt`,
  `SandboxMount`, `SandboxPolicyError`, `run_in_docker_sandbox`) have live
  production callers in `daedalus/runtimes/container_fault_driver.py` and
  are exercised directly by `tests/kernel/test_docker_sandbox_*.py` and
  `tests/test_promotion_trust_root_adversarial.py`. No dead code found.
- `_ENGINE_UNREACHABLE_MARKERS` / `_engine_unreachable` (:219-235) has one
  caller, `run_in_docker_sandbox:308`. Not dead.
- No duplicate regex/validator/digest helper found in this file.

## What I did not cover

- Did not attempt to run Docker or exercise the sandbox live, per the
  brief's static-only instruction.
- Did not audit `daedalus/runtimes/container_fault_driver.py` itself (out of
  my assigned slice) beyond confirming it is the sole production caller and
  the location of the covering Effect Registry row.
- Did not determine whether a different, non-fault-driver production path
  is planned to route ordinary Attempt execution through this sandbox in a
  later Work Packet; I report only what is wired today.
