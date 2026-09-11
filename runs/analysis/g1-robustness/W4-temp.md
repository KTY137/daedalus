# W4 — Temporary files and directories: cleanup a crash skips

Scope: `daedalus/` and `tools/` (Python only). `tests/`, `apps/`, `vault/`,
`.quarantine/`, `daedalus/lanes/` out of scope. Read-only static sweep, no
mutation, no execution.

Commit: local `main` @ `2233a148` (session header; task brief named `54f09753`
as of dispatch — tree unchanged by this agent either way, read-only).

Canonical defect writeup read first: `daedalus/kernel/effects.py:576-587`
(`EffectLeaseLedger._initialize`) — a resource released by a non-deterministic
program point (GC finalization) gives its on-disk companion state (`-wal`/
`-shm`) an indeterminate lifetime, visible to an unrelated scanner as a file
that vanishes between existence-check and resolve. This sweep looks for the
same shape in temp-file/temp-dir lifecycle: cleanup gated on normal return,
`with`, or GC — not on a program point that also runs after a crash.

## Raw grep counts (daedalus/ + tools/)

| pattern | daedalus hits (files) | tools hits (files) |
|---|---|---|
| `tempfile` (import/use) | 21 files | 6 files |
| `mkdtemp` / `mkstemp` | 12 files | 5 files |
| `TemporaryDirectory` | 5 call sites (4 files) | 1 call site (1 file) |
| `NamedTemporaryFile` | 3 call sites (3 files, 1 is a policy-inventory string literal) | 0 |
| `rmtree` | ~28 lines (11 files, several are comments/docstrings) | 13 lines (6 files) |
| `.tmp`/`.partial`/`.new` (fixed or pid/uuid-suffixed sibling) | 7 files | 6 files |
| `atexit` | 2 lines (1 file) | 0 |
| `weakref.finalize` / `__del__` | 1 line (1 file, unrelated to temp files) | 0 |
| `.unlink(` | 31 lines (20 files) | 6 lines (5 files) |

Triaged: every `mkdtemp`/`mkstemp`/`TemporaryDirectory`/`NamedTemporaryFile`
call site (18 distinct sites), every `rmtree` call site that is real code (not
comment/docstring, 16 sites), every fixed-or-derived `.tmp` sibling-file
helper (13 sites), the `atexit` registration, and the one `__del__`. Sites in
`daedalus/gates/repository_write_inventory.py` and
`repository_write_stdlib_delta.py` are a static-analysis pattern *list*
(string literals naming APIs for a scanner) — read and excluded as not usage.

## Site table

| site | API | cleanup mechanism | survives exception | survives SIGKILL | name |
|---|---|---|---|---|---|
| `daedalus/ignition/gate1.py:762-765` (`scratch`) | `tempfile.mkdtemp` | `shutil.rmtree(scratch, ignore_errors=True)` in `finally` (line 1350) | yes (silently, `ignore_errors`) | no | random (mkdtemp) |
| `daedalus/ignition/gate1.py:1443-1466,1550-1554` (`half`/`broken`/`control`) | `Path / "name"` + `shutil.copytree` | `shutil.rmtree(..., ignore_errors=True)` guarded by `.exists()` before next use, no try/finally around the copytree itself | no (only cleaned at next call, not on exception in between) | no | fixed subpath under `control_root` |
| `daedalus/kernel/attempt_execution.py:1107` (`tmpdir`, gate scratch) | `tempfile.mkdtemp(prefix="daedalus-gate-")` | `_remove_gate_tmpdir` → guarded walker (`ScratchCleanupPort`, see `kairos/worktree.py:644 remove_tree_no_follow`), reported not swallowed | yes | no | random, but **predictable prefix** (`daedalus-gate-`), documented as attacker-reachable ground — see the function's own docstring |
| `daedalus/eval/correctness.py:525-576` (`tmpdir`, pytest scratch) | `tempfile.mkdtemp(prefix="daedalus-correctness-")` | `remove_tree_no_follow(tmpdir)` in `finally`, failure reported into `output`, never swallowed | yes | no | random |
| `daedalus/eval/correctness.py:786-802` (`apply_patch`) | `NamedTemporaryFile(delete=False)` | `os.unlink(patch_path)` in `finally` | yes | no | random (mkstemp-style) |
| **`daedalus/integrations/hermes/runtime_adapter.py:342,526`** (`runtime_root`) | `tempfile.mkdtemp(prefix="daedalus-hermes-runtime-")` | raw **`shutil.rmtree(runtime_root, ignore_errors=True)`** in `finally` (not the guarded walker) | yes (silently) | no | random |
| **`daedalus/runtimes/container_fault_driver.py:299-330`** (`workspace`) | `tempfile.mkdtemp(prefix="daedalus-container-fault-")` | raw `shutil.rmtree(workspace, ignore_errors=True)` at end of function, **no try/finally** | **no** | no | random |
| `daedalus/runtimes/live_probe_drivers.py:482-496` (`workspace`) | `tempfile.mkdtemp(prefix="live-probe-drift-")` | `shutil.rmtree(workspace, ignore_errors=True)` in `finally` | yes | no | random |
| `daedalus/kernel/source_trees.py:317-332` (CAS `put_bytes`) | `tempfile.mkstemp(prefix=f".{sha256}.", dir=target.parent)` | `temporary.unlink(missing_ok=True)` in `finally` | yes | no | content-addressed prefix + random suffix |
| `daedalus/kernel/promotion_trust_root.py:514-525` (allowed-signers file) | `tempfile.mkstemp(prefix="promotion-signers-")` | `os.unlink` in `finally`, `OSError` swallowed | yes | no | random |
| `daedalus/runtimes/provider_observation_store.py:512-579` | `tempfile.mkstemp(dir=path.parent, ...)` | multi-branch `finally`: unlinks temp, and rolls back a partially-published link | yes | no | random |
| `daedalus/runtimes/container_fault_driver.py:490-498` (`_atomic_write`) | `tempfile.mkstemp(dir=path.parent)` | `Path(temporary).unlink(missing_ok=True)` on `BaseException`, else `os.replace` | yes | no | random |
| `daedalus/council/vendors.py:373-388,414` (`council_cwd`, `run_managed`) | `tempfile.TemporaryDirectory` | both real call sites (`vendors.py:734,912`) use `with` | yes | yes (both callers use `with`) | random |
| `daedalus/ikarus_os.py:1621` (codex chat) | `tempfile.TemporaryDirectory` | `with` | yes | yes | random |
| `daedalus/providers/codex_cli.py:223` | `tempfile.TemporaryDirectory` | `with` (not read line-by-line but grep shows `with tempfile.TemporaryDirectory` at that line) | yes | yes | random |
| `daedalus/runtimes/fixture_fault_collector.py:816` | `tempfile.TemporaryDirectory` | `with` | yes | yes | random |
| `daedalus/desktop_runtime.py:1048-1068` (SSH host-key scan) | `NamedTemporaryFile(delete=False)` | `Path(name).unlink()` in `finally` | yes | no | random |
| `daedalus/desktop_runtime.py:342` | n/a (`atexit.register(self.close)`) | atexit hook, not GC-timing but still SIGKILL-fragile | n/a | no | n/a |
| `daedalus/ikarus_os.py:1567-1575` (`_neutral_cwd`) | fixed dir under `tempfile.gettempdir()`, no `mkdtemp` | **none — deliberately persistent**, documented as intentional (CLI cache warmth) | n/a | n/a | **fixed**: `daedalus_neutral_cwd` |
| `tools/gate_discrimination.py:523-544` / `755` | `tempfile.mkdtemp` (`Sandbox`, `_coverage`) | `.destroy()` called in caller's `finally` | yes | no | random |
| `tools/system_check.py:116-227` | `tempfile.mkdtemp` (`Sandbox`) | `.destroy()` called in caller's `finally` (line 1046-1048) | yes | no | random |
| `tools/mutation_score.py:672-693` | `tempfile.mkdtemp` (`Sandbox.build`) | `.destroy()` in caller's `finally` (line 938), destroys `self.root.parent` (i.e. the whole mkdtemp dir, correct) | yes | no | random |
| `tools/operability_drill.py:170,259,377,471` (4 drills) | `tempfile.mkdtemp` | each wrapped in its control's `try/finally: shutil.rmtree(..., ignore_errors=True)` | yes | no | random |
| `tools/gui_check.py:318-438` | `tempfile.mkdtemp` | `finally: shutil.rmtree(work, ignore_errors=True)` (also kills a leaked server process first) | yes | no | random |
| `tools/operability_drill.py:672-674` (drill receipt) | hand-rolled `out.with_suffix(".json.tmp")` | `write_text` then `os.replace`, **no try/except**, no unlink-on-failure | no (litters on failure, but next run overwrites) | no | **fixed** — sibling of `RECEIPT_REL_PATH`, no pid/uuid |
| `daedalus/hooks/_common.py:282-294` (`_write_atomic`) | `path.with_name(path.name + f".{os.getpid()}.tmp")` | write, then `os.replace` retried 20×; **no unlink-on-failure branch** | no (litters) | no | pid-suffixed |
| `daedalus/kernel/policy/ledger.py:972-994` (`_store`) | pid-suffixed `.tmp` | `os.replace` retried 10×; `except OSError: tmp.unlink()` **only for the outer OSError branch**, not for the write itself | partial | no | pid-suffixed |
| `daedalus/desktop_runtime.py:1071-1077` (known_hosts publish) | pid-suffixed `.tmp` | `os.replace`, no unlink-on-failure | no (litters) | no | pid-suffixed |
| `daedalus/interfaces/desktop/settings.py:110` | pid-suffixed `.tmp` | not read line-by-line; same family as above | — | — | pid-suffixed |
| `daedalus/runtimes/fault_attestation_issuer.py:542-545` (`_atomic_write`) | `path.with_name(f".{path.name}.tmp")` | write then `os.replace`, **no try/except at all** | no | no | **fixed**, no pid/uuid — manual operator tool ("no driver calls it") |
| `tools/select_desktop_release_assets.py:306-316` (`archive_macos_app`) | `archive_path.with_name(f".{name}.tmp")` | pre-flight collision check (`if temporary.exists(): raise`) + `except BaseException: temporary.unlink(missing_ok=True); raise` | **yes, explicitly guarded** | no | fixed, but self-refusing on collision |
| `daedalus/atomic.py:183-273` (`_tmp_sibling`, `write_text_atomic`, `write_bytes_atomic`, `publish_bytes_once`) | `target.with_name(f"{name}.{uuid4().hex[:8]}.tmp")` | `replace_with_retry` unlinks on final failure; `publish_bytes_once` unlinks in `finally` | yes | no | **uuid-suffixed by design** — docstring explicitly names the fixed-name race this avoids |

## Findings

### 1. `daedalus/runtimes/container_fault_driver.py:299-330` — mkdtemp workspace has NO exception guard at all

```python
workspace = Path(tempfile.mkdtemp(prefix="daedalus-container-fault-"))
policy = DockerSandboxPolicy(..., candidate_workspace=workspace, ...)
receipt = run_in_docker_sandbox(policy, (...))
evidence: ... = {}
raw_evidence: ... = {}
if receipt.launch_state == "completed":
    evidence, raw_evidence = _collect_workspace_evidence(workspace)
run = ContainerScriptRun(...)
self._runs[relative] = run
shutil.rmtree(workspace, ignore_errors=True)
return run
```

**Failure enabled**: `workspace` is mounted into a Docker container as
`candidate_workspace` — i.e. content inside it is written by whatever the
container's executor script does, not by this process. There is no
`try/finally`. If `run_in_docker_sandbox` raises, or `_collect_workspace_evidence`
raises (it reads and hashes whatever the container wrote, an obvious raise
site for a malformed/oversized/permission-denied file), the function returns
via exception and `shutil.rmtree` on line 330 **never executes at all** — not
even a "ran but ignored an error" outcome. This is the plain "non-context-
manager `mkdtemp` whose removal is a bare `rmtree` at the end of a function,
skipped on exception" shape named in the task brief, and it is the *only*
mkdtemp site in this sweep with zero exception-safety net.

**On mid-operation kill**: `%TEMP%/daedalus-container-fault-<random>/`
survives, containing whatever the container wrote (candidate/attacker-
influenced content, since it was Docker-mounted). Random suffix name, so it
does not block a later run from starting — it accumulates as litter. A
later scan/enumeration of `%TEMP%` (the same class of "unrelated scanner"
that tripped on the WAL companion files in the canonical writeup) would see
this directory and its container-written contents indefinitely.

**Severity**: Medium-high. This is inside `daedalus/runtimes/`, the fault-
injection/attestation path that also feeds live-runtime evidence
(`daedalus/runtimes/fixture_fault_collector.py`, `live_probe_drivers.py`) —
not a throwaway dev script, and the mounted content is exactly the kind of
adversarial/candidate-controlled material the repo elsewhere treats as
"attacker-reachable ground" requiring the guarded walker (see
`attempt_execution.py`'s `_remove_gate_tmpdir` docstring). Blast radius is
disk litter plus an un-swept candidate-writable directory, not data loss.

**Confidence**: High — read the full function; the absence of `try`/`finally`
around the `rmtree` is unambiguous in the source.

### 2. `daedalus/integrations/hermes/runtime_adapter.py:342,526` — raw `rmtree` over a subprocess-writable runtime root, not the repo's own guarded walker

```python
runtime_root = Path(tempfile.mkdtemp(prefix="daedalus-hermes-runtime-"))
...
try:
    ...
finally:
    ...
    shutil.rmtree(runtime_root, ignore_errors=True)
```

`build_sanitized_environment` (`daedalus/integrations/hermes/configuration.py:347-362`)
points `home`, `tmp`, and `hermes_home` at subdirectories of `runtime_root`,
which is then handed to the spawned Hermes worker subprocess as its writable
scratch space — i.e. this is candidate/agent-writable ground while the
process is live, structurally identical to the gate scratch directory that
`daedalus/kernel/attempt_execution.py`'s `_remove_gate_tmpdir` docstring
(lines 937-965) explicitly explains **why raw `shutil.rmtree` is unsafe**
there (Windows `scandir` stat-cache staleness against a reparse point
substituted mid-walk, measured 3/3 destroyed on this box) — and for which
the repo built `daedalus/kairos/worktree.py:644 remove_tree_no_follow` as the
one sanctioned replacement, with an explicit comment that the guarded walker
exists precisely so callers don't reach for `shutil.rmtree` "because the safe
thing looked internal."

**Failure enabled**: this call site is *wrapped* in `finally` (so it does run
on ordinary exceptions), but it uses the raw, unguarded API the sibling
kernel code deliberately avoids for the same resource shape. `ignore_errors=True`
also means a Windows partial-delete (see brief risk #7 — read-only files,
handle still open by the just-killed worker) is silently swallowed rather
than reported, unlike `_remove_gate_tmpdir`, which reports failures instead
of hiding them.

**On mid-operation kill**: the mkdtemp'd runtime root (random suffix)
survives, containing worker-written `home`/`tmp`/`hermes-home` content. Not a
collision risk (random name), but the same category of un-swept, agent-
written wreckage the canonical fix in `effects.py` was written to eliminate
in its own resource class.

**Severity**: Medium. Hermes is an integrations-layer effectful runtime path,
not a throwaway tool, but the observed defect here is "wrong helper used,
error hidden" rather than "no cleanup at all" — one severity notch below
finding 1.

**Confidence**: Medium-high — confirmed `runtime_root` is passed to
`build_sanitized_environment` and used as the worker's `HOME`/`TMP`; did not
trace as far as the worker's own write behavior inside those directories.

### 3. `daedalus/ignition/gate1.py` — several `shutil.rmtree(..., ignore_errors=True)` sites over copytree'd candidate trees, with no reported-failure path

Lines 166, 1350, 1445, 1457, 1552. The scratch-dir case (762-765/1350) is the
Gate-1 ignition workspace and is at least wrapped in `finally`. The four
`half`/`broken`/`control` sites (1443-1466, 1550-1554) `shutil.copytree` the
candidate tree and then `rmtree(..., ignore_errors=True)` it, but only
*before reuse on the next call*, not in a `finally` around the copy/measure
work in between — an exception raised by `ignition_checks.schema_check`,
`link_check`, or `pytest_check` on the copied tree skips cleanup for that
particular control directory entirely, leaving it for the *next* invocation's
pre-use `.exists()` check to sweep (or never, if there is no next invocation
in that process).

**On mid-operation kill**: `%TEMP%/daedalus-ignition-<random>/{half-renamed,
broken-links, revert-*}` directories survive. `prepare_ignition_repo`
(called earlier in the same function, line 767) initializes a real git
repository in the scratch tree (see the `GIT_AUTHOR_*`/`FROZEN_COMMIT_MESSAGE`
constants near the top of the file) — so the abandoned scratch tree can
contain `.git` pack files, which are read-only on Windows (per the task
brief's own Windows note). `ignore_errors=True` here means a genuinely
partial `rmtree` (stopped partway through a read-only `.git/objects/pack`)
is never surfaced, which is worse than not deleting: a later "does this
directory exist" check on a reused scratch path would see a mutilated tree
instead of either a clean directory or an intact one.

**Severity**: Medium. This is the Gate-1 rehearsal path (owner-authorized,
non-promoting per master-plan Revision 3), not a production promotion path,
but it does construct and destroy real git checkouts under `%TEMP%`
repeatedly, and the ignore-errors pattern is exactly the anti-pattern the
rest of the kernel (attempt_execution.py, eval/correctness.py) has already
moved away from in favor of the guarded, error-reporting walker.

**Confidence**: Medium — confirmed the `ignore_errors=True` calls and the
`prepare_ignition_repo` git-init constants; did not trace whether the
copied `candidate` tree passed into `_measure_discrimination`/
`measure_subject_coverage` actually contains a nested `.git` (it is copied
from `candidate`, itself built earlier in the pipeline — plausible but not
directly confirmed by reading that assignment).

### 4. `tools/operability_drill.py:672-674` — fixed-name `.tmp` sibling, no per-run uniqueness

```python
tmp = out.with_suffix(".json.tmp")
tmp.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
os.replace(tmp, out)
```

**Failure enabled**: `out` is a fixed repo-relative receipt path
(`RECEIPT_REL_PATH`). `tmp` has no pid/uuid suffix, unlike every other atomic-
write helper this sweep found (`daedalus/atomic.py`'s `_tmp_sibling` uses
`uuid4().hex[:8]`, explicitly because — quoting its own docstring — "a fixed
`.tmp` name means two publishers racing on one target write the same scratch
file and one of them publishes the other's half-written bytes"). This
call site does not use that helper. Two concurrent `operability_drill` runs
would race on the same `.json.tmp`; `os.replace` keeps `out` itself always
whole (readers never see a torn read), but one run's receipt content can be
silently clobbered by the other's, mid-write, without either process
noticing. Not the collision-blocks-restart case (c) — a later run simply
overwrites the stale tmp and proceeds — but it is the exact "FIXED-name temp
path" the brief asked to be enumerated separately.

**On mid-operation kill**: `daedalus-<...>/operability_drill.json.tmp` (fixed
sibling of the receipt) survives; harmless, overwritten on next run.

**Severity**: Low. Single-operator dev/CI tool, not invoked concurrently by
design, and the final artifact (`out`) is still protected by `os.replace`.

**Confidence**: High — read the full write path; no uniqueness suffix present.

### 5. `daedalus/runtimes/fault_attestation_issuer.py:542-545` — fixed-name `.tmp` sibling, no exception guard

```python
def _atomic_write(path: Path, payload: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)
```

**Failure enabled**: fixed name (no pid/uuid), and unlike every other
`_atomic_write`-style helper found in this sweep (`hooks/_common.py`,
`kernel/policy/ledger.py`, `container_fault_driver.py`,
`select_desktop_release_assets.py` all wrap the write in a `try` that at
least unlinks on failure) this one has **no exception handling whatsoever**.
A failure between `write_bytes` and `replace` leaves the fixed-name temp
file in place with no cleanup attempt.

**On mid-operation kill**: a fixed `.{name}.tmp` sibling survives next to
whatever attestation output path was targeted. The module's own docstring
says this is "an explicit operator step; no driver calls it," so accidental
concurrent invocation is unlikely, and the fixed name is silently overwritten
by the next successful run — not a restart-blocking collision.

**Severity**: Low — manual, non-driver-invoked tool; narrow blast radius.

**Confidence**: High — full function read, four lines, no `try`.

## NOT findings (explicitly ruled out, with reason)

- **`daedalus/council/vendors.py:373-388` `council_cwd`** (10) — returns a
  `TemporaryDirectory` object rather than being used inline, which matches
  the brief's "assigned to a variable, not `with`" shape at first grep. Read
  the function and both of its real call sites
  (`vendors.py:734`, `vendors.py:912`): both use `with council_cwd(...) as
  cwd:`. The bare-return form only exists so the function itself can
  `.cleanup()` before raising on the repo-root-containment check. Not a
  finding.
- **`daedalus/ikarus_os.py:1567-1575` `_neutral_cwd`** (1) — fixed path
  under the OS temp dir, but explicitly and deliberately never cleaned up —
  it is a persistent CLI cache directory by design (documented, with a
  measured latency/token justification), not a crash-skipped temp resource.
- **4 `TemporaryDirectory` sites used with `with`** (`ikarus_os.py:1621`,
  `providers/codex_cli.py:223`, `runtimes/fixture_fault_collector.py:816`,
  `tools/smoke_tauri_sidecar.py:28`) — correct usage, cleanup runs on the
  `with` exit including most exceptions (not SIGKILL, but that is true of
  every `with`-based cleanup and is not itself a defect).
- **12 `mkdtemp`/`mkstemp` sites with proper `try/finally` rmtree/unlink,
  random-suffix names** (`kernel/attempt_execution.py`,
  `eval/correctness.py` ×2, `kernel/source_trees.py`,
  `kernel/promotion_trust_root.py`, `runtimes/provider_observation_store.py`,
  `runtimes/live_probe_drivers.py`, `runtimes/container_fault_driver.py:490`
  `_atomic_write`, `tools/gate_discrimination.py` ×2,
  `tools/mutation_score.py`, `tools/system_check.py`,
  `tools/operability_drill.py` ×4, `tools/gui_check.py`,
  `desktop_runtime.py:1048` SSH scan) — survive ordinary exceptions, litter
  only (never collide) on SIGKILL because names are random. Not findings
  under this brief's failure shape, though every one of them is still
  SIGKILL-fragile in the trivial "abandoned directory" sense common to all
  non-`with` `mkdtemp` usage — noted in the table, not elevated to a finding
  because none is fixed-name, none blocks a restart, and none holds anything
  more sensitive than test/measurement scratch content.
- **`daedalus/atomic.py`** (whole module) — the repo's own hardened atomic-
  write primitive: uuid-suffixed temp names (explicitly to avoid the fixed-
  name race), `finally`-guarded unlink, hard-link-based `publish_bytes_once`
  for CAS semantics. Reference implementation, not a finding.
- **`daedalus/gates/repository_write_inventory.py`,
  `repository_write_stdlib_delta.py`** — string-literal pattern lists for a
  static write-surface scanner (`_FILESYSTEM_FUNCTIONS` etc.), not actual
  `tempfile`/`shutil` usage. Read in full to confirm.
- **`daedalus/spine/killswitch.py` unlink sites** (3) — the switch's own
  permit/marker state files, not scratch/temp resources; out of this
  resource class.
- **`daedalus/structcore/cache.py:246`, `daedalus/runtimes/providers/contracts.py:92`,
  `daedalus/shift.py`, `daedalus/kairos/drafts.py`, `daedalus/agents_registry.py:127`** —
  read each; cache eviction, provider-rollback bookkeeping, and draft/shift
  state cleanup, all persistent product state rather than temp-file
  lifecycle. Not this resource class.
- **`daedalus/spine/cancel.py:593` `__del__`** — the only `__del__`/
  `weakref.finalize` hit in the entire sweep; unrelated to temp files
  (process-handle cleanup), noted for completeness per the method brief but
  not a temp-resource finding.
- **`atexit` — `daedalus/desktop_runtime.py:342`** (`atexit.register(self.close)`) —
  the only `atexit` hit; registers cleanup for a desktop-runtime resource,
  not a `mkdtemp`/`TemporaryDirectory`. Dies with SIGKILL like every `atexit`
  hook, consistent with the brief's #6, but not itself a temp-file finding —
  noted, not elevated.

## Enumerated universal-claim set

"Every `mkdtemp`/`mkstemp` site in scope is wrapped in `try/finally`" is
**false** — the enumerated counterexample set has size 1:
`daedalus/runtimes/container_fault_driver.py:299-330` (finding 1). All other
17 `mkdtemp`/`mkstemp` sites triaged in the table above do reach a cleanup
call on ordinary exceptions (whether or not that cleanup uses the repo's
guarded walker, and whether or not `ignore_errors=True` hides a partial
failure).

"No production Python temp path uses a fixed, collision-prone name" is
**false** — enumerated set, size 2: `tools/operability_drill.py:672`
(finding 4) and `daedalus/runtimes/fault_attestation_issuer.py:543`
(finding 5). Neither blocks a restart (both are silently overwritten by the
next successful run), so **no FIXED-name temp path found in this sweep would
cause a later run to refuse to start** — the worst enumerated case is a
silent overwrite race, not a startup collision.
