# SCC dossier: `health` (daedalus/health.py)

Base: main @ 851ff43c. Read-only static analysis.

## Step 1 — Measured edges (raw AST probe)

Command: `.venv/Scripts/python.exe C:/Users/Administrator/scc-scratch/probe.py health`

```
### OUTGOING edges FROM health to other SCC members
  -> spine.picker               FUNCTION-LOCAL (deferred)  in _p_picker
       daedalus/health.py:576   from .spine.picker import build_queue
  -> file_bridge                FUNCTION-LOCAL (deferred)  in _p_bridge
       daedalus/health.py:690   from . import file_bridge as fb

### INCOMING edges INTO health from other SCC members
  <- progress                   MODULE-LEVEL               in <module>
       daedalus/progress.py:104   from .health import ASSUMED, INHERITED, MEASURED, Fact, assumed, measured
  <- progress_sources           MODULE-LEVEL               in <module>
       daedalus/progress_sources.py:79   from .health import INHERITED, inherited, measured
  <- status                     MODULE-LEVEL               in <module>
       daedalus/status.py:46   from . import health
```
[MEASURED]

### Verification against source

Read `daedalus/health.py:1-120, 505-745, 1764-1900` and the three citing files' import lines.

- `health.py:576` `from .spine.picker import build_queue` — inside `_p_picker` (line 574), wrapped in a `try/except Exception` (lines 575-579) that returns `unknown(...)` on import failure. Not `TYPE_CHECKING`. Real, reachable, called at line 580 (`queue = build_queue(ctx.repo_root, limit=10)`). CONFIRMED, correctly classed FUNCTION-LOCAL/deferred.
- `health.py:690` `from . import file_bridge as fb` — inside `_p_bridge` (line 688), same try/except-to-`unknown` pattern. `fb` is then used for `fb.INBOX`, `fb.OUTBOX`, `fb.ARCHIVE`, `fb.heartbeat_status`, `fb.unread_reports` (grep confirms 5 distinct attributes). CONFIRMED, real, reachable, correctly deferred.
- `progress.py:104` (incoming) — module-level, six names (`ASSUMED, INHERITED, MEASURED, Fact, assumed, measured`) imported unconditionally under `from __future__ import annotations`. Of the six, `ASSUMED` is imported but never referenced as a runtime value anywhere in `progress.py` (only appears inside docstring prose) — a genuinely dead import, confirmed by grep. The other five (`Fact`, `INHERITED`, `MEASURED`, `assumed`, `measured`) are used as live constructors/values (`Fact(...)` at lines 580, 659; `assumed(...)` at line 538; `measured(...)` at lines 573, 578; `INHERITED`/`MEASURED` as `provenance=` arguments at lines 581, 659) — **not** annotation-only, so `from __future__ import annotations` does not make this import a free cut.
- `progress_sources.py:79` (incoming) — module-level, three names (`INHERITED, inherited, measured`), all live (grep shows `P.Fact` used but that comes via `progress`, not directly from `health`; `inherited`/`measured`/`INHERITED` used directly for provenance-tagged facts throughout the file). CONFIRMED real.
- `status.py:46` (incoming) — module-level `from . import health`, used for `health.assess/verdict/to_payload/render` in `status.main()`. CONFIRMED real (see `status.md` dossier for detail; out of scope here except as an incoming edge).
- No corrections to the probe's classification were needed.

### Dynamic references

`grep -n "importlib.import_module\|__import__"` over `daedalus/health.py`: **0 matches** [MEASURED]. String literals naming other SCC members: `CAPABILITY_MODULES` (health.py:1731-1744) contains dotted strings like `"daedalus.spine.containment"`, `"daedalus.semantic_route"`, `"daedalus.memory.embeddings"` — none of these coincide with the 18 SCC member keys given in the task; they are targets `_p_islands`/`production_importers` grep the *tree* for via regex text search, not `importlib`/`__import__` dynamic imports of this module itself, and they name capability modules outside this SCC. No hidden dynamic coupling to an SCC member found.

## Step 2 — What it actually does

`health.py` is a read-only, non-effectful diagnostic battery (`python -m daedalus.health`): roughly 25 `_p_*` probe functions each inspect one live artifact on disk or over the network (git status, spine ledger opened `read_only=True`, vector-index sqlite in `mode=ro`, file-bridge queues, Ollama hosts via `/api/tags` and a fixed-literal embedding, a remote bench host over SSH/PowerShell, the picker's candidate queue, production-importer wiring) and classify each into exactly one of five closed states (`working/present/degraded/absent/unknown`), never a sixth. Every reported `Fact` is provenance-stamped `MEASURED`/`INHERITED`/`ASSUMED` via a small dataclass vocabulary (`Fact`, `Report`, lines 141-332) that the module defines itself but that has zero SCC-internal dependencies. `assess()` runs the whole battery and `main()` renders it as text or JSON with an exit code from `verdict()`; two probes (`_p_picker`, `_p_bridge`) additionally import a live SCC-member module to exercise it, and `_p_islands`/`production_importers` (lines 1764-1864) separately grep the whole `daedalus/`, `runs/`, `apps/` trees to prove a declared capability module has a real production caller, not just a test.

## Step 3 — Layer

**Verdict: interfaces** (diagnostic/CLI reporting surface) for the module as a whole, but the module is two layers fused, with a clean, already-partly-executed split point.

Justification: `health.py` holds no policy, no leases, no promotion, no effectful writes — its own docstring states this explicitly and backs it with code (`SpineLedger(path, read_only=True)`, sqlite `mode=ro`, no write to the vector index, no vendor CLI invocation). That rules out kernel/spine/twin/runtimes as the *primary* verdict; it is a client-facing reporting tool (`python -m daedalus.health`, `--json`), the same shape as `status.py`. However, the module fuses two genuinely different responsibilities by symbol:
- **foundation-shaped vocabulary** (lines 87-332): the `STATES`/`PROVENANCE` constants, `Fact`, `Report`, and the `measured/inherited/assumed/working/present/degraded/absent/unknown` constructors. This part imports only stdlib plus `.kernel.contracts.observations` (already outside this SCC — `ABSENT/DEGRADED/OBSERVATION_STATES/PRESENT/UNKNOWN/WORKING`, confirmed at lines 87-94) and has **zero** outgoing edges to any SCC member. It is exactly what `progress.py` and `progress_sources.py` actually reach into `health` for.
- **interfaces-shaped probe battery + CLI** (lines 380-1994): `Ctx`, all `_p_*` probes, `assess/verdict/render/to_payload/main`. This part owns both of `health`'s outgoing SCC edges (`_p_picker` -> `spine.picker`, `_p_bridge` -> `file_bridge`) and all the effectful-adjacent read probing (SSH, HTTP, subprocess).

`daedalus/kernel/contracts/observations.py` already exists as the designated "belongs below both consumers" home for the closed-state vocabulary (its own docstring says exactly that) and already owns `OBSERVATION_STATES`; the `Fact`/`Report`/provenance half of `health.py` is the same kind of shared contract that has not yet made the same move.

## Step 4 — Severance, per outgoing edge

### Edge 1: `health -> spine.picker` (function-local, deferred, in `_p_picker`)

- Symbols crossing: exactly 1 — `build_queue`. Grep of `health.py` for `build_queue` shows exactly 1 call site (line 580), inside the single function that imports it.
- Cheapest severance: **(c) event/late binding through an existing registry is not needed — this edge is already the cheapest form it can take.** The import is function-local, wrapped in `try/except Exception -> unknown(...)`, so `health.py` already tolerates `spine.picker` being absent, broken, or moved without failing import of `health` itself. If the SCC-breaking exercise still needs the *governance test's* edge count to drop (per `test_import_scc_hierarchy.py`, which counts function-scope imports too — "it walks the whole AST... had no opinion about when it ran"), the only way to remove this edge for real is **(a) port/protocol extraction**: define a `CandidateQueuePort` Protocol carrying `build_queue(repo_root, *, limit) -> Queue` (with `.candidates`, `.degraded_sources`, `.sources`, `.notes` — the 4 attributes `_p_picker` actually reads), living in `daedalus/kernel/contracts/` alongside the other kernel-owned ports, with `spine.picker` registered as its implementation via `spine/bootstrap.py`'s existing port-factory pattern (the dossier for `status.md` names the same pattern for its own `health` edge).
- Why cheapest: 1 symbol, 1 call site, already deferred and already exception-tolerant — the Protocol extraction is a single-signature change with no behavioral risk, cheaper than merging (`health` and `spine.picker` are unrelated responsibilities — probing vs. queue-building) and cheaper than callback injection (the caller of `_p_picker` is `assess()`'s generic probe registry, which would need a picker-specific parameter threaded through an otherwise uniform `Callable[[Ctx], Report]` probe signature — a Protocol is the natural fit here, not a plumbed argument).

### Edge 2: `health -> file_bridge` (function-local, deferred, in `_p_bridge`)

- Symbols crossing: `fb` module alias, used for 5 distinct attributes (`INBOX`, `OUTBOX`, `ARCHIVE`, `heartbeat_status`, `unread_reports`), all inside `_p_bridge` (grep confirms no other function in `health.py` references `fb.`).
- Cheapest severance: **(a) port/protocol extraction.** Define a `BridgeQueuePort` Protocol carrying the 2 constants (`INBOX`, `OUTBOX`; `ARCHIVE` only if actually read — verify at use site) as attributes/properties plus `heartbeat_status()` and `unread_reports()` as methods. Location: same `daedalus/kernel/contracts/` home as Edge 1's port, or a shared `HealthProbePorts` module if the two probes are extracted together (both are already deferred, both already exception-tolerant, both are single-call-site).
- Why cheapest: 5 symbols but 1 call site and 1 consuming function; already deferred and already `try/except`-guarded, so behavior does not change, only the coupling's shape. Cheaper than a genuine merge (bridge queue logic and health probing are unrelated domains) and cheaper than callback injection for the same reason as Edge 1 — `_p_bridge` is dispatched through `assess()`'s uniform probe registry.

## Step 5 — Tests that pin this

`grep -rn` over `tests/` for `daedalus.health` / `from daedalus import health` / `daedalus\.health\.` / `patch("daedalus.health` [MEASURED]:

- **Files with a direct import of `daedalus.health` or `daedalus.health.X`:** `tests/contracts/test_observation_state_hierarchy.py` (`import daedalus.health as health`, line 10), `tests/test_health_admission.py` (`from daedalus import health`, line 32, 9 further `health.` references), `tests/test_health_surface.py` (`from daedalus import health` + `from daedalus.health import (ABSENT, ASSUMED, DEGRADED, INHERITED, MEASURED, PRESENT, STATES, UNKNOWN, WORKING, Ctx, Fact, ProbeSpec, Report, measured)`, lines 42-45), `tests/test_ikarus_shells.py` (`from daedalus import health, ikarus_os`, line 18, 11 further `health.` references), `tests/test_web_api_health.py` (`from daedalus import health as _health`, line 128, 2 further references). **5 files** [MEASURED].
- `tests/test_health_surface.py` is the module's own dedicated test file and pins by name (representative, not exhaustive — 59 `def test_` functions in the file): `test_there_is_no_skipped_state`, `test_inherited_without_a_source_is_refused`, `test_inherited_without_an_age_is_refused`, `test_assumed_must_name_where_the_assumption_lives`, `test_a_probe_that_raises_reports_unknown`, `test_the_ledger_probe_opens_read_only`, `test_the_ledger_probe_does_not_create_a_missing_ledger`, `test_the_vector_probe_does_not_create_the_index`, `test_a_dead_watcher_over_a_queued_task_is_degraded`, `test_a_degraded_picker_source_is_degraded_even_with_candidates` (line 356 — directly exercises the `_p_picker`/`spine.picker` edge), `test_a_module_with_no_production_caller_is_an_island`, `test_every_import_FORM_counts_as_a_caller`, `test_a_wired_module_is_not_an_island`, `test_the_health_module_does_not_count_as_a_caller`. Moving `Fact`, `Report`, `Ctx`, `ProbeSpec`, `measured`, or the STATES constants off `daedalus.health` breaks the import block at lines 43-45 outright; moving `_p_picker`'s internals changes behavior these named tests assert on directly.
- **Governance/architecture test:** `tests/contracts/test_import_scc_hierarchy.py` names `"daedalus.health"` explicitly in `OLD_CROSS_DOMAIN_COMPONENT`/`REMAINING_CROSS_DOMAIN_COMPONENT`/`CURRENT_CROSS_DOMAIN_COMPONENT` (lines 17-48) and its two tests (`test_observation_contract_breaks_the_next_cross_domain_scc`, `test_intent_ledger_port_breaks_the_selected_cross_domain_scc`) assert an exact edge count (`CENSUS_EDGES = 1630`), an exact SHA-256 digest of the full component partition (`CURRENT_COMPONENTS_SHA256`), `max(map(len, components)) == 18`, and membership of `CURRENT_CROSS_DOMAIN_COMPONENT` (which still contains `"daedalus.health"`) in the component set. This test's own comment (lines 86-92) confirms it counts function-scope/deferred imports too, so **severing either `health` edge (Step 4) or breaking the `progress`/`progress_sources` incoming edges changes this SCC's shape and requires updating `CENSUS_EDGES`, the SHA-256, and the component-membership assertions in the same change** — this is the test most directly "pinning" this SCC's exact structure.
- No `mock.patch("daedalus.health...")` string-target patches found in the files above (`monkeypatch`/direct-attribute patterns are used instead, e.g. `test_health_surface.py`'s helpers construct `Ctx`/`ProbeSpec` directly rather than patching by string path).

Total: **6 test files** reference `daedalus.health` directly or via its governance membership (5 import-based + 1 governance/SCC-shape test), all [MEASURED] by grep; not executed per instructions.

## Pass-through vs. real coupling verdict

**Split verdict, matching the Step 3 split point.** Relative to its two SCC-internal *callers* (`progress`, `progress_sources`), the part of `health.py` they actually use — `Fact`, `Report`, `MEASURED/INHERITED/ASSUMED`, `measured/inherited/assumed` — is a **pure, leaf-ish vocabulary provider**: zero SCC-internal imports of its own, no probing logic, no effects. But `health.py` as a whole is **not** a leaf: its probe battery makes it a real (if lazily-bound) coupling point to `spine.picker` and `file_bridge`, both already deferred and exception-tolerant, which is the correct shape for optional diagnostics but does not remove them as edges the governance test counts. The practical consequence: `progress`/`progress_sources` are coupled to a 1994-line module to get ~40 lines of provenance vocabulary they need, and pay for `health`'s own two SCC edges transitively in the dependency graph (though not in `import`-time failure risk, since those two edges are deferred and caught). Extracting the vocabulary half to `daedalus/kernel/contracts/observations.py` (Step 3) would let `progress`/`progress_sources` depend on a genuine leaf and would visibly separate "who needs the provenance vocabulary" from "who needs the live diagnostic battery" — the two are currently answered by the same import.
