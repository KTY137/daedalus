# Loose parts of Daedalus — what is actually unwired at HEAD

**Revision bound:** `17bfb1c90f192d575b0e2e4ad27f57b7e84c8074`
(`packet/g1-pkg-split3`, 2026-09-03).

**Classification:** `ALIGNED` — read-only inventory. No `daedalus/` source file
was modified and nothing was staged by this lane.

**Every SHA in this document was re-pinned on 2026-09-03** after an
owner-authorised history rewrite purged a private note from every commit. The
rewrite changed 1088 commit identities and left 78992 unchanged. Each hex
reference below was translated mechanically through
`docs/recovery/purge-20260903/sha-map.tsv`, then checked three ways: that each
names the commit the surrounding prose describes, that each still resolves, and
that each is **reachable from a published ref**. Not matched by subject line,
which is the same same-looking-identity inference that cost this branch a commit
that day.

The reachability check is the one worth naming, because the obvious check is
too weak. `git cat-file -e` and `git log <sha>` both succeed for an object that
exists locally but is referenced by nothing — it survives until the next `gc`
and then the pin breaks in a fresh clone, silently and later. Two pins in
another lane's document were exactly that. `git merge-base --is-ancestor <sha>
<ref>` is the check that distinguishes them. Every reference here is reachable
from `origin/main`, except `ce8273bf` and `37ca6080`, which are commits of this
branch and are reachable from `origin/packet/g1-map-02`.

One reference is deliberately untranslated: `fe634b58`, the head the
discrimination receipt is bound to, is not in the map because it was not
rewritten, so it still means what it meant.

**Concurrency caveat — the tree moved underneath this survey.** At the start the
checkout was on `packet/g1-pkg-split2` with 130 dirty files. Mid-survey another
lane committed and merged that packet (`1f35c173`, `cd160c9f`), added `17bfb1c9`,
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
| `daedalus/orchestration/ikarus/oneshot.py` | imported by `missions/one_shot.py:20` |
| `daedalus/orchestration/ikarus/effect_bridge.py` | imported by `missions/one_shot.py:15` |
| `daedalus/orchestration/ikarus/tool_scope.py` | imported by `ikarus_effect_bridge.py:22` |

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
2. ~~**G1-WIRE-L3 — the artifact-admission chain.**~~ **WITHDRAWN — see §6.**
   `G0-GR-24` owns it and states that it "does not discharge any canonical
   repository-write finding". Wiring it would discharge one.
3. ~~**G1-WIRE-L2 — `twin/extractors/`.**~~ **WITHDRAWN — see §4.1.** Not loose:
   reached from `scripts/fourfold_repo_probe.py`.
4. ~~**G1-WIRE-L1 — kernel promotion/authorization.**~~ **WITHDRAWN — see §6.**
   Every module in it is owned by a packet that declines to wire it.

**All three wiring packets are withdrawn.** §6 records why, and what the real
bottleneck is instead. The ranking above is kept rather than deleted because the
reasoning that produced it was wrong in a way worth being able to re-read: it
mistook a correctly-executed bounded packet for neglected work, twice.

A note on ordering that the measurement, not preference, produced: fixing the
instrument is not overhead before the real work. At this revision a quarter of
the accusations are false, and three of the four largest clusters would have
been approached with a wrong prior about what already calls them.

---

## 5. G1-MAP-02 — the gate could not be read at all

§4.4 left three things undone. Closing the first two turned up a larger
problem: `daedalus map --check` **failed**, and 91% of what it said was not
about this project `[MEASURED 2026-09-03]`.

| origin of drift row | rows |
| --- | --- |
| `runs/` — run artifacts | 1082 |
| `apps/web/src-tauri/backend/_internal/` — gitignored Tauri build output | 148 |
| `vault/` — the Obsidian knowledge vault | 11 |
| **`daedalus/` — the actual signal** | **87** |
| other | 20 |
| | **1348** |

### 5.1 A declared scope with no reader

This is a known regression, stated in the gate's own prose
(`daedalus/mapping/drift.py`): *"`DAEDALUS_IGNORE` and `.daedalusignore` narrow
the structural index. Since the gate now reads the tree through `reach`, which
walks the filesystem itself, they cannot narrow what the gate sees."* The
declaration was already correct — `.daedalusignore` ignores `runs/` and
`vault/` — and the engine that took over the walking never asked.

The fix follows the doctrine already written in
`daedalus/structcore/ignore.py:ProjectScope`: a file outside the project is
**shell** — *"still indexed and still resolvable as an import target, so edges
pointing at it stay true, but withheld from every metric"*. So `reach` keeps
walking everything and only marks the periphery; `drift` and `inventory` do the
withholding. The walk is deliberately **not** narrowed: dropping files would
make an import into a vendored tree resolve to nothing, turning a true edge into
a missing one — the silent direction of error.

### 5.2 An existing test refuted the first implementation

The first cut marked shell from `project_scope()`, which folds in
`DAEDALUS_IGNORE` and `DAEDALUS_CENTER`. A pre-existing test —
`test_the_gate_does_not_read_the_tree_through_the_ignore_configuration` —
failed, and it was right: a scope an environment variable can widen is a gate
anyone can silence without leaving a diff. Marking now reads the committed
`.daedalusignore` **only**. Pinned by
`tests/test_mapping_scope.py::test_the_environment_cannot_make_a_module_periphery`.

### 5.3 Result

| | before | after |
| --- | --- | --- |
| `daedalus map --check` | **FAILED**, 1348 rows | **OK**, no drift |
| islands | 181 | 60 |
| shims | 11 | 4 |
| unknown | 61 | 27 |
| modules ranked | 1155 | 672 |
| periphery withheld | — | 493 (reported, not hidden) |

Two further leaks were closed on the way: `index_extra_edges` bypassed the
filter, so all four `ENGINE DISAGREEMENT` rows were a Tauri build copy
disagreeing with itself (now 1, and real); and `daedalus/eval/fixtures/` — §4.4's
by-design fixture class — is now declared periphery in `.daedalusignore` rather
than special-cased in code, which is what retired the six `NEW ISLAND` rows.

`docs/architecture-state.json` is internally consistent again (672 modules,
672 rows) — the off-by-one class that
`docs/GATE0_INTEGRATION_GAPS_20260825.md` §0 recorded as invalidating every
snapshot-derived number.

### 5.4 The picker was ranking work against files that are not this project

`docs/FEATURE_INVENTORY.json` feeds the self-improvement picker's two highest
bands. It reported 181 islands; 121 of them were run artifacts and gitignored
build output. The inventory now applies the same withholding, and was
regenerated: 60 islands, 483 withheld.

Regenerating it surfaced separate rot: **25 hand-written annotations no longer
matched any module**, orphaned by the recent flatten/package packets, which
moved the code and left its rationale behind. 22 were remapped to their verified
successors (each resolved against the tree and, where ambiguous, against the
rename in Git history — `daedalus/cli.py -> interfaces/cli/entry.py` at `R095`,
`daedalus/token_policy.py` deleted at `824099fb` after its owner appeared at
`b1cf896d`). Three were dropped: `ikarus.py`, `mission_control.py` and
`decompose.py` were re-export facades whose own note read *"keep until callers
migrate"*, and `7838ce3b` retired them once every caller named its owner. A
collision guard refused the whole write until `decompose.py` was resolved that
way rather than overwriting the real `kairos/decompose.py` annotation.

### 5.5 Still not done

- ~~**The `center:` directive in `.daedalusignore` is inert.**~~ **CLOSED by
  G1-MAP-03** (`37ca6080`). Nothing parsed it: `project_scope` read its center
  from an explicit argument or `DAEDALUS_CENTER` only, and `_parse_line` turned
  the directive into an anchored ignore pattern matching no path. The
  precedence the file's comment claims — explicit argument, then
  `DAEDALUS_CENTER`, then the directive — now holds, and the center is part of
  the scope fingerprint so two scopes that see different trees cannot share a
  cache key.

  What it had been costing is in `structcore/index.py`'s own comment: shell
  files are withheld from every metric, which "costs ~2% (the per-file parse)
  and saves ~96% (clone passes)". Every ordinary caller builds with
  `center=None`, so the whole repository was the core and every hotspot
  ranking, clone pass and slice expansion ranged over vendored trees.

  **Reach was deliberately left out of it.** It passes an explicit empty
  center — the strongest tier — so the island census still covers the whole
  repository. Honouring the declaration there would make `scripts/` periphery,
  and `scripts/fourfold_repo_probe.py` is exactly the operator entry point
  whose absence manufactured the false island in §4.1. What is periphery for a
  hotspot ranking is not automatically periphery for *"can anything reach this
  at all"*.

  One true finding fell out, reported and not merged:
  `tools/gate_discrimination.py:104` does `import system_check as sc` after
  inserting `TOOLS_DIR` into `sys.path`. With `tools` declared a center root
  structcore resolves that edge; the reachability walk does not follow
  sys.path-relative sibling imports, so the gate names one more genuine
  `ENGINE DISAGREEMENT`. The edge is real — the `sys.path` insert is two lines
  above it — and making the two engines agree is its own question.
- The remaining readable gate findings are now worth acting on: `NEW UNKNOWN`
  (2), `ENGINE DISAGREEMENT` (1), `NEW DARK SWITCH` (3), `DOC DRIFT` (16),
  `TEST ONLY` (22).

---

## 6. The answer to the original question: almost nothing here is loose by accident

With the map finally true (§4, §5), the honest loose list under `daedalus/` is
**33 modules**, periphery excluded `[MEASURED 2026-09-03]`. This section asks the
question the survey should have asked first: *why* is each one unconsumed?

Every one of the 33 was checked against `docs/work-packets/`, `docs/adrs/` and
the architecture narrative. The result:

| | count |
| --- | --- |
| owned by a named Work Packet that **explicitly declines to wire it** | 31 |
| documented as a precondition for later-gate work | 1 |
| named by an open, Gate-wide obligation carried in other packets | 1 |
| **genuinely orphaned, explicable by nothing** | **0** |

### 6.1 They say so themselves

These are not inferences. The packets state the boundary in their own prose:

- `G0-GR-24` (artifact admission, 4 modules): *"Admission is not origin
  authentication or release authority... It does not update the evidence index,
  replace the legacy release contract, or issue `Gate0ReleaseReceipt`. **It does
  not discharge any canonical repository-write finding.** Issue #194 remains
  open."*
- `G0-RTC-06Z` (provider observation store, 2 modules): *"**It does not register
  those entrypoints**, verify or begin an Effect Lease, open SQLite, initialize
  a store, bind a row, migrate the broker, recover an execution, merge, promote
  or change a Gate state."*
- `G1-RUNTIME-02` (runtime authorization issuer): *"This slice does not migrate
  provider registries, open inventory-only rows, alter persistence, add a
  runtime... merge, promote, or close Gate 1."*
- `daedalus/kairos/shadow_shell.py` is an Ariadne precondition recorded in
  `docs/adrs/015-ariadne-preconditions.md` — later-gate by the plan's own order.
- `daedalus/kernel/promotion_fingerprint.py` was the one module no packet names.
  It is not orphaned either: it is the tool for *Gate-wide Primary-Checkout
  mutation exclusion*, which `G0-GR-24` lists under **"remain separate dependent
  work"** and `G0-PRM-19` lists among its builder tests. Its own creating commit
  says it plainly — *"main asked for a checkout fingerprint that nothing on main
  could produce"*.

### 6.2 What that means for "integrate the loose parts"

Most of this must **not** be integrated, and not by me. Wiring `G0-GR-24`'s
admission chain would discharge a finding the packet says it does not discharge;
wiring `G0-RTC-06Z` would register entrypoints it says it does not register.
Master plan §10 forbids starting a dependent build phase on an unreviewed
parent, and §13 lists *"dependent feature packets built on an unreviewed or red
parent packet"* as a forbidden direction. A lane that "tidied up the islands"
would be breaking the build discipline, not repairing it.

The incoherence is real, but it is not the shape it looks like from the census.
Daedalus lands **bounded, tested, deliberately unconsumed contract boundaries**,
and the packets that would consume them are blocked on a small, named set:

| blocker | named in | kind |
| --- | --- | --- |
| issue #194 (repository-write findings) | `G0-GR-24` | open issue |
| issue #189 (provider-observation persistence paths) | `G0-GR-24`, `G0-RTC-06R` | open issue |
| Docker sandbox evidence | `G0-GR-24`, `G0-RTC-06R` | **open owner position** — master plan Revision 8 records "Docker host procurement stays an open owner position" |
| complete fault injection | `G0-GR-24`, Revision 8 | evidence obligation |
| Gate-wide Primary-Checkout mutation exclusion | `G0-GR-24`, `G0-PRM-19` | open obligation |
| live runtime receipts | Revision 8 | evidence obligation |

So the bottleneck is not code anyone can write. Four of the six are evidence or
infrastructure obligations, and one is an owner decision the plan itself records
as open. The count of unconsumed boundaries is the *cost* of that blockage, and
it grows with every additive packet that lands while the blockers stand.

### 6.3 The one thing this survey got wrong twice

§3 ranked `G1-WIRE-L3` (the admission chain) as the best next work, on the
grounds that it was "the sharpest illustration of the incoherence" — four
modules, eleven test files, four CI workflows, no consumer. That reading was
wrong for the second time in this document: the first time because the survey
had not read `scripts/` (§4.1), and this time because it had not read the
packet. The evidence density that made it look like neglected work is what a
correctly-executed bounded packet looks like from the outside.

`G1-WIRE-L3` and `G1-WIRE-L1` are withdrawn. Neither is available as ordinary
work; both are downstream of the table above.

---

## 7. The same defect, in the other instrument

§0 found the reachability engine blind to an indirection this codebase uses
everywhere. The switch inventory turned out to have the identical problem, and
it was hiding something worse than an island.

`daedalus/mapping/switches.py` resolves `os.environ.get(SOME_CONST)`. It could
not resolve the shape the most important switches actually use — a helper that
takes the variable name as a parameter:

```python
ENV_CEILING = "DAEDALUS_BUDGET_USD"

def _env_float(name, default):
    raw = os.environ.get(name)      # a PARAMETER; no literal is ever here
    ...

return _env_float(ENV_CEILING, DEFAULT_CEILING_USD)
```

So the gate reported `DAEDALUS_BUDGET_USD` and `DAEDALUS_BUDGET_MAX_CALLS` as
**"documented, but no code reads it any more"** — both sitting in
`.env.example` under *"Spend ceiling for one activation period"*. That is the
`$5.00` period ceiling of master plan §4.1 and Revisions 9 and 10, read at
`daedalus/kernel/policy/ledger.py:657`. The instrument was telling an operator
that the monetary ceiling is dead configuration `[MEASURED 2026-09-03]`.

A function is now an env-reader when it hands one of its **own** parameters to
`os.environ` — structural, never by name, so a formatter that accepts something
called `name` is not one. The first argument at each call site goes through the
existing constant resolver, which already follows imports; that is what recovers
`DAEDALUS_BUDGET_MAX_CALLS` from `pricing.py`. The read is attributed to the
call site, because that is where the variable is chosen. An unresolvable
argument stays a dynamic read: this widens what can be *proven*, never what is
guessed.

**Seeing further immediately found three switches never reported at all**, and
one is the point: `DAEDALUS_BUDGET_PERIOD_CEILING_ENABLED` turns the period USD
ceiling **off**, and it was invisible to the inventory whose job is listing
switches. A switch that disables the monetary ceiling should not be able to hide
from that list. The other two are the embedding wall-clock ceilings in
`semantic_route`.

Two further findings on the way, both the same "two answers to one question"
shape as §5.2:

- `_PLATFORM_ENV` — whose comment says OS variables must not "bury the ones
  that are" Daedalus switches — held `USERNAME` and `USERPROFILE` but not
  `USER`, `USERDOMAIN` or `PROCESSOR_IDENTIFIER`. Documenting them instead of
  excluding them merely flips a `code-only` row into a `doc-only` one, because
  no Daedalus module owns the name.
- `_augment_documented` was passed every read name while `_drift` filtered
  `_PLATFORM_ENV` out, so the two disagreed about what "read" means and a bare
  doc mention of an OS variable became a phantom *"documented, but no code reads
  it any more"*.

### 7.1 Result

| | before | after |
| --- | --- | --- |
| doc drift, total | 47 | 30 |
| read but undocumented (`code-only`) | 14 | **0** |
| name mismatches | 1 | **0** |
| dark switches | 5 | **0** |

`docs/ENV_SWITCHES.md` documents every remaining `DAEDALUS_*` lever from its
call site. The 30 that survive are all `doc-only` and all in `docs/` —
amendment proposals, work packets, recovery kits and plans naming variables no
code reads. **None is operator-facing** `[MEASURED]`: nothing in `README.md`,
`.env.example` or the desktop/go-live pages names a switch that does not exist.
Editing the historical records to close the rest would be rewriting evidence,
which §16 forbids, so that number is expected to stay non-zero.

### 7.2 What the day actually found

Five distinct blind spots in the two instruments that decide what Daedalus
knows about itself, all the same shape — a scanner that cannot read an
indirection the codebase uses everywhere — and each one producing a confident,
false, actionable-looking statement:

1. a lazy `__getattr__` façade → the flagship mission path reported as islands;
2. a package `__init__` bound to a name no import writes → a module with five
   callers called an orphan;
3. an aliased `import_module` → both façade tables invisible;
4. a declared project scope nobody read → 91% of the drift gate's output was
   other people's trees, and the picker ranked work against them;
5. an env-reader helper → the spend ceiling reported as dead configuration.

None of these was a missing feature. Every one was a measurement that read as
authoritative and was wrong, in a repository whose entire discipline is that
claims carry evidence. That is the coherence problem — not the module count.

---

## 8. The blockers, measured instead of quoted

§6 named six blockers and stopped there. This section measures them, because
"blocked" is a claim like any other and two of the six turn out not to be what
the packets say they are.

### 8.1 How much each one gates `[MEASURED 2026-09-03, 217 work packets]`

| blocker | packets naming it | kind |
| --- | --- | --- |
| Docker sandbox evidence | 11 | open **owner position** (Revision 8) |
| Gate-wide Primary-Checkout mutation exclusion | 11 | engineering |
| issue #189 (provider-observation persistence) | 7 | open issue |
| complete fault injection | 7 | evidence |
| live runtime receipts | 6 | evidence |
| issue #194 (repository-write findings) | 5 | open issue |

The two heaviest gate eleven packets each. Only one of those two is an owner
decision, which makes it the highest-leverage thing on this list.

### 8.2 The Docker blocker is not procurement any more

Master plan Revision 8 records that *"Docker host procurement stays an open
owner position"*. On this host, today `[MEASURED]`:

- `docker --version` → **29.7.2** — the CLI is installed;
- `wsl --status` → default distribution present (`NVIDIA-Workbench`), version 2;
- `docker info` → **fails**: cannot connect to
  `npipe:////./pipe/dockerDesktopLinuxEngine`.

So the machine has Docker and WSL2 and the daemon is not running. That is a
materially different position from *procurement*: the question in front of the
owner is starting or configuring an engine, not acquiring a host. Eleven
packets' evidence obligation sits behind it.

This does not close the blocker and this lane did not start anything — a
container engine is a host-level service and its own decision. It records that
the blocker's stated shape is stale.

### 8.3 This repository declares every checkout unfit to produce its own evidence

`tools/gate_host_preflight.py` exists to answer whether a machine can produce a
gate discrimination receipt. Run here it reports **NOT FIT**, for exactly one
reason out of twelve checks `[MEASURED]`:

```text
[FAIL] module coverage: NOT IMPORTABLE
NOT FIT: 1 required check(s) failed.
```

Everything else passes: Python 3.12.13, pytest 9.1.1, git, 8 worktrees, 58 GiB
headroom, and `daedalus` resolving to this checkout.

`coverage` is declared **nowhere**. It is in no extra in `pyproject.toml`, and
`uv.lock` contains zero occurrences of it `[MEASURED]`. So it cannot be
installed from this project's own packaging at all, and any environment built
the documented way is NOT FIT by the repository's own instrument.

Worse, the two instruments disagree about whether it is required:

- `tools/gate_host_preflight.py:49` — a required-modules tuple naming `pytest`
  and `coverage` (written here without the assignment form on purpose: the
  switch scanner reads `NAME` followed by `=` in prose as an operator
  declaring an environment variable, and quoting the real line manufactured a
  phantom `REQUIRED_MODULES` switch in this gate's own doc-drift list),
  justified as *"a gate run on this host would not measure what the receipt
  would claim it measured"*;
- `tools/gate_discrimination.py:752` — `_coverage_probe` returns `None` when
  `python -m coverage` is not runnable, and the module's own comment says this
  *"changes only WHICH of the 12 corpus entries spend a gate run, never the SHA
  a receipt is bound to or how CAUGHT/SURVIVED is decided"*.

The second is the honest one, and it is honest in the way that matters: the
receipt carries `coverage_guided` and `coverage_state` fields, so a run without
coverage says so rather than silently claiming the stronger measurement. The
receipt does not claim what it did not measure.

### 8.4 The preflight blocks a run that would not have used coverage

The disagreement is sharper than "one is strict". Coverage-guided
discrimination is **opt-in** `[MEASURED]`:

- `tools/gate_discrimination.py:913` — `coverage_guided: bool = False`;
- `:1130` — `--coverage-guided` is a `store_true` flag;
- `:968` — without it, `coverage_state = "not_requested"` and the module is
  never invoked.

And the committed receipt, `runs/spine/gate_discrimination.json`, was produced
that way: `coverage_guided: false`, `coverage_state: "not_requested"`.

So the default gate run never touches `coverage` at all, and the preflight
declares a host unfit to perform it anyway. That is not a strictness preference;
the required-module list is simply stricter than the run it gates.

This is on the promotion path, not a side quest. `docs/STATUS.md` records that
promotion is blocked "on `runs/spine/gate_discrimination.json` being stale at
HEAD — a measurement, not a pen stroke". It is stale: the receipt is bound to
`head: fe634b58`, and HEAD is `ce8273bf` `[MEASURED]`. Refreshing it is what
clears that block, and the instrument that decides whether this machine may
refresh it says no, for a module the refresh would not use.

### 8.5 The fix, and which part of it is which

Two changes, and they are not the same change:

1. **`tools/gate_host_preflight.py`** — `coverage` belongs in
   `OPTIONAL_MODULES`, or in a required set that is conditional on
   `--coverage-guided`. As written it fails hosts for a capability the default
   run does not exercise. This is the part that unblocks the receipt refresh.
2. **`pyproject.toml`** — `coverage` should still be declared in the test
   extra, because the opt-in mode is currently *unusable*: it cannot be
   installed from this project's packaging at all. This does not unblock
   anything by itself; it makes the stronger evidence available to anyone who
   asks for it.

Doing only (2) would make hosts fit while leaving the preflight's logic wrong.
Doing only (1) leaves `--coverage-guided` permanently unavailable. An earlier
draft of this section recommended (2) alone, before the opt-in default was
measured; that recommendation was wrong.

**Both landed.** (1) in `90462c30`: the host verdict goes NOT FIT → **FIT TO
MEASURE**, which is what unblocks a receipt refresh. (2) in `0580898c`, once the
history rewrite's freeze lifted and the lockfile could move safely.

The lockfile turned out to be stale independently of this change. `uv lock`
added `coverage` as intended, and also `pytest-xdist` and `execnet`, which
`pyproject.toml` already declared at line 81 and the lock simply did not carry
— so `uv sync --frozen` had been passing only because it never checked for the
missing ones. The diff is 154 insertions and **zero deletions**: three packages
added, no existing version moved.

Declaring the dependency is deliberately not the same act as provisioning an
environment, and the two were kept separate: `coverage` is still absent from
this machine's venv, the preflight still reports it absent-but-optional, and the
host is still FIT. What changed is that anyone who wants the stronger gate now
has a supported way to get it.

## 9. What was deliberately not fixed

Three `ENGINE DISAGREEMENT` rows survive on this branch, and the decision not to
close them is the point.

All three are the same shape: `tools/` modules importing siblings by bare name
after `sys.path.insert(0, TOOLS_DIR)`, where `TOOLS_DIR` is literally
`Path(__file__).resolve().parent`.

```text
tools/gate_discrimination.py -> tools/system_check.py
tools/self_test.py           -> tools/system_check.py
tools/system_check.py        -> tools/self_test.py
```

The edges are real at runtime — the `sys.path` insert is two lines above the
import. structcore resolves them because §5 made `tools` a declared center root.
The reachability walk does not, and **should not**: a sibling rule keyed on
`sys.path` mutation would add edges on an inference about runtime path state,
and `reach.py`'s governing rule is that a false *reachable* is worse than a
false island because it is silent. The gate's own design agrees — these are
"reported, never merged", and a visible disagreement between two engines is the
intended outcome rather than a defect to be resolved by making one of them
guess.

So they are **accepted, dated and reasoned** rather than banked into a snapshot:
each carries the explanation above and expires 2026-11-30. The tool refused a
119-day horizon on the way — *"an acceptance nobody has to retype is a
permanent one wearing a date"* — which is the correct instinct and worth
recording as one of the few places today where an instrument was stricter than
the person using it.

**One row in this document was a defect this document caused.** §8.3 quoted the
preflight's required-modules line verbatim, in the assignment form, and the
switch scanner reads `NAME` followed by `=` in prose as an operator declaring an
environment variable. The survey therefore manufactured a phantom
`REQUIRED_MODULES` switch into the very doc-drift list it was reporting on. It
is rephrased, and `doc_drift` returns to 30. The comment above `_DOC_ENV_FORMS`
warns about exactly this — "without this filter every SCREAMING_CASE doc
filename becomes a phantom switch" — and the filter works; prose that writes the
operator form is not a false positive, it is a declaration.

Gate state on this branch: **OK**, `dark_switches=0`, `doc_drift=30`,
`islands=60`, `unreached=91`, three accepted disagreements carrying their reason
`[MEASURED 2026-09-03]`.

---

`Iron Plan: ALIGNED`
`Iron Gate: 1`
`Evidence: daedalus.mapping.reach.analyse at 17bfb1c9 (census, 52 flagged rows);
independent AST import-graph cross-examination (production vs test importers per
row); runtime resolution of daedalus.orchestration.run_mission; git ls-files /
check-ignore on apps/web/src-tauri/backend/_internal; tests/contracts import
contracts 6 passed; tests/gates + tests/kernel full run, no failures. No
daedalus/ source file modified.`
