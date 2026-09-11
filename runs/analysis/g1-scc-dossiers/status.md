# SCC dossier: `status` (daedalus/status.py)

Base: main @ 851ff43c. Read-only static analysis.

## Step 1 — Measured edges (raw AST probe)

Command: `.venv/Scripts/python.exe C:/Users/Administrator/scc-scratch/probe.py status`

```
### OUTGOING edges FROM status to other SCC members
  -> health                     MODULE-LEVEL               in <module>
       daedalus/status.py:46   from . import health
  -> file_bridge                MODULE-LEVEL               in <module>
       daedalus/status.py:47   from .file_bridge import INBOX, OUTBOX

### INCOMING edges INTO status from other SCC members
  <- core                       MODULE-LEVEL               in <module>
       daedalus/core.py:19   from .status import collect_status
```
[MEASURED]

### Verification against source

Read `daedalus/status.py` in full (199 lines) and `daedalus/core.py:1-30`.

- Line 46 `from . import health` — top-level statement, module scope (`<module>` correct), unconditional, no `TYPE_CHECKING` guard. Real, reachable. CONFIRMED.
- Line 47 `from .file_bridge import INBOX, OUTBOX` — same block, unconditional. `INBOX`/`OUTBOX` are then used at runtime in `collect_status` (lines 98-99: `OUTBOX.glob(...)`, `INBOX.glob(...)`). Not a typing-only import. CONFIRMED, and load-bearing (not vestigial).
- `core.py:19` `from .status import collect_status` — part of `core.py`'s top-level import block (lines 14-19), unconditional, module scope. CONFIRMED.
- No corrections needed to the probe's classification.

`status.py` also imports two names NOT in the SCC (`from .memory import TODO_PATH, load_events` at line 48, `from .projects import resolve_repo_root` at line 49) — outside probe scope, noted only for completeness.

### Dynamic references

`grep -n "importlib|__import__"` over `daedalus/status.py`: **0 matches** [MEASURED]. No string-literal references to other SCC member module names found either (only `from daedalus.budget import ...` and `from daedalus.spine.effect_boundary import ...` inside `main()`, both outside the 18-member SCC set given). No dynamic/reflective coupling to SCC members.

## Step 2 — What it actually does

`status.py` is the `daedalus status` CLI: `collect_status()` gathers six legacy counters (git branch/status, outbox/inbox file counts, memory-event count, open-TODO count) by shelling `git` and reading `file_bridge`'s `INBOX`/`OUTBOX` paths and `memory`'s event log. `main()` then calls `daedalus.health.assess(...)` to get a per-subsystem working/present/degraded/absent/unknown verdict and renders either the old counters (`--counters`), a JSON payload with both (`--json`, always exit 0), or the health report plus counters as the default human view, computing the process exit code from `health.verdict(reports)`. Before doing any of that, `main()` calls `begin_effect("cli.status", ...)` against the `spine.effect_boundary` registry — an out-of-SCC guard call, not a domain effect.

## Step 3 — Layer

**Verdict: interfaces** (CLI-surface / status-reporting), currently mis-sited relative to the target layout, but only mildly — it is the correct home for a `daedalus status` command once `daedalus/interfaces/` exists.

Justification: `status.py` produces no domain effects itself — it reads (git subprocess, filesystem globs, `memory` event log) and formats output for a human or the VS Code extension (`core.py`'s web API and status bar consume `collect_status`, per its own docstring lines 14-15, 88-90). It holds no policy, no leases, no promotion logic, no orchestration/scheduling. Its only SCC-internal behavioral dependencies are `health` (an assessment aggregator, itself outside this SCC's effect surface) and `file_bridge` (read of two path constants only — `INBOX`/`OUTBOX`, not the queue logic). `main()` calls a policy boundary (`begin_effect`) defensively before doing read-only work, which is the interfaces layer's normal relationship to the kernel (call the gate, don't own it). It is currently placed at `daedalus/status.py`, i.e. top-level package, not under a `foundation` or `interfaces` package — current directory placement is not evidence either way per the task's own instruction, but behaviorally this is a client-facing reporting surface, not kernel/spine/twin/runtime/orchestration/workload logic.

## Step 4 — Severance, per outgoing edge

### Edge 1: `status -> health` (module-level, `from . import health`)

- Symbols crossing: the whole `health` module object, used via `health.assess(...)`, `health.verdict(...)`, `health.to_payload(...)`, `health.render(...)` — 4 distinct call sites/symbols (`assess`, `verdict`, `to_payload`, `render`), all inside `main()` (lines 176-192).
- Cheapest severance: **(a) port/protocol extraction.** Define a `HealthReporterPort` Protocol carrying exactly `assess(only, *, repo_root, probe_remote, deep) -> Sequence[Report]`, `verdict(reports) -> int`, `to_payload(reports) -> dict`, `render(reports, *, verbose) -> str`. Location: a new `daedalus/kernel/ports.py` or, if one already exists for attempt execution (`daedalus/kernel/attempt_execution.py` already hosts `AttemptWorkspacePort`/`AttemptEvaluatorPort`), colocate there as `HealthReporterPort`. `status.main()` would accept the port via a parameter (not a module import) or via a lazy factory the way `spine/bootstrap.py` already does for `attempt_ports_factory`.
- Why cheapest: only 4 call sites, all within one function, all against a stable read-only surface (assessment, not mutation). `health` itself is a report aggregator with no back-edge to `status`, so a Protocol is a clean, minimal-surface cut with no behavior change — cheaper than merging (the two modules have distinct, separately-testable responsibilities: `health` is a probe framework, `status` is a CLI presenter) and cheaper than callback injection (four functions would need four separate callback parameters vs. one Protocol object).
- Not already deferred: this import is eager/module-level, so it is not already a de-facto seam.

### Edge 2: `status -> file_bridge` (module-level, `from .file_bridge import INBOX, OUTBOX`)

- Symbols crossing: exactly 2 — `INBOX`, `OUTBOX` (both `Path` constants). Grep of `status.py` for `INBOX`/`OUTBOX` shows each used exactly once, both inside `collect_status()` (lines 98-99), only to call `.glob("*.json")` / `.glob("*.report.json")` and `.exists()`.
- Cheapest severance: **(b) callback/parameter injection**, not a Protocol — two path constants don't justify a Protocol class. Give `collect_status(repo_root, *, inbox_dir: Path | None = None, outbox_dir: Path | None = None)` and let the caller (`main()`, or ultimately `core.py`) pass `file_bridge.INBOX` / `file_bridge.OUTBOX` in. `core.py` already imports both `status` and (transitively via other calls) `file_bridge`-shaped concerns, so it is a natural caller to own the wiring.
- Why cheapest: only 2 symbols, both simple `Path` values (not behavior), used in exactly 2 call sites in one function. Constructing a whole Protocol for two paths is overkill; parameter injection with defaults preserves the current zero-argument call convenience for existing callers while breaking the import-time coupling to `file_bridge`.
- Not already deferred: eager/module-level.

## Step 5 — Tests that pin this

`grep -rn` over `tests/` for `daedalus.status` / `from daedalus import status` / `from daedalus.status` / `status\.collect_status` / `patch("daedalus.status` [MEASURED]:

- **5 files** matched broadly for `status` module references relevant to `daedalus.status` (not the generic English word "status", which appears pervasively and was excluded by requiring `daedalus.status` or `from daedalus import status`):
  - `tests/test_health_surface.py` — imports `from daedalus.status import collect_status` (line 614), `from daedalus.status import _count_open_todos` (line 622), `from daedalus import status as status_mod` (lines 633, 648). Test functions that pin public symbols/behavior: `test_collect_status_keeps_every_legacy_key` (line 613), `test_count_open_todos_still_exists_for_its_test` (line 621), `test_json_mode_exits_zero_and_carries_the_verdict` (line 625), `test_human_mode_propagates_the_verdict` (line 645). These pin `collect_status`'s legacy key set, `_count_open_todos`'s continued existence, and `main()`'s `--json`/human-mode exit-code and verdict behavior — i.e., exactly the health-integration surface (Edge 1) and the counters (independent of Edge 2 symbol identity, since `INBOX`/`OUTBOX` are used internally, not asserted on directly by name here).
  - `tests/test_cli_effect_boundary.py` — `test_shift_status_stays_fail_open_read_only` (line 113) invokes `main(["status"])` end-to-end; `test_status_refuses_fail_closed_before_any_probe` (line 330) does `from daedalus import status` then `monkeypatch.setattr(status, "collect_status", _exploded)` (line 336) and calls `status.main([])` (line 338) — this is a `mock.patch`-shaped symbol-path pin on `daedalus.status.collect_status` specifically; renaming or moving `collect_status` off `status` breaks it.
  - `tests/test_comms.py` — string literal `"daedalus.status"` (line 148) and `"Daedalus: status"` (line 106) appear in what looks like router/agent-name plumbing, not a direct import; UNVERIFIED whether these are functionally coupled to this module or coincidental string matches (would need reading `test_comms.py` around those lines, out of scope for this dossier's edge-severance question).
  - `tests/test_agent_env.py` — `from daedalus.status import _count_open_todos` (line 12), used across several TODO-counting tests (lines ~133-135 area). Pins the private `_count_open_todos` symbol path directly.
  - `tests/contracts/test_import_scc_hierarchy.py` — references the literal string `"daedalus.status"` (line 39) as part of the SCC membership list itself (governance test, not a behavioral pin on internals).

Total: **5 test files**, with `tests/test_health_surface.py` and `tests/test_agent_env.py` and `tests/test_cli_effect_boundary.py` (3 files) containing genuine `mock.patch`/import-path pins on `daedalus.status` public and private symbols (`collect_status`, `_count_open_todos`, `main`). Moving `collect_status` or `_count_open_todos` off `daedalus.status`, or rewiring the `health`/`file_bridge` imports without preserving these symbol paths, would break these tests. [MEASURED] (grep counts and line numbers above; not executed).

## Pass-through vs. real coupling verdict

**`status` is a real (if thin) coupling point, not a pure pass-through.** Both outgoing edges are eager/module-level and both are load-bearing at runtime: `health` is invoked with 4 distinct calls that shape the CLI's primary output and exit code (this is the module's *raison d'être* per its own docstring — the counters were demoted specifically because `health` exists), and `file_bridge.INBOX`/`OUTBOX` are read directly inside `collect_status`, which is itself re-exported and consumed by `core.py` and (per the docstring) the VS Code extension. `status` does not merely re-export `health`'s or `file_bridge`'s symbols unchanged — it composes them (`collect_status()` + `health.assess()` merged into one JSON payload, one exit-code policy) and adds real logic (`_count_open_todos`, `_git`, `print_counters`, the exit-code table in the module docstring at lines 25-27). It cannot sink to a zero-SCC-edge leaf without severing both edges (Step 4); it is a small aggregator with exactly 2 outgoing edges and 1 incoming edge, which is a minimal but genuine coupling, not zero.
