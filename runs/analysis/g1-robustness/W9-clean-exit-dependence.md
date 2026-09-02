# W9 — Clean-exit dependence (Gate-1 robustness sweep)

Read-only static sweep. No files modified, no git mutation, no code executed.

- Scope: `daedalus/` and `tools/` only (`tests/`, `apps/` out of scope).
- Repo: `C:/Users/Administrator/daedalus`.
- Commit at start of sweep: `c42c8c13` (branch `wip/g1-freeze-2026-08-31` per session
  header). Mid-sweep the checkout moved to `main @ c4b27e09` — **this is a shared
  checkout with many concurrent agent sessions** (per house knowledge:
  "uncommitted code is live for every session" / "shared-checkout git index
  trap"); every file read here was read at the path, not pinned to a single SHA.
  Line numbers cited below were correct at time of read; re-verify before acting
  if the tree has moved again.
- Thesis read first: `daedalus/kernel/effects.py:576-587` (the just-fixed
  `with sqlite3.connect(...)` transaction-vs-close defect — leaked connections in
  a reference cycle were finalized by the generational GC at an unpredictable
  moment, making WAL companion-file lifetime a function of unrelated process
  allocation rather than a fact of the code).
- Patterns grepped and raw counts (`daedalus/` + `tools/`):

| pattern | daedalus/ | tools/ |
|---|---|---|
| `atexit.register` | 1 | 0 |
| `def __del__` | 1 | 0 |
| `weakref.finalize` / `weakref.ref` (true hits, dunder-attr noise excluded) | 1 (`WeakSet`, not `finalize`) | 0 |
| `tempfile.TemporaryDirectory`/`NamedTemporaryFile` | 8 call sites | 0 |
| `signal.signal(...)` (installing an incoming handler) | **0** | **0** |
| `SIGTERM`/`SIGINT` (any mention, incl. outgoing `send_signal`/`killpg`) | 7 | 0 |
| `os._exit(` | 0 | 0 |
| `sys.exit(` | 4 (all `sys.exit(main())` CLI boilerplate) | 1 (inside a string literal, not code) |
| `finally:` | 119 (59 files) | 19 (8 files) |
| `"running"`/`'running'` | 14 (7 files) | 0 |
| `in_progress` | 0 | 0 |
| `started_at` | 109 (23 files) | 0 |
| `state\s*=\s*["']` | 53 (15 files) | 0 |

Triaged (after reading surrounding code): **3 material findings**, **2 notable
correct patterns worth contrasting**, rest is NOT-findings (see bottom).

## Cleanup-mechanism sites

| file:line | mechanism | releases | survives exception | survives SIGTERM | survives taskkill /F | deterministic alt. path? |
|---|---|---|---|---|---|---|
| `daedalus/desktop_runtime.py:342` | `atexit.register(self.close)` | bridge-watch stop-event, IDE subprocess/Docker container, tunnel subprocess, ollama `ManagedProcess` | yes (atexit still runs on unhandled exception → interpreter shutdown) | **no** (no `signal.signal(SIGTERM,...)` anywhere in the repo; default SIGTERM disposition terminates without unwinding) | **no** | **no** — no other call site of `DesktopRuntimeManager.close()`/`.stop_ide()`/`.stop_ollama()` found in `daedalus/` |
| `daedalus/desktop_runtime.py:981` → `_spawn_ollama_process` (`daedalus/spine/cancel.py` `ManagedProcess`) | Windows Job Object, `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` | ollama child process | n/a (OS-level) | **yes** (job closes when parent's handle table is torn down, regardless of how the parent died) | **yes** | n/a — this is the deterministic, kill-safe path; contrast with the row above |
| `daedalus/desktop_runtime.py:703` (`self._ide = subprocess.Popen(...)`) and `:1152` (`self._tunnel = subprocess.Popen(...)`) | plain `subprocess.Popen`, `creationflags` = `CREATE_NO_WINDOW` only | IDE process / tunnel process | only via the atexit path above | **no** | **no** | **no** — no Job Object, no `CREATE_NEW_PROCESS_GROUP`, no deterministic caller |
| `daedalus/desktop_runtime.py:823-846` (`docker run --detach --name daedalus-ide ...`, no `--rm`) | Docker daemon-managed container, stopped only by `stop_ide()` (`:876`) | Docker container (port 3000 bind + bind-mount) | only via the atexit path above | **no** | **no** | **no** — container lifetime is entirely independent of the Python process; on the *next* run it is silently re-adopted by label match (`:859 _docker_container_matches`) rather than flagged as a leak from a prior crash |
| `daedalus/spine/cancel.py:570-597` `ManagedProcess.close()`/`__exit__`/`__del__` | `finally` (in `close()`) + context manager `__exit__` + `__del__` backstop | child process tree (Job Object / process-group kill ladder) + container/backend release | yes | n/a (kernel already dies with parent per row 2) | n/a | **yes** — every real call site in `daedalus/` I found (`kernel/attempt_execution.py:1147/1154`, `council/vendors.py:420`, `chip_design/executor.py:1722`, `desktop_runtime.py:134`) uses `with ManagedProcess(...)` or an equivalent deterministic `with proc:`; `__del__` here is a correctly-scoped backstop, not the only path — **the fixed-defect pattern done right** |
| `daedalus/interfaces/bridge/watcher.py:50-126` `_BridgeWatcherLock` | real OS lock (`msvcrt.locking` / `fcntl.flock`), released in `__exit__` | file-bridge watcher ownership | yes | **yes** (OS releases the lock when the process's file table is torn down, any exit path) | **yes** | n/a — OS-guaranteed, not code-guaranteed; the *correct* answer to the sqlite thesis's problem, used here instead of an existence-convention lock file |
| `daedalus/kernel/effects.py:915` `EffectLeaseLedger.finish()` — `UPDATE ... SET state=?, finished_at=?...` | `finally`-free plain SQL write, invoked only by the caller after a real effect outcome is known | flips `effect_executions.state` from `STARTED` to a terminal value | n/a | n/a | n/a — see reconciliation gap below | see next section |
| `daedalus/kernel/effect_recovery.py:554-606` `reconcile_unknown_effect` | explicit, evidence-gated re-entry (not exit-path cleanup at all) | resolves an orphaned `STARTED` row given a caller-supplied signed `ExternalEffectObservation` | n/a | n/a | n/a | reactive-only, see below |

## Long-running entrypoints and their graceful-shutdown story

- **`daedalus/desktop_runtime.py` (`DesktopRuntimeManager`)** — the desktop
  sidecar supervisor (bridge thread, ollama, IDE, tunnel). No SIGTERM handler
  anywhere in the file or the repo. Only cleanup path is the `atexit.register`
  at `:342`. **Finding 1** (below).
- **`daedalus/web_api.py` `run()`/`main()` (`:1164-1230`)** — plain
  `ThreadingHTTPServer(...).serve_forever()`. Zero `signal.signal`, zero
  `atexit`, no `except KeyboardInterrupt`, no `httpd.shutdown()` call anywhere
  in the file. There is no graceful-shutdown story at all, not even for
  Ctrl+C — `serve_forever()` just runs until the process is killed by any
  means. Sockets are OS-cleaned either way; the only thing left mid-flight is
  whatever kernel effect a request was holding, which routes to the same
  reconciliation gap as Finding 2. Severity kept LOW here specifically because
  socket state itself needs no reconciliation and effect state is already the
  kernel's job (Finding 2), but flagged because the claim "the server has a
  shutdown path" would be false if anyone made it — nobody does, so this is a
  gap, not a false claim.
- **`daedalus/file_bridge.py` `watch()` / `daedalus/interfaces/bridge/watcher.py`
  `watch_loop()`** — no SIGTERM handler either, but the watcher's mutual
  exclusion is a real OS lock (see table), so a kill leaves nothing to
  reconcile: the lock releases itself and the heartbeat is read as staleness by
  timestamp, not as a false "I'm alive" claim. **Not a finding** of this
  resource class — cited as the correct contrast pattern.
- **`daedalus/token_monitor.py` `watch()` (`:210-221`)** — bare
  `while True: ...; time.sleep(interval_s)`. No lock, no lease, no atexit, no
  signal handler. Each iteration's `STATUS_PATH.write_text(...)` (`:191`) is a
  complete write, so a kill mid-loop just means the file reflects the last
  completed iteration, not a half-written or "running" record. Low severity,
  noted for completeness only.
- **`daedalus/spine/killswitch.py` `KillSwitch._watch_loop` (`:1018-1051`)** —
  a background **daemon thread** (not a signal handler) that polls a
  kill-switch flag and, once tripped, force-kills tracked `ManagedProcess`
  children via the grace-then-sweep ladder described in the large comment at
  `:1018-1046`. This is a deliberate, correctly-scoped mitigation for
  "the OS gives no cancellation guarantee to grandchildren" — it protects
  *children* of the host process. It does **not** protect the host process
  itself: if the process holding this thread is hard-killed, the thread dies
  with it, same as everything else. I read the surrounding docstrings for an
  overclaim and found none — it never asserts host-crash survival, only
  attribution-correctness for cooperative cancellation vs. the sweep. **Not a
  false claim.**
- **`daedalus/kairos/scheduler.py main()` and
  `daedalus/integrations/hermes/worker.py main()`** — both one-shot, not
  daemons (`worker.py`'s own docstring: "Hermes child process for the Daedalus
  JSONL one-shot runtime"). The worker is spawned and terminated
  *deterministically* by `HermesRuntimeAdapter._terminate()`
  (`daedalus/integrations/hermes/runtime_adapter.py:299-321`, a
  terminate-then-SIGKILL/`killpg` escalation ladder called from `execute()`'s
  own cleanup, not from atexit). Not this resource class's failure mode.

## States nothing reconciles after a kill

- **`daedalus/kernel/effects.py` `EffectLeaseLedger.effect_executions.state`**
  is a mutable column: `STARTED` (written at `:829-840`) →
  `COMPLETED`/`FAILED`/`CANCELLED` (written by `finish()`, `:901-915`, gated on
  `row["state"] == "STARTED"`, `:910`). A hard kill between the `STARTED`
  insert and `finish()` leaves a **permanent `STARTED` row** — there is no
  TTL, no reaper, nothing that ages it out.
  - A reconciliation primitive **does exist**:
    `daedalus/kernel/effect_recovery.py:554` `reconcile_unknown_effect`, wired
    through `daedalus/runtimes/recovery.py:224`
    `reconcile_runtime_provider_unknown`. It is well-designed: it demands the
    caller already hold the exact `execution_id`, the original
    `LeasedEffectStartReceipt`, and a freshly *signed*
    `ExternalEffectObservation` from the provider before it will flip a
    `STARTED` row to terminal; on mismatch it fails closed
    (`EffectRecoveryStateError`), never guesses. This is evidence-gated
    reconciliation done right, and another agent's kernel audit
    (`runs/analysis/g1-kernel-audit/effect_recovery.py.md`) already covers its
    internal correctness — I am not re-deriving that.
  - What I did verify and is **not** covered elsewhere: the mechanism is
    **strictly reactive, single-execution**. I grepped every SQL touching
    `effect_executions.state` (`daedalus/kernel/effects.py:806,830,910,915` —
    the only three write/read sites) and found **no enumeration query**
    anywhere in `daedalus/` or `tools/` of the shape
    `SELECT ... FROM effect_executions WHERE state='STARTED'` — the only
    `COUNT(*) ... WHERE state='STARTED'` (`:806`) is scoped to one
    `lease_sha256`, and `execution_state()` (`:937`) takes one
    `execution_id`. **Nothing in this codebase walks the ledger on startup and
    proactively reconciles every outstanding `STARTED` row.** The caller has
    to already know which `execution_id` to ask about. **Finding 2.**
  - Contrast: `daedalus/kernel/attempt_ledger.py` uses the canonical
    Event-Store instead of a mutable status column —
    `STATE_INTENDED`/`STATE_COMPLETED`/`STATE_FAILED`
    (`daedalus/spine/ledger.py`, consumed at `attempt_ledger.py:202-211`). A
    crash before the terminal event just means `_completion_for()` returns
    `None` (read as "still pending", `:202-203`) — it can never be misread as
    a false success, and (unlike the effect ledger) it *is* enumerable via
    `read_attempt_intents` (`attempt_spine_reader.py`). This is architecturally
    immune to the "stale RUNNING masquerading as done" failure mode and would
    make a natural drive-list for kernel-level effect reconciliation on
    restart — but I found no code in `daedalus/` or `tools/` that actually
    connects "walk `STATE_INTENDED` attempts → extract their effect
    `execution_id`s → call `reconcile_unknown_effect` for each" into one
    automatic resume routine. **That connective tissue is the actual gap**,
    not the primitive itself.
- **Desktop sidecar state** (ide/tunnel/docker) is not represented as a
  persisted status field at all — it lives only in
  `DesktopRuntimeManager` instance attributes (`self._ide`, `self._tunnel`,
  `self._ide_docker_managed_id`). There is nothing to reconcile in the sense of
  "flip a stale record", but there *is* an orphaned OS/Docker resource with no
  record pointing back at it once the owning process is gone — see Finding 1.

## Findings

### Finding 1 — Desktop sidecar cleanup is atexit-only; two of three managed children are not kill-safe

**File/line:** `daedalus/desktop_runtime.py:342` (`atexit.register(self.close)`),
consuming `daedalus/interfaces/desktop/lifecycle.py:25-44` (`close()`), which
calls `stop_ide()` (`:876-934`) and `stop_ollama()` (`:1198-1215`).

**Failure enabled:** `DesktopRuntimeManager.__init__` registers `self.close`
with `atexit` as the *only* cleanup path I could find a call site for (grepped
`\.close\(\)` and every `DesktopRuntimeManager(` construction in `daedalus/`;
no other caller). `close()` stops three different child resources:
1. ollama — spawned via `ManagedProcess` (`:981`, `_spawn_ollama_process`),
   which on win32 assigns the child to a Job Object with
   `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. This one *is* kill-safe independent of
   atexit — the OS tears it down when the parent's handle table closes, on any
   exit path including `taskkill /F`.
2. the IDE process — spawned as a **plain** `subprocess.Popen`
   (`:703`, only `creationflags=CREATE_NO_WINDOW`) when `ide.mode != "docker"`.
   No Job Object, no `CREATE_NEW_PROCESS_GROUP`.
3. the tunnel process — same pattern, plain `subprocess.Popen` (`:1152`).
4. the Docker-mode IDE — `docker run --detach --name daedalus-ide ...` with no
   `--rm` (`:823-846`). The container is a daemon-managed resource with a
   lifetime **completely decoupled** from the Python process; only `stop_ide()`
   ever issues a stop/remove.

**On mid-operation kill:** `taskkill /F` on the desktop_runtime process (or any
SIGTERM, since no handler is installed anywhere in this repo) skips atexit
entirely. Ollama dies anyway (Job Object). The plain-Popen IDE and tunnel
processes are orphaned — they keep running, holding whatever ports/sockets
they had. The Docker IDE container keeps running indefinitely; on the next
launch it is silently **re-adopted** by label match
(`_docker_container_matches`, `:859`) rather than flagged as a leftover from a
crashed prior run, so the leak is invisible in normal operation and only
surfaces as "why is there an unexpected container/process holding this port."

**Severity:** MEDIUM-HIGH for the Docker container path (a daemon-managed
resource that outlives not just the crashed process but any single machine
session until manually removed, and is never surfaced as orphaned); MEDIUM for
the plain-Popen tunnel/IDE processes (ordinary orphan, cleaned by a reboot).

**Confidence:** HIGH — read `__init__` through every `stop_*`/`close` call
site and confirmed via grep there is no second caller of `.close()` in
`daedalus/`. (`apps/` — the Tauri shell that presumably launches this process —
is out of scope for this sweep per task instructions, so I cannot say whether
Tauri sends `/T` on process exit; even if it does, that is an *external*
guarantee this Python code makes no attempt to provide or document.)

### Finding 2 — Effect-lease `STARTED` reconciliation is reactive-only; no proactive sweep exists

**File/line:** `daedalus/kernel/effects.py:806,910,937` (only queries against
`effect_executions.state`); `daedalus/kernel/effect_recovery.py:554-606`
(`reconcile_unknown_effect`); `daedalus/runtimes/recovery.py:224-264`
(`reconcile_runtime_provider_unknown`).

**Failure enabled:** the ledger has no enumeration query for outstanding
`STARTED` rows and no code in `daedalus/`/`tools/` that walks them
automatically. Reconciliation exists but requires a caller who *already knows*
the exact `execution_id` plus a freshly signed provider observation.

**On mid-operation kill:** a `STARTED` row from a killed process is a
permanently orphaned "we don't know what happened" record unless some future
process (a) independently knows to ask about that exact `execution_id` and
(b) can still obtain a valid signed observation for it. Nothing in this sweep's
scope automatically derives (a) from the attempt ledger's own enumerable
`STATE_INTENDED` rows.

**Severity:** MEDIUM. The design fails closed (no false success is ever
reported) rather than open, which is the important half of this — this is a
missing *automation* gap, not a correctness/safety hole. Given Gate 1's
promotion invariants, an un-reconciled `STARTED` row is inert (it grants no
authority to re-execute — `effects.py` docstring at `:1-14`/replay semantics
already establish `execute=False` on a start replay) rather than dangerous.

**Confidence:** MEDIUM — I confirmed the absence of an enumeration query and
of an automatic drive-list by grep + read of the three call sites that touch
`state`, but I did not exhaustively read every kernel/runtimes orchestration
entrypoint in the 100+ `started_at`-touching files; a resume routine could
exist under a name this sweep's keyword list didn't catch. Flagging as a
question for whoever owns `kaud-w5-effects`/`kaud-w7-exec` (concurrently
auditing this exact area per the session's agent roster) rather than as a
closed verdict.

### Finding 3 — `desktop_runtime.py` has no SIGTERM handler at all (repo-wide gap, not unique to this file)

**File/line:** repo-wide — zero `signal.signal(` calls installing an incoming
handler anywhere in `daedalus/` or `tools/` (confirmed by exhaustive grep;
every `SIGTERM`/`SIGINT` hit is either outgoing (`send_signal`, `killpg`,
`terminate`) or a docstring/fault-matrix string).

**Failure enabled:** per this task's own framing, `atexit` does not run on
SIGTERM unless a handler is installed — and none is, anywhere. This means
`atexit.register(self.close)` (Finding 1) is *strictly weaker* than its own
placement suggests: it protects against `sys.exit()` and uncaught exceptions,
not against the two most likely ways an operator actually stops a long-running
service (service-manager `SIGTERM`, or on Windows, `taskkill` without `/F`
still delivers `WM_CLOSE`/console-control rather than a Python-visible signal
in most launch configurations, and `taskkill /F` skips it entirely).

**Severity:** MEDIUM — this is the root cause underlying Finding 1's severity,
called out separately because it's a repo-wide absence, not a per-file bug.

**Confidence:** HIGH (exhaustive grep, zero hits).

## NOT findings

- **`daedalus/spine/cancel.py` `ManagedProcess.__del__` (`:593-597`)** — looks
  like the fixed thesis pattern on first grep, but reading `close()`/`__exit__`
  shows every real call site uses `with ManagedProcess(...)` (4 production
  sites checked: `kernel/attempt_execution.py:1147/1154`,
  `council/vendors.py:420`, `chip_design/executor.py:1722`,
  `desktop_runtime.py:134`). `__del__` is a correctly-scoped backstop with a
  deterministic primary path — the fixed defect's pattern, done right. Not a
  finding.
- **`daedalus/interfaces/bridge/watcher.py` `_BridgeWatcherLock`** — real OS
  file lock (`msvcrt.locking`/`fcntl.flock`), released by the kernel on any
  process death. Correct answer to the exact class of problem this sweep is
  looking for. Not a finding.
- **8 `tempfile.TemporaryDirectory`/`NamedTemporaryFile` call sites** — all 8
  read (`desktop_runtime.py:1048`, `ikarus_os.py:1621`,
  `council/vendors.py:381,414`, `eval/correctness.py:786`,
  `runtimes/fixture_fault_collector.py:816`, `providers/codex_cli.py:223`) are
  used as context managers (`with tempfile.TemporaryDirectory(...) as td:`) or,
  for `council_cwd` (`:373-388`), returned as an unentered handle whose only
  two real callers (`council/vendors.py:734,912`) both wrap it in `with
  council_cwd(...) as cwd:`. `weakref.finalize` inside `TemporaryDirectory` is
  stdlib's own documented backstop and is never the *only* path here. Not a
  finding.
- **`daedalus/spine/killswitch.py` watch daemon thread** — correctly scoped to
  child-process cancellation; docstrings never claim host-crash survival.
  Checked for an overclaim per instruction 7; found none. Not a finding.
- **4 `sys.exit(main())` sites** (`memory/projection_worker.py:1014`,
  `mapping/render.py:1657`, `mapping/inventory.py:1058`,
  `mapping/drift.py:1567`) — ordinary CLI boilerplate; `SystemExit` still
  unwinds `finally`/atexit normally. Not a finding.
- **`os._exit()`** — 0 hits in `daedalus/`/`tools/`. Not a finding (nothing to
  find).
- **`in_progress`** — 0 hits. The repo's mutable-state vocabulary for this
  resource class is `STARTED`/`state=` (kernel) and `"running"` (desktop/
  progress UI), not `in_progress`. Covered above.
- **`kairos/scheduler.py`, `hermes/worker.py` mains** — one-shot, not daemons;
  out of this resource class.
- **`token_monitor.py watch()`** — no lease, no lock, per-iteration atomic
  write; a kill loses nothing beyond "the monitor stopped monitoring", which
  is externally observable (process gone) rather than a stale-but-plausible
  record. Noted, not escalated.

## What deserves its own fix packet

1. **Finding 1** (desktop sidecar) — the Docker-container leak specifically:
   either add `--rm` semantics compatible with the reuse-by-label design (so a
   genuinely-orphaned container from a crashed prior run is distinguishable
   from a deliberately-detached one across restarts), or have the *next*
   `ensure_ide()` explicitly check the container's start time / a liveness
   marker against the previous run's recorded PID and treat a mismatch as
   "adopted from crash" evidence rather than silent reuse. Independently,
   wrap the plain-Popen IDE/tunnel spawns through the same `ManagedProcess`
   Job Object path ollama already uses, or accept the orphan risk explicitly
   in a comment (currently undocumented either way).
2. **Finding 3** — if graceful shutdown for `desktop_runtime.py` is a real
   product requirement (it manages user-visible child services), install a
   `signal.signal(signal.SIGTERM, ...)` handler that calls the same `close()`
   atexit already reaches, so the intentional "stop the service" path is not
   weaker than the crash path.
3. **Finding 2** — lower priority given it fails closed: if kernel resume
   logic is desired, wire an automatic sweep from `AttemptLedger`'s enumerable
   `STATE_INTENDED` rows to `reconcile_unknown_effect` at process/attempt
   resume time. Coordinate with `kaud-w5-effects`/`kaud-w7-exec` before
   duplicating — they are auditing this exact ledger concurrently per the
   session's agent roster.
