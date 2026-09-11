# SCC dossier: `progress` (daedalus/progress.py)

Base: main @ 851ff43c. Read-only static analysis.

## Step 1 — Measured edges (raw AST probe)

Command: `.venv/Scripts/python.exe C:/Users/Administrator/scc-scratch/probe.py progress`

```
### OUTGOING edges FROM progress to other SCC members
  -> health                     MODULE-LEVEL               in <module>
       daedalus/progress.py:104   from .health import ASSUMED, INHERITED, MEASURED, Fact, assumed, measured
  -> progress_sources           FUNCTION-LOCAL (deferred)  in main
       daedalus/progress.py:764   from . import progress_sources

### INCOMING edges INTO progress from other SCC members
  <- build_exec                 MODULE-LEVEL               in <module>
       daedalus/build_exec.py:80   from . import progress
  <- progress_sources           MODULE-LEVEL               in <module>
       daedalus/progress_sources.py:78   from . import progress as P
```
[MEASURED]

### Verification against source

Read `daedalus/progress.py` in full (782 lines) and `daedalus/progress_sources.py:70-80, 90-780` (576 lines).

- `progress.py:104` `from .health import ASSUMED, INHERITED, MEASURED, Fact, assumed, measured` — top-level, unconditional, under `from __future__ import annotations`. **Correction to a naive "annotations make it free" read:** `Fact` also appears in two type-only positions (`facts: tuple[Fact, ...]` line 509, `facts: list[Fact] = []` line 570) which *would* stringify under the future import — but `Fact`, `INHERITED`, `MEASURED`, `assumed`, `measured` are also used as **live runtime values**: `Fact(label="last observed", ..., provenance=INHERITED)` (lines 580-581), `Fact(label="terminal_fraction", value=frac_value, provenance=MEASURED)` (line 659), `assumed("unit_id", unit_id, ...)` (line 538), `measured(f"last {kind}", ...)` / `measured("bytes observed generating", ...)` (lines 573, 578). Not a free cut. `ASSUMED` itself, however, is imported but **never used anywhere in `progress.py` outside its own import statement** (grep confirms 0 further occurrences besides prose mentions of the word "ASSUMED" inside docstrings at lines 31/44/48, which are not code) — a genuinely dead symbol on this edge, though removing it alone does not sever the edge (5 other symbols remain live).
- `progress.py:764` `from . import progress_sources` — inside `main()` (line 764), guarded by `if args.ledger:` (line 763), a CLI-only flag path. Not `TYPE_CHECKING`. Real and reachable only when `daedalus progress --ledger` is invoked; correctly classed FUNCTION-LOCAL/deferred. Single call site: `progress_sources.open_attempts()` (line 765).
- `build_exec.py:80` (incoming) — module-level `from . import progress`, out of scope for this module's own edges but confirms the SCC membership claim.
- `progress_sources.py:78` (incoming) — module-level `from . import progress as P`, verified in Step 4 below to carry 19 distinct symbols across 48 use sites — the deepest single edge measured in this dossier.
- No corrections needed to the probe's FUNCTION-LOCAL/MODULE-LEVEL classifications.

### Dynamic references

`grep -n "importlib.import_module\|__import__"` over `daedalus/progress.py`: **0 matches** [MEASURED]. String literals naming other SCC members: none found (the only `"daedalus.…"` string literal is `"daedalus.verifier.verify()'s refusal of…"` at line 239, inside a docstring/comment, not a live reference, and `daedalus.verifier` is not an SCC member). No dynamic coupling found.

## Step 2 — What it actually does

`progress.py` defines a closed, provenance-honest vocabulary for the observed state of one dispatched unit of work — ten `EVENT_KINDS` (`QUEUED` through `DONE`) recorded as immutable `ProgressEvent`s in an additive, best-effort JSONL trail (`ProgressLog`, no WAL, no cross-process lock, matching `daedalus/memory/__init__.py`'s durability posture per its own docstring). Producer functions (`open_unit`, `claim_unit`, `heartbeat`, `record_generating`, `record_tool_ran`, `record_gate_verdict`, `record_disk_change`, `record_patch_produced`, `record_done`) append typed events; `record_disk_change` mechanically refuses any `basis` outside `DISK_EVIDENCE_BASES` so a caller cannot construct a DISK_CHANGED event from a model's self-report. Reader functions (`snapshot`, `batch_snapshot`) recompute every fact's age fresh at call time from the immutable event timestamps — deliberately never a cached/memoised verdict — and expose a `UnitProgress`/`BatchProgress` view with a `fraction_hint` explaining why there is no fabricated percent-complete field. `main()` is a thin CLI (`python -m daedalus.progress [unit-id] [--json] [--ledger]`) that reads the default log and, only behind `--ledger`, additionally pulls in `progress_sources.open_attempts()` to merge ledger-backed open-intent snapshots into the same view.

## Step 3 — Layer

**Verdict: foundation**, with one CLI-only interfaces-shaped wart at the exact point the SCC edge to `progress_sources` fires.

Justification: the module's core (everything except `main()`'s `--ledger` branch) is a domain-neutral observability primitive — a typed event log, age computation, and snapshot rendering with zero policy, zero effects beyond an additive local file append, and zero knowledge of what kind of work it is tracking (chat stream, offload, attempt, or anything else — `progress_sources.py`'s docstring is explicit that translating *specific* signals onto this vocabulary is deliberately kept out of `progress.py` itself). Its only SCC-internal dependency for that core is the small provenance vocabulary in `health.py` (Step 4 of `health.md` names this as itself foundation-shaped and not yet physically relocated). The module is imported by `build_exec.py` at module level purely for this primitive role (queue/record progress of a build attempt), which is exactly how a foundation module is consumed. The one exception is `main()`'s `if args.ledger:` branch (lines 763-765): a CLI composition decision — "also show me ledger-backed open attempts" — that has no place in a foundation primitive and is the sole reason `progress.py` needs to know `progress_sources` exists at all. That four-line branch is interfaces-shaped and is a plausible split point: it could move to a thin CLI wrapper (or the existing `daedalus.progress:main` entry named in the CLI registry, see Step 5) without touching any of the producer/reader API `build_exec.py` and others depend on.

## Step 4 — Severance, per outgoing edge

### Edge 1: `progress -> health` (module-level, `ASSUMED, INHERITED, MEASURED, Fact, assumed, measured`)

- Symbols crossing: 6 named, 5 live (`Fact`, `INHERITED`, `MEASURED`, `assumed`, `measured`; `ASSUMED` dead — see Step 1). Call sites: `Fact(...)` × 2 (lines 580, 659), `assumed(...)` × 1 (line 538), `measured(...)` × 2 (lines 573, 578), `INHERITED`/`MEASURED` as bare values × 2 (lines 581, 659).
- Cheapest severance: **(a) port/protocol extraction — but of a data contract, not a behavioral Protocol.** As established in `health.md` Step 3, `Fact`/`Report`/the provenance constants and constructors are already a self-contained, zero-SCC-dependency vocabulary inside `health.py` (lines 141-332), and `daedalus/kernel/contracts/observations.py` already exists as the designated "belongs below both consumers" home for the adjacent `OBSERVATION_STATES` vocabulary (its own docstring says exactly that, and `health.py` itself already imports `ABSENT/DEGRADED/PRESENT/UNKNOWN/WORKING` from there rather than defining them locally). Moving `Fact`, `MEASURED/INHERITED/ASSUMED`, and `measured/inherited/assumed` into that same module, then repointing `progress.py:104` at `.kernel.contracts.observations` instead of `.health`, removes this edge entirely rather than merely deferring it.
- Why cheapest: only 5 live symbols, all pure-data/pure-function with no further SCC dependency of their own (confirmed in `health.md`), and the target module already exists and already owns the sibling vocabulary — this is a pure relocation, not a new abstraction, with a smaller diff than a Protocol class and no merge risk (`health`'s probe battery, which does carry real SCC edges of its own, stays untouched).

### Edge 2: `progress -> progress_sources` (function-local, deferred, in `main`, behind `--ledger`)

- Symbols crossing: 1 — `progress_sources.open_attempts`. Call sites: exactly 1 (line 765), gated behind the `args.ledger` CLI flag.
- Cheapest severance: **(b) callback/parameter injection**, at the CLI composition layer, not inside the library API. `main()` currently owns the decision to merge in ledger-backed snapshots; move that decision to whichever caller assembles the final CLI surface (`tests/test_registry_new_doors.py` shows a `"cli.progress": "daedalus.progress:main"` command registry already exists at line 107 — a natural place to compose `progress.main` with an injected `extra_snapshots: Callable[[], list[UnitProgress]] | None` parameter, defaulting to `None`, with the registry or a thin `if __name__ == "__main__":` wrapper passing `progress_sources.open_attempts` only when it is available). `progress.py`'s public producer/reader API needs no change.
- Why cheapest: 1 symbol, 1 call site, already deferred, already scoped to a single optional CLI flag with no other caller depending on `main()` importing `progress_sources` at all — this is the smallest possible edge to begin with; genuinely already close to a de-facto seam, and formalizing it as an injected callable removes it from the static AST graph the governance test counts (Step 5) without touching the two-way `progress_sources -> progress` edge, which is the load-bearing direction (see verdict below).
- **Do not treat this as the artificial half of the 2-cycle.** The reverse edge (`progress_sources -> progress`, 19 symbols, 48 use sites, module-level — see Step 4 note below) is the real coupling; this edge only exists because `progress.py`'s own CLI convenience feature reaches back for one function. Severing this direction alone still leaves the cycle's substance (`progress_sources` depending on nearly all of `progress`'s public surface) untouched — see the inherited-context judgment below.

### Inherited-context judgment: is the `progress`/`progress_sources` split artificial?

**Not artificial — option (d) genuine merge does not hold.** Measured: `progress_sources.py` references 19 distinct `P.<symbol>` names from `progress` across 48 use sites (`P.ProgressLog`, `P.UnitProgress`, `P.claim_unit`, `P.record_done` ×7, `P.record_tool_ran`, `P.record_gate_verdict`, `P.record_generating`, `P.record_disk_change`, `P.record_patch_produced`, `P.default_log` ×5, `P.snapshot`, `P.heartbeat`, `P.now_iso`, `P.parse_iso`, `P.format_age`, `P.Fact`, `P.QUEUED`, `P.CLAIMED`, `P.DONE`) — nearly the entirety of `progress.py`'s public `__all__` (28 names). That volume alone would argue for merging. But `progress_sources.py`'s own docstring states its reason for existing separately: it is an **adapter layer** translating signals from modules `progress.py` itself does *not* and should not depend on — `daedalus.ikarus_os`, `daedalus.offload`, `daedalus.spine.attempt`, `daedalus.spine.ledger`, `daedalus.file_bridge` — onto `progress`'s vocabulary. Merging the two files would force every current importer of the lightweight `progress` primitive (`build_exec.py`, confirmed module-level in Step 1) to transitively pull in the ledger/bridge/attempt/offload/ikarus_os stack it currently does not need. The split is real: `progress` is the vocabulary + storage primitive (foundation), `progress_sources` is the domain-specific adapter set built on top of nearly all of it (a real, by-design dependent, not a coincidental one). What forces the *cycle* specifically is narrow and already identified above: `progress.main()`'s one CLI convenience call back into `progress_sources.open_attempts()`. Sever Edge 2 (Step 4) and the SCC's `progress <-> progress_sources` mutual edge becomes a one-way `progress_sources -> progress` dependency, which is not a cycle at all.

## Step 5 — Tests that pin this

`grep -rn` over `tests/` for `daedalus.progress` / `from daedalus import progress` / `from daedalus.progress import` / `progress\.` module-attribute patches [MEASURED]:

- **3 files** match `daedalus\.progress\b` or an equivalent import form: `tests/test_loop.py`, `tests/test_registry_new_doors.py`, `tests/contracts/test_import_scc_hierarchy.py`.
  - `tests/test_loop.py` — `test_events_land_in_the_progress_log_under_the_candidate_id` (line 482) does `from daedalus.progress import ProgressLog` and sets `d._progress_log = log` (line 487). Moving/renaming `ProgressLog` off `daedalus.progress` breaks this test directly.
  - `tests/test_registry_new_doors.py` — line 107, `"cli.progress": "daedalus.progress:main"` inside what its own comment (lines 36-39) describes as a CLI command registry test that specifically checks `--ledger`'s composition path got a registry row instead of silently returning no verdict. This is a **string-target pin** on the exact module path `daedalus.progress:main` (equivalent in effect to a `mock.patch` string target) — moving `main` off `daedalus.progress` or changing its callable name breaks this registry row.
  - `tests/contracts/test_import_scc_hierarchy.py` — `"daedalus.progress"` is a named member of `OLD_CROSS_DOMAIN_COMPONENT`/`REMAINING_CROSS_DOMAIN_COMPONENT`/`CURRENT_CROSS_DOMAIN_COMPONENT` (lines 17-48); its two tests assert an exact `CENSUS_EDGES = 1630`, a SHA-256 digest over the whole component partition, and membership of the still-18-member `CURRENT_CROSS_DOMAIN_COMPONENT` (containing `"daedalus.progress"`) in the measured component set. Any of the Step 4 severances change this SCC's edge count and component shape and require updating this test's constants in the same change.
- **Module-attribute pins (not string `mock.patch`, but functionally equivalent — `monkeypatch.setattr` directly on the imported module object) on `progress._DEFAULT_LOG`:**
  - `tests/test_loop_lease.py` (line 283 `from daedalus import budget, core, progress`; line 290-292 `monkeypatch.setattr(progress, "_DEFAULT_LOG", progress.ProgressLog(tmp_path / "progress.jsonl"))`).
  - `tests/test_bridge_restart.py` (line 430, same import; line 443-445, identical `monkeypatch.setattr(progress, "_DEFAULT_LOG", ...)` pattern). Both pin the private module-global name `_DEFAULT_LOG` (confirmed present at `progress.py:323`) and the `ProgressLog` constructor signature; renaming `_DEFAULT_LOG` or changing how `default_log()`/`reset_default_log()` reach it breaks both tests silently (an `AttributeError` from `monkeypatch.setattr`, not a normal assertion failure).
- **Inventory/coverage test:** `tests/test_envelope_coverage.py` line 205 lists the literal string `"daedalus/progress.py"` inside a `_CALIBRATION[CO_LOCATED]` tuple (a composition-root producer-scan calibration list, per the surrounding comment about `file_bridge.py`'s recent removal from the same list). This pins `progress.py`'s *file path* as a co-located envelope producer, not a specific symbol — moving the file would require updating this tuple.

Total: **5 test files** reference `daedalus.progress` in a way that would break under symbol/path movement (`test_loop.py`, `test_registry_new_doors.py`, `test_import_scc_hierarchy.py`, `test_loop_lease.py`, `test_bridge_restart.py`), plus 1 file-path-only pin (`test_envelope_coverage.py`). [MEASURED] by grep and line-read; not executed per instructions.

## Pass-through vs. real coupling verdict

**`progress` is a real coupling point on its `health` edge and a near-trivial one on its `progress_sources` edge — asymmetric, matching Step 4.** It is not a pure pass-through of `health`: it uses `Fact`/`measured`/`assumed`/`INHERITED`/`MEASURED` as load-bearing constructors inside its own `UnitProgress`/`BatchProgress` rendering (Step 1), and that usage is exactly why `health.md` identifies `progress` as one of the two modules that only need `health`'s foundation-shaped half, never its probe battery. Its edge to `progress_sources`, in contrast, is genuinely thin (1 symbol, 1 gated call site) and exists solely to serve `main()`'s `--ledger` convenience feature — the substantive direction of that relationship runs the other way (`progress_sources` depending on 19 of `progress`'s symbols), which this dossier's inherited-context judgment (Step 4) confirms is a real, intentional adapter-over-primitive dependency, not an artificial split.
