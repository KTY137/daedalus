# W7 — Timeouts on every blocking call (read-only static sweep)

Scope: `daedalus/` and `tools/` (Python only; `tests/`, `apps/` out of scope).
Repo: `C:/Users/Administrator/daedalus`. Commit at sweep time: `41e1b26549dc60721f0213ca06491cf4cd684852`
(local main; session tree shows working branch `wip/g1-freeze-2026-08-31` with one
untracked `runs/analysis/` dir and one modified test file — neither touched by
this sweep). No files modified, no commands executed against repo code, no git
mutation performed.

Canonical defect-shape reference read first: `daedalus/kernel/effects.py:576-587`
(`with sqlite3.connect(...)` commits but does not close; a bound/scope that
looks enforced but isn't). Generalized resource class for this sweep: **a
bound that is declared but not actually enforced at the program point that
blocks** — specifically execution **wall time**, which
`docs/IKARUS_ARIADNE_MASTER_PLAN.md` §4 invariant 8 and §4.1 name as an
explicitly enumerated, bounded-by-default axis.

De-duplication: `subprocess.run` / `Popen.communicate` / `Popen.wait` on the
**stdlib subprocess** path were covered in depth by a parallel worker and are
NOT re-enumerated here except where they interact with a finding in my own
resource class (asyncio subprocess `.wait()`, and a raw ctypes/`os.waitpid`
primitive that is not `subprocess.*` at all).

## Patterns grepped and raw counts

| Pattern | daedalus/ | tools/ | Notes |
| --- | --- | --- | --- |
| `requests\.(get\|post\|put\|delete\|patch\|head\|Session)` | 0 | 0 | `requests` the HTTP library is not imported anywhere; every `requests` hit was `daedalus.conversation_requests`, an unrelated internal module |
| `urlopen` (raw string) | 60 files matched a looser `httpx\.` pass first — re-run precisely | — | see corrected counts below |
| `urllib\.request\.urlopen(` — actual call sites | 16 | 5 | all 21 pass `timeout=` explicitly |
| `httpx` | 0 real calls (2 files reference the string only as a forbidden-import name in `integrations/hermes/conformance.py` and `tools/vet.py`) | 0 | httpx is not a runtime dependency of this code |
| `http\.client` | 0 | 0 | not used |
| `socket\.(socket\|create_connection)` | 6 real network sites + 2 `bind()`-only in tools/ | included above | all 6 network sites pass `timeout=`/`settimeout()` |
| `queue\.Queue` / `.get(timeout=` | 1 real usage (`integrations/hermes/runtime_adapter.py`) | 0 | bounded, inside a deadline loop |
| `threading.Event().wait(` | 6 real call sites | 0 | all pass an explicit poll interval |
| `.acquire(` (explicit, not `with lock:`) | 0 | 0 | no bare `.acquire()` anywhere |
| `ThreadPoolExecutor`/`ProcessPoolExecutor` + `.result()`/`as_completed`/`.map()` without a future-level `timeout=` | 4 live sites (+1 in a `.src` template, inert) | 0 | see Finding 2/3 for the one with a real gap |
| `asyncio.wait_for` | 5 real call sites | 0 | all pass `timeout=` |
| `await <asyncio subprocess>.wait()` / `.communicate()` with no `wait_for` wrapper | 3 sites | 0 | 2 are a genuine gap (Finding 2), 1 is the plan's sanctioned explicit-disable path (Finding 5) |
| `while True:` | 39 | 2 (+2 comment-only) | triaged individually below; 37 bounded, 1 unbounded lock loop (Finding 1), 1 unbounded doubling loop (Finding 3) |
| `time.sleep(` | 23 | 7 (+2 comment-only) | all inside a `deadline = time.monotonic() + X` loop except the two flagged |
| `input(` / `sys.stdin` on an unattended path | 0 interactive `input()` calls anywhere in daedalus/tools; `sys.stdin` used in 3 places, all bounded transitively or are dev CLIs expecting piped input | — | not a finding, see below |
| `os.waitpid(` without `WNOHANG` | 2 (via `_NATIVE_WAITPID`/`_NATIVE_CLEANUP_WAITPID` aliases = `os.waitpid`) | 0 | Finding 4 |

## Master inventory (every blocking call site touched by this resource class)

Legend: **TO** = timeout present; **Default-if-absent** = what happens if no
bound existed; **Eff.** = effectful/kernel path (mission, attempt, lease,
ledger, evidence, promotion, or a canonical runtime-contract entrypoint) vs.
dev tool.

| file:line | API | TO y/n | Default-if-absent | Eff. |
| --- | --- | --- | --- | --- |
| daedalus/doctor.py:69 | `urlopen` | y (3s) | infinite hang | dev tool |
| daedalus/desktop_runtime.py:496 | `urlopen` | y (param) | infinite hang | y (desktop IDE probe) |
| daedalus/desktop_runtime.py:944 | `urlopen` | y (param) | infinite hang | y |
| daedalus/accelerators.py:242 | `urlopen` | y (3s) | infinite hang | y |
| daedalus/health.py:490 | `urlopen` (`_http_json`) | y (param) | infinite hang | y (health/admission) |
| daedalus/health.py:1007 | `urlopen` | y (5s) | infinite hang | y |
| daedalus/core.py:125 | `urlopen` (Ollama tags) | y (5s) | infinite hang | y |
| daedalus/eval/harness.py:663 | `urlopen` | y (2s) | infinite hang | y (eval harness) |
| daedalus/semantic_route.py:288 | `urlopen` | y (param) | infinite hang | y |
| daedalus/runtime_registry.py:335 | `urlopen` | y (3s) | infinite hang | y |
| daedalus/memory/embeddings.py:517 | `urlopen` (Ollama embed) | y (param, def 10s) | infinite hang | y |
| daedalus/providers/_openai_compat.py:58,156,185 | `urlopen` | y (param) | infinite hang | y (provider calls) |
| daedalus/providers/_ollama_native.py:214 | `urlopen` | y (param) | infinite hang | y |
| daedalus/providers/ollama.py:360 | `urlopen` (warm_model) | y (param) | best-effort, caught | y, but non-fatal |
| tools/smoke_tauri_sidecar.py:54,73,84 | `urlopen` | y (1–3s) | infinite hang | dev smoke test |
| tools/gui_check.py:171 | `urlopen` | y (3s) | infinite hang | dev tool |
| tools/system_check.py:676 | `urlopen` | y (3s) | infinite hang | dev tool |
| daedalus/hooks/tools.py:82 | `socket.create_connection` | y | infinite hang | dev/hook |
| daedalus/integrations/hermes/tool_gateway.py:150–169,246–247 | `socket.socket`/`create_connection`/`settimeout` | y (all) | infinite hang | y (Hermes tool gateway — canonical MCP-shaped effect surface) |
| tools/gui_check.py:151, tools/system_check.py:270 | `socket.socket()` | n/a (bind-only, no connect/recv) | n/a | dev tool — NOT a finding |
| daedalus/integrations/hermes/runtime_adapter.py:439 | `queue.Queue.get(timeout=...)` | y, inside outer deadline loop | infinite hang | y (Hermes runtime) |
| daedalus/build_exec.py:1084 | `threading.Event.wait(interval)` | y | busy-loop, not hang | y |
| daedalus/progress_sources.py:312 | `threading.Event.wait(interval)` | y | n/a | y |
| daedalus/spine/killswitch.py:939,1043,1050 | `threading.Event.wait(timeout)` | y | n/a | y (kill switch) |
| daedalus/lanes/fanout.py:467–473 | `ThreadPoolExecutor` + `as_completed` + `fut.result()` | **no future-level TO**; transitively bounded by `timeout_s` passed into `_one_call`→provider call | pool worker blocks until provider call returns/raises | y (fan-out advisory review lane) |
| daedalus/kairos/scheduler.py:356–362 | `ThreadPoolExecutor` + `f.result()` | **no future-level TO**; transitively bounded by `offload()`→attempt `timeout_s` | pool worker blocks until offload returns | y (kairos scheduler dispatch) |
| daedalus/structcore/index.py:544–545 | `ProcessPoolExecutor.map(analyze_chunk, chunks)` | **no timeout at all** | CPU-bound parse of source text could hang the whole `_compute()` call indefinitely on pathological input | dev/index tool (code intelligence), not itself kernel-effectful, but feeds context capsules used by effectful calls |
| daedalus/kairos/_gated_writes_legacy.py.src:483–508 | `ThreadPoolExecutor` + `fut.result()` | no TO | n/a — **file has a `.src` extension, is not live Python**, template/reference only | n/a |
| daedalus/adapters/subprocess_adapter.py:338–364 | `asyncio.wait_for(process.stdout.readline(), timeout=remaining)` | y, deadline-tracked | n/a | y (vendor-neutral Agent Runtime Contract adapter) |
| **daedalus/adapters/subprocess_adapter.py:365–366** | `await process.wait()`, `await session.stderr_task` | **n — no timeout** | unbounded hang if child closed stdout but did not actually exit | **y — Finding 2** |
| daedalus/adapters/subprocess_adapter.py:477 | `asyncio.wait_for(process.wait(), timeout=5)` | y | n/a | y |
| daedalus/adapters/subprocess_adapter.py:480 | `await process.wait()` (post-kill) | n, but reached only after `process.kill()` | near-instant in practice | y, low severity |
| daedalus/adapters/subprocess_adapter.py:502 | `asyncio.wait_for(session.stderr_task, timeout=1)` | y | n/a | y |
| daedalus/kairos/evolution.py:126–134 | `asyncio.wait_for(process.communicate(), timeout=timeout_s)` (when `limit_policy.enforces("wall_time")`) | y | n/a | y (Ariadne-style candidate eval) |
| **daedalus/kairos/evolution.py:136–138** | `await process.communicate()` — **no wrapper at all** when `limit_policy.enforces("wall_time")` is False | n, **by explicit owner policy** | genuinely unbounded | y — **Finding 5, sanctioned** |
| **daedalus/kairos/evolution.py:38–48** | `asyncio.gather(*tasks, return_exceptions=True)` in `generate_candidates` | **no timeout wrapper anywhere in this method** (unlike `evaluate_candidates` in the same file) | unbounded if any `run_task()` hangs | **y — part of Finding 2 chain** |
| daedalus/kairos/shadow_shell.py:59 | `async for event in self.adapter.events(session_id)` | bounded by `session.timeout_s` EXCEPT the tail (see Finding 2) | n/a | y |
| daedalus/atomic.py:100–108, 156–180 | retry loop, `time.sleep` | y, deadline-tracked | n/a | y (atomic publish) |
| daedalus/kernel/attempt_execution.py:975–1002 (`_poll_until_done`) | retry loop, `time.sleep(poll_s)` | y, `deadline = started + timeout_s`, `None` allowed explicitly | n/a when timeout_s given | y (gate child polling — canonical) |
| daedalus/kernel/events/ledger.py:377–388 (`_set_journal_mode_wal_with_retry`) | retry loop | y, deadline from `busy_timeout_ms` | n/a | y (event store) |
| daedalus/kernel/policy/ledger.py:259–294 (`_BudgetLock`), 972–986 (`_store` replace retry) | retry loop | y, deadline / fixed 10 attempts | refuses rather than hangs | y (budget ledger) |
| daedalus/council/vendors.py:412–431 | retry loop around `ManagedProcess` poll | y, `deadline = started + timeout_s` | n/a | y (council/vendor CLI runner) |
| **daedalus/interfaces/bridge/watcher.py:73–93** (`_BridgeWatcherLock.__enter__`) | `msvcrt.locking` retry loop (Windows) / `fcntl.flock(..., LOCK_EX)` (POSIX) | **n when `blocking=True`** | **genuinely unbounded wait for a cross-process file lock** | **y — Finding 1, File Bridge claim path** |
| daedalus/spine/containment.py:1144,1168–1170 | `WaitForSingleObject`/spin-wait | y (`timeout_s=900` default / `grace_s`) | n/a | y (Windows job containment) |
| daedalus/hooks/_common.py:228–256 (`_Lock`) | retry loop + stale-lock breaker | y, deadline | n/a | dev/hook state |
| daedalus/shift.py:203–222 | retry loop | y, deadline (short, 2s) | reports `False`, does not raise | dev bookkeeping |
| daedalus/desktop_runtime.py:470–479, 727–734, 866–870, 998–1002, 1162–1166 | retry/poll loops | y, all deadline-bound (`end = time.monotonic() + N`) | n/a | y (desktop runtime bring-up) |
| daedalus/eval/correctness.py:544–558 | poll loop around `ManagedProcess`/`subprocess.run(timeout=)` | y | n/a | y (eval harness) |
| daedalus/interfaces/http/sse.py:296–341, 378+ | `while True` + `time.sleep(1.0)` | y, `TASK_EVENTS_MAX_S` / `TASK_EVENTS_GRACE_S` deadlines | client gets a `final` event with `timed_out: true` | y (SSE task/conversation events) |
| **daedalus/runtimes/providers/context.py:71–77** (`render_provider_brief`) | `while True: ...; capacity *= 2` | **n — no iteration cap, no deadline** | unbounded local compute retry before the timed provider call even starts | **y — Finding 3**, used by `providers/deepseek.py:367` and `providers/ollama.py:955` |
| daedalus/runtimes/provider_executable_object_registry.py:701–989 | native fork/exec poll loop | y, `deadline` from `timeout` param | n/a | y (native subprocess primitive) |
| **daedalus/runtimes/provider_executable_object_registry.py:983,1016** | `os.waitpid(pid, 0)` (no `WNOHANG`) | **n**, reached only after `SIGKILL` | blocking wait, bounded in practice by kernel reap after kill, not mathematically bounded | **y — Finding 4, low severity** |
| daedalus/shift_ticker.py:85–90 | `while True: ...; time.sleep(max(1.0, every))` | intentional infinite service loop, exits on `KeyboardInterrupt` or `--once` | n/a — this is a daemon, not a hang | dev/ops watch CLI — NOT a defect finding |
| daedalus/token_monitor.py:210–221 | `while True: ...; time.sleep(interval_s)` | same as above | n/a | dev/ops watch CLI — NOT a defect finding |
| daedalus/spine/killswitch.py:1018–1050 (`_watch_loop`) | `while True` + `self._watch_stop.wait(poll_s)` | y, bounded per-iteration wait, loop itself is an intentional daemon thread | n/a | y (kill switch watcher — designed to run until `stop_watch()`) |
| daedalus/integrations/hermes/runtime_adapter.py:427–441 | `while True` + `output_queue.get(timeout=...)` inside `deadline = time.monotonic() + max_wall_seconds` | y | n/a | y (Hermes worker orchestration — canonical) |
| daedalus/hooks/_common.py:76–81, 250 | `sys.stdin` (JSON hook payload) | n/a — Claude Code always supplies a payload on this path | would hang only if invoked manually with a closed stdin | dev/hook, not kernel |
| daedalus/integrations/hermes/worker.py:36,250 | `sys.stdin.buffer` (`read_message`) | no per-read timeout in the child itself | bounded **transitively**: the parent (`runtime_adapter.py:426–441`) enforces `max_wall_seconds` and force-kills the child on deadline | y (Hermes worker subprocess) |
| tools/guarded_call.py:49 | `json.load(sys.stdin)` | none | hangs if run interactively with no piped input | dev CLI tool — NOT a finding (expected usage is piped) |

## Findings

### Finding 1 — `_BridgeWatcherLock` blocks forever on a cross-process claim when `blocking=True` (HIGH)

`daedalus/interfaces/bridge/watcher.py:73-93`:

```python
while True:
    try:
        msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
        break
    except OSError as exc:
        ...
        if not self.blocking or exc.errno not in contention_errnos:
            raise
        time.sleep(0.05)
```

and on POSIX, the `else` branch: `fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)` — a
blocking syscall with no timeout parameter available in the stdlib `fcntl` API.

This lock is constructed with `blocking=True` at exactly one call site,
`daedalus/file_bridge.py:749-753`, inside the lambda passed as the `lock=`
port to `claim_and_dispatch_request` (`daedalus/interfaces/bridge/dispatch.py:493-514`),
which is the canonical per-request claim for the **File Bridge** effect
surface — one of the entrypoints Gate 0 explicitly names as requiring policy
coverage ("MCP/File Bridge"). Every other lock helper in this codebase
(`_BudgetLock`, `atomic.replace_with_retry`, `_Lock` in hooks/_common.py,
`kernel/events/ledger.py`'s WAL retry, `council/vendors.py`) uses a
`deadline = time.monotonic() + X` pattern and raises/refuses on expiry. This
one is the exception: when `blocking=True`, there is no deadline anywhere in
the call chain — the Windows `time.sleep(0.05)` retry loop above is
unconditional, and the POSIX `flock(..., LOCK_EX)` call is a direct blocking
kernel call with no bound at all.

**Failure enabled**: two processes racing to claim the same filename-derived
request key — a normal, expected race for a File Bridge whose whole design is
concurrent watchers/dispatchers — makes the loser block indefinitely if the
winner is itself slow (not crashed) to finish processing that request.

**On mid-operation kill / on hang**: what is held is only the calling
thread; the file handle contended for is the lock file itself. If the lock
holder *crashes* (hard-killed), the OS releases `msvcrt.locking`/`flock`
automatically on process/handle teardown, so this is not a permanent
deadlock — but it is an uncapped *wait*, and nothing in `daedalus.limit_policy`
represents this wait as a configured (even if disabled) axis. It is not a
"disabled cap"; it is an **absent** one — exactly the pattern the task brief
calls out. What the operator sees: the calling thread (an HTTP/File Bridge
dispatch path) simply stops responding with no error and no progress line
until the other side's work finishes.

**Severity**: HIGH — effectful canonical entrypoint, genuinely unbounded,
silent (no log line, no error) while blocked.
**Confidence**: HIGH — read both branches of `__enter__`, confirmed the one
call site passes `blocking=True`, confirmed no caller wraps the `with lock(...)`
in any independent timeout.

### Finding 2 — `SubprocessAdapter` session end has an unguarded `process.wait()` tail; propagates into an unbounded `asyncio.gather` (MEDIUM)

`daedalus/adapters/subprocess_adapter.py:338-366`: the per-line `readline()`
loop is properly bounded by `asyncio.wait_for(..., timeout=remaining)`
against `session.timeout_s`. But once the loop exits on EOF (`if not raw_line: break`):

```python
exit_code = await process.wait()
stderr = (await session.stderr_task).decode(...)
```

Both calls are **unguarded**. EOF on `stdout` does not guarantee the child
process has exited — a process can close stdout while continuing to run
(daemonizing, orphaned grandchild holding the real work, or a hostile/buggy
candidate). If that happens, `process.wait()` blocks with no bound, and the
`session.timeout_s` budget that governed the loop above no longer applies to
this tail.

This is reached from `daedalus/kairos/shadow_shell.py:59`
(`async for event in self.adapter.events(session_id)`, i.e. the SAME
generator), which is called from `daedalus/kairos/evolution.py:45`
(`manager.run_task(task)`) inside `generate_candidates`'s
`asyncio.gather(*tasks, return_exceptions=True)` at line 48 — **that gather has
no `wait_for`/timeout wrapper of its own anywhere in the method**, unlike the
neighboring `evaluate_candidates()` in the same file, which correctly wraps
its subprocess call in `asyncio.wait_for(..., timeout=timeout_s)` (line
132-134). So the one place in `evolution.py` that is NOT explicitly bounded
is exactly the one whose only internal bound (the adapter's `session.timeout_s`)
has the gap described above.

**Failure enabled**: a spawned agent CLI (Claude/Codex/etc., via the
vendor-neutral Agent Adapter contract) that closes stdout without exiting
stalls candidate generation for the whole population, with no candidate ever
scored, error'd, or reported — `asyncio.gather` in `generate_candidates` has
`return_exceptions=True` but nothing ever raises to be caught.

**On mid-operation kill / on hang**: holds the `ShadowShellManager`'s worktree
and the adapter session slot; the operator sees `generate_candidates()` simply
never returning — no log, no partial result, no "timed out" report (contrast
with `evaluate_candidates`, which explicitly reports `"Evaluation timed out
after {timeout_s}s"` on the bounded path).

Cross-reference: this is `asyncio.subprocess.Process.wait()`, not
`subprocess.run`/`Popen.communicate` — outside the parallel subprocess
worker's stated scope, though the same family of primitive.

**Severity**: MEDIUM — real gap, but only reachable after the (already rare)
EOF-without-exit condition, and only exercised via the experimental
`EvolutionaryOrchestrator` (its own docstring: "not autonomous code
evolution... a trusted verifier still has to inspect a candidate").
**Confidence**: MEDIUM-HIGH — traced the full call chain by reading all three
files; did not execute anything to reproduce the EOF-without-exit precondition
(read-only sweep).

### Finding 3 — unbounded capacity-doubling loop in provider context rendering (MEDIUM)

`daedalus/runtimes/providers/context.py:71-77`:

```python
capacity = max(1, bounded_chars)
try:
    while True:
        result = graph_brief(repo_root, paths, hops=1, budget_chars=capacity)
        if not result.truncated:
            return result.text
        capacity *= 2
except Exception:
    return ""
```

No iteration cap, no deadline, no maximum `capacity`. This runs on the
`ExecutionLimitPolicy.enforces("tokens")` == False branch, i.e. exactly when
an owner has widened token limits — meaning the one case this loop is
reachable is also the case where its own bound is most likely to matter. It
is called from `daedalus/providers/deepseek.py:367` and
`daedalus/providers/ollama.py:955`, i.e. it runs **before** the actual,
properly-timed provider network/subprocess call — so none of the timeout
machinery verified elsewhere in this sweep covers it.

**Failure enabled**: if `graph_brief` keeps returning `truncated=True` (e.g.
a pathological project graph, or a bug in the truncation predicate), this
loop doubles `capacity` forever, consuming CPU/memory and never reaching the
call it's building context for.

**On mid-operation kill / on hang**: holds nothing external (no lock, no
lease, no connection) — it is pure local compute — but it does hold the
calling thread of a provider dispatch, which upstream (fanout/scheduler) may
itself be inside a `ThreadPoolExecutor` worker with no outer timeout (see
inventory rows for `fanout.py`/`scheduler.py`). Operator sees: the whole
provider call never starts; no progress line, since this precedes the
network/subprocess phase entirely.

**Severity**: MEDIUM — no lock/lease held, but a genuine "silently absent cap
on a declared axis" (§4.1 names "input/context ... tokens" and "execution ...
wall time" explicitly as bounded-by-default axes; this loop enforces neither).
**Confidence**: HIGH — read the full function and both call sites.

### Finding 4 — blocking `os.waitpid(pid, 0)` without `WNOHANG` in cleanup path (LOW)

`daedalus/runtimes/provider_executable_object_registry.py:983` and `:1016`
(via `_NATIVE_WAITPID`/`_NATIVE_CLEANUP_WAITPID`, confirmed at line
1700-1701 to be `os_module.waitpid`). Both are reached only in a `finally`/
cleanup path, **after** `SIGKILL` has already been sent to the child
(`:978`/`:1011`). This is the raw ctypes/ABI-level POSIX fork/exec primitive
this module implements as an alternative to `subprocess.Popen` — distinct
from, and not covered by, the parallel worker's `subprocess.run`/`Popen`
sweep.

**Failure enabled**: on almost every real system a `SIGKILL`'d process is
reaped near-instantly, so this is bounded in practice; it is not
*structurally* bounded (a process stuck in uninterruptible D-state I/O wait
inside the kernel does not honor `SIGKILL` promptly, and `os.waitpid(pid, 0)`
would then block for however long that lasts).

**On mid-operation kill / on hang**: holds the calling thread inside cleanup
of the native exec primitive; the operator sees whatever called this native
primitive appear to hang during its own teardown, i.e. a shutdown that never
completes rather than a normal hang.

**Severity**: LOW — narrow precondition, already-fatal signal sent, defensive
code, not on the primary happy path.
**Confidence**: MEDIUM — confirmed the alias resolves to `os.waitpid`;
did not enumerate every caller of this native registry to assess blast radius
of the exec primitive itself (out of scope for a read-only per-line sweep).

### Finding 5 — `evolution.py`'s explicit wall-time opt-out (INFORMATIONAL, not a defect)

`daedalus/kairos/evolution.py:132-138`:

```python
if self.limit_policy.enforces("wall_time"):
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_s)
else:
    # Explicit owner policy: the evaluator still records the result but
    # imposes no Daedalus wall-clock deadline.
    stdout, stderr = await process.communicate()
```

This is a real, actually-unbounded blocking call — but it is the **one place
in this whole sweep** that matches §4.1's sanctioned shape exactly: the
absence of a bound is conditioned on an explicit `ExecutionLimitPolicy`
enforcement flag (`enforces("wall_time")`), not silent, and the comment
states the tradeoff honestly. Included here as the positive control that
makes Findings 1 and 3 legible as violations by contrast: those two have no
flag, no policy check, and no comment acknowledging the absent bound at all.

## NOT findings (enumerated, with counts)

- **21/21** `urllib.request.urlopen(...)` call sites (16 in `daedalus/`, 5 in
  `tools/`) pass an explicit `timeout=`. Zero missing.
- **0** actual `requests` (python-requests) library calls anywhere in
  `daedalus/` or `tools/`. The only 2 files matching `requests\.` were
  `daedalus.conversation_requests` (an unrelated internal module) references.
- **0** actual `httpx` calls. The only 2 matches are `daedalus/tools/vet.py`
  and `daedalus/integrations/hermes/conformance.py`, both of which list
  `httpx`/`requests`/`urllib.request` as **forbidden import patterns to flag
  in candidate/reviewed code** — i.e. this codebase's own static reviewer
  already treats unbounded-by-default HTTP libraries as a defect shape to
  catch, consistent with this sweep's finding class.
- **0** `http.client` usage.
- **6/6** real `socket.socket`/`socket.create_connection` network sites pass
  `timeout=`/`.settimeout()`. 2 additional `socket.socket()` calls in
  `tools/gui_check.py:151` and `tools/system_check.py:270` only call `.bind()`
  to allocate a free port and never connect/recv — not a blocking-call site.
- **1/1** `queue.Queue.get(timeout=...)` usage is bounded, inside an outer
  `deadline = time.monotonic() + max_wall_seconds` loop
  (`integrations/hermes/runtime_adapter.py:427-441`). No other `queue.Queue`
  construction found in `daedalus/`/`tools/`.
- **6/6** `threading.Event.wait(...)` call sites pass an explicit interval
  (`build_exec.py:1084`, `progress_sources.py:312`, `spine/killswitch.py:939,1043,1050`).
  No bare `.wait()` (infinite) found.
- **0** explicit `Lock.acquire()` calls anywhere. All locking goes through
  `with lock:` context managers. These are in-process `threading.Lock`
  instances protecting short local critical sections (dict/attribute
  mutation), not I/O — out of this sweep's resource class (network / queue /
  futures / asyncio / stdin / FIFO / waitpid) and out of scope per the
  parallel lock-*release*-discipline worker's ownership; not individually
  enumerated (dozens of sites, would be pure noise for this axis).
- **5/5** `asyncio.wait_for` call sites pass `timeout=`.
- **37 of 39** `while True:` loops in `daedalus/` (and both real ones in
  `tools/`, excluding 2 comment-only string literals in
  `tools/operability_drill.py`) are bounded by a `deadline =
  time.monotonic() + X` pattern, terminate on local EOF/exhaustion (chunked
  file reads, Tarjan SCC, filesystem ancestor walks — not blocking I/O), or
  are intentional daemon/service loops (`shift_ticker.py`, `token_monitor.py`,
  `spine/killswitch.py:_watch_loop`) that exit via `KeyboardInterrupt` or an
  external `Event`/flag rather than by design ever "timing out" — not a
  defect shape, these are meant to run until stopped. The remaining 2 are
  Findings 1 and 3.
- **No** interactive `input()` calls anywhere in `daedalus/` or `tools/`.
  `sys.stdin` reads: `daedalus/hooks/_common.py` (Claude Code hook JSON,
  always supplied by the harness on this path), `daedalus/integrations/hermes/worker.py`
  (child worker's protocol read, bounded transitively by the **parent's**
  `max_wall_seconds` deadline loop which force-kills the child — see
  `runtime_adapter.py:426-441` in the inventory table), and
  `tools/guarded_call.py:49` (a dev CLI whose documented usage is piped
  input — same class as any Unix filter tool, not an effectful/kernel path).
- **0** named-pipe/FIFO reads outside the subprocess pipe plumbing already
  covered above (Windows named pipes in
  `runtimes/provider_executable_object_registry.py`'s
  `_NATIVE_WINDOWS_DRAIN`/`PeekNamedPipe` path use non-blocking peek-then-read,
  bounded by the same `deadline` as the rest of that function).
- `kairos/_gated_writes_legacy.py.src:483-508` uses `ThreadPoolExecutor` +
  bare `fut.result()` with no timeout, but the file has a `.src` extension —
  it is not live, importable Python (confirmed by extension; not executed to
  verify further, per the read-only constraint). Noted, not counted as a live
  finding.

## Which of these are the §4.1 wall-time axis

`docs/IKARUS_ARIADNE_MASTER_PLAN.md` §4.1 names "execution/provider/gate/
evaluation wall time" as one of the canonical axes that must be either
enforced by default or **explicitly** disabled with a visible flag and
nullable value — never silently absent.

- **Finding 1** (File Bridge lock wait) is the clearest violation: the wait
  is not represented as ANY axis in `ExecutionLimitPolicy` at all. It isn't a
  disabled cap with a flag — it's a wait the policy system has no opinion
  about, on a canonical effectful entrypoint.
- **Finding 2** (subprocess_adapter tail `process.wait()`) is a scoped
  violation inside the Agent Runtime Contract's session lifecycle: the axis
  IS enforced for 95% of the session (`session.timeout_s` governs the
  readline loop) but silently stops applying for the final `wait()`/
  `stderr_task` await.
- **Finding 3** (context capacity-doubling) is a violation of the adjacent
  axis this same section enumerates — "input/context and output tokens" and
  general "execution ... wall time" — with no enforcement flag, no maximum
  iteration count, and no nullable-value contract; it just loops.
- **Finding 4** (`os.waitpid` without `WNOHANG`) is a marginal case: in
  practice bounded by the kernel's post-`SIGKILL` reap time, so it is closer
  to "unlikely to matter" than "silently absent cap," but it is still,
  structurally, an unbounded blocking syscall with no declared axis.
- **Finding 5** (evolution.py's `process.communicate()` under
  `enforces("wall_time") == False`) is explicitly **compliant**: it is the
  one call in the whole sweep that is unbounded *and* honestly conditioned on
  a visible, owner-controlled policy flag — exactly what §4.1 asks for. It is
  included as the contrast case, not as a defect.

## Cross-reference to the subprocess-focused parallel worker

Only two overlaps, both explicitly out of that worker's stated
`subprocess.run`/`Popen`/`communicate` scope and noted here rather than
re-enumerated: `daedalus/adapters/subprocess_adapter.py`'s `asyncio.subprocess.Process`
API (Finding 2), and `daedalus/runtimes/provider_executable_object_registry.py`'s
raw ctypes fork/exec + `os.waitpid` primitive (Finding 4). Neither is a
`subprocess.run`/`Popen` call site.
