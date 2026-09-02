# W8 — Exception swallowing that hides other resource-class defects

Read-only static sweep. Repo `C:/Users/Administrator/daedalus`, local `main @41e1b265`
(hook-reported HEAD at session start; task brief cited `54f09753` — both are
`main`, no mutating command was run either way). Scope: `daedalus/` and
`tools/` (Python only), 434 + 27 = 461 `.py` files. `tests/`, `apps/`, `vault/`,
`.quarantine/`, `daedalus/lanes/` untouched. No file was written except this one.

Canonical defect writeup read first: `daedalus/kernel/effects.py:576-587`
(`with sqlite3.Connection` commits, does not close; leaked connections got an
indeterminate GC-timed finalization; a `-wal`/`-shm` topology scan then hit a
TOCTOU between `exists()` and resolve). This worker's job: find the exception
handlers that would have turned *that* bug — or `close()`/`release()`/
`rmtree()`/`terminate()`/ledger-write failures generally — into a silent
"success" instead of a loud one.

## Raw counts (patterns grepped, whole scope)

| pattern | count |
| --- | --- |
| `except Exception` | 308 (daedalus) + 31 (tools) = 339 |
| `except BaseException` | 49 (daedalus) + 1 (tools) = 50 |
| bare `except:` | 0 |
| `finally:` | 119 (daedalus) + 19 (tools) = 138 |
| `contextlib.suppress(...)` | 0 |
| `def __del__` | 1 |
| `def __exit__` | 18 |
| `.exists()` | 191 |
| except-block whose next line is `pass` | 131 occurrences across 51 files (45 in daedalus, 6 in tools) |

## Triaged counts (what was actually read, not just grepped)

- **Read in full context** (surrounding function, not just the grep line):
  ~230 of the 389 `except Exception`/`except BaseException` sites, concentrated
  in `daedalus/kernel/*` (effects.py, approvals.py, promotion.py,
  promotion_execution.py, promotion_trust_root.py, attempt_execution.py,
  attempt_ledger.py, attempt_workspace.py, authorization.py, source_trees.py,
  runtime_effects.py, runtime_effect_replay.py, fourfold_evidence.py,
  offload_lease.py, artifacts.py, runtime_conformance.py, events/ledger.py,
  policy/ledger.py), `daedalus/spine/*` (containment.py, killswitch.py,
  cancel.py, picker.py, bootstrap.py, attempt.py, receipts.py, docref_gate.py),
  `daedalus/gates/*` (fault_matrix.py, fault_matrix_binding.py, baseline.py,
  release.py, report.py, repository_write_artifact_cas.py,
  provider_observation_persistence_inventory.py,
  provider_target_receipt_retention_inventory.py,
  guard_implementation_manifest.py, python_target_structure.py),
  `daedalus/eval/correctness.py`, `daedalus/interfaces/http/effects.py`,
  `daedalus/orchestration/missions/service.py`, `daedalus/runtimes/broker.py`,
  `daedalus/desktop_runtime.py`, `daedalus/hooks/_common.py`,
  `tools/watchdog.py`, `tools/operability_drill.py`.
- **All** `__exit__` implementations (18) read in full — none return truthy.
- **The one** `__del__` (spine/cancel.py) and the closely related close-path
  siblings (spine/containment.py `ContainedProcess.close`) read in full.
- **All** 0 `contextlib.suppress` and 0 bare `except:` — confirmed absent, not
  just absent from a sample.
- **NOT read individually**: roughly 110-130 `except Exception` sites in
  `daedalus/chip_design/executor.py` (23+16 hits across two large files),
  `daedalus/ikarus_os.py` (18), `daedalus/core.py` (17, partially sampled via
  `_head_sha` cross-check), `daedalus/health.py` (14), `daedalus/structcore/*`
  (parse.py, cache.py, tokens.py, metrics.py, markdown.py, clones.py — 20+
  combined), `daedalus/observe/shape.py`, `daedalus/interfaces/bridge/*`
  (dispatch.py, watcher.py, projection.py, conversation.py, cli.py),
  `daedalus/runtimes/*` other than broker.py (provider_executable_*,
  fixture_fault_collector.py, live_fault_collector.py,
  host_fault_runner.py, container_fault_driver.py), `daedalus/mapping/*`,
  `daedalus/council/*` (session.py, canary.py, vendors.py — sampled the two
  `except BaseException` sites only), `daedalus/integrations/hermes/*`
  (sampled worker.py/tool_gateway.py's `BaseException` sites, not every
  `Exception` site), `daedalus/kairos/*`, `daedalus/lanes/*`,
  `daedalus/providers/*`, most of `tools/` besides watchdog.py and
  operability_drill.py (system_check.py, gate_discrimination.py,
  gui_check.py, gate_host_preflight.py, audit_triage.py,
  select_desktop_release_assets.py, guarded_call.py, funnel.py,
  bootstrap_receipt.py).
- Budget ran out before a second pass over `chip_design/executor.py` (the
  single largest concentration of `except BaseException`, 12 sites) and
  `ikarus_os.py`/`core.py` (35 combined `except Exception` sites) — these are
  the highest-value unread surface if this sweep continues. `core.py` was
  spot-checked once (the `_head_sha` wrapper) and looked consistent with the
  fail-closed pattern found elsewhere, but that is one data point, not
  coverage.

## Findings

### 1. `KillSwitch.stop_children` can silently sweep nothing and still report a kill — `daedalus/spine/killswitch.py:965-985`

```python
def stop_children(self) -> list:
    results = []
    with self._lock:
        tracked = list(self._tracked)
        self._children_stopped = True          # <-- set BEFORE any kill is attempted
    for proc in tracked:
        try:
            results.append(proc.cancel(grace_s=self.kill_grace_s))
        except Exception:  # noqa: BLE001 - one stuck child may not block the rest
            pass
    if self._sweep_managed:
        try:
            results.extend(cancel_all_managed(grace_s=self.kill_grace_s))
        except Exception:  # noqa: BLE001
            pass
    return results
```

**What is hidden**: a failed `proc.cancel()` (per-tracked child) or a failed
`cancel_all_managed()` call (the process-wide backstop sweep, itself already
swallowing per-process exceptions with `continue` in `spine/cancel.py:410-415`)
disappears with no trace. `results` silently has fewer entries than live
children, indistinguishable from "everything was already dead."
`self._children_stopped = True` is set **unconditionally, before the loop
even starts** — so the public `children_stopped` property (line 988-989)
answers "did stop_children() get called" not "were children actually
stopped." This is exactly criterion #2: a GATE-shaped function
(`children_stopped`) that can report a passing value having verified nothing.

**Failure enabled**: the exact resource leaks W1-W7 are hunting for
(subprocess, file handle, lock, temp dir, thread, sqlite connection) all
route through child-process cancellation. If a kill trips and one child's
`cancel()` raises, that child is not killed, is not retried, and is not
reported — the caller sees `stop_children()` return normally.

**On mid-operation kill**: this function *is* the kill-switch's central
sweep, called unconditionally on trip (`killswitch.py:1046`). A failure here
means the kill-switch's own "last resort" backstop can itself fail silently —
the one place the master plan (§4 invariant 8, §4.1) says must never be
degraded quietly.

**Severity**: HIGH. **Confidence**: HIGH (read in full; `_children_stopped`
assignment position confirmed against the loop below it).

**No caller found** for the `children_stopped` property in `daedalus/` or
`tools/` production code at time of read (grepped both) — so today nothing
downstream is actively misled by it, but the function's *own* contract
(docstring: "idempotent... cheap and harmless") does not mention that a
child can survive silently, and any future caller of `children_stopped`
would be misled by construction, not by omission.

### 2. `ContainedProcess.close()` can leave a Windows Job Object leaked and unreachable by the kill-switch backstop — `daedalus/spine/containment.py:1189-1210`

```python
def close(self) -> None:
    if self._closed:
        return
    try:
        if self.returncode is None:
            self.cancel(grace_s=0.0)
    except Exception:                       # noqa: BLE001
        pass
    finally:
        self._closed = True
        self._unregister()                  # removes self from cancel._LIVE
        for handle in (self.handle, self.thread, self._job):
            if handle:
                try:
                    # KILL_ON_JOB_CLOSE: closing the last job handle
                    # destroys any survivor.
                    _kernel32.CloseHandle(wintypes.HANDLE(handle))
                except Exception:           # noqa: BLE001
                    pass
        self._job = None
```

**What is hidden**: the actual kill mechanism this class relies on for a
contained candidate process is `KILL_ON_JOB_CLOSE` — closing the job handle
is what kills the tree, not `cancel()`. That `CloseHandle` call is wrapped in
`except Exception: pass`. If it fails (invalid handle, race, exhausted handle
table — the same OS-level conditions `killswitch.py`'s own docstring names
as reasons `Path.exists()` lies), the job is never actually closed, the
contained process can survive, and `self._job = None` plus `self._closed =
True` are set anyway on the very next line — so a second `close()` call is a
guaranteed no-op (`if self._closed: return`), and there is no retry path.

**Compounding**: `_unregister()` (line 1200) removes this process from
`cancel._LIVE` in the *same* `finally` block, regardless of whether the
`CloseHandle` above it succeeds. `cancel._LIVE` is exactly the registry
`KillSwitch.stop_children` sweeps as the backstop for a driver that "forgot
to thread `cancel=` through" (containment.py's own docstring, lines 1091-1097,
and cancel.py's, lines 378-385). So a process whose real close failed
un-registers itself from the one safety net designed to catch a failed
close — the failure and the removal from the backstop happen in the same
`finally`, both silently.

**Failure enabled**: leaked Windows Job Object / contained child process,
invisible to both the local retry logic and the process-wide kill-switch
sweep.

**On mid-operation kill**: directly relevant — this is the Windows
containment backend for candidate execution (master plan §4 invariant 3,
"Isolation... capability-bounded").

**Severity**: MEDIUM-HIGH (narrow trigger — `CloseHandle` failing on a
valid, just-used handle is rare — but the blast radius is exactly the
isolation boundary, and the failure mode matches the canonical bug's shape:
a "closing" step that isn't verified, paired with self-removal from the
registry that exists to catch it). **Confidence**: HIGH (read in full,
including the docstring cross-references to `cancel._LIVE`).

### 3. `ManagedProcess.__del__` swallows `Exception`, including a `finally`-hidden `release()` failure — `daedalus/spine/cancel.py:570-597`

```python
def close(self, grace_s: float = DEFAULT_GRACE_S) -> CancelResult | None:
    if self._released:
        return None
    result = None
    try:
        if self._process is not None and self._process.poll() is None:
            result = self.cancel(grace_s=grace_s)
    finally:
        self._backend.release()       # NOT try/except'd — can raise, replacing
        self._released = True         #   whatever cancel() raised (finally-raises)
        with _LIVE_LOCK:
            _LIVE.discard(self)
    return result

def __del__(self) -> None:  # pragma: no cover - GC timing
    try:
        self.close(grace_s=0.0)
    except Exception:
        pass
```

**What is hidden**: same shape as finding 2 on the POSIX/session-backend
side — `_backend.release()` runs unconditionally in `finally`, unguarded, so
if it raises it silently *replaces* any exception `cancel()` raised
(criterion #6: a `finally` that can itself raise destroys the original
diagnosis) — and this combined failure is then swallowed by `__del__`'s own
`except Exception: pass` (criterion #7: `__del__` failures are invisible by
construction; Python would normally at least print the exception to stderr,
but this handler suppresses even that print).

**Failure enabled**: same as finding 2 — an orphaned contained process whose
release failed leaves no trace anywhere, not even the usual CPython
"Exception ignored in `__del__`" stderr line, because the `except Exception:
pass` swallows before the interpreter gets a chance to report it.

**Confidence check**: read `cancel()` and `kill_tree()` — both already
internally swallow their own `OSError`s (lines 349-355, 539-540, 545-546), so
in practice `cancel()` rarely raises; the more likely raiser inside `close()`
is `_backend.release()`, which is not defensively wrapped at all.

**Severity**: MEDIUM (GC-timing dependent, `# pragma: no cover` by the
author's own admission — nobody is testing this path). **Confidence**:
HIGH.

### 4. `_rollback_runtime_fence` swallows `BaseException`, not `sqlite3.Error`, during cleanup — `daedalus/runtimes/broker.py:354-360`

```python
def _rollback_runtime_fence(connection: sqlite3.Connection) -> None:
    if not connection.in_transaction:
        return
    try:
        connection.execute("ROLLBACK")
    except BaseException:
        pass
```

**What is hidden**: nothing about the *originating* error (this helper is
always called from an `except ...: _rollback_runtime_fence(connection);
raise` site, so the real cause still propagates) — but the `BaseException`
catch is strictly wider than needed and inconsistent with the equivalent,
narrower pattern used elsewhere in the same kernel layer
(`kernel/effects.py:690/696/725/931`, `kernel/approvals.py:628/636`, both of
which correctly scope this exact "rollback-then-reraise" idiom to
`sqlite3.Error`). A `KeyboardInterrupt`/`SystemExit` landing during this
specific `ROLLBACK` statement is silently absorbed here (criterion #4);
in the `effects.py`/`approvals.py` siblings it would propagate.

**Failure enabled**: an operator's Ctrl-C or the runtime's own `SystemExit`
inside this narrow window is dropped rather than honored; the code falls
through to the caller's `raise`, which re-raises the *original* database
error instead of the interrupt — so the process does not exit when the
operator asked it to, at exactly the runtime-trust termination fence
(`_finish_completed_under_runtime_fence`, the function that persists
`COMPLETED` state).

**Severity**: LOW-MEDIUM (narrow window — one SQL statement — and the
surrounding function still fails loudly for every other error; this is a
correctness/consistency defect, not a hidden-success one). **Confidence**:
HIGH (read in full; cross-checked against the narrower sibling pattern).

### 5. Inconsistent cleanup-failure reporting inside `daedalus/eval/correctness.py`

Two cleanup-on-`finally` sites ~150 lines apart handle the same class of
problem (a scratch resource cleanup that can fail) with opposite discipline:

```python
# line 570-576 — reported
finally:
    try:
        from daedalus.kairos.worktree import remove_tree_no_follow
        remove_tree_no_follow(tmpdir)
    except Exception as e:       # noqa: BLE001 - reported, never swallowed
        output = f"{output}\n[scratch dir {tmpdir} NOT removed: {e}]"

# line 719-723 — silently dropped
finally:
    try:
        manager.reap_branches()
    except Exception:    # noqa: BLE001 - a leaked ref never fails a run
        pass
```

**What is hidden**: a failed `reap_branches()` (worktree/branch git-ref
cleanup) leaves a leaked git ref with zero evidence — no line in `output`,
no log — unlike the sibling five lines of code away, which explicitly names
the failure to the reader. The `noqa` comment defends *why the run should
not fail*, which is reasonable, but conflates "must not fail the run" with
"must not be reported at all"; the first `finally` block proves both are
achievable simultaneously in this exact file.

**Failure enabled**: silent accumulation of leaked git branch refs from
gate/attempt worktrees over time — this is a "leaked ref" resource-class
defect (branches/worktrees, adjacent to W3/W4's territory) whose only
witness would have been this exception, and it's discarded.

**Severity**: LOW (leaked git refs are cheap and eventually visible via
`git branch --list`, not a correctness hazard). **Confidence**: HIGH.

### 6. `shutil.rmtree(..., ignore_errors=True)` on a captured-source staging directory after a raised exception — `daedalus/kernel/source_trees.py:643-683`

```python
try:
    ...
    os.replace(staging, target)
    self._fsync_directory(target.parent)
except BaseException:
    shutil.rmtree(staging, ignore_errors=True)
    raise
```

**What is hidden**: this is criterion #1's named target directly
(`rmtree()` under a swallowed-errors flag). The *original* exception still
propagates (`raise` at the end), so the caller is not lied to about the
materialization failing — but if the `rmtree` itself fails (locked file,
permission denial, AV scanner holding a handle — all real on Windows), the
staging directory is silently left behind with no record of *that* second
failure. Over many failed materializations this is exactly the "wreckage
whose lifetime nobody can reason about" the canonical bug write-up
describes, just for a directory tree instead of a sqlite connection.

**Severity**: LOW-MEDIUM (does not mask the primary failure; only masks the
cleanup-of-the-failure). **Confidence**: HIGH.

### 7. `store_canonical_json` / evidence-store dedup checks: `exists()` → `read_bytes()` TOCTOU, uncaught — `daedalus/kernel/artifacts.py:74-78`, `daedalus/kernel/runtime_conformance.py:51-55,144-148`

```python
if path.exists():
    if path.read_bytes() != raw:
        raise ArtifactIdentityError("content-addressed artifact collision")
else:
    path.write_bytes(raw)
```

**What is hidden**: nothing is *swallowed* here — if the file vanishes
between `exists()` and `read_bytes()` (concurrent GC, a repair sweep, a
crash-recovery pass), `read_bytes()` raises `FileNotFoundError` uncaught and
the whole operation crashes loudly. This is criterion #8's named pattern
exactly, but it fails LOUD, not silently — so it's out of this worker's
"hides a defect" mandate, but it is the same TOCTOU shape as the canonical
bug (a stat/exists success followed by a read that assumes the file is
still there) and is flagged per the brief's explicit instruction to check
every `exists()`-then-open/resolve/stat pair. Recommend the sqlite-adjacent
workers (W6) or a follow-up note this as a correctness/availability
robustness item, not an exception-swallowing one.

**Severity**: INFO/LOW for this worker's mandate (loud failure, not
hidden). **Confidence**: HIGH.

### 8. `daedalus/desktop_runtime.py:146-161` — double-nested `BaseException` swallow around a managed-process close

```python
with _DLL_DIRECTORY_LOCK:
    _set_windows_dll_directory(None)
    managed: ManagedProcess | None = None
    try:
        managed = spawn()
    finally:
        try:
            _set_windows_dll_directory(str(frozen_root))
        except BaseException:
            if managed is not None:
                try:
                    managed.close(grace_s=0.0)
                except BaseException:
                    pass
            raise
```

**What is hidden**: if restoring the DLL search directory fails *and* the
subsequent best-effort `managed.close()` also fails, the second failure
(a failed close of an already-spawned desktop child process) is fully
discarded; only the original DLL-directory error propagates via the bare
`raise`. This is criterion #1's named target (`close()` swallowed) stacked
two levels deep.

**Severity**: LOW (double-failure path, narrow; the desktop app's own
process supervision is a secondary backstop here, not the sole one).
**Confidence**: MEDIUM (read in full, but did not trace every caller of
`launch_desktop`/whatever wraps this to confirm nothing downstream assumes
the child is dead).

## "Handlers that turn a failed cleanup into a reported success"

- `daedalus/spine/killswitch.py:965-985` `stop_children()` — finding 1. The
  strongest instance: not just unreported, but the one status flag
  (`children_stopped`) is set to `True` *before* the cleanup is attempted.
- `daedalus/spine/containment.py:1189-1210` `ContainedProcess.close()` —
  finding 2. `self._closed = True` is set in the same `finally` as the
  swallowed `CloseHandle`, making the "did close() work" question
  unanswerable after the fact, and idempotency (`if self._closed: return`)
  guarantees no retry.
- `daedalus/spine/cancel.py:570-583` `ManagedProcess.close()` — finding 3.
  `self._released = True` set in `finally` regardless of whether
  `_backend.release()` (unwrapped) raised.
- `daedalus/eval/correctness.py:719-723` `reap_branches()` — finding 5.
  Lower stakes (git-ref leak, not a live process), but same "cleanup fails,
  function returns as if the wave completed cleanly" shape.

## "Verify/check functions that return a passing value from an except block"

- `daedalus/spine/killswitch.py` `children_stopped` property — its backing
  field is set `True` unconditionally at the top of `stop_children()`,
  before any cancellation is attempted, so it never actually answers
  "were children stopped"; it answers "was stop_children() invoked."
  **No production caller found** in `daedalus/` or `tools/` at time of
  read — real defect in the exposed contract, not yet a live incident.
- **Reviewed and found already fixed / correctly fail-closed** (worth
  recording as precedent, since it's the exact shape being hunted): 
  `daedalus/spine/bootstrap.py:298-346` `gate_discrimination()`. Its own
  docstring documents a *previous* incident of this exact defect class —
  "the revision clause failed OPEN when HEAD could not be read... a
  repository with no readable `.git` turned a receipt from ANY revision
  into `proven=True`" — and the current code now resolves `head` inside a
  `try/except Exception: head = None`, immediately followed by an explicit
  `if not head: return GateDiscrimination(False, ...)`. This is the
  fixed/correct version of the exact pattern this worker was sent to hunt;
  cited here so the coincidence isn't mistaken for something unread.
- **Reviewed, deliberately fail-open, not hidden**: `daedalus/spine/picker.py`
  `~line 870-946` (the map/inventory freshness check backing candidate
  ranking, not promotion). Returns `{"fresh": True, "reason": "git could not
  report HEAD; freshness unknown, failing open", ...}` when `_head_sha`
  returns `None`. This is the mirror image of the `bootstrap.py` incident,
  but the docstring (lines 912-914) explicitly argues the opposite tradeoff
  on purpose ("turning 'I cannot tell' into 'refuse everything' would be a
  worse failure than ranking") and the caller is explicitly named as a
  non-promotion, informational ranking path, not `gate_discrimination`'s
  promotion-adjacent one. Flagged for visibility, not classified as a
  defect — it is the one place in the sweep where "fail open" is chosen and
  argued in writing rather than fallen into.
- `daedalus/gates/fault_matrix_binding.py:92-103` `_read_receipt()` returns
  `None` on `OSError`/decode failure. Read the caller
  (`_candidates_matching_source`/binding logic) — `None` is treated as
  "no receipt," which correctly feeds an "unbound" verdict rather than a
  pass. Not a defect.

## NOT findings (checked, ruled out)

- **Bare `except:`** — 0 occurrences anywhere in `daedalus/` or `tools/`.
- **`contextlib.suppress(...)`** — 0 occurrences in scope (one use in
  `tests/test_spine_return_arc.py`, out of scope).
- **`__exit__` returning a truthy value** — all 18 implementations read;
  every one returns `False`, `None`, or nothing (implicit `None`). None
  silently suppress an in-flight exception.
- **`finally: return`** — 0 matches for a `finally` block whose first
  statement is `return` (searched both directories, multiline).
- **The kernel's own `ROLLBACK`-then-reraise idiom**
  (`kernel/effects.py`, `kernel/approvals.py`) — repeated ~7 times, all
  structurally identical: `except sqlite3.IntegrityError/Exception: try:
  ROLLBACK except sqlite3.Error: pass; raise` inside a function whose
  `finally: conn.close()` always runs. Reviewed as a class and judged sound:
  the primary exception always propagates, the narrow `sqlite3.Error` scope
  on the rollback-swallow is correct (contrast with finding 4's broader
  scope in `runtimes/broker.py`), and `close()` on a connection with an
  open transaction implicitly rolls back in the sqlite3 module regardless.
- **`daedalus/gates/repository_write_artifact_cas.py`** — read in full for
  its `except` sites; this module is the strongest positive example in the
  sweep: narrow typed exceptions throughout, an explicit TOCTOU-safe
  `_revalidate_exact_path` helper that re-stats after reading, and only one
  swallow (`os.close(descriptor)` in a `finally`, scoped to `OSError`, on a
  read-only resolver that has already obtained its content) — judged low
  severity, not written up as a numbered finding.
- **`daedalus/spine/killswitch.py`'s own `.exists()` avoidance** — the
  module's docstring (lines 20-24) and a guard's docstring (lines 820-824)
  independently argue against `Path.exists()` for the exact TOCTOU/ACL
  reason the canonical bug hinges on, and the code backs it with narrow
  `FileNotFoundError`/`NotADirectoryError` catches instead. Cited as
  precedent that this defect class is already understood by at least one
  author in this codebase — makes findings 1-3 (same module family) more
  notable, not less, since the awareness clearly didn't reach
  `stop_children()`/`ContainedProcess.close()`.
