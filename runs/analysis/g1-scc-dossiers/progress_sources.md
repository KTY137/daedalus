# SCC dossier: `daedalus.progress_sources` (`daedalus/progress_sources.py`)

Base: main @ 851ff43c (per task header). File is 576 lines [MEASURED, `wc -l`].

## Step 1 — Measured edges (raw AST probe)

Command: `.venv/Scripts/python.exe C:/Users/Administrator/scc-scratch/probe.py progress_sources` [MEASURED]

```
### OUTGOING edges FROM progress_sources to other SCC members
  -> progress                   MODULE-LEVEL               in <module>
       daedalus/progress_sources.py:78   from . import progress as P
  -> health                     MODULE-LEVEL               in <module>
       daedalus/progress_sources.py:79   from .health import INHERITED, inherited, measured
  -> file_bridge                FUNCTION-LOCAL (deferred)  in snapshot_from_bridge
       daedalus/progress_sources.py:498   from . import file_bridge as fb
  -> spine.attempt              FUNCTION-LOCAL (deferred)  in track_call
       daedalus/progress_sources.py:339   from .spine.attempt import AttemptResult

### INCOMING edges INTO progress_sources from other SCC members
  <- progress                   FUNCTION-LOCAL (deferred)  in main
       daedalus/progress.py:764   from . import progress_sources
```

### Verification against the source (Read, full file)

- `progress_sources.py:78` `from . import progress as P` — module level, inside `<module>` scope (after the module docstring ends at line 70, `from __future__ import annotations` at 71). Not inside `TYPE_CHECKING`. **Real, heavily used at runtime**: `P.default_log`, `P.claim_unit`, `P.record_generating`, `P.record_done`, `P.record_disk_change`, `P.record_patch_produced`, `P.record_tool_ran`, `P.record_gate_verdict`, `P.heartbeat`, `P.snapshot`, `P.UnitProgress`, `P.Fact`, `P.parse_iso`, `P.format_age`, `P.now_iso`, `P.DONE/CLAIMED/QUEUED` throughout the file (lines 133–576). Confirmed real, not annotation-only — no free cut available via `TYPE_CHECKING` hoisting.
- `progress_sources.py:79` `from .health import INHERITED, inherited, measured` — module level, `<module>` scope. Used at runtime: `measured(...)` (lines 365, 371, 373, 462), `inherited(...)` (line 464), `INHERITED` (lines 367, 466). Real value usage, not type annotations. **Not a free cut.**
- `progress_sources.py:498` `from . import file_bridge as fb` — confirmed function-local, inside `snapshot_from_bridge` (def at line 481). Used for `fb.ARCHIVE`, `fb.quarantined_requests()`, `fb.INBOX`, `fb.heartbeat_status()`, `fb.OUTBOX` (lines 502–545). Real and reachable, already deferred by the original author.
- `progress_sources.py:339` `from .spine.attempt import AttemptResult` — confirmed function-local, inside `track_call` (def at line 285). Guarded by `try/except Exception` (338–341) that treats an import failure as "no AttemptResult available" (`AttemptResult = ()`), then used only for an `isinstance` check (line 342). Real and reachable, already deferred and already defensively tolerant of the edge not resolving.

Probe tool correctness: enclosing-function attribution and MODULE-LEVEL/FUNCTION-LOCAL classification both check out against the source; no correction needed.

### Dynamic references (grep)

`importlib.import_module` / `__import__`: **none found** [MEASURED, `Grep` over the file, 0 matches]. No string literal anywhere in the file names another SCC member for dynamic dispatch — every cross-module reference is one of the four AST-visible imports above.

## Step 2 — What it actually does

`progress_sources.py` is a set of pure, read-only adapter functions that translate signals other modules *already* produce (a chat-stream event iterator, an `offload()` result dict, a `spine.attempt.AttemptResult`, the spine ledger, and the file-bridge outbox/inbox/archive lifecycle) into `daedalus.progress.ProgressEvent` records via `daedalus.progress`'s recording API (`P.claim_unit`, `P.record_generating`, `P.record_done`, etc.). It deliberately refuses one specific signal — a worker's self-reported `report["files_changed"]` — accepting only a mechanical content-hash diff (`result["wrote"]`) as proof of a disk change, and keeps HEARTBEAT (thread-alive) strictly separate from GENERATING (bytes actually produced). Three of its seven public functions (`snapshot_from_ledger`, `open_attempts`, `snapshot_from_bridge`) are read-only pollers that open `SpineLedger(read_only=True)` or stat files under `file_bridge`'s outbox/inbox/archive, never writing anything themselves; `snapshot_any` is a one-entry-point fallback across the module's own log, the ledger, and the bridge.

## Step 3 — Layer

**Verdict: `orchestration`** (with a `foundation`-flavored read-only-adapter character), and it is **not** mis-sited relative to the target layout's intent — it belongs next to `daedalus.progress`, wherever that lands.

Justification: the module holds no policy, no effect authority, and no write path of its own — every "write" it performs is a call into `daedalus.progress`'s own event-recording API (never a raw file/DB write), and its three poll functions open the ledger `read_only=True` explicitly matching `daedalus.health`'s discipline (module docstring, lines 31–37). What it *does* do is observe and translate the state of in-flight mission/attempt/bridge work — CLAIMED/GENERATING/DONE/DISK_CHANGED/PATCH_PRODUCED events for units of work dispatched elsewhere (`ikarus_os.ask_stream`, `offload.offload()`, `spine.attempt.TaskAttempt`, `spine.ledger`, `file_bridge`) — which is squarely progress-tracking for orchestrated work, i.e. `orchestration`. It imports `health` (a status/diagnostic module) and `spine.attempt`/`file_bridge`/`spine.ledger` (dispatch/effect modules) but never imports `kernel.*` promotion/policy code and is imported only by `progress` itself among SCC members — it is a leaf adapter feeding the orchestration-layer progress log, not a trust-boundary module.

## Step 4 — Severance, per outgoing edge

### `-> progress` (MODULE-LEVEL, line 78)

Cheapest severance: **(d) genuine merge with the target.** `progress_sources` exists *solely* to produce `P.ProgressEvent`s through `progress`'s own recording functions — every one of its 7 public functions calls into `P.*` (`claim_unit`, `record_generating`, `record_done`, `record_disk_change`, `record_patch_produced`, `record_tool_ran`, `record_gate_verdict`, `heartbeat`, `snapshot`, plus the `P.UnitProgress`/`P.Fact` value types and `P.parse_iso`/`P.format_age`/`P.now_iso`/`P.DONE`/`P.CLAIMED`/`P.QUEUED` constants). Grepping the file for `P\.` shows the API is used in essentially every function body (module docstring already says as much: "Nothing in this file is a second source of truth"). This is a 2-cycle of exactly one shared vocabulary — `progress_sources` cannot mean anything without `progress`'s event/type vocabulary, and `progress` only reaches back into `progress_sources` via one deferred import inside `main` (a CLI entry point, `progress.py:764`) purely to expose these adapters to a command-line tool. The split is artificial: `progress_sources` is not consumed by anything else in the SCC as an independent unit (see Step 4 "only importer" note below) and both files together define one cohesive concept (the progress-event vocabulary + its adapters). Merging `progress_sources` functions into `progress.py` (or moving both under one `orchestration/progress/` package with `__init__` re-exports) removes the 2-cycle for free; the alternative — porting `P.*` behind a Protocol — would require carrying ~10 symbols (5 record_* functions, `claim_unit`, `heartbeat`, `snapshot`, `default_log`, plus 3 value types and 3 constants) through an artificial seam for no behavioral gain, since `progress` never calls back into `progress_sources` except through the one CLI deferred import.

### `-> health` (MODULE-LEVEL, line 79)

Cheapest severance: **(a) port/protocol extraction**, but it is a **cheap, nearly-free cut**, not urgent. `progress_sources` imports exactly 3 symbols — `INHERITED` (a provenance-tag constant), `inherited(...)`, and `measured(...)` (both tiny factory functions building `Fact`-shaped provenance tags). Grep shows 6 call sites (`measured` x3: lines 365, 371, 373; `inherited` x1: line 464; `INHERITED` x2: lines 367, 466). A `ProvenanceTag` Protocol/module (e.g. a new `daedalus/provenance.py` or moving these 3 symbols into `daedalus.progress` itself, which already owns the `Fact`/`UnitProgress` types they decorate) would carry just `INHERITED`, `inherited()`, `measured()`. Because `progress` already defines `P.Fact` (the type these functions build) and is the module `progress_sources` cannot be severed from anyway (see above), the cheapest real move is **hoisting these 3 symbols into `daedalus.progress`** and having `progress_sources` (and `health`) both import them from there — turning this edge into a strict subset of the edge already being merged in Step (d) above, at zero net new module count.

### `-> file_bridge` (FUNCTION-LOCAL / deferred, line 498)

Cheapest severance: **(b) callback / parameter injection**, and the deferral already functions as a de-facto port seam. Only one function (`snapshot_from_bridge`) uses it, reaching exactly 5 attributes: `fb.ARCHIVE`, `fb.INBOX`, `fb.OUTBOX`, `fb.quarantined_requests()`, `fb.heartbeat_status()`. Because the import is deferred to function scope, it already does not participate in any module-load-order cycle — the SCC edge exists only because the AST walk counts function-scope imports too (per the governance test's own stated methodology, `tests/contracts/test_import_scc_hierarchy.py:86-92`). The cheapest actual severance: give `snapshot_from_bridge` a `bridge: BridgePort | None = None` parameter (defaulting to a lazy `file_bridge` import if `None`, as today) where `BridgePort` is a `Protocol` carrying `ARCHIVE: Path`, `INBOX: Path`, `OUTBOX: Path`, `quarantined_requests() -> list[dict]`, `heartbeat_status(now: float) -> dict` — defined in a new small `daedalus/progress_ports.py` (or co-located in `progress.py` if merged per (d) above). This lets a caller inject a fake bridge for tests without touching `file_bridge` itself, and removes the SCC edge's *module-scope* character entirely (it never had one).

### `-> spine.attempt` (FUNCTION-LOCAL / deferred, line 339)

Cheapest severance: **(b) callback / parameter injection**, cheapest of all four edges. Exactly 1 symbol crosses (`AttemptResult`, used only for `isinstance`), 1 call site (line 342), already deferred, and already wrapped in a `try/except Exception` that tolerates the import failing (lines 338–341: `AttemptResult = ()` on failure). This is close to a free cut: `track_call` could accept an optional `attempt_result_type: type | tuple = ()` parameter from its caller (which already knows whether it is dispatching through `spine.attempt.TaskAttempt`), removing the need for `track_call` to import `spine.attempt` at all. Given the single isinstance use and the pattern's existing defensiveness, this is effectively already a de-facto port — the deferred-import + try/except IS the seam; formalizing it as a parameter is a small mechanical change.

### Judgment on the inherited framing (progress / progress_sources 2-cycle)

The task's inherited context frames this as needing a judgment call between "genuine merge" and "real seam." Verdict: **genuine merge (d)**, not a real seam. The forcing symbols are `progress`'s own event/type vocabulary (`P.claim_unit`, `P.record_*`, `P.UnitProgress`, `P.Fact`, `P.snapshot`, `P.DONE`/`P.CLAIMED`/`P.QUEUED`, `P.now_iso`/`P.parse_iso`/`P.format_age`) flowing one way (module-level, ~10 symbols, dozens of call sites) versus `progress` importing `progress_sources` only inside `main()` (a CLI entry point) to expose these same adapters as commands — a one-directional, thin, deferred back-reference that exists purely for CLI wiring, not because `progress` needs `progress_sources`'s logic to function. `progress_sources` has exactly one importer in the whole SCC (`progress`, and only from its `main` function), confirming it is not an independently-consumed module — it is `progress`'s adapter layer, artificially split into a second file. Splitting was presumably done for the module docstring's own stated reason (an evidence-provenance essay distinct from the event-log core), which is a documentation/readability argument, not an architectural one.

## Step 5 — Tests that pin this

Grep of `tests/` for `progress_sources`: **2 files, 2 matching lines** [MEASURED].

1. `tests/contracts/test_import_scc_hierarchy.py:34` — `"daedalus.progress_sources"` listed in `OLD_CROSS_DOMAIN_COMPONENT` (the 18-member frozenset naming this exact SCC). This is the **governance/architecture test** that would break: `test_observation_contract_breaks_the_next_cross_domain_scc` (line 198) asserts `CENSUS_EDGES == 1630`, `len(components) == 12`, `max(map(len, components)) == 18`, and a SHA-256 hash (`CURRENT_COMPONENTS_SHA256`) of the exact serialized component structure. Any edge severance touching `progress_sources` (cutting `-> health`, `-> progress`, `-> file_bridge`, or `-> spine.attempt`) changes the edge count and very likely the SCC partition, which will fail this exact assertion and must be updated deliberately as part of any severance work — it is *designed* to catch this.
2. `tests/test_web_api.py:312` — `mock.patch("daedalus.progress_sources.snapshot_from_bridge", return_value=progress)` inside `test_terminal_task_snapshot_keeps_requested_lane_and_actual_provider` (class body starting at line 295). This is a **string-target mock patch**: it would break if `snapshot_from_bridge` were renamed or moved out of `daedalus.progress_sources` (e.g. as a side effect of the Step-4(d) merge into `daedalus.progress`), even though the patch target string is unrelated to the import-edge severance itself.

No other test file references `progress_sources` by name [MEASURED, 0 additional matches]. Total: 2 test files, 2 test functions directly implicated (`test_observation_contract_breaks_the_next_cross_domain_scc`, `test_terminal_task_snapshot_keeps_requested_lane_and_actual_provider`); `test_intent_ledger_port_breaks_the_selected_cross_domain_scc` (same file) is also worth re-running since it asserts on the same `_tracked_module_graph()` machinery, though it does not name `progress_sources` directly.
