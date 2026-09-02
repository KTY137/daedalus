# The Gate-1 hierarchy target file tree

Status: projection, not authority
Active gate: 1
Observed revision: `851ff43cc63dd788d1da63a6f7fa44fcc6ed0291`
Observed: 2026-09-02
Owner: whoever holds the next G1-HIER packet

The owner asked what the proposed file tree is. Until this file existed the
honest answer was: there is no canonical document. The target layout lived as
folklore distributed across `docs/work-packets/G1-HIER-*.md`, the allowlists in
`docs/architecture/import-boundaries.json`, and comments in
`tests/contracts/test_import_scc_hierarchy.py`. This file collects it and
stamps every number.

Provenance discipline for this document: every number is `[MEASURED]` with the
command that produced it, `[INHERITED]` with the run it came from named, or
`[ASSUMED]`. There are no unstamped numbers. Where this document disagrees with
the brief that commissioned it, the disagreement is recorded rather than
smoothed — see §2.3.

---

## 1. The tree as it IS

### 1.1 Headline counts

All commands run in this worktree at `851ff43c`.

| quantity | value | provenance |
| --- | --- | --- |
| tracked `.py` under `daedalus/`, all depths | 433 | `[MEASURED]` |
| flat modules directly under `daedalus/` | 76 | `[MEASURED]` |
| immediate subpackages of `daedalus/` | 25 | `[MEASURED]` |
| import edges in the tracked module graph | 1630 | `[MEASURED]` |
| non-trivial import SCCs | 12 | `[MEASURED]` |
| largest SCC | 18 modules | `[MEASURED]` |

```console
$ git ls-files -- 'daedalus/***.py' | wc -l
433
$ git ls-files -- ':(glob)daedalus/*.py' | wc -l
76
$ git ls-files -- ':(glob)daedalus/*/__init__.py' | wc -l
25
```

**A reader trap, recorded because it bit during this measurement.** In git
pathspec, `*` crosses directory separators. `git ls-files 'daedalus/*.py'`
returns **433**, not 76 — it is a recursive glob wearing a flat glob's syntax.
The flat count requires `':(glob)daedalus/*.py'`. Any future census of "how many
flat modules are left" that uses the naive form will report the whole package
and conclude nothing moved. The 76 includes `daedalus/__init__.py`, so 75 are
flat modules proper plus the package initializer.

The SCC numbers were recomputed here rather than inherited from the test. The
graph builder in `tests/contracts/test_import_scc_hierarchy.py:128`
(`_tracked_module_graph`) was re-run standalone against `851ff43c`; it
reproduces the four constants that file pins — `CENSUS_MODULES = 433`
(line 57), `CENSUS_EDGES = 1630` (line 118), `len(components) == 12` (line 205),
`max(map(len, components)) == 18` (line 206) — and the component digest
`36d80ea6d701892c1cbb08057c2715477fbfcad972aa36b9f331d3065f3434a1`
(line 49). `[MEASURED]` — no pytest was run; the graph function was executed
directly under `.venv/Scripts/python.exe`.

### 1.2 The layer packages that already exist

`.py` file counts at all depths beneath each immediate subpackage. `[MEASURED]`
via `git ls-files -- 'daedalus/***.py' | awk -F/ 'NF>2{print $2}' | sort | uniq -c`.

| package | files | package | files |
| --- | --- | --- | --- |
| `runtimes` | 64 | `wiki` | 8 |
| `kernel` | 50 | `mapping` | 7 |
| `gates` | 35 | `ignition` | 6 |
| `structcore` | 24 | `hooks` | 6 |
| `interfaces` | 21 | `council` | 6 |
| `eval` | 19 | `lanes` | 5 |
| `spine` | 15 | `adapters` | 5 |
| `chip_design` | 15 | `memory` | 4 |
| `integrations` | 14 | `tools` | 3 |
| `twin` | 13 | `observe` | 2 |
| `providers` | 11 | `gui` | 2 |
| `kairos` | 11 | `resources` | 1 |
| `orchestration` | 10 | | |

The structural point: **the target layer packages mostly already exist.** The
refactor is not "create the layers". It is "empty the 76 flat modules into
them", and that is why the flat count is the number to watch.

### 1.3 The 76 flat modules

`[MEASURED]` via `git ls-files -- ':(glob)daedalus/*.py'`:

```text
__init__ accelerators agents_registry arch_memory atomic benchmark bookkeeper
bootstrap_prompt budget build build_exec categories claude_bridge claude_detect
cli config context_plan control_plane conversation conversation_requests core
dctx decompose desktop_runtime doctor dotenv drafts editor_context enforce env
fallback file_bridge gui_catalogue health hierarchy ikarus ikarus_act
ikarus_chat ikarus_effect_bridge ikarus_oneshot ikarus_os ikarus_runtime_events
ikarus_runtime_role ikarus_supervisor ikarus_tool_scope langgraph_adapter
limit_policy llm_client loop metrics mission_control offload orchestrate
preservation primary_tree progress progress_sources projects provider_router
router runbook runtime_registry schemas selftest semantic_route sensitivity
shift shift_ticker skills status storage text_integrity token_monitor
token_policy verifier web_api
```

---

## 2. The tree as TARGETED

### 2.1 The target layout

```text
daedalus/
├── kernel/          Mission, Attempt, Evidence, policy, promotion, contracts
├── spine/           the canonical event spine — infrastructure, below product
├── twin/            the four-plane Project Twin
├── runtimes/        provider/runtime adapters and admission
├── orchestration/   mission composition above the kernel
├── interfaces/
│   ├── cli/         ← DOES NOT EXIST YET
│   ├── http/        exists (6 files)
│   ├── bridge/      exists (8 files)
│   └── desktop/     exists (6 files)
│
├── atomic.py        ─┐
├── budget.py         │
├── config.py         │ the seven DECLARED-FLAT foundation modules:
├── limit_policy.py   │ these stay flat on purpose
├── primary_tree.py   │
├── sensitivity.py    │
└── storage.py       ─┘
```

Everything else currently flat is intended to leave the top level. This
document does not say where for the modules §3 lists as unresolved.

`interfaces/cli/` is `[MEASURED]` absent:
`git ls-files -- 'daedalus/interfaces/cli*'` returns nothing, while
`bridge`, `desktop`, and `http` each have an `__init__.py`. It is the one
named target subpackage that is still purely proposed.

### 2.2 The seven declared-flat foundation modules — and a precision correction

All seven exist. `[MEASURED]`,
`git ls-files -- "daedalus/<name>.py"` for each: `atomic`, `budget`, `config`,
`limit_policy`, `primary_tree`, `sensitivity`, `storage` — 7/7 present.

The folklore says these seven are "declared in the allowlists" of
`docs/architecture/import-boundaries.json`. That is true of **one** rule, not of
the file. `[MEASURED]` by parsing the four rules' `allowed_target_prefixes`:

| rule | allowlist size | of the seven |
| --- | --- | --- |
| `kernel-no-outer-layers` | 10 | **all 7** |
| `spine-no-outer-layers` | 8 | 5 — missing `primary_tree`, `storage` |
| `twin-no-outer-layers` | 3 | 0 — allows only `kernel`, `spine`, `structcore` |
| `runtimes-no-gates` | 0 | n/a — empty allowlist, forbid-only rule |

So the seven are a **kernel-layer** foundation declaration. The spine is
permitted only five of them, and the twin none. Writing "the seven are declared
flat in the allowlists" without that qualifier would state a uniformity the
file does not have. Whether the spine's omission of `primary_tree` and
`storage` is deliberate scoping or an unclosed gap is **not** determined here —
`kernel-no-outer-layers`' rationale explains the seven as "foundation the
kernel is meant to sit on" and says nothing about the spine.

A second tension, `[MEASURED]`: `daedalus.budget` is simultaneously a
declared-flat foundation module in `kernel-no-outer-layers` **and** a
registered shim in `docs/architecture/shim-registry.json` with three declared
targets (`daedalus.kernel.policy.ledger`, `daedalus.kernel.policy.pricing`,
`daedalus.runtimes.execution.budget_process`) and removal criteria. A module
cannot be both permanently flat and slated for removal. This document records
the contradiction; resolving it belongs to a packet, not to a chronicler.

Note also that `daedalus.offload` sits in `kernel-no-outer-layers`'
allowlist while its own rationale states it is **not** foundation: "it is a
workload, and `attempt_execution.py:1209` importing it is a genuine inversion."
It is listed to be visible, not to be blessed.

### 2.3 `daedalus/schemas.py` and its death path

`daedalus/schemas.py` is 95 lines `[MEASURED: wc -l]`. It is a pure
re-export facade — no lazy `__getattr__`, no dynamic import. It re-exports from
exactly three owners, at module scope:

- `daedalus/schemas.py:10` — `from daedalus.kernel.contracts.canonical import (`
- `daedalus/schemas.py:55` — `from daedalus.orchestration.legacy_reports import AgentTask, RunState`
- `daedalus/schemas.py:56` — `from daedalus.runtimes.contracts.provider_report import (`

These match its `shim-registry.json` entry exactly (`kind:
mixed_owner_contract_reexport_facade`), whose removal criteria read:

> "Source, runtime-string, wheel, documentation, monkeypatch, and pickle audits
> show no remaining caller importing kernel contracts, agent tasks, or provider
> reports through this module; each caller names the owning module directly.
> The kernel is already migrated by G1-HIER-10 and the boundary contract
> forbids it from returning."

**Remaining users inside `daedalus/`: 34, not 33.** `[MEASURED]` by AST walk at
`851ff43c`, catching every spelling including relative and function-scope.

The brief that commissioned this document said 33 users measured 2026-09-02.
That number is reproducible and is what a regex-based census returns:

```console
$ git grep -lE '(from|import)\s+daedalus\.schemas|from\s+\.{1,3}schemas\s+import' \
    -- '*.py' | grep '^daedalus/' | wc -l
33
```

The 34th is `daedalus/core.py:382`, which imports the facade as
`from . import schemas` inside a function body. That spelling names the module
as an *attribute of the package*, not as a dotted module path, so no pattern
matching `schemas` as a module target sees it. This is the document's own
subject matter arriving in its own measurement: the naive reader undercounts by
exactly one, and it undercounts a **deferred** import, which is the same class
of construct that G1-HIER-12 and G1-HIER-13 were dispatched to close.

By scope, `[MEASURED]`:

| | files |
| --- | --- |
| module-scope only | 29 |
| function-scope (deferred) only | 4 |
| both scopes in one file | 1 — `daedalus/ignition/gate1.py` (lines 619, 657) |
| **distinct files** | **34** |

The seven deferred import sites: `daedalus/build_exec.py:580`,
`daedalus/chip_design/completion_publication.py:316`, `daedalus/core.py:382`,
`daedalus/ignition/gate1.py:619`, `daedalus/ignition/gate1.py:657`,
`daedalus/langgraph_adapter.py:161`, `daedalus/langgraph_adapter.py:187`.

Repo-wide the facade has **129** distinct callers `[MEASURED]`, by area: 33
`daedalus/` (regex form; 34 by AST), 94 `tests/`, 1 `scripts/`, 1 `runs/`. The
test-side 94 is the bulk of the remaining work and no packet has claimed it.

By layer, the 34 in-package users cluster in exactly the layers the boundary
rules already forbid from reaching the facade's targets — `gates` 15,
`chip_design` 5, `orchestration/missions` 3, `ignition` 2, plus 9 flat modules
(`build`, `build_exec`, `core`, `ikarus_effect_bridge`, `ikarus_oneshot`,
`ikarus_supervisor`, `ikarus_tool_scope`, `langgraph_adapter`, `runbook`).
`[MEASURED]`; sums to 34. **Zero** are under `daedalus/kernel`, `daedalus/spine`, or
`daedalus/twin`: G1-HIER-10, -11 and -12 closed those three layers, and
`kernel-no-outer-layers`, `spine-no-outer-layers` and `twin-no-outer-layers`
each name `daedalus.schemas` in their forbidden sets to keep them closed.

The death path is therefore: **the three protected layers are done; the
34 in-package and 94 test callers are not, and no packet currently owns
them.**

---

## 3. UNRESOLVED — the 18-member cross-domain SCC

`[MEASURED]` at `851ff43c`: the largest non-trivial import SCC has 18 members.
It is asserted as `CURRENT_CROSS_DOMAIN_COMPONENT` in
`tests/contracts/test_import_scc_hierarchy.py:46` and re-derived here
independently:

```text
daedalus.build                      daedalus.offload
daedalus.build_exec                 daedalus.progress
daedalus.core                       daedalus.progress_sources
daedalus.doctor                     daedalus.spine.attempt
daedalus.file_bridge                daedalus.spine.bootstrap
daedalus.health                     daedalus.spine.picker
daedalus.ikarus_supervisor          daedalus.status
daedalus.kairos.gated_writes
daedalus.kairos.scheduler
daedalus.kernel.attempt_execution
daedalus.kernel.promotion
```

**Their destinations are not decided, and this document does not invent them.**
They await the port-extraction design. Three properties make guessing actively
harmful:

1. A cycle has no layering. Assigning any one of these 18 to a layer while the
   cycle stands creates an edge that some rule must then forbid, and the
   forbidding is what the port extraction is for.
2. Three of the 18 are already *inside* protected layers —
   `kernel.attempt_execution`, `kernel.promotion`, and three `spine.*` modules.
   They are not flat modules awaiting a home; they are layered modules whose
   cycle crosses back out through flat ones. `daedalus.offload` is the named
   example: `kernel-no-outer-layers` allowlists it while calling
   `attempt_execution.py:1209`'s import of it "a genuine inversion".
3. The component shrank by *removal from the cycle*, not by relocation:
   `daedalus.kernel.offload_lease` and
   `daedalus.runtimes.admission.offload_egress` left in G1-HIER-07A, and
   `daedalus.conversation` left in G1-HIER-07B — each by extracting a port, not
   by moving a file. That is the precedent this document defers to.

A related unresolved: **`kairos` versus `orchestration`.** Both exist as
packages (11 and 10 files `[MEASURED]`), the boundary rules forbid them as two
separate prefixes, and four flat-module shims declare `daedalus.kairos.*`
destinations (`decompose`, `drafts`, `ikarus`, `mission_control`
`[MEASURED]` from `shim-registry.json`). `kairos` appears **0 times** in
`docs/IKARUS_ARIADNE_MASTER_PLAN.md` `[MEASURED: grep -cin]`, and the plan's §3
permits exactly three public concepts, with existing components surviving "as
internal modules". Whether `kairos` is a permanent internal package or a
staging area that folds into `orchestration` is undecided in every source
consulted.

### 3.1 Flat modules that DO have a declared destination

`[MEASURED]` from `docs/architecture/shim-registry.json` (21 entries total; 9
are flat modules):

| flat module | kind | declared target(s) |
| --- | --- | --- |
| `budget` | `effect_and_compatibility_facade` | `kernel.policy.{ledger,pricing}`, `runtimes.execution.budget_process` |
| `decompose` | `module_reexport` | `kairos.decompose` |
| `drafts` | `module_reexport` | `kairos.drafts` |
| `file_bridge` | `registered_effect_facade` | `interfaces.bridge.*` (7 modules) |
| `ikarus` | `module_reexport` | `kairos.scheduler` |
| `mission_control` | `module_reexport` | `kairos.control` |
| `orchestrate` | `cli_facade` | `kairos.orchestrate` |
| `schemas` | `mixed_owner_contract_reexport_facade` | `kernel.contracts.canonical`, `orchestration.legacy_reports`, `runtimes.contracts.provider_report` |
| `token_policy` | `module_reexport` | `runtimes.providers.token_policy` |

That is 9 of 76. **The other 67 flat modules have no declared destination in
any tracked artifact** — not in the shim registry, not in the boundary
contract, not in a packet doc. Counting them as "planned" would be inventing a
plan.

---

## 4. The migration rule

> **A module moves only when the instruments that read it can follow the
> resulting construct.**

The instruments are: the import census
(`tests/contracts/test_import_scc_hierarchy.py`), the effect-registry
derivation, the producer scan, and the substitution guard
(`tests/test_deepseek_substitution_guard.py`). The rule exists because this
week produced a run of incidents in which an instrument reported **green** while
the thing it existed to see was invisible to it. A module relocated behind a
construct its reader cannot follow does not become clean; it becomes
*unmeasured*, which reads identically from the outside.

The incidents, in the order they were recorded:

**(a) The forbidden set could only refuse what it enumerated.**
`import-boundaries.json`, rule `kernel-no-outer-layers`, rationale, `[MEASURED]`
2026-09-02: the rule "named eight package prefixes while 76 modules sat flat
under `daedalus/`, so kernel imports of `daedalus.offload`, `daedalus.core` or
`daedalus.doctor` read as clean." The fix was to add an *allowlist*, because a
denylist over a flat namespace is unbounded by construction. This is the
structural reason the 76-module flat layer is a measurement hazard and not
merely untidy.

**(b) A leak that crossed a permitted edge was invisible one layer up.**
`twin-no-outer-layers` rationale, `[MEASURED]` at `515b5fce`, before G1-HIER-11:
four `daedalus.twin` modules imported the `daedalus.schemas` facade *by relative
import*, and a cold `import daedalus.kernel.fourfold_evidence` loaded "eleven
`daedalus.runtimes` modules and two `daedalus.orchestration` modules, all of
them invisible to `kernel-no-outer-layers` because the leak crossed a permitted
edge."

**(c) A facade laundered a rule's own forbidden set in one hop.**
`spine-no-outer-layers` rationale, `[MEASURED]` at `4c370f2ad757`: "a cold
`import daedalus.spine.receipts` loaded 13 modules under `daedalus.orchestration`
and `daedalus.runtimes` plus the facade itself, and the rule passed." Importing
`daedalus.schemas` loaded exactly the prefixes the rule already forbade — one
hop away, therefore green.

**(d) An adversarial probe found a larger hole than the packet was sent to
close.** Same rationale, `[MEASURED]`: a `daedalus/spine` module importing
`daedalus.gates.report` — "an ordinary, static, module-scope import needing no
dynamic trickery" — transitively loaded 19 `daedalus.runtimes` modules, 2
`daedalus.orchestration` modules and the facade, "while both the boundary
checker and the packet's own test file reported green." Larger than the 13 of
incident (c).

**(e) The cold-import instrument is blind across 494 edges.**
`docs/work-packets/G1-HIER-12_SPINE_CONTRACT_OWNER_IMPORTS.md:111-136`
`[INHERITED]` measured 495 function-scope `daedalus.*` imports at `4c370f2a`.
Re-measured here at `851ff43c` `[MEASURED]`: **494** — the difference is the one
edge G1-HIER-12 removed, and the layer split still reconciles (`spine` 34,
`kernel` 33, `runtimes` 13, `twin` 0; the doc predicted "34 after this packet"
for the spine). The packet's own verdict:

> "the runtime instrument is blind across 495 edges and was *load-bearing on
> none of them by luck*, and that the static checker — not the cold import — is
> what has actually been holding the line."

It proved this mechanically rather than arguing it: mutation **M2** reverted
`picker.py` to a function-scope facade import, turning four tests red while
`test_cold_spine_picker_import_loads_no_outer_implementation` **stayed green**.
`daedalus/twin` is the only rule-governed layer at 0, because G1-HIER-11's
`test_twin_layer_has_no_lazy_or_sys_modules_escape` bans deferred imports there
outright — the one place the hazard was removed rather than measured.

**(f) The census had no opinion about *when* an import ran.**
`tests/contracts/test_import_scc_hierarchy.py:88-92`:

> "This graph counts an edge wherever the import appears, module scope or
> function scope, because it walks the whole AST. […] That is also why this
> census was NOT an instrument that could have caught the deferred facade import
> G1-HIER-12 removed — it saw the edge all along and had no opinion about when
> it ran."

Two instruments, opposite blind spots: the cold import sees timing but not
deferred edges; the census sees deferred edges but not timing. Neither alone
covers a move.

**(g) A guard widened until it passed — rejected, and named as the branch's
open CRITICAL shape.**
`G1-HIER-13_ALIAS_AWARE_STATIC_READERS.md:265-276` (read via
`git show packet/g1-hier-13:docs/work-packets/G1-HIER-13_ALIAS_AWARE_STATIC_READERS.md`;
the file is **not** at `851ff43c`). Adding `__firstlineno__` and
`__static_attributes__` to a literal expected set was rejected because it "goes
green while re-arming the identical trap for CPython 3.14, and widening a
guard's expected set until it passes is precisely the shape this branch already
carries one open CRITICAL for."

**(h) The measurement that was wrong for the right-looking reason.**
Same document, section "A measurement of mine that was wrong, recorded because
it nearly stood": a fixture reported twelve cases as "refuse" — seven of them
"ok" *for entirely the wrong reason* — because `repo_root="/tmp/overfollow"`
resolves on Windows to a drive-relative `\tmp\overfollow` that does not exist,
so `_module_path` returned `None` and every case refused with "module does not
exist". The packet's own summary: "This is the same family of defect the packet
exists to fix, produced while fixing it."

**(i) The fresh CRITICAL on `packet/g1-hier-13`'s reader.** `[INHERITED]` —
raised in this session's review of that branch and **not verifiable from the
tracked tree**; it is recorded here as an inherited claim, with the source
named, not as a measurement of this document's.

What *is* `[MEASURED]` about that reader, from
`git show packet/g1-hier-13:daedalus/lanes/checks.py`: it recognises **exactly
one** alias construct — `sys.modules[__name__] = _owner`
(`_alias_target`, line 169) — follows at most `_MAX_ALIAS_HOPS = 4` (line 166),
and treats `__getattr__`/`__getattribute__` as dynamic-protocol markers
(`_DYNAMIC_ATTRIBUTE_HOOKS`, line 226). Its own docstring calls it
"Deliberately narrow, because a reader taught to follow aliases can be taught
to follow too much" (line 192). The branch's diff touches
`daedalus/lanes/checks.py` (+248 lines) and five test files; **none** of it is
merged into `851ff43c`. Anyone acting on the CRITICAL must read the branch, not
this file.

### 4.1 What the rule means operationally

Before moving a module, name the instrument that will read it afterwards and
show it can. Specifically, `[MEASURED]` limitations that a move must not walk
into — all four are stated in the tracked artifacts, none is hypothetical:

- the boundary checker "observes direct import syntax only"
  (`twin-no-outer-layers` rationale) — it cannot see a leak through a permitted
  intermediate layer, which is why each layer needs its own rule;
- it is blind to "dynamic imports (`importlib.import_module`, `__import__`,
  `sys.modules`, `exec`), a module-level `__getattr__`, and any file under
  `daedalus/spine` that was never `git`-added, since the tracked-source command
  is the observation boundary" (`spine-no-outer-layers` rationale);
- "a caller hidden in a string is invisible to every static instrument here"
  (`G1-HIER-09_UNCOMPOSED_GATE_CALLERS.md:174`);
- `tools/architecture_boundaries.py` "still cannot see" the case named at
  `G1-HIER-10_KERNEL_CONTRACT_OWNER_IMPORTS.md:154-157`, and "that limitation is
  not repaired" by that packet.

Corollary, and the reason this section is longer than the target tree itself:
**a clean instrument reading after a move is evidence only if the instrument
could have gone red.** Every incident above is an instrument that was green and
wrong.

---

## 5. What this document is NOT

- **It is not authority over the master plan.** Under
  `docs/IKARUS_ARIADNE_MASTER_PLAN.md` §0, the plan is the sole semantic
  authority; root instructions, skills and derived documents are a "derived
  projection" whose job is to "load the plan, report drift, block ordinary
  mutation". This file is such a projection. Where it conflicts with the plan,
  the plan wins and this file is the thing that is wrong.
- **It is not a gate, a contract, or an enforced artifact.** Nothing reads it.
  `docs/architecture/import-boundaries.json` is the enforced contract, with four
  rules, checked by `tools/architecture_boundaries.py` and
  `tests/contracts/`. This file describes intent; that file refuses edges.
  If the two disagree, the JSON is what runs.
- **It is revisable by an ordinary commit.** It carries no amendment
  obligation. It is not the plan, not the amendment chain, not `AGENTS.md`, and
  not a guard, so §16's amendment protocol does not apply. Correcting it is
  ordinary work; correcting it is *expected* as packets land.
- **It does not decide destinations.** §3's 18 SCC members and the 67 flat
  modules with no declared target are open questions recorded as open. A future
  editor who fills them in from intuition rather than from a landed packet has
  turned a chronicle back into folklore, which is the condition this file was
  written to end.
- **It is not evidence that any of this is done.** Every count is a measurement
  of `851ff43c` on 2026-09-02 and expires the moment a packet lands. Re-measure
  with the commands given; do not cite these numbers forward.

---

## Sources consulted

| source | ref | used for |
| --- | --- | --- |
| `docs/IKARUS_ARIADNE_MASTER_PLAN.md` §0, §3, §13 | `851ff43c` | authority model, three public concepts, forbidden directions |
| `docs/architecture/import-boundaries.json` | `851ff43c` | four rules, allowlists, measured blindness rationales |
| `docs/architecture/shim-registry.json` | `851ff43c` | 21 entries, 9 flat-module destinations, removal criteria |
| `tests/contracts/test_import_scc_hierarchy.py` | `851ff43c` | census constants, SCC membership, census-blindness comment |
| `docs/work-packets/G1-HIER-01..12` | `851ff43c` | 23 packet docs present |
| `docs/work-packets/G1-HIER-13_ALIAS_AWARE_STATIC_READERS.md` | `packet/g1-hier-13` | **not at HEAD**; alias reader, rejected widening, wrong-measurement note |
| `daedalus/lanes/checks.py` | `packet/g1-hier-13` | **not at HEAD**; `_alias_target`, `_MAX_ALIAS_HOPS` |

G1-HIER-14 is referenced in `test_import_scc_hierarchy.py:94-117` (the 33-file
`daedalus/runtimes` facade repoint, `1624 -> 1630` edges) but **has no packet
document at `851ff43c`** `[MEASURED]`: `git ls-files` matches
`G1-HIER-01` through `G1-HIER-12` only, 23 files. G1-HIER-15 appears in no
tracked artifact found. The brief's "G1-HIER-01..15" therefore describes a
packet range that is partly unwritten; that gap is recorded rather than
papered over.
