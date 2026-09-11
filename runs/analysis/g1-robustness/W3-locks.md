# W3 — Locks and lockfiles: static robustness sweep

Scope: `daedalus/` and `tools/` (Python only); `tests/`, `apps/`, `vault/`,
`.quarantine/`, `daedalus/lanes/` (edits) out of scope. `.gitignore` read
(never edited) for Task 2. Read-only sweep — no file mutated, no code
executed, no git state changed.

Repo: `C:/Users/Administrator/daedalus`, local `main @54f09753` (branch at
sweep time: `wip/g1-freeze-2026-08-31`, HEAD `d17ea2f`).

Canonical defect writeup read first: `daedalus/kernel/effects.py:576-587`
(`with sqlite3.connect(...)` is a transaction scope, not a closing scope;
leaked connections + GC-timed finalization gave WAL/`-shm` companions an
indeterminate lifetime). Generalized resource class for this sweep: **locks
and lockfiles** whose release is not bound to a deterministic program point.

## Patterns grepped and raw hit counts (daedalus/ + tools/, *.py)

| pattern | raw hits | in-scope files | triaged as real lock-release risk |
|---|---|---|---|
| `\.acquire\(` (literal `Lock/Semaphore.acquire()` call) | 0 | 0 | 0 — codebase uses `with lock:` exclusively |
| `acquire` (broad) | ~90 | many | 0 threading-lock hits; all `acquire_*_lease()` (EffectLease issuers) or lock-class internals already covered below |
| `\.release\(` | 7 | tools/watchdog.py (1, `Reservation.release`, budget not lock), daedalus/spine/cancel.py (3, `_backend.release()`, process-container handle not a threading lock) | 0 manual `threading.Lock.release()` calls anywhere in scope |
| `threading\.(Lock\|RLock\|Semaphore\|Condition\|BoundedSemaphore)\(` | 24 (daedalus/) + 0 (tools/) | 24 (`experiments/` 1 excluded, out of scope) | see enumerated table below — 24/24 use `with` |
| `flock\|msvcrt\|portalocker\|filelock` | 8 files matched repo-wide | in-scope: `daedalus/atomic.py`, `daedalus/kernel/policy/ledger.py`, `daedalus/interfaces/bridge/watcher.py`, `daedalus/budget.py` (docstring cross-reference only, no code) | 3 real OS-lock implementations, all context-manager-based |
| `O_EXCL` / `open(..., "x")` sentinel creation | 13 in-scope files | see Task-1 findings | 2 genuine locks (`shift.py`, `hooks/_common.py`), 1 with a stale-window bug (`shift.py`) |
| `atexit\.register` | 1 (`daedalus/desktop_runtime.py:342`) | 1 | not a lock release — subprocess/handle teardown at process exit |
| `pid` / pidfile idioms | 0 real pidfile locks in daedalus/tools | 0 | none found |

## Task 2 — `.gitignore` crash-release claims, verified statically

Every comment in `.gitignore` that makes an explicit release-mechanism claim
(searched the full 174-line file for "crash", "release", "OS-", "survives",
"advisory", "transient" — three qualifying comments found):

| pattern | `.gitignore` line | comment claim (quoted) | writer code | mechanism actually used | verdict |
|---|---|---|---|---|---|
| `runs/bridge_watcher.lock` | 51-53 | *"Fixed, crash-released Managed Bridge OS-lock identity. The file deliberately survives process exit; only the lock ownership is transient runtime state."* | `daedalus/interfaces/bridge/watcher.py::_BridgeWatcherLock` (`msvcrt.locking` / `fcntl.flock` on a persistent `a+b` handle) | Real OS-held byte-range lock. Kernel releases it when the process dies (or the fd closes), independent of `__exit__` running. | **TRUE** |
| `projects/.registry.lock` | 55-57 | *"Fixed, crash-released project-registry OS-lock identity. The JSON rows are authoritative; this persistent filename only anchors transient kernel state."* | `daedalus/projects.py::register_project` → `daedalus/atomic.py::ExclusiveFileLock` (`msvcrt.locking` / `fcntl.flock`) | Real OS-held lock via the shared `atomic.ExclusiveFileLock` primitive. | **TRUE** |
| `memory/offload_metrics.local.jsonl.lock` | 163-166 | *"Fixed, crash-released offload-metrics OS-lock identity. Same reasoning as the bridge and registry locks above: the file survives process exit by design, only the ownership is transient."* | **none.** `daedalus/metrics.py` is the only writer of `offload_metrics.local.jsonl`; its serialization is `_WRITE_LOCK = threading.Lock()` — an **in-process thread lock**, never a file. Repo-wide grep for the literal filename `offload_metrics.local.jsonl.lock` matches **only `.gitignore` itself** — nothing in `daedalus/` or `tools/` ever opens, creates, or locks that path. | **FALSE — stale ignore rule.** The comment describes an OS-lock mechanism (and cites the bridge/registry locks as precedent) for a file that nothing in the tree creates. Either the OS-lock variant of `metrics.py` was planned/removed and the `.gitignore` entry + comment were never cleaned up, or the comment was copy-pasted from the two real cases without checking this one. Not dangerous by itself (an ignore rule for a phantom file is inert), but it is a false claim about a locking mechanism sitting in the repo's own release-safety documentation — exactly the kind of drift this sweep exists to catch. |

Other lock-shaped entries checked for completeness (no explicit crash-release
claim attached, so no verdict required, but mechanism confirmed for the
record):

- `runs/budget/ledger.json.lock` (line 49) — grouped under a comment about
  `ledger.json` being live operational state (Invariant 8), not a mechanism
  claim. Mechanism: real OS lock, `daedalus/kernel/policy/ledger.py::_BudgetLock`
  (`daedalus/budget.py` re-exports it; it is **not** a duplicate implementation
  as first suspected — `budget.py` is a compatibility facade over
  `kernel/policy/ledger.py`).
- `runs/watchdog/.pass.lock`, `.docs.lock`, `.work.lock` (lines 150-152) — no
  mechanism claim in the grouped comment. Mechanism: `tools/watchdog.py::PassLock`,
  `O_CREAT|O_EXCL` sentinel with a generous, correctly-separated stale-break
  window (`max(MODEL_TIMEOUT_S, PRUNE_TIMEOUT_S) + 60`) — a crash leaves the
  file on disk, but the next run's stale check reclaims it; not OS-released,
  self-healing instead. No false claim exists here because none is made.
- `memory/vectors.db-wal` / `-shm` (lines 19-24, exception case named in the
  task) — comment only says the index is "derived" and "rebuilt from
  [the journal]"; it makes no "always vanishes" claim, so nothing to verdict.
  For the record: the named regenerator, `daedalus/memory/projection_worker.py`,
  opens its read path as a bare `sqlite3.connect(...)` at line 293 with no
  `contextlib.closing`/explicit `.close()` visible in the surrounding 20 lines
  — the same defect shape as the fixed 13 sites, potentially still present
  here. This is WAL/connection-lifetime territory, not lock territory; flagged
  for the parallel WAL sweep (`wal-leak-sweep` / `walcls-*` agents are already
  active on this class) rather than re-litigated in this lock-scoped file.

## Task 1 — acquire-without-guaranteed-release

### Enumerated `threading.*` lock objects in daedalus/ (24, all in scope)

| site | kind | acquired via |
|---|---|---|
| `conversation_requests.py:91` (`self._lock`) | Lock | `with` (2 sites) |
| `conversation_requests.py:430` (`_MANAGERS_LOCK`) | Lock | `with` |
| `conversation.py:916` (`_STORE_CACHE_LOCK`) | Lock | `with` |
| `council/bus.py:136` (`_WRITE_LOCK`) | Lock | `with` |
| `council/canary.py:1070` (`gate`) | Semaphore | `with gate:` |
| `editor_context.py:498` (`self._lock`) | Lock | `with` (3 sites) |
| `desktop_runtime.py:60` (`_DLL_DIRECTORY_LOCK`) | Lock | `with` |
| `desktop_runtime.py:318` (`self._lock`) | RLock | `with` (12 sites) |
| `ikarus_runtime_events.py:258` (`self._lock`) | Lock | `with` |
| `integrations/hermes/worker.py:35` (`self._lock`) | RLock | `with` (2 sites; nested reentrant call verified safe — see below) |
| `kernel/policy/ledger.py:1414` (`_DEFAULT_LOCK`) | Lock | `with` |
| `kernel/attempt_clock.py:35` (`self._lock`) | Lock | `with` |
| `metrics.py:22` (`_WRITE_LOCK`) | Lock | `with` |
| `kernel/events/ledger.py:310` (`self._lock`) | RLock | `with` (11 sites) |
| `lanes/fanout.py:408` (`lock`) | Lock | `with` (2 sites) |
| `progress.py:279` (`self._lock`) | Lock | `with` |
| `progress.py:324` (`_DEFAULT_LOG_LOCK`) | Lock | `with` |
| `runtime_registry.py:428` (`_status_cache_lock`) | Lock | `with` |
| `structcore/index.py:1180` (`_LOCKS_GUARD`) | Lock | `with`, held only for a dict `setdefault` |
| `structcore/index.py:1185` (`_BUILD_LOCKS[key]`) | Lock (per-key) | `with _build_lock(key):` |
| `spine/cancel.py:391` (`_LIVE_LOCK`) | Lock | `with` (3 sites) |
| `spine/killswitch.py:519` (`_CONTROL_CHECK_LOCK`) | Lock | `with` (2 sites) |
| `spine/killswitch.py:744` (`self._lock`) | Lock | `with` (7 sites) |

**Finding A — NOT a finding, but stated because it is the universal claim
this sweep needs to earn:** every one of the 24 threading lock objects above
is exercised exclusively through `with lock:`. A repo-wide grep for
`\.acquire\(` on a threading primitive and for manual `\.release\(` on one
returns **zero** hits in `daedalus/` and `tools/`. Python's `with` statement
guarantees `__exit__` (hence `release()`) runs for every exception type,
including `KeyboardInterrupt`/`SystemExit`, raised inside the block, so a
mid-operation kill via a catchable signal cannot leave one of these 24 locks
held. (An uncatchable kill — `SIGKILL`/power loss — takes the whole process
and every in-process `threading.Lock` with it; that is expected and not a
defect, since no other process can ever have been waiting on a lock that
lived only inside the dead interpreter.)

**Finding B — reentrancy check, explicitly requested:** the one path that
recurses into its own lock is `integrations/hermes/worker.py::_ProtocolBridge`:
`call_tool()` acquires `self._lock`, and while still holding it calls
`self.emit(...)`, which acquires `self._lock` again. This is correctly typed
as `threading.RLock()` (line 35), so it is not a bug — it is exactly the case
`RLock` exists for. No plain `Lock` in the enumerated set was found on a path
that calls back into itself while held.

**Finding C — `structcore/index.py::_build_lock` (per-key `threading.Lock`,
not RLock), low confidence:** `cached_index()` holds `_build_lock(key)` while
calling `build_index(...)`. If `build_index()` ever transitively calls back
into `cached_index()` for the *same* scope key (not verified either way in
this static pass — `build_index` was not traced end to end), a plain `Lock`
would self-deadlock the calling thread permanently, and every other caller
waiting on that key would then block forever too (no timeout on this lock).
Given the size of `structcore/index.py`, tracing every transitive call inside
`build_index` was out of the time budget for this sweep; flagged for the
owner or a follow-up static trace, not asserted as a live bug.

### OS-level / sentinel-file locks

**Finding D — `daedalus/interfaces/bridge/watcher.py::_BridgeWatcherLock`,
unbounded blocking acquire (Severity: medium, Confidence: high).**

```
daedalus/interfaces/bridge/watcher.py:70-93 (__enter__, blocking branch)
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
Called with `blocking=True` from `daedalus/file_bridge.py:749-751`. There is
**no deadline** in this loop — if another process (or another thread in the
same process on a hung syscall) holds the OS lock and never releases it while
staying alive, this call polls every 50ms forever. Since the primitive is a
real OS lock, a crashed holder releases it automatically (kernel-level), so
this is not the sentinel-file "survives forever" failure mode — but it is
exactly the "`acquire()`/`acquire(blocking=True)` with NO timeout" pattern
this sweep was asked to flag, and it contradicts the master plan's §4.1
bounded-execution invariant (execution/provider wall time bounded by default)
for the one caller that opts into `blocking=True`.
**Failure enabled:** the file-bridge watcher startup thread can hang
indefinitely with no operator-visible timeout if a live peer holds the lock
for an extended period (not just a crash window).
**On mid-operation kill:** the *holder's* death releases the OS lock
immediately (correct); the *waiter* is unaffected by kills of unrelated
processes — this finding is about liveness under contention, not about
crash-safety of the lock itself.

**Finding E — `daedalus/shift.py::_ShiftLock`, stale-break threshold equals
the acquire timeout, so a legitimate slow holder can be double-acquired
(Severity: low-medium — module's own docstring rates the resource as
"bookkeeping", but the actual failure is a lost/interleaved write, not a
graceful "expired" report; Confidence: high).**

```
daedalus/shift.py:198-222
    def __init__(self, path: Path, timeout_s: float = 2.0) -> None:
        self.path = Path(str(path) + ".lock")
        self.timeout_s = timeout_s
        ...
    def __enter__(self) -> bool:
        deadline = time.monotonic() + self.timeout_s
        while True:
            try:
                self._fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
                return True
            except FileExistsError:
                if time.monotonic() >= deadline:
                    try:
                        if time.time() - self.path.stat().st_mtime > self.timeout_s:
                            self.path.unlink()
                            continue
                    except OSError:
                        pass
                    return False
                time.sleep(0.05)
```
Compare with the two siblings that do this correctly:
`daedalus/hooks/_common.py` uses `LOCK_TIMEOUT_S = 5.0` for the caller's own
patience but `LOCK_STALE_S = 30.0` (6x larger) before considering the holder
dead; `tools/watchdog.py::PassLock` uses `max(MODEL_TIMEOUT_S,
PRUNE_TIMEOUT_S) + 60` as its stale window, deliberately larger than the
longest legitimate hold. `_ShiftLock` uses the **same** `timeout_s` (2.0s,
the default) for both "how long am I willing to wait" and "how old must the
file be before I assume its owner is dead". A holder A that creates the lock
at t=0 and is still legitimately working at t=2.1s (slow disk, GC pause, a
briefly loaded machine — this repo's own memory notes record background
mutators and shared-checkout contention as real conditions here) will have
its lock file's mtime read as "stale" (age > 2.0s) by any waiter B whose own
2.0s patience window has just expired at the same moment. B then unlinks A's
still-live lock and creates its own. Both A and B now believe they hold
exclusive access to the same `Shift` state file (`note()` at
`daedalus/shift.py:267-275`: read-modify-write under the lock). The result is
a lost update — one of the two notes silently disappears — not a timeout
error, and not something either process can detect after the fact, because
each one plausibly held the lock throughout its own view of the operation.
**Failure enabled:** the shift-note ledger loses writes under contention that
exceeds ~2 seconds, which is not the same failure mode as "an operator lost a
checkpoint to a genuinely dead process" the docstring reasons about.
**On mid-operation kill:** a hard kill of A leaves the lock file on disk;
the NEXT B to contend for it (not necessarily the currently-waiting one)
reclaims it once B's own wait also exceeds 2.0s — bounded, self-healing,
consistent with the module's stated intent. The bug is specifically the
double-acquire-while-alive case above, not the crash case.
**Severity:** low-medium (blast radius is one advisory bookkeeping file,
explicitly documented as low-stakes by its own author) but it is a genuine,
reproducible correctness gap distinct from the crash-safety the module
intends to provide.

**Finding F (informational, not a defect) — `runs/council/room.py::_RoomLock`
degrades to a documented no-op** when the OS lock cannot be taken (30 retries
over ~3s on Windows, one blocking `fcntl.flock` call on POSIX with no
timeout at all on POSIX). The class docstring states this trade-off
explicitly ("losing serialisation is bad, losing the human's message is
worse") and `verify_room()` is the named compensating control. Out of my
edit scope (`runs/council/` is not `daedalus/`/`tools/`) and not raised as a
finding beyond noting the POSIX branch (`fcntl.flock(fh.fileno(),
fcntl.LOCK_EX)` at line 904, no `LOCK_NB`) is *also* an unbounded blocking
call with no deadline — same shape as Finding D, lower severity because the
class already treats "could not lock" as an accepted, handled outcome on the
Windows branch; POSIX has no such escape hatch, so on POSIX this can hang
the calling thread indefinitely, mitigated only by the fact this is a room
transcript writer, not a control path.

### Lock ordering

No site in the enumerated set (24 threading locks + 3 OS-file locks with
real code paths) was found acquiring a second named lock while already
holding a first. The one place two lock objects are visible in the same
function (`spine/killswitch.py::verify_control_root`, using module-level
`_CONTROL_CHECK_LOCK`) releases it before calling the potentially-slow
`_verify_control_root_uncached`, and the class using `self._lock`
(`KillSwitch`) never calls `verify_control_root` while holding its own lock
in the code paths read. No acquisition-order table is produced because no
second concurrently-held lock was found; this is a bounded-depth static
finding, not a proof — `structcore/index.py`'s `build_index()` internals
were not fully traced (see Finding C).

## NOT findings (checked, clean)

- 24/24 `threading.Lock/RLock/Semaphore` sites in `daedalus/`: all `with`,
  zero manual `acquire()`/`release()`.
- `daedalus/atomic.py::ExclusiveFileLock`, `daedalus/kernel/policy/ledger.py::_BudgetLock`
  (re-exported by `daedalus/budget.py`, not duplicated),
  `daedalus/interfaces/bridge/watcher.py::_BridgeWatcherLock`: all three
  release the OS lock and close the handle inside `__exit__`, which Python
  guarantees runs for any exception raised inside the `with`-body, including
  `KeyboardInterrupt`/`SystemExit`. (`__enter__`-time interruption, e.g. a
  `KeyboardInterrupt` landing inside the pre-acquire retry sleep, can leak an
  *unlocked* open file handle since `__exit__` is never invoked for a
  `with`-statement whose `__enter__` itself raised — cosmetically a leaked fd,
  not a leaked lock; the OS reclaims the fd at process exit either way. Noted,
  not raised as a numbered finding: no held lock outlives the process in this
  path.)
- `daedalus/hooks/_common.py::_Lock` and `tools/watchdog.py::PassLock`:
  O_EXCL sentinel + stale-breaker, correctly sized stale windows (30s vs 5s;
  and MODEL/PRUNE-timeout-derived vs 60s respectively) — bounded, self-healing
  on a hard kill.
  Not a lock at all): permanent single-use claim/CAS markers, correctly never
  meant to be released.
- `daedalus/kernel/offload_lease.py::issuer_keyring`,
  `daedalus/runtimes/admission/authorization.py::_load_or_create_key`,
  `daedalus/ikarus_supervisor.py` publish (`open("x")`),
  `daedalus/hooks/events.py` precompact note create (`open("x")`),
  `daedalus/integrations/hermes/tool_gateway.py` token file: all
  create-once-or-read idempotent patterns, not mutex locks — no release
  semantics apply.
- `atexit.register(self.close)` in `daedalus/desktop_runtime.py:342`: closes
  managed subprocess handles (tunnel/Ollama/IDE), not a lock; `self.close()`
  is also called from ordinary shutdown paths, so atexit is a backstop, not
  the only release path.
- Lock ordering: no two-lock nesting found in the enumerated set (bounded
  confidence — see Finding C caveat).

## Totals

- Threading locks enumerated: 24 (0 unsafe).
- OS-level file-lock classes read in full: 5 (`atomic.ExclusiveFileLock`,
  `budget._BudgetLock`, `watcher._BridgeWatcherLock`, `room._RoomLock`,
  `shift._ShiftLock`) + 2 O_EXCL sentinel-with-stale-breaker classes
  (`hooks._common._Lock`, `watchdog.PassLock`) + 6 one-shot O_EXCL
  create-once markers (not locks).
- `.gitignore` crash-release claims verified: 3 explicit claims found and
  verdicted (2 TRUE, 1 FALSE/stale).
- Task-1 numbered findings: 3 real (D, E, plus the POSIX branch of F), 1
  low-confidence flagged-not-asserted (C).

## Ranked for a fix packet

1. **Task 2 / FALSE claim — `memory/offload_metrics.local.jsonl.lock`**
   (`.gitignore:163-166`): delete the stale ignore rule and its comment, or
   (if an OS-lock variant of `metrics.py` is actually intended) implement it.
   Cheapest fix, highest documentation-trust value — this is the repo's own
   safety notes asserting a mechanism that does not exist in code.
2. **Finding E — `daedalus/shift.py::_ShiftLock`** stale-threshold conflated
   with acquire-timeout: raise the stale window well above `timeout_s` (mirror
   `hooks/_common.py`'s 5s/30s split), or drop the self-steal branch entirely
   and let contention resolve to `return False` (the module already treats a
   failed acquire as an acceptable "note not written under lock" outcome, per
   its own docstring — so removing the steal is likely a smaller, safer diff
   than tuning it).
3. **Finding D — `daedalus/interfaces/bridge/watcher.py::_BridgeWatcherLock`**
   blocking-mode retry loop: add a bounded deadline (with a named, owner-
   configurable ceiling per §4.1) to the one `blocking=True` call site in
   `file_bridge.py`.
4. **Finding C — `structcore/index.py::_build_lock`**: trace `build_index()`
   for self-recursion into `cached_index()` under the same key; if none
   exists, downgrade to closed/no-action; if one exists, either break the
   recursion or switch the per-key lock to `RLock`.
