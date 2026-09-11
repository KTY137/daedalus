# SCC dossier: `doctor` (`daedalus/doctor.py`)

Base: main @ 851ff43c. 180 lines [MEASURED, `wc -l`].

## Step 1 — Measured edges (raw AST probe)

Command: `.venv/Scripts/python.exe C:/Users/Administrator/scc-scratch/probe.py doctor` [MEASURED]

```
### OUTGOING edges FROM doctor to other SCC members
  -> file_bridge                FUNCTION-LOCAL (deferred)  in _print_watcher_heartbeat
       daedalus/doctor.py:105   from .file_bridge import STALE_AFTER_S, heartbeat_status

### INCOMING edges INTO doctor from other SCC members
  <- core                       FUNCTION-LOCAL (deferred)  in _availability_from_doctor
       daedalus/core.py:976   from .doctor import check
  <- offload                    FUNCTION-LOCAL (deferred)  in _offload_impl
       daedalus/offload.py:386   from .doctor import check
```

**Verification.** Read every cited site:

- `doctor.py:105`, inside `_print_watcher_heartbeat` (def at `:102`) — real, reachable, no
  `TYPE_CHECKING` guard. Both `STALE_AFTER_S` (used `:122`) and `heartbeat_status` (called `:107`)
  are actually consumed, not an unused import. Confirmed [MEASURED].
- `core.py:976`, inside `_availability_from_doctor` (def at `:975`) — real; `check()` called `:978`.
  Confirmed [MEASURED].
- `offload.py:386`, inside `_offload_impl` (def at `:358`) — real; `check()` called `:387`, guarded
  only by `if availability is None:` (a normal default-parameter branch, not a dead/TYPE_CHECKING
  branch — it fires whenever the caller does not pre-supply availability). Confirmed [MEASURED].

No corrections to the probe's classification were needed.

**Dynamic references.** `grep -n "importlib|__import__"` over `doctor.py`: no matches [MEASURED].
No `TYPE_CHECKING` guard in the file [MEASURED]. No string literals naming other SCC members beyond
the plain import statements above.

## Step 2 — What it actually does

`doctor.py` answers "can Daedalus offload real work right now": `check()` probes `claude`/`codex` on
`PATH`, hits the local Ollama server's `/api/tags` over HTTP to see which model is pulled, and reads
`DEEPSEEK_API_KEY`, returning one flat availability dict that `core._availability_from_doctor` and
`offload._offload_impl` both consume to pick a lane. `codex_status()` additionally shell-execs
`codex --version` / `codex login status` (spend-ceiling-gated) for a richer human-readable line.
`main()` is the `python -m daedalus.doctor` / `daedalus doctor` CLI entrypoint that prints all of the
above plus one extra check that is not about provider availability at all: whether the file-bridge
watcher's heartbeat is fresh (`_print_watcher_heartbeat`, `:102-129`).

## Step 3 — Layer

**Verdict: runtimes**, with one clearly bolted-on **interfaces**-shaped CLI probe.

The bulk of `doctor.py` (`_ollama_models`, `check`, `codex_status`) is a read-only conformance/health
probe over external runtime adapters (Ollama HTTP, `claude`/`codex` CLIs) — exactly the "provider
adapters, faults, conformance" definition of `runtimes`. It holds no policy, no effects beyond a
`begin_effect("cli.doctor", ...)` registration in `main()` (`:136`) that is itself gated by
`process_guard_boundary_decision()`, and nothing here writes or promotes anything. The one piece that
does not fit — `_print_watcher_heartbeat` — is not a runtime-provider check at all; it is a
file-bridge-queue liveness check reusing the CLI's stdout, i.e. it belongs with `interfaces` (or
directly beside `file_bridge`/`daedalus/interfaces/bridge/`), not with provider-availability probing.
Both `core.py` and `offload.py` consume only `check()` (the runtimes half) — nobody outside
`doctor.py` itself calls `_print_watcher_heartbeat` in production, which corroborates that it is a
foreign concern grafted onto this module's `main()` rather than a caller-driven need. `doctor.py` is
therefore not badly mis-sited for its dominant behavior, but the heartbeat print is.

## Step 4 — Severance

`doctor` has exactly one outgoing SCC edge — see the SPECIAL DEPTH section below, which covers it in
full since it is also the second joint-best cut [INHERITED].

## Step 5 — Tests that pin this

`grep -rn` over `tests/` [MEASURED]:

- Import/reference of `doctor` (module import or `patch("daedalus.doctor...")`) : **5 files, 32
  matching lines** [MEASURED].
- String-pinned `patch("daedalus.doctor.<attr>", ...)` targets: `check` (`tests/test_codex_provider.py:338,418,436`;
  `tests/test_dynamic.py:177,218,263,331,350,381,414,442` — 8 sites; `tests/test_selftest.py:16,31,43`
  — 3 sites), `shutil.which`, `_ollama_models`, `subprocess.run`, `codex_status`
  (`tests/test_codex_provider.py`, several lines each). These all pin `daedalus.doctor.<name>` as an
  exact attribute path; none of them touch the `file_bridge`-facing half of the module.
- `tests/test_bridge_signals.py::DoctorHeartbeatTests` (`:197-220`) is the test that actually pins
  the edge under review:
  - `test_doctor_warns_on_stale_heartbeat_with_restart_one_liner` (`:205`) and
    `test_doctor_ok_on_fresh_heartbeat` (`:212`) both call
    `from daedalus.doctor import _print_watcher_heartbeat; _print_watcher_heartbeat()` **with zero
    arguments** and separately do `patch.object(file_bridge, "STALE_AFTER_S", -1.0)` (`:207`) —
    i.e. they rely on `doctor.py`'s function-local `from .file_bridge import STALE_AFTER_S,
    heartbeat_status` re-reading the (possibly patched) module attribute on every call.
  - `test_doctor_notes_missing_heartbeat_without_false_alarm` (`:217`) calls the same zero-arg
    `_print_watcher_heartbeat()`.
  - `tests/test_codex_provider.py::test_doctor_main_renders_codex_line` (`:409`) and
    `::test_doctor_main_renders_codex_absent` (`:427`) call `doctor.main()` with **zero arguments**
    and no heartbeat-related patching at all — they exercise the real `file_bridge.heartbeat_status()`
    call path incidentally (against whatever heartbeat file happens to exist on disk) while only
    asserting on the codex lines.

All five of these tests require `_print_watcher_heartbeat()`/`main()` to keep working with **no
arguments supplied**, which is the binding constraint on the severance design below.

---

## SPECIAL DEPTH: `doctor -> file_bridge` (joint-best cut, collapses SCC 18 → 7 [INHERITED])

**Exact crossing symbols:** two — `STALE_AFTER_S` (a float constant, `file_bridge.py:41`) and
`heartbeat_status` (a function, `file_bridge.py:927`). No other name crosses this edge [MEASURED via
grep of `file_bridge\.|STALE_AFTER_S|heartbeat_status|\bfb\.` over `doctor.py`: only lines 105, 107,
122 match].

**Functions/call sites carrying it:** one function (`_print_watcher_heartbeat`, `doctor.py:102-129`),
one import (`:105`), two uses (`heartbeat_status()` at `:107`, `STALE_AFTER_S` at `:122`). Both
symbols are genuinely needed: `heartbeat_status()` reads `HEARTBEAT_PATH` (a `file_bridge`-owned
`Path` constant, `file_bridge.py:33`) and classifies watcher liveness; `STALE_AFTER_S` is only used
to print the staleness threshold in the warning line, not to make a decision (the decision already
lives inside `heartbeat_status()`'s return value, `hb["state"]`).

**Why file_bridge, and not a lower-level module, owns these:** `file_bridge.py` itself gets the
*algorithm* for `heartbeat_status` from `daedalus/interfaces/bridge/watcher.py` (a non-SCC module —
`bridge_watcher.heartbeat_status`, called at `file_bridge.py:937`), but the *concrete* path/threshold
constants (`HEARTBEAT_PATH`, `STALE_AFTER_S`, `BUSY_BUDGET_S`, `INBOX`, `OUTBOX`, `ARCHIVE`, `ROOT`)
are defined only in `file_bridge.py` (`:28-42` [MEASURED]), not in `interfaces/bridge/watcher.py`.
`doctor.py` cannot bypass `file_bridge` and call `bridge_watcher.heartbeat_status(...)` directly
without also duplicating those constants, which would be a worse outcome (two owners of the same
path).

**Minimum port surface / cheapest severance — (b) callback/parameter injection at the one real
caller, with defaults preserved for the pinned zero-arg tests via a module-level fallback that does
NOT reference `file_bridge` in `doctor.py`'s own source:**

1. Change the two functions' signatures to accept the port explicitly, defaulting to `None`:
   ```python
   # doctor.py
   def _print_watcher_heartbeat(
       heartbeat_status: Callable[[float | None], dict[str, Any]] | None = None,
       stale_after_s: float | None = None,
   ) -> None:
       heartbeat_status = heartbeat_status or _default_heartbeat_port()
       stale_after_s = _STALE_AFTER_S_DEFAULT if stale_after_s is None else stale_after_s
       ...
   ```
2. The only way to give `_default_heartbeat_port()` a real implementation **without** a static
   `from .file_bridge import ...` in `doctor.py` is the same push-registration pattern used for the
   `file_bridge -> core` cut: `doctor.py` exposes
   `register_heartbeat_port(fn: Callable[..., dict], stale_after_s: float) -> None` that sets two
   module-level globals (`_HEARTBEAT_STATUS`, `_STALE_AFTER_S_DEFAULT`, both `None` until
   registered), and `file_bridge.py` calls it once at its own **module level**, right after defining
   `heartbeat_status`/`STALE_AFTER_S` (`file_bridge.py:41` / `:927`):
   `from . import doctor as _doctor; _doctor.register_heartbeat_port(heartbeat_status, STALE_AFTER_S)`.
   This direction is safe: it is `file_bridge -> doctor`, which is not one of this SCC's 18x18 pairs
   today in either direction, so it cannot recreate the cycle by itself, and `doctor.py` no longer
   contains any `import`/`from` naming `file_bridge`.
3. This satisfies all five pinned tests unchanged: `_print_watcher_heartbeat()` and `main()` keep
   working with zero arguments (the registered default fires), and
   `patch.object(file_bridge, "STALE_AFTER_S", -1.0)` still works **only if** `doctor.py` re-reads
   `_STALE_AFTER_S_DEFAULT` fresh on every call rather than caching it at registration time — so
   `register_heartbeat_port` should store the *module reference* (or a zero-arg getter) rather than
   snapshotting the float, e.g. `register_heartbeat_port(fn, get_stale_after_s=lambda: file_bridge.STALE_AFTER_S)`.
   This is the one place this severance is less clean than the `core` cut: it requires threading a
   getter, not a plain value, specifically to keep `test_doctor_warns_on_stale_heartbeat_with_restart_one_liner`
   green.

**Why this is cheapest:** only 2 crossing symbols, 1 consuming function, 2 call sites, and the
registration flips to the safe direction (`file_bridge -> doctor`) using a pattern already directly
analogous to how `file_bridge.py` itself receives `bridge_dispatch`/`bridge_watcher` callables from
`daedalus/interfaces/bridge/*` today. Cost is 0 production call-site changes (the only caller,
`daedalus/cli.py:1139`, still does `from .doctor import main as m; m()`) and 0 test edits — the
5 pinned tests all keep their current zero-arg call shape.
