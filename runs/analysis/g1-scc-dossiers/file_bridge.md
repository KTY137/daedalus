# SCC dossier: `file_bridge` (`daedalus/file_bridge.py`)

Base: main @ 851ff43c. 1110 lines [MEASURED, `wc -l`].

## Step 1 — Measured edges (raw AST probe)

Command: `.venv/Scripts/python.exe C:/Users/Administrator/scc-scratch/probe.py file_bridge` [MEASURED]

```
### OUTGOING edges FROM file_bridge to other SCC members
  -> core                       FUNCTION-LOCAL (deferred)  in _process_request_claimed
       daedalus/file_bridge.py:766   from .core import process_bridge_payload

### INCOMING edges INTO file_bridge from other SCC members
  <- core                       FUNCTION-LOCAL (deferred)  in queue_task
       daedalus/core.py:931   from .file_bridge import enqueue
  <- doctor                     FUNCTION-LOCAL (deferred)  in _print_watcher_heartbeat
       daedalus/doctor.py:105   from .file_bridge import STALE_AFTER_S, heartbeat_status
  <- health                     FUNCTION-LOCAL (deferred)  in _p_bridge
       daedalus/health.py:690   from . import file_bridge as fb
  <- progress_sources           FUNCTION-LOCAL (deferred)  in snapshot_from_bridge
       daedalus/progress_sources.py:498   from . import file_bridge as fb
  <- status                     MODULE-LEVEL               in <module>
       daedalus/status.py:47   from .file_bridge import INBOX, OUTBOX
```

**Verification.** Read every cited site:

- `file_bridge.py:766`, inside `_process_request_claimed` (def at `:759`) — real, reachable, not
  under `TYPE_CHECKING`. Confirmed [MEASURED].
- `core.py:931`, inside `queue_task` (def at `:923`) — real. Confirmed [MEASURED].
- `doctor.py:105`, inside `_print_watcher_heartbeat` (def at `:102`) — real. Confirmed [MEASURED].
- `health.py:690`, inside `_p_bridge` (def at `:688`, a `@probe(...)`-decorated function) — real,
  wrapped in `try/except Exception` but the import itself is unconditionally attempted, so it is a
  live edge. Confirmed [MEASURED].
- `progress_sources.py:498`, inside `snapshot_from_bridge` (def at `:481`) — real. Confirmed
  [MEASURED].
- `status.py:47` — genuine module-level `from .file_bridge import INBOX, OUTBOX`, no guard.
  Confirmed [MEASURED]. This is the only MODULE-LEVEL edge touching `file_bridge` in the whole set;
  every other edge in and out of this module is already deferred.

No corrections to the probe's classification were needed.

**Dynamic references.** `grep -n "importlib|__import__"` over `file_bridge.py`: no matches
[MEASURED]. No `TYPE_CHECKING` guard in the file [MEASURED]. No string literals naming other SCC
members were found beyond the plain import statements above.

## Step 2 — What it actually does

`file_bridge.py` is the durable, crash-safe request/report queue between the API/CLI/UI and the
provider dispatch: `enqueue()` writes a JSON request atomically into `outbox/`, `process_request()`
claims one file under an OS lock and drives it through a documented five-step idempotent state
machine (journal → dispatch → report → archive → conversation projection) so a restarted watcher
never double-bills a provider, and `heartbeat_status()`/`bridge_status()` expose whether the watcher
process is alive, busy, wedged or dead. Most of the actual state-machine logic already lives in
`daedalus/interfaces/bridge/{dispatch,projection,watcher}.py`, which `file_bridge.py` wraps with its
own concrete paths (`INBOX`, `OUTBOX`, `ARCHIVE`, `HEARTBEAT_PATH`) and callback bundles (`*Ports`
dataclasses) — i.e. it is already the "adapter/wiring" layer, not the algorithm itself.

## Step 3 — Layer

**Verdict: interfaces**, with a currently-misplaced sliver of **foundation**-shaped constants.

`file_bridge.py` shapes and durably persists request/report envelopes for an external-facing queue
(outbox/inbox files consumed by the CLI, the file-bridge watcher process, and the VS Code
extension); it holds no policy or effect-authorization logic itself — the one effectful boundary
call it makes (`begin_effect("file_bridge.process", ...)`, `:738`) is a pass-through registration
into the canonical kernel, not a decision. It is a bridge/transport surface, i.e. `interfaces`, and
the current directory (top-level `daedalus/`) already partially disagrees with that: the codebase
has been actively migrating the state-machine bodies into `daedalus/interfaces/bridge/*` while
leaving `file_bridge.py` itself, plus its raw path constants, at the top level. `file_bridge.py` is
mis-sited today; its natural target home is `daedalus/interfaces/bridge/` alongside the modules it
already wraps.

## Step 4 — Severance

### `file_bridge -> core` (`process_bridge_payload`) — one of the two SPECIAL DEPTH edges, see below.

## Step 5 — Tests that pin this

`grep -rn` over `tests/` [MEASURED]:

- Import/reference of `file_bridge` (module import, `mock.patch("daedalus.file_bridge...")`, etc.):
  **19 files, 35 matching lines** [MEASURED].
- `mock.patch("daedalus.file_bridge.<attr>", ...)` string-pinned targets found: `enqueue` (2x in
  `tests/test_categories_integration.py:130,153`; 1x in `tests/test_comms.py:264`), `OUTBOX`,
  `INBOX`, `ARCHIVE`, `heartbeat_status` (all 4 twice, in `tests/test_health_surface.py:332-335` and
  `:347-350`). These pin exact symbol *paths* on the `file_bridge` module object — moving
  `heartbeat_status`, `OUTBOX`/`INBOX`/`ARCHIVE`, or `enqueue` out of `file_bridge.py` (even into a
  module it re-exports from) breaks these patches unless `file_bridge` keeps them as real bound
  module attributes.
- Heaviest single file: `tests/test_bridge_restart.py` — **48 call sites** of `fb.process_request(...)`
  [MEASURED, `grep -c`], covering the crash/restart/idempotency matrix (test names include
  `test_*_crash_before_report`, `test_*_crash_after_report`, `test_restart_replays_...`, etc. — the
  file is unittest-free pytest with a shared `work` fixture, see Step 4 below). All of them go
  through the **one** fixture `work` (`tests/test_bridge_restart.py:136-150`), which does
  `monkeypatch.setattr("daedalus.core.process_bridge_payload", m)` — this is the load-bearing test
  seam for the `file_bridge -> core` edge; see the severance section below.
- `tests/test_dynamic.py`: 8 call sites of `file_bridge.process_request(req)` [MEASURED].
- `tests/interfaces/test_bridge_*_strangler.py` (6 files) and `tests/interfaces/test_bridge_cli_owner.py`:
  1 file_bridge reference each — these exercise the `interfaces/bridge/*` decomposition directly and
  would need re-pointing if `file_bridge.py` itself moves into that package.

---

## SPECIAL DEPTH: `file_bridge -> core` (joint-best cut, collapses SCC 18 → 7 [INHERITED])

**Exact crossing symbol:** exactly one — `process_bridge_payload` (a plain function defined at
`core.py:1455`). No other name crosses this edge [MEASURED via grep of `core\.` and
`process_bridge_payload` over `file_bridge.py`: only lines 766 and 797 match].

**Functions/call sites carrying it:** one function (`_process_request_claimed`, `file_bridge.py:759`),
one import (`:766`), one use (`:797`, where it is threaded into
`bridge_dispatch.ClaimedDispatchPorts(..., process_bridge_payload=process_bridge_payload, ...)`).
The import is **already function-local/deferred** — i.e. this is already a de-facto port seam at
runtime (`from .core import process_bridge_payload` performs a fresh attribute lookup on
`sys.modules['daedalus.core']` every call, so `monkeypatch.setattr("daedalus.core.process_bridge_payload", ...)`
is already observed correctly by production code today). The SCC edge is a **purely static** AST
artifact of that one `from .core import ...` line, not a real runtime coupling problem.

**Why the static edge still matters:** `daedalus/interfaces/bridge/dispatch.py` already declares
`ClaimedDispatchPorts.process_bridge_payload: Callable[..., dict[str, Any]]` (`:187`) as an
injectable field — the *port already exists one layer down*. The only reason `file_bridge.py` itself
still has a static reference to `core` is that it is the one that resolves the concrete callable
before building the `Ports` object.

**Minimum port surface / cheapest severance — (a) port extraction as a push-registration, not a pull-import:**

1. In `file_bridge.py`, replace the local `from .core import process_bridge_payload` at `:766` with
   a module-level indirection cell that `file_bridge.py` owns and `core.py` populates:
   ```python
   # file_bridge.py, near INBOX/OUTBOX/ARCHIVE
   _BRIDGE_WORK: Callable[..., dict[str, Any]] | None = None

   def register_bridge_work(fn: Callable[..., dict[str, Any]]) -> None:
       """Called once by daedalus.core at import time; the reverse direction
       (core -> file_bridge) already exists in this SCC, so this does not add
       a new pair -- it only removes the file_bridge -> core direction."""
       global _BRIDGE_WORK
       _BRIDGE_WORK = fn
   ```
   `_process_request_claimed` then reads `_BRIDGE_WORK` (raising a clear `RuntimeError` if `None`,
   since production always registers it) instead of importing `core`.
2. In `core.py`, immediately after `def process_bridge_payload(...): ...` (`:1455` onward), add one
   module-level line: `from . import file_bridge as _file_bridge` (safe: after this change
   `file_bridge.py` contains zero references to `core`, so this direction alone cannot cycle) and
   `_file_bridge.register_bridge_work(process_bridge_payload)`. `core.py` already imports
   `file_bridge` transitively at module level via `status.collect_status` (`status.py:47`), so this
   adds no new import-time risk.
3. `core.process_bridge_payload` stays exactly where it is, with exactly its current signature — the
   **7 test files** that call `core.process_bridge_payload(...)` directly
   (`test_agents_registry.py`, `test_codex_provider.py`, `test_comms.py`, `test_dynamic.py`,
   `test_loop_lease.py`, plus the `core, "process_bridge_payload"` object-patches in
   `test_bridge_restart.py:496,682`) are untouched.
4. The **one** load-bearing fixture (`tests/test_bridge_restart.py:136-150`, `work`) changes its one
   line from `monkeypatch.setattr("daedalus.core.process_bridge_payload", m)` to
   `monkeypatch.setattr(file_bridge, "_BRIDGE_WORK", m)`. This is a single-fixture edit, not 48
   individual call-site edits, because every one of those 48 `fb.process_request(req)` calls in that
   file already goes through the shared `work` fixture rather than patching inline.

**Why this is cheapest:** exactly 1 crossing symbol, 1 production import site, and — the number that
actually matters here — **1 test fixture** absorbs the entire migration cost despite 48+8 raw call
sites depending on the seam. A plain "make the parameter mandatory and update every caller" approach
would look like it costs ~56 call-site edits; tracing the fixture shows the real cost is 1 line in
`file_bridge.py`, ~2 lines in `core.py`, and 1 line in one pytest fixture.
