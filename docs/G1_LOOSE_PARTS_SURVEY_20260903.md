# Loose parts of Daedalus — what is actually unwired at HEAD

**Revision bound:** `8eaa5adf87095b77811c8545c04124350bf0e9e9`
(`packet/g1-pkg-split3`, 2026-09-03).

**Classification:** `ALIGNED` — read-only inventory. No `daedalus/` source file
was modified and nothing was staged by this lane.

**Concurrency caveat — the tree moved underneath this survey.** At the start the
checkout was on `packet/g1-pkg-split2` with 130 dirty files. Mid-survey another
lane committed and merged that packet (`d6114b83`, `aac730d6`), added `8eaa5adf`,
and moved the checkout to `packet/g1-pkg-split3`. Four files were dirty at the
close: `daedalus/providers/hermes_agent.py` (deleted, staged),
`docs/architecture/shim-registry.json`, `tests/contracts/test_import_scc_hierarchy.py`,
`tests/test_architecture_boundaries.py`. That lane is deleting shims this survey
also names, so rows marked *(being retired)* may already be gone.

**Provenance rule:** `[MEASURED]` = run by this lane at the revision above.
`[ASSUMED]` = derived by reading, not by executing. No timing numbers appear —
another lane was writing concurrently and every wall-clock figure would be noise.

**Instrument:** the repository's own reachability engine
`daedalus/mapping/reach.py`, called read-only as `analyse(Path('.'))`, plus an
independent AST import-graph walk written for this survey to cross-examine it.

---

## 0. Read this first — the instrument under-reports reachability

The engine is the thing that decides what is loose, and
`docs/GATE0_INTEGRATION_GAPS_20260825.md` records that its output feeds
`docs/FEATURE_INVENTORY.json`, which feeds the self-improvement picker: *the
thing that chooses what gets worked on next.* At this revision **17 of its 52 flagged rows are misclassified**, and 8 of those
are wrong in the direction that matters: wired, production-called code accused of
being loose. The other 9 are milder — 3 attempt-chain modules filed as islands
when their parent is registry-dispatched, and 6 eval-corpus files that are
unreachable by design.

Two distinct defects, both `[MEASURED]`.

### Defect 1 — the lazy-facade idiom is invisible

`daedalus/mapping/reach.py:53-57` states the engine follows
`importlib.import_module("pkg.mod")` only where the target is a **literal**.
Ten modules under `daedalus/` use a lazy `__getattr__` facade whose target is
computed, so every edge through them is dropped.

The worst case is the flagship product path. `daedalus/orchestration/__init__.py:17`
resolves its single export with an f-string:

```python
value = import_module(f"{__name__}.missions").run_mission
```

The edge dies there, `missions/__init__.py` degrades to `shim`, and the whole
Ikarus mission subsystem below it is reported as islands. It is not loose:

```text
>>> import daedalus.orchestration as o; o.run_mission.__module__
'daedalus.orchestration.missions.service'
```

with live production callers at `daedalus/core.py:1245`,
`daedalus/build_exec.py:1449` and `daedalus/interfaces/cli/entry.py:137`
`[MEASURED]`.

Note the engine is *honest* about this class of gap — it marks the facade a
`shim` rather than accusing it — but the consequence still lands on the modules
underneath, which are accused.

Two facades carry **literal** name→module tables that a static reader could
follow today without any new machinery: `_EXPORTS` in `daedalus/__init__.py:11`
and `_LAZY_MODULES` in `daedalus/kernel/__init__.py:152`. Reading `_LAZY_MODULES`
alone restores the edges into the kernel attempt chain — `attempts`,
`attempt_clock`, `attempt_contracts`, `attempt_spine_reader` `[MEASURED]` — with
no new machinery beyond parsing a frozenset of string constants.

### Defect 2 — a package `__init__` with five importers is called an orphan

`daedalus/resources/__init__.py` is classified `orphan` with the reason
*"on disk; imports nothing and nothing imports it"*. That reason is false. The
module has a 138-line body and five direct production importers `[MEASURED]`:

| importer |
| --- |
| `daedalus/config.py:31` |
| `daedalus/router.py:6` |
| `daedalus/orchestration/categories.py:23` |
| `daedalus/orchestration/gui_catalogue.py:123` |
| `daedalus/runtimes/providers/personas.py:9` |

Every one of them spells it `from .resources import ...` / `from daedalus.resources import ...`,
i.e. a package imported by directory name. The engine appears not to bind that
form back to the package's `__init__.py` row `[ASSUMED]` — this survey did not
isolate the exact line, and that isolation is the first task of the packet
proposed in §3.

### The census, and what it becomes after correction

Scoped to `daedalus/`, at the revision above `[MEASURED]`:

| class | engine says | after this survey | why it moves |
| --- | --- | --- | --- |
| reachable | 319 | 327 | +8 W rows (§1) |
| entry | 61 | 61 | unchanged |
| island | 33 | 18 | −6 W, −3 R, −6 F |
| unknown | 11 | 14 | +3 R rows that depend on a registry-dispatched module |
| shim | 7 | 6 | −1 W row |
| orphan | 1 | 0 | the class was one false row |
| *fixture* | — | 6 | new by-design class (§1 F) |

Both columns total 432 modules. The `unknown` count *rises*: three attempt-chain
modules currently called islands are reached from `attempt_ledger`, which is
itself registry-dispatched, so the honest class for them is the same "a static
walk cannot decide this" that their parent already carries.

Tree-wide the engine reports 302 entry / 577 reachable / 167 island / 749 test,
with entry kinds `main_guard=298`, `cli=95`, `module_main=17`, `bus=7`,
`http=5`, `script=2`, and `broken_entries` empty `[MEASURED]`.

---

## 1. Verdicts on all 52 flagged rows

Four verdicts. **W** = wired, engine wrong. **R** = registry-wired, engine
correctly cautious. **F** = unreachable by design. **L** = genuinely loose.

### W — wired, the engine is wrong (8 rows)

| module | proof |
| --- | --- |
| `daedalus/resources/__init__.py` | 5 production importers, table in §0 |
| `daedalus/orchestration/missions/__init__.py` | `orchestration.__getattr__` → `run_mission` |
| `daedalus/orchestration/missions/service.py` | defines `run_mission`; `__module__` verified at runtime |
| `daedalus/orchestration/missions/one_shot.py` | imported by `missions/service.py:22` |
| `daedalus/orchestration/missions/supervisor_projection.py` | imported by `missions/service.py:22` |
| `daedalus/orchestration/ikarus_oneshot.py` | imported by `missions/one_shot.py:20` |
| `daedalus/orchestration/ikarus_effect_bridge.py` | imported by `missions/one_shot.py:15` |
| `daedalus/orchestration/ikarus_tool_scope.py` | imported by `ikarus_effect_bridge.py:22` |

These need **no integration work**. They need the map fixed.

### R — registry-wired by ID; `unknown` is the correct answer (5 rows)

`daedalus/spine/effect_boundary.py:347-381` registers the attempt chain as
canonical `EntrypointSpec` rows — `id="kernel.attempt.begin"`,
`target="daedalus.kernel.attempt_ledger:AttemptLedger.begin"`,
`wiring=Wiring.LOCAL_GUARDS` — dispatched by ID, not by import `[MEASURED]`.

| module | reached via |
| --- | --- |
| `daedalus/kernel/attempt_ledger.py` | `EntrypointSpec` target, effect boundary |
| `daedalus/kernel/attempt_workspace.py` | `EntrypointSpec` target, effect boundary |
| `daedalus/kernel/attempt_clock.py` | `attempt_ledger.py` |
| `daedalus/kernel/attempt_contracts.py` | `attempt_ledger.py`, `attempt_spine_reader.py`, `attempt_workspace.py` |
| `daedalus/kernel/attempt_spine_reader.py` | `attempt_ledger.py` |

A static walk cannot prove a registry dispatch and should not pretend to. These
rows are correct as `unknown`; they are listed so nobody mistakes them for work.

### F — unreachable by design (6 rows)

`daedalus/eval/fixtures/sunny_garden/**` — `__init__.py` ×3, `garden/care.py`,
`garden/cli.py`, `garden/plants.py`. This is the eval corpus: a small fake
project the evaluator operates *on*. Reaching it from an entry point would be
the bug. It should be excluded from the island class, not wired.

### L — genuinely loose (33 rows)

No production consumer at this revision. Grouped by the cluster that would have
to be wired together, largest first.

| # | cluster | modules | test files | what it is |
| --- | --- | --- | --- | --- |
| L1 | `kernel/` promotion + authorization | `promotion_execution`, `promotion_execution_reader`, `promotion_fingerprint`, `runtime_authorization_issuer`, `effect_recovery`, `contracts/security`, `contracts/campaigns` *(shim)*, `contracts/registry` *(shim)*, `attempts` *(shim)* | 9 | sealed-promotion and runtime-authorization contracts. Invariant 5 machinery, built, not called |
| L2 | `twin/extractors/` | `__init__` *(shim)*, `contracts`, `registry`, `root_file_adapter`, `tree_sitter_adapter` | 5 | four-plane extraction registry — the master plan's central prior (§5), with no production caller |
| L3 | `gates/repository/` artifact admission | `write_artifact_admission`, `write_artifact_cas`, `write_artifact_verifier`, `write_evidence` | 4 | ~11 test files, 4 CI workflows, mutation harnesses. Consumed only by its own siblings |
| L4 | `runtimes/` recovery + observation | `faults`, `recovery`, `provider/observation_store`, `provider/observation_store_contract` | 4 | fault/recovery and provider-observation persistence |
| L5 | `kairos/` evolution | `archive`, `evolution`, `shadow_shell`, + `eval/provenance` | 4 | Ariadne-shaped evolution machinery; `eval/provenance` has exactly one importer, `kairos/evolution.py` |
| L6 | `observe/` | `__init__` *(shim)*, `shape` | 2 | observation shape contract |
| L7 | singletons | `gates/fault_matrix`, `orchestration/ikarus_runtime_events`, `integrations/hermes/conformance`, `providers/personas` *(shim, being retired)*, `structcore/artifacts` | 5 | see note below |

Notes on the singletons:

- `daedalus/gates/fault_matrix.py` — `python -m daedalus.gates` dispatches only
  to `report.build_gate0_report`; the fault matrix is not on that path
  `[MEASURED]`.
- `daedalus/structcore/artifacts.py` — imported by `daedalus/eval/graph_delta.py`
  inside a swallowed `ImportError`, which the engine correctly refuses to count
  as proof anything runs it.
- `daedalus/providers/personas.py` — a shim over the real
  `daedalus/runtimes/providers/personas.py`. The concurrent lane is deleting
  this class of shim.

**L3 is the sharpest illustration of the incoherence.** Four modules, eleven
test files, four dedicated CI workflows and a mutation-scoring harness, all
proving the behaviour of a chain that nothing in the product calls. The tests
are not wrong; the chain simply has no consumer yet.

**Correction recorded:** an earlier pass of this survey concluded the whole
17-module `gates/repository/` family was unwired. That was wrong. Six of its
modules *are* consumed in production — `head_revision` by
`daedalus/chip_design/cli.py:22`, `tree` by
`daedalus/gates/python_target_structure.py:16`, and `write_classification`,
`write_evidence_materialization`, `write_inventory_v2`, `write_effect_lease`,
`write_evidence_origin` by the `scripts/declare_write_surfaces.py` entry point.
Only the artifact-admission chain is loose.

---

## 2. What is *not* wrong

Recorded so later lanes do not re-investigate:

- **`apps/web/src-tauri/backend/_internal/daedalus/` is not a second kernel.**
  It is gitignored Tauri build output — `git ls-files` returns 0 tracked files
  and `git check-ignore` names `apps/web/src-tauri/.gitignore:2` `[MEASURED]`.
  A tree-wide reach run reports its 19 modules as shims; they are copies and
  must be excluded from any census.
- **`[project.scripts]` is honest.** `broken_entries` is empty — both declared
  console scripts (`daedalus`, `daedalus-chip`) resolve `[MEASURED]`.
- **The package split that landed mid-survey is green.**
  `tests/contracts/test_no_dangling_daedalus_imports.py` and
  `tests/contracts/test_import_scc_hierarchy.py`: 6 passed. `tests/gates` and
  `tests/kernel`: full run, no failures `[MEASURED]`.

---

## 3. Proposed packet order

Not started. Recorded as `BACKLOG` under plan §10; each is one Work Packet with
one primary acceptance claim.

1. **G1-MAP-01 — make the map true.** Teach `reach.py` the two literal facade
   tables (`_EXPORTS`, `_LAZY_MODULES`), the `orchestration/__init__.py`
   single-export shape, and fix the package-`__init__` binding behind Defect 2.
   Add `eval/fixtures/**` to the by-design exclusion. Acceptance: the 13 W/R
   rows in §1 stop being reported as loose, the 33 L rows still are, and
   `docs/FEATURE_INVENTORY.json` is re-baselined. This packet must land first —
   every later packet is aimed by its output, and the picker is reading it.
2. **G1-WIRE-L3 — the artifact-admission chain.** Smallest genuinely-loose
   cluster with the heaviest existing evidence, so the wiring is the only new
   risk. Give it its production consumer or record the decision that it stays a
   contract library and retire the accusation deliberately.
3. **G1-WIRE-L2 — `twin/extractors/`.** Highest plan value (§5, the central
   prior). Needs a design decision, not just a wire: who owns extraction, and
   at which revision boundary.
4. **G1-WIRE-L1 — kernel promotion/authorization.** Touches invariant 5 and the
   sealed promotion path, so it needs the full adversarial matrix of §10 step 6.
   Do not start it on an unreviewed parent.

L4–L7 are unranked until G1-MAP-01 confirms them.

A note on ordering that the measurement, not preference, produced: fixing the
instrument is not overhead before the real work. At this revision a quarter of
the accusations are false, and three of the four largest clusters would have
been approached with a wrong prior about what already calls them.

---

`Iron Plan: ALIGNED`
`Iron Gate: 1`
`Evidence: daedalus.mapping.reach.analyse at 8eaa5adf (census, 52 flagged rows);
independent AST import-graph cross-examination (production vs test importers per
row); runtime resolution of daedalus.orchestration.run_mission; git ls-files /
check-ignore on apps/web/src-tauri/backend/_internal; tests/contracts import
contracts 6 passed; tests/gates + tests/kernel full run, no failures. No
daedalus/ source file modified.`
