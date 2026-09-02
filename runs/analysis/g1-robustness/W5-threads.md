# W5 — Threads and Concurrency: read-only static sweep

- **Repo**: `C:/Users/Administrator/daedalus`
- **Commit at sweep time**: `2233a148b6423bd5085ab189e1bc9b3f97613191` (2026-09-02 12:15:52 +0200) — local `main`; task brief named `54f09753`, tree had since advanced. No file was modified, no git command mutated state, no code was executed.
- **Scope**: `daedalus/` and `tools/` (Python only). `tests/`, `apps/`, `vault/`, `.quarantine/`, `daedalus/lanes/` write-paths were read where in scope for grep hits (`daedalus/lanes/fanout.py` is in-scope source, not touched/written) but nothing under those trees was written.
- **Canonical defect writeup read first**: `daedalus/kernel/effects.py:576-587` (`EffectLeaseLedger._initialize`) — the shape is *a resource whose release is not bound to a deterministic program point*.

## Patterns grepped, raw hit counts

| Pattern | Raw hits (daedalus/) | Raw hits (tools/) |
|---|---|---|
| `threading\.Thread` | 11 files, 16 construction sites | 0 |
| `\.start\(\)` (thread starts only, filtered from `re.match.start()` noise) | 12 real thread `.start()` calls | 0 |
| `\.join\(` (thread joins only) | 7 real thread `.join()` calls | 0 |
| `daemon` | 12 threads created with `daemon=True`; 0 with `daemon=False`; 0 left unset | 0 |
| `ThreadPoolExecutor\|ProcessPoolExecutor\|concurrent\.futures` | 7 files | 1 (comment/guard string only) |
| `queue\.Queue` | 1 file, 1 construction | 0 |
| `threading\.Event\(\)\|threading\.Condition\(` | 5 files | 0 |
| `signal\.signal\(` | 0 | 0 |
| `threading\.Lock\(\)\|threading\.RLock\(\)` | 17 files | 0 |

Triaged: 16 thread-construction sites read in full with surrounding class/function; 7 `ThreadPoolExecutor`/`ProcessPoolExecutor` call sites read in full; all 17 `Lock()`/`RLock()` files' usage sites read; both `Event`/`Condition` non-thread-pool usages read; `KeyboardInterrupt` handling cross-referenced against which thread executes it (2 files: `daedalus/loop.py`, `daedalus/offload.py`); module-level mutable caches enumerated (11 caches: `conversation.py:_STORE_CACHE`, `council/bus.py:_APPEND_CACHE`, `health.py:_SSH_CACHE`/`_SOURCE_CACHE`, `ikarus_os.py:_HAND_CACHE`, `runtime_registry.py:_status_cache`, `semantic_route.py:_ROLE_VEC_CACHE`, `tools/vet.py:_INVISIBLE_CACHE`, `spine/killswitch.py:_CONTROL_CHECK_CACHE`, `structcore/index.py:_RESOLVER_CACHE`+`_INDEX_CACHE`) and their lock discipline checked.

## Daemon-thread inventory (one line)

12/12 threading.Thread construction sites in `daedalus/` use `daemon=True` explicitly (none unset, none `daemon=False`); every one is either (a) explicitly joined with a timeout on all exit paths, or (b) deliberately abandoned per a written-out rationale that the abandoned work has no owned resource or is bounded by atomic writes — except the two gaps below.

## Full table — every thread/executor creation site

| Site | daemon | Joined? | Owns | At interpreter exit |
|---|---|---|---|---|
| `daedalus/build_exec.py:1093` `beat_thread` | True | Yes, `join(timeout=2.0)` in `finally` (line 1191) | Nothing (emits progress events only, itself lock-protected) | Clean — joined before wave returns |
| `daedalus/conversation_requests.py:171` `worker` | True | **No** — only `.is_alive()` polled (lines 304-306, 360) | Spine intent (`mark_completed`/`mark_failed`), provider stream, `runtime.condition`/events | **Abrupt kill mid-turn** if process exits while streaming; spine intent stays `INTENDED` forever (module docstring explicitly accepts this: "reported as `unknown`... never automatically replayed") |
| `daedalus/council/session.py:715` `thread` (per vendor call, `_dispatch_round`) | True | Yes, `join(deadline - now)` (line 733); if the deadline already passed, `join(0)` returns immediately and the thread is **left running** in the background | Vendor adapter subprocess/socket, bounded separately by `spine.cancel.ManagedProcess` inside the adapter | Deliberately documented (lines 62, 704-708): "a thread cannot be killed... abandoned at the cap" |
| `daedalus/council/canary.py:1080` `thread` (per lane, `run_canary`) | True | Same pattern as session.py (line 1089) | Same — vendor probe, bounded by adapter-level process containment | Same documented rationale (lines 1038-1042) |
| `daedalus/desktop_runtime.py:457` `thread` (`_bridge`, file-bridge watcher) | True | **No** — `ensure_bridge()` polls `.is_alive()` for 1.5s (lines 470-479); `close()` → `desktop_lifecycle.close()` (line 35) only sets `_bridge_stop`, never calls `.join()` | File-bridge heartbeat/lock files under `self.root` (writes go through `write_text_atomic`) | **Abandoned at process exit** — atomic writes bound per-file corruption, but not cross-file (heartbeat+companion) consistency, and `atexit.register(self.close)` (line 342) never actually waits for the thread to stop |
| `daedalus/hooks/_common.py:177` `worker` (`with_deadline`) | True | Yes, `join(seconds)` (line 179) | Whatever `fn` does (e.g. `arch_memory.render_delta`, which writes via `write_text_atomic`) | Deliberately documented (lines 162-167): "dies with the process... milliseconds later"; atomic-write callees bound the damage to an orphaned temp file |
| `daedalus/integrations/hermes/runtime_adapter.py:262` `self._thread` (`_BoundedStderr._consume`) | True | Yes, `join(timeout=2.0)` in `finish()` (line 280), called from the adapter's `finally` (line 525) | Nothing owned — reads a pipe into an in-memory digest | Clean |
| `daedalus/integrations/hermes/runtime_adapter.py:419` `stdout_thread` | True | **No** — never joined anywhere in `execute()` | Puts worker-protocol messages onto `output_queue`; reads `process.stdout` | Self-limiting (stream closed in `finally` at line 518-523 causes the blocking read to fail/return), but **not verified to have exited** before `execute()` returns — a leaked daemon thread per call under load |
| `daedalus/integrations/hermes/tool_gateway.py:158` `self._thread` (`_serve`) | True | Yes, `join(timeout=2.0)` in `close()` (line 221), always called via `hermes_runtime_session`'s `try/finally` (session.py:56-57) | Listener socket, one accepted client socket | Clean |
| `daedalus/progress_sources.py:319` `thread` (`_beat`, `track_call`) | True | **No** — only `stop.set()` in `finally` (line 333); thread's own `stop.wait()` returns promptly but is never awaited | Nothing owned directly; calls `P.heartbeat()` which is lock-protected (`progress.py:279,284`) | Bounded race window: `track_call()` can return while the heartbeat thread is still mid-`P.heartbeat()` call, though both writers share `ProgressLog._lock` so no corruption — just a possible post-return write |
| `daedalus/providers/ollama.py:375` anonymous `Thread` (`warm_model_async`) | True | No — explicitly fire-and-forget by design (docstring line 368) | Nothing (best-effort HTTP GET/POST with its own timeout) | Harmless — no owned resource |
| `daedalus/spine/killswitch.py:1004` `self._watcher` (`_watch_loop`) | True | Yes, `join(timeout=timeout)` in `stop_watch()` (line 1016), guarded against joining self | Nothing directly; polls `should_stop()`/marker file and calls `stop_children()` | Clean, and explicitly designed to be a bounded daemon (lines 996-998) |

**Executor sites (all clean — `with` context manager used, futures' `.result()`/exceptions retrieved on every path):**

| Site | Type | Shutdown | Result/exception retrieval |
|---|---|---|---|
| `daedalus/kairos/scheduler.py:356` (`KairosScheduler.dispatch`, `_run_one`) | `ThreadPoolExecutor` | `with` block | `f.result()` per future (line 362), `BudgetRefused` caught per-future; other exceptions propagate (not silently discarded) |
| `daedalus/structcore/index.py:544` (`_compute`) | `ProcessPoolExecutor` | `with` block | `ex.map(...)` iterated fully; any exception falls through to the outer `except Exception:` at line 548, which **silently swallows it** and falls back to serial (see finding below) |
| `daedalus/lanes/fanout.py:467` (`run_fanout` or similar) | `ThreadPoolExecutor` | `with` block, `as_completed` | `fut.result()` per completed future (line 473), exception captured into `FanoutResult.errors`, not discarded |

## Findings

### 1. `daedalus/kairos/scheduler.py:333-376` — Ctrl-C during parallel dispatch does not stop, it hangs on executor shutdown

```python
if can_parallel and len(live_tasks) > 1:
    from concurrent.futures import ThreadPoolExecutor
    ...
    with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
        futs = {pool.submit(_run_one, a, True, pos): k
                for k, (pos, a) in enumerate(pending)}
        for f in futs:
            k = futs[f]
            try:
                done[k] = f.result()
            except BudgetRefused as exc:
                done[k] = spend_refused_result(pending[k][1], exc)
```
`_run_one` (line 272) calls `daedalus.offload.offload(...)` directly inside the pool worker. `offload.py:939` has:
```python
except (KeyboardInterrupt, SystemExit) as exc:
    ...  # maps to a "killswitch" stop reason
```
**Failure enabled**: `KeyboardInterrupt`/`SIGINT` in CPython is delivered only to the **main thread**. When `dispatch()` is parallel, `offload()` runs inside a worker thread, so `offload.py`'s `except (KeyboardInterrupt, SystemExit)` clause is unreachable for this call path — dead code exactly where the codebase's own `loop.py`/`offload.py` killswitch mapping was meant to catch it. The interrupt instead lands on the **main thread**, wherever it currently is — inside the `for f in futs: f.result()` loop, or (worse) inside the implicit `pool.__exit__()` triggered by that exception unwinding through the `with ThreadPoolExecutor(...) as pool:` block. `Executor.__exit__` calls `shutdown(wait=True)`, which **blocks until every submitted task finishes** — including workers that were never told to stop.

**On mid-operation kill**: not abandoned wreckage but the opposite failure mode — the process **cannot exit**. A Ctrl-C during a parallel wave blocks in executor teardown until every in-flight `offload()` call finishes on its own (which can be the multi-minute gate/test run the wave was dispatching), silently defeating the "abandon a stuck worker" intent documented everywhere else in this sweep (`council/session.py`, `council/canary.py`, `spine/killswitch.py`). No cancellation token is threaded into `_run_one`/`offload()` on this path.

**Severity**: HIGH — blast radius is the operator-facing kill/interrupt story for the one dispatch path that is supposed to run several attempts concurrently; a stuck gate under a parallel wave becomes unkillable by Ctrl-C.
**Confidence**: HIGH — traced the exact call chain (`dispatch` → `ThreadPoolExecutor` → `_run_one` → `offload`), confirmed `KeyboardInterrupt`/`SystemExit` handling exists only in `offload.py` and is main-thread-only by CPython semantics, confirmed `with ThreadPoolExecutor(...)` has no `cancel_futures=True` usage (`shutdown(wait=True)` is the default `__exit__` behavior in this Python's `concurrent.futures`, i.e. no `cancel_futures` argument passed).

### 2. `daedalus/conversation_requests.py:171-178,304-306,360` — chat-turn worker thread is never joined; a killed process abandons mid-generation state

```python
worker = threading.Thread(
    target=self._run, args=(intent.id,),
    name=f"ikarus-turn-{intent.id}", daemon=True)
runtime.worker = worker
...
worker.start()
```
Only `runtime.worker.is_alive()` is ever consulted afterward (status/cancel paths); the thread itself is never `.join()`ed anywhere in the module.

**Failure enabled**: `daemon=True` means a clean `sys.exit`/process shutdown kills this thread abruptly, mid-`_run()`. `_run()` does provider streaming and, on `final`, calls `self.spine.mark_completed(...)` (line 251) inside the loop body — a kill between "provider produced the final frame" and "`mark_completed` returns" leaves the canonical spine `Intent` stuck at `STATE_INTENDED` forever.

**On mid-operation kill**: the module's own docstring (lines 8-10) names this exactly: *"After a server restart an unresolved request is reported as `unknown` and is never automatically replayed."* This is a **documented, accepted** instance of the defect shape — not a silent gap — but it is real: a killed process during any in-flight chat turn leaves an intent that reads as `unknown` forever, with no automatic reconciliation, and no operator-visible flag distinguishing "still running elsewhere" from "died mid-turn."

**Severity**: MEDIUM — correctness-bounded by design (canonical spine, not a corrupted file), but user-visible: an in-flight reply silently vanishes with no automatic recovery, and nothing marks the stuck intent for cleanup.
**Confidence**: HIGH — read the full `create()`/`_run()`/`status()`/`cancel()` methods; confirmed no `.join()` call exists anywhere in the file (`Grep` for `worker.join`, `runtime.worker.join`: 0 hits).

### 3. `daedalus/desktop_runtime.py:342,419-468,1220` + `daedalus/interfaces/desktop/lifecycle.py:25-43` — bridge watcher thread is stopped but never joined, including at `atexit`

```python
# desktop_runtime.py:342
atexit.register(self.close)
...
# interfaces/desktop/lifecycle.py:25
def close(manager, *, strict, timeout, error_type) -> None:
    manager._closed = True
    manager._bridge_stop.set()          # <- only this
    ...                                   # no manager._bridge.join(...)
```
**Failure enabled**: `close()` — the method registered with `atexit` — sets the stop `Event` but never calls `manager._bridge.join()`. The bridge thread (`_watch_bridge` → `file_bridge.watch`, polling every 2.0s per the constructor args at line 430) may still be inside `file_bridge.watch`'s loop body when the interpreter proceeds to finish exiting; being `daemon=True`, it is then terminated wherever it happens to be.

**On mid-operation kill**: `file_bridge.watch` writes through `write_text_atomic` (confirmed in `daedalus/file_bridge.py:14,310,476,918`), so any single file write is individually atomic (temp+rename) and cannot leave a half-written file. The residual risk is **cross-write consistency**: if one poll cycle updates more than one companion artifact (e.g. a heartbeat file and a lock/ownership file) and the kill lands between the two atomic writes, the pair can go stale/inconsistent relative to each other, even though neither file alone is corrupt. Also, because `close()` doesn't wait, the up-to-2-second poll window is not actually bounded at process-exit time — the "8s timeout" parameter on `close()` (`desktop_runtime.py:1220`) is spent on `stop_ide`/`stop_ollama`, not on the bridge thread at all.

**Severity**: MEDIUM — atomic per-file writes bound single-file corruption; the exposure is stale/torn multi-file state and an unbounded (if short) exit-time race, not silent data loss.
**Confidence**: HIGH — read `ensure_bridge`, `close`, and `desktop_lifecycle.close` in full; confirmed no `.join()` call on `_bridge` exists anywhere in `desktop_runtime.py` (`Grep` for `_bridge.*join`: 0 hits) or in `lifecycle.py`.

### 4. `daedalus/integrations/hermes/runtime_adapter.py:419-425` — `stdout_thread` created and started but never joined

```python
stdout_thread = threading.Thread(
    target=self._stdout_reader, args=(process.stdout, output_queue),
    name="daedalus-hermes-stdout", daemon=True)
stdout_thread.start()
```
No `stdout_thread.join(...)` exists anywhere in `execute()` (confirmed by grep of the whole method, lines 333-541); only `stderr_reader.finish()` (which does join its own thread) is awaited in the `finally` block.

**Failure enabled**: `_stdout_reader` loops on `read_message(stream)` until `EOFError`/exception, pushing items to `output_queue`. `execute()`'s `finally` block closes `process.stdout` (line 518-523), which should cause the blocking read inside `_stdout_reader` to raise and the thread to exit — but `execute()` returns its `HermesRuntimeResult` without ever confirming that exit happened.

**On mid-operation kill**: low direct damage — the thread owns no file/lock/DB, only pushes to an in-memory `queue.Queue` that becomes unreachable and is garbage-collected. The exposure is a per-call leaked daemon thread whose lifetime is bounded only by "the OS eventually delivers EOF/error on the closed pipe," which is exactly the class of *not-a-deterministic-program-point* release this sweep is chartered to find, even though the blast radius here is low (no persisted side-state).

**Severity**: LOW — matches the defect shape structurally, but no observable side-effect (no file, no lock, no DB) is at stake.
**Confidence**: HIGH — read the entire `execute()` method; grepped for `stdout_thread` across the file (3 hits: construction, `.start()`, none for `.join`).

### 5. `daedalus/structcore/index.py:820-928,1240-1253` — `_RESOLVER_CACHE` is mutated with no lock, from inside `build_index()` itself, while `_INDEX_CACHE`'s caller-side lock (`_build_lock`) only wraps the *caching wrapper*, not `build_index()` when called directly

```python
_RESOLVER_CACHE[resolver_key] = resolver          # inside build_index(), line 919 — unlocked
...
_RESOLVER_CACHE: dict[str, "graph.SymbolResolver"] = {}
...
_INDEX_CACHE: dict[str, dict] = {}
_BUILD_LOCKS: dict[str, threading.Lock] = {}
...
def _index_cached(...):
    if not refresh and key in _INDEX_CACHE:        # read outside any lock
        return _INDEX_CACHE[key]
    with _build_lock(key):
        ...
        _INDEX_CACHE[key] = build_index(...)        # build_index() writes _RESOLVER_CACHE here, still under _build_lock(key)
```
**Failure enabled**: `build_index()` is a public function (used directly by callers other than `_index_cached`, e.g. CLI/report tooling) and unconditionally writes `_RESOLVER_CACHE[resolver_key]` with no lock at all. When invoked only through `_index_cached`, the per-key `_build_lock` incidentally serializes it; when invoked directly and concurrently (e.g. two callers building the same root from two threads, one via the cached path and one calling `build_index()` directly), the two writes race on the same dict key with no ordering guarantee. CPython's GIL makes the individual `dict.__setitem__` atomic (no memory corruption), but the *last writer wins* non-deterministically, and the module's own comment block (lines 886-892) documents that this exact resolver/index pairing has drifted before ("resolved callees against a `defs_by_file` that still contained SHELL units") — the fix applied was aligning the cache **keys**, not adding a lock around `build_index()`'s cache write.
**On mid-operation kill**: not applicable (no thread is created here — this is a same-process concurrent-caller race, in scope per item 3 of the brief: "shared mutable state touched from more than one thread without a lock").
**Severity**: LOW — GIL bounds it to a non-corrupting race; worst case is duplicate work or a transient resolver/index pairing mismatch of the kind already fixed once by key alignment, not a crash or data loss. Not on the effect/ledger/evidence path — `structcore` feeds distillation reports, not spine writes.
**Confidence**: MEDIUM — confirmed the unlocked write exists and `build_index` is exported/callable directly (`def build_index(` at module scope, no leading underscore); did not enumerate every external call site of bare `build_index()` to prove concurrent direct callers exist today, so this is a real latent hazard rather than a demonstrated live race.

### 6. `daedalus/structcore/index.py:544-552` — `ProcessPoolExecutor` failures are silently discarded, not surfaced

```python
try:
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for batch in ex.map(analyze_chunk, chunks):
            for i, analysis in batch:
                out[i] = analysis
except Exception:
    # No usable pool (sandbox, spawn failure, unpicklable payload): the
    # serial path is always correct, just slower.
    for i, rel, text, spec in pending:
        out[i] = analyze_file(rel, text, spec, ts_on)
```
**Failure enabled**: this is a deliberate, documented fallback (comment explains the rationale), so it is not the resource-*lifetime* defect this sweep targets, but it is exactly the "exception never retrieved" pattern named in item 2 of the brief: a crashed pool worker's real exception (a genuine bug in `analyze_chunk`, not just an environment/pickling issue) is caught by the same blanket `except Exception:` and silently replaced by a full serial re-run with no log line distinguishing "environment doesn't support processes" from "a worker crashed on this input." Recorded here as a borderline item, not counted in the headline findings.
**Severity**: LOW (by design, but the swallow is broader than the stated rationale).
**Confidence**: HIGH.

## NOT findings — deliberately abandoned/joined patterns, read and confirmed correct

- `daedalus/council/session.py:704-734` (`_dispatch_round`) — daemon threads abandoned at the per-council budget deadline, explicitly documented ("a thread cannot be killed... abandoned at the cap"), each `box` result defaults to an `unavailable`/`timeout` chained turn so no participant silently vanishes. Correct by design.
- `daedalus/council/canary.py:1030-1089` (`run_canary`) — identical documented pattern, `threading.Semaphore` used correctly to bound `max_parallel` probes.
- `daedalus/spine/killswitch.py:993-1016` — watcher thread started/stopped/joined correctly, with explicit self-join guard (`watcher is not threading.current_thread()`).
- `daedalus/build_exec.py:1080-1191` — heartbeat thread started, stopped and joined with a 2.0s timeout in a `finally` on every wave exit path, with an explicit comment on why the join matters even though the thread is a daemon (long-lived host process, stale "still working" signal risk).
- `daedalus/integrations/hermes/tool_gateway.py:108-232` — server thread started/closed correctly through `__enter__`/`__exit__`, always invoked via `hermes_runtime_session`'s `try/finally` (`session.py:38-57`); socket listener has its own timeout so `accept()` cannot block forever.
- `daedalus/integrations/hermes/runtime_adapter.py:256-282` (`_BoundedStderr`) — thread joined with a 2.0s timeout in `finish()`, itself always called from the adapter's outer `finally`.
- `daedalus/hooks/_common.py:151-180` (`with_deadline`) — daemon-thread abandonment explicitly reasoned about in the docstring; joined with the caller's own deadline before returning a `default`.
- `daedalus/providers/ollama.py:366-377` — explicit fire-and-forget, no owned resource, timeout-bounded HTTP call inside.
- All three `ThreadPoolExecutor`/`ProcessPoolExecutor` production call sites (`kairos/scheduler.py:356`, `structcore/index.py:544`, `lanes/fanout.py:467`) use `with` and retrieve every future's result/exception — no leaked pool, no discarded exception on the primary paths.
- `queue.Queue.get()` in `runtime_adapter.py:439` uses an explicit bounded timeout; no unbounded `queue.get()`/`put()` exists in scope.
- No `threading.Event.wait()`/`Condition.wait()` without a timeout exists in scope (`conversation_requests.py:336` and every other `.wait(` hit carries an explicit timeout argument).
- `signal.signal(` — zero occurrences in `daedalus/` or `tools/`; nothing to flag for item 6's first half.
- `KeyboardInterrupt` handlers in `daedalus/loop.py:1506` and `daedalus/offload.py:939` are both reachable correctly **when their caller runs on the main thread** (the default, sequential dispatch path) — see Finding 1 for the one path where that assumption breaks.
- Every module-level cache/lazy-singleton found (`conversation.py:_STORE_CACHE`, `council/bus.py:_APPEND_CACHE`, `runtime_registry.py:_status_cache`, `budget` ledger's `_DEFAULT`/`_DEFAULT_LOCK`, `spine/killswitch.py:_CONTROL_CHECK_CACHE`, `spine/cancel.py:_LIVE`/`_LIVE_LOCK`, `progress.py:_DEFAULT_LOG`/`_DEFAULT_LOG_LOCK`) uses the correct double-checked-lock-with-mutex idiom: a dedicated `threading.Lock`/`RLock` guards both the read-check and the write. `daedalus/ikarus_os.py:_voice_client()` is not a singleton at all (constructs fresh every call, by design, per its own comment) so it was not a lazy-init race candidate.
- Read-only/no-lock caches not on any effect/ledger/evidence path (`health.py:_SSH_CACHE`/`_SOURCE_CACHE`, `ikarus_os.py:_HAND_CACHE`, `semantic_route.py:_ROLE_VEC_CACHE`, `tools/vet.py:_INVISIBLE_CACHE`) are simple dict get/set operations; CPython's GIL makes each individual operation atomic, and worst case is a redundant recompute or a stale liveness read — not counted as findings.
- `tools/` (in scope per the brief) has **zero** `threading.Thread`, `ThreadPoolExecutor`/`ProcessPoolExecutor`, `queue.Queue`, or `signal.signal` usage. `tools/bootstrap_receipt.py:684` has an untimed `subprocess.Popen.wait()` — that is a **subprocess**, not a thread, resource and is out of this W-track's resource class (belongs to the subprocess-lifetime sweep).
- `daedalus/adapters/subprocess_adapter.py` and `daedalus/kairos/evolution.py`'s untimed `await process.wait()` calls are asyncio subprocess waits, not thread/Event/Condition waits — out of scope for this sweep, noted only so they are not silently missed by a different track.

## Totals

- Thread-construction sites enumerated: **16** (12 real running threads in production paths + 4 shown are the same 12 counted once each — see table; 12 distinct named threads, all `daemon=True`).
- Threads properly joined on every path: **7** (`build_exec` beat, `hooks/_common` deadline worker, `hermes` stderr reader, `hermes` tool-gateway server, `spine/killswitch` watcher — 5 always-clean; plus `council/session` and `council/canary` per-vendor threads which join with a deadline-bounded timeout that can legitimately be zero, by design).
- Threads never joined (genuine gaps): **4** — `conversation_requests.py:171`, `desktop_runtime.py:457`, `runtime_adapter.py:419`, `progress_sources.py:319`.
- Fire-and-forget by explicit design, no owned resource: **1** (`providers/ollama.py:375`).
- `ThreadPoolExecutor`/`ProcessPoolExecutor` sites: **3**, all clean (context-managed, results retrieved).
- Unlocked shared mutable state found: **1** (`structcore/index.py` `_RESOLVER_CACHE` write inside `build_index()`), latent not demonstrated live.
- Silently-discarded pool exceptions: **1**, by documented design but broader than its stated rationale (`structcore/index.py:548`).
- `signal.signal()` registrations: **0**.
- Untimed `Event.wait()`/`Condition.wait()`: **0**.
- Untimed `queue.get()`/`put()`: **0**.
