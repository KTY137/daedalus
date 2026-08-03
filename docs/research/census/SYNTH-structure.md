# SYNTH — Structure and Coupling

Synthesis lane 3 of 3. Inputs: `runs/eval/census300/_census.json` (300 slices,
677 DEPENDS / 193 READS / 107 WRITES / 155 UNWIRED / 92 SMELL) and the 20
cross-file reviews in `docs/research/census/reviews/`.

## Method, and what "verified" means here

The census is a cheap-model artefact and its per-line claims are not
trustworthy (two SMELL lines about missing `__all__` targets in
`spine/containment.py` and `kairos/worktree.py` were checked by others and are
both **false**). So the census was used **only as a lead generator**. Every
structural number below comes from an **independent AST import graph** I built
over the tree (`ast.parse` on every `.py`, resolving absolute and relative
imports, including `from pkg import submodule` forms), plus targeted greps.

Ground truth of that walk: **367 Python files, 367 modules, 0 parse errors**,
excluding `.git`, `node_modules`, `dist`, `build/`, `runs/`, `.venv`.
Two exclusions matter and are discussed below (`build/` and `runs/`) because
both contain Python that the rest of the tree talks about.

Each claim is tagged:
**[V]** = I read the file or grepped it myself.
**[C]** = passed through from the census, unverified.

---

## 1. The dependency spine

### 1.1 The single most consequential structural fact: 38% of internal coupling is deferred

**[V]** Counting internal, non-test module→module edges:

| edge kind | count |
|---|---|
| module-level (top-of-file) imports | **324** |
| imports that appear ONLY inside a function or method | **202** |
| total | 526 |

Nearly two in five internal dependencies do not exist at import time. This is
not incidental style. `daedalus/cli.py` has **37 internal dependencies and every
single one is deferred** — the entire CLI dispatch table is `from .doctor import
main as m; m()` inside branches (`cli.py:1079`, `:1100`, `:1102`). The same
pattern runs through `spine/picker.py` (11 deferred), `core.py` (10),
`health.py` (10), `ikarus_os.py` (10), `loop.py` (9), `offload.py` (9),
`web_api.py` (9).

Consequences that are invisible in a file listing:

- **Static tools systematically under-report this codebase.** Any analysis that
  reads only top-level imports sees roughly 60% of the real graph. The census's
  own DEPENDS tag partially catches deferred imports (it annotates some, e.g.
  `daedalus.spine.cancel (conditional in _spawn_pytest)`), which is why its
  aggregate shape is usable even though its detail is not.
- **Import errors surface at call time, not at start-up.** A broken import in a
  rarely-taken CLI branch stays green until someone runs that subcommand.
- **The acyclic top-level graph is an artefact of the deferral, not of the
  design** — see 1.3.

### 1.2 Genuine hubs (fan-in, non-test importers only)

**[V]** All counts are distinct non-test modules that import the target.

| fan-in | module | what a change there touches |
|---:|---|---|
| 23 | `daedalus/sensitivity.py` | the fence; every write/egress decision |
| 23 | `daedalus/__init__.py` | see 1.2.1 — this one is a trap |
| 16 | `daedalus/projects.py` | repo-root resolution |
| 14 | `daedalus/router.py` | task→agent routing |
| 14 | `daedalus/structcore/index.py` | the code index |
| 14 | `daedalus/structcore/parse.py` | tree-sitter parse layer |
| 13 | `daedalus/structcore/languages.py` | language table |
| 11 | `daedalus/core.py` | the aggregate read-model |
| 11 | `daedalus/providers/ollama.py` | local inference |
| 10 | `daedalus/spine/attempt.py` | the attempt/worktree runner |
| 10 | `daedalus/config.py` | project config |
| 10 | `daedalus/memory/__init__.py` | event log |

Including test importers, `sensitivity.py` reaches **44 importers** and
`structcore/index.py` 33 — the two most heavily pinned modules in the tree.

#### 1.2.1 `daedalus/__init__.py` is a six-line module with 83 importers

**[V]** `daedalus/__init__.py` is 6 lines and does:

```python
from .router import route_task
from .schemas import AgentReport, AgentTask, RunState, validate_report
```

83 modules (23 non-test) reference the package root. Because the `__init__` is
**not empty**, `import daedalus.anything` eagerly executes `router.py` and
`schemas.py`. Those two modules are therefore loaded by literally every entry
into the package, and their import-time cost and side-effects are paid
unconditionally. This is the highest-leverage single file in the tree by
blast radius and the least obvious one, because nothing "depends on" it in a
way a reader would notice.

### 1.3 Fan-out: the four command surfaces

**[V]**

| fan-out | module | note |
|---:|---|---|
| 37 | `daedalus/cli.py` | all 37 deferred |
| 32 | `daedalus/web_api.py` | 9 deferred, 23 top-level |
| 18 | `daedalus/core.py` | the read-model aggregator |
| 15 | `daedalus/ikarus_os.py` | the chat/intent layer |
| 14 | `daedalus/loop.py`, `daedalus/offload.py`, `daedalus/structcore/index.py` | |

The shape is a classic four-headed application: **CLI, HTTP API, read-model,
intent layer** — each independently reaching deep into the same core. Nothing
sits between them. `core.py` is both a hub (11 importers) and a spoke
(18 dependencies), which is what makes it part of the cycle in 1.4.

### 1.4 Cycles: a 13-module runtime core held apart by lazy imports

**[V]** Tarjan SCC over non-test modules.

**Top-level imports only** — two small cycles:

- `structcore/{__init__, cache, index, perfile}` (4)
- `tools/{__init__, inventory}` (2)

**Counting deferred imports too** — the real runtime picture:

- **13-module cycle**: `benchmark.py`, `core.py`, `doctor.py`,
  `eval/correctness.py`, `file_bridge.py`, `health.py`,
  `kairos/gated_writes.py`, `kairos/scheduler.py`, `offload.py`,
  `spine/attempt.py`, `spine/bootstrap.py`, `spine/picker.py`, `status.py`
- `structcore/{__init__, cache, index, perfile, slice}` (5)
- `mapping/{drift, inventory, render}` (3)
- `progress.py ↔ progress_sources.py` (2)
- `tools/{__init__, inventory}` (2)

Spot-verified: `spine/bootstrap.py` imports `spine.picker` at `:153`, `:333`,
`:578`, `:586`, `:610` and `spine.attempt` at `:273`, `:608`, `:674` — all
inside function bodies; `spine/picker.py` imports `..mapping.spectral` at
`:2304` and `. docrefs` at `:2354`, likewise deferred.

**This is a deliberate, load-bearing pattern, not sloppiness** — the deferral is
what keeps `python -c "import daedalus"` working. But it means the honest
description of the system is: *there is one 13-module mutually-recursive core
spanning `daedalus(top)`, `daedalus/spine`, `daedalus/kairos` and
`daedalus/eval`, and it is not decomposable without breaking behaviour.* Any
plan that says "extract the spine" is planning against a 13-node SCC.

### 1.5 Package-level coupling

**[V]** Cross-package edge counts (non-test), and which pairs are bidirectional:

```
daedalus(top) <-> daedalus/kairos      20 / 19    <-- effectively one package
daedalus(top) <-> daedalus/spine       20 /  6
daedalus(top) <-> daedalus/structcore  20 /  2
daedalus(top) <-> daedalus/providers   13 /  9
daedalus(top) <-> daedalus/council      6 /  4
daedalus(top) <-> daedalus/eval         1 /  3
daedalus/eval <-> daedalus/spine        2 /  2
daedalus/kairos <-> daedalus/spine      2 /  1
daedalus/eval  -> daedalus/structcore  17 /  0    <-- clean one-way
tools          -> daedalus/spine       10 /  0    <-- clean one-way
```

`daedalus(top) ↔ daedalus/kairos` at 20/19 is not a layered relationship; the
`kairos` subpackage and the top level are one mutually-dependent unit that
happens to be spelled as two. `eval → structcore` (17/0) and `tools → spine`
(10/0) are the only large strictly-one-way relationships in the tree, i.e. the
only two package boundaries that are actually boundaries.

---

## 2. Layering violations, and the fence

The question that matters: **can anything an agent controls influence the
fence?** I read the actual imports.

### 2.1 The fence's import surface is clean [V]

| module | internal imports | verdict |
|---|---|---|
| `daedalus/sensitivity.py` (44.7 KB) | **none** — stdlib only (`re`, `os`, `pathlib`, `ipaddress`, `urllib.parse`, `dataclasses`, `collections.abc`) | **CLEAN.** Nothing upward, nothing at all. 23 non-test modules depend on it and it depends on nobody. This is the correct shape for a policy leaf and it is genuinely that shape. |
| `daedalus/budget.py` (58.7 KB) | `.sensitivity` only | **CLEAN.** One downward edge to the other leaf. |
| `daedalus/enforce.py` (3.4 KB) | `.config`, `.projects` | **CLEAN in the sense asked.** It writes an enforcement block into a repo's `AGENTS.md`; it makes no allow/deny decision. Its two dependencies resolve repo roots and init config. |
| `daedalus/spine/killswitch.py` | `daedalus.spine.cancel` only | **CLEAN.** |
| `daedalus/provider_router.py` | `.config`, `.providers`, `.router`, `.semantic_route`, `.sensitivity`, `.structcore*` | The lane guard sits **above** the fence, correctly, and pulls `structcore` in — see 2.3. |

**No low-level module imports a high-level one.** I found no case of the fence
reaching up into orchestration, the web API, or a provider.

### 2.2 The real exposure is not an import — it is the guard's process scope [V]

`budget.py`'s spend cap has two halves: declared reservations, and an
**interposer** (`install_process_guard()`, `budget.py:1184`) that monkeypatches
`subprocess.run`, `subprocess.Popen` (as a class — `budget.py:1114`, with a
measured incident about `asyncio` subclassing it) and `urlopen`.

Verified install sites — **exactly three**:

- `daedalus/cli.py:1076` — in `main()`, before subcommand dispatch, so every
  CLI verb including `daedalus web` is covered
- `daedalus/loop.py:1255`
- `daedalus/claude_bridge.py:191`

Plus `tools/operability_drill.py:186` and the tests.

Now the coupling that matters. `budget.py:1228–1282` carries `SPEND_SITES`, a
hand-plus-detector register of every place in the tree that can cost money.
**Eight of its entries name files that live under `runs/`** [V]:

- `runs/council/room.py` — `ask_codex`, `ask_fable`, `ask_opus`, `ask_agy`, `ask_ollama`
- `runs/council/summarize.py` — `cli_summariser`, `ollama_summariser`
- `runs/ab/run_arm.py` — `call_claude`

These are **real Python modules with their own entrypoints, living inside the
artefact output directory.** `ls runs/council/*.py` returns five files:
`dead_letter_replay.py`, `room.py`, `room_server.py`, `stream_hook.py`,
`summarize.py`. None of them is imported by the package; none of them installs
the guard. So the register is honest (it is explicitly annotated
`"explicit": False`, i.e. covered only if the guard is installed in that
process) but the coverage is not there.

**This is the layering violation, and it is a directory violation rather than an
import violation:** executable, spend-capable code lives in the directory that
is otherwise the agent-writable artefact sink, outside the package, outside the
import graph, and outside the process that installs the cap. `daedalus/skills.py`
(`:103`, `:219`) and `daedalus/spine/envelope.py` (`:676`, `:679`) also cite
`runs/council/*.py` as normative references. The fence's *code* is clean; the
fence's *world model* points into `runs/`.

### 2.3 A second-order note [V]

`provider_router.py` imports `structcore` and `structcore.index`. `structcore`
indexes repository source — content an agent writes. That is a routing input,
not a permit decision, and `sensitivity.py` is imported alongside it rather than
through it, so the deny path does not pass through indexed content. Worth
knowing, not worth alarm. I did not trace every call path inside
`provider_router.py`; **[C]** on anything stronger than "the import exists".

---

## 3. The artefact graph

### 3.1 Shape

**[V]** From my own grep of `runs/[a-z_]+` across `daedalus/`, 78 hits across
40 modules, resolving to these namespaces: `runs/spine`, `runs/build`,
`runs/council`, `runs/drafts`, `runs/budget`, `runs/gui`, `runs/eval`,
`runs/ab`, `runs/processed`, `runs/patches`, `runs/shift`, `runs/progress`,
`runs/canary`, `runs/ikarus`, `runs/acceptance`, `runs/arch_memory`.

There is **one module that knows the whole namespace**: `daedalus/spine/envelope.py`.
It carries a table of every run-record producer with its format, id scheme and
conversion cost (`envelope.py:100–160`) and a `UNCONVERTED_PRODUCERS` map
keyed by producer path (`:616–706`). Its own docstring states the problem
plainly: six run-record formats under six id schemes — `intent_id`, `run_id`,
`council_id`, `entry_sha`, `source_hash`, bridge `epoch` — **and no id is shared
between any two of them**. `envelope.py` adds one ambient `trace_id` alongside
them rather than unifying. So the artefact graph is *documented centrally and
implemented in fourteen dialects*, by design and with the design written down.

### 3.2 Written but never read

Verified by repo-wide grep (excluding `runs/`, `build/`, `node_modules`,
`apps/web/dist`, and the census transcripts themselves):

| artefact | producer | reader |
|---|---|---|
| `runs/last_claude_prompt.md` | `daedalus/claude_bridge.py:115` | **none.** [V] |
| `runs/last_codex_report.json` | `daedalus/providers/codex_cli.py:264` | **none.** [V] Classified in `envelope.py:692` as "latest-only", so this is intentional. |
| `runs/eval/graph_delta.json` | `daedalus/eval/graph_delta.py:505` | **none in code.** [V] Only `docs/research/GRAPH_DELTA_CALIBRATION.md` cites it. |
| `runs/gui/report.json` | `daedalus/gui/lint.py:263` | **none but itself** [V] — `lint.py:257` reads `runs/gui/*.json` back via argv. `docs/design/SLOP_METRICS_CALIBRATION.md` cites it as evidence. |
| `docs/architecture-map.html` | `daedalus/mapping/render.py` | **none** [V] — browser artefact; rv01 flagged it as a missing edge, which it is, benignly. |
| `runs/last_claude_report.json` | `claude_bridge.py:146`, `:164` | written twice, read never; the path is returned to the caller in-memory. [V] |
| `memory/offload_metrics.local.jsonl` | `daedalus/metrics.py` | **[C]** rv17's claim; not verified. |

The pattern: these are all **latest-only mirrors and evidence files for humans**,
not pipeline stages. `envelope.py` already classifies four of them as
"NOT A RUN RECORD". The correct reading is not "dead writes" but "the tree
distinguishes receipts-for-people from records-for-machines and does not label
them differently on disk".

### 3.3 Read but produced from outside the package — the one that matters

**`runs/spine/gate_discrimination.json`** [V], both sides checked:

- **Consumer:** `daedalus/spine/bootstrap.py:73`
  (`DISCRIMINATION_REL_PATH = "runs/spine/gate_discrimination.json"`), and
  `daedalus/config.py:228` makes it the precondition for auto-promotion:
  *"nothing auto-promotes until that measurement exists and is fresh against
  HEAD"* (same text ships in `templates/agentenv.json:38`).
- **Producer:** `tools/gate_discrimination.py:149` — a **script with zero
  importers**, outside the package, not reachable from any CLI verb I found.

So the artefact that authorises promotion is consumed by the package's
promotion gate and produced only by a standalone script that nothing calls.
`docs/archive/2026-07/HANDOFF_ANTIGRAVITY.md:328` and `.room/room.md:1442` both record that the
receipt on disk is currently stale against HEAD. This is the single most
significant producer/consumer asymmetry in the tree: **a safety precondition
whose producer is not part of the system that depends on it.**

Secondary, same class: `docs/architecture-state.json` is read by
`spine/bootstrap.py` and `health.py` and written by `mapping/drift.py` — both
inside the package, so that one is fine. rv07 flagged it only because its slice
could not see the writer.

---

## 4. Genuine isolation

**[V]** Zero-internal-importer modules, all cross-checked with a repo-wide grep
for string references (`importlib`, `python -m`, docs, config, `.ps1`).
220 modules have zero internal importers; 191 of those are tests. Of the 29
non-test ones, here is the honest breakdown.

### 4.1 Dead compatibility shims — five modules, zero callers [V]

| module | forwards to | referenced anywhere? |
|---|---|---|
| `daedalus/decompose.py` | `.kairos.decompose` | no — live callers use `daedalus.kairos.decompose` (`build.py:42`, `kairos/scheduler.py:311`, `tests/test_dynamic.py:16`) |
| `daedalus/drafts.py` | `.kairos.drafts` | no — live callers use `daedalus.kairos.drafts` (`cli.py:452`, `web_api.py:16`, `tests/test_drafts.py:15`) |
| `daedalus/ikarus.py` | `.kairos.scheduler` | only `docs/GO_LIVE.md:53` (`from daedalus.ikarus import Ikarus`) — a stale doc pointing at a shim |
| `daedalus/mission_control.py` | `.kairos.control` | no |
| `daedalus/orchestrate.py` | `.kairos.orchestrate` | no — but `.claude/agents/core-dev.md` still lists `orchestrate.py` as an owned file |

`.serena/memories/code_structure.md:47` records **three** shims. There are
**five**. Every one has zero importers: the migration to `kairos/` is complete
and the compatibility layer is pure carry.

### 4.2 Modules whose only caller lives outside this repository [V]

This is the finding I did not expect. `.claude/settings.json` **in this repo
contains no hook wiring at all**. But `~/.claude/settings.json` — the user's
machine-global, un-versioned file — invokes:

- `daedalus/arch_hook.py`
- `daedalus/crew_hook.py`
- `daedalus/shift_hook.py`
- `runs/council/stream_hook.py`

Four modules that are islands to every static tool, are alive in practice, and
whose call site does not survive a fresh clone. `docs/architecture-narrative.md:254`
already records this for `stream_hook.py`; it is true for three more.

### 4.3 Legitimate entrypoints (islands by construction) [V]

`daedalus/shift_ticker.py` (`python -m daedalus.shift_ticker`, documented at
`:5–6`), `daedalus/memory/__main__.py`, `daedalus/structcore/__main__.py`,
`daedalus/gui/lint.py` (`python -m daedalus.gui.lint`, `:257`),
`daedalus/eval/mutate.py`, `daedalus/runbook.py`, and all nine `tools/*.py`.

### 4.4 Genuinely dead [V]

- **`daedalus/langgraph_adapter.py`** — zero importers, zero string references
  anywhere outside itself and a Serena memory. It probes for an optional
  `langgraph` dependency that nothing asks about.
- **`daedalus/gui/__init__.py`** — empty package marker.
- **`.claude/hooks/docs-drift-reminder.py`** — zero importers, and not
  referenced from the repo's own `.claude/settings.json`.

### 4.5 The shadow tree — `build/lib/daedalus/` [V]

`build/` is gitignored (`.gitignore:43`) and **untracked** (`git ls-files build`
returns 0), yet it contains **142 stale `.py` files** — a complete second copy
of the package. `diff -q build/lib/daedalus/cli.py daedalus/cli.py` and the same
for `sensitivity.py` report no difference *today*, which is exactly what makes
it dangerous: it is a silent duplicate that will diverge and that every naive
`grep -r` in this repo hits. My own first grep in this analysis returned
`build/lib/daedalus/build.py:42` alongside the real file. Any census, audit or
LLM-driven search run over this tree without an explicit `build/` exclusion is
double-counting the entire package.

---

## 5. Duplicated responsibility

### 5.1 Three mutation engines — the repo already measured this [V]

`docs/ABSORPTION.md:679–689` states it and I confirmed the files exist and are
all islands:

| module | LOC (measured now) | LOC per ABSORPTION | oracle |
|---|---:|---:|---|
| `tools/self_test.py` | 371 | 371 | `system_check.py`'s CHECKS |
| `tools/mutation_score.py` | 740 | 740 | a test selection |
| `tools/gate_discrimination.py` | **1176** | 789 | plain `pytest tests/` |

~2,290 lines implementing seed-a-defect-and-require-a-red against three
different oracles. Note the drift: `gate_discrimination.py` has grown **49%**
since ABSORPTION measured it, so the duplication is not static — it is the
component that is actively accreting. ABSORPTION's own prescription is
"collapse three engines into one, keep three corpora", and it notes the instinct
is already "30% applied" (`gate_discrimination.py` imports
`system_check.Sandbox` and `bootstrap.CRITICAL_DEFECT_CLASSES` rather than
re-typing them). This is the strongest duplication finding in the tree and it is
one the repo has already diagnosed and not acted on.

### 5.2 Three answers to "is the system OK?" [V]

rv17 flagged `status.py` vs `doctor.py`. There are three, and the boundaries are
asserted in prose rather than enforced by structure:

| module | LOC | CLI verb | question |
|---|---:|---|---|
| `daedalus/doctor.py` | 172 | `daedalus doctor` (`cli.py:1079`) | can the bench execute right now? |
| `daedalus/status.py` | 191 | `daedalus status` (`cli.py:1100`) | what is WORKING vs merely PRESENT vs unrun |
| `daedalus/health.py` | **1893** | `daedalus health` (`cli.py:1102`) | is the SYSTEM working or merely PRESENT |

`status.py:1` and `health.py:1` open with **the same distinction in almost the
same words**. Both then carry a near-identical `RELATION TO tools/system_check.py`
paragraph (`status.py:33`, `health.py:49`) disclaiming overlap with a *fourth*
module, `tools/system_check.py` (1119 LOC). `conversation.py:98` imports
`health.py`'s outcome vocabulary rather than re-declaring it — the right move,
and evidence that `health.py` won the vocabulary argument while the other two
kept their surfaces. Four modules, 3,375 lines, one question, four CLI/entry
surfaces. Divergence here is silent by construction: nothing compares their
verdicts.

### 5.3 Two `inventory.py` — a name collision, NOT a duplication [V]

- `daedalus/mapping/inventory.py` (1048 LOC) — generates `docs/FEATURE_INVENTORY.json`
- `daedalus/tools/inventory.py` (232 LOC) — enumerates skills and MCP servers with a `vet` verdict

Different domains, unrelated code. rv17 called `tools/inventory.py` orphaned; it
is not — it is in a 2-cycle with `tools/__init__.py`. Reported here so the pair
is not "fixed" by someone merging them.

### 5.4 The spine-DB resolver pair — an intentional split, do not unify [V]

The census/review shape would flag `spine/picker.resolve_spine_db_path()` and
`spine/ledger.default_db_path()` as duplicated. **They are not.** Both docstrings
cross-reference each other and record the incident:

- `ledger.default_db_path()` (`ledger.py:151–161`) is **process-global** and
  honours `DAEDALUS_SPINE_DB`.
- `picker.resolve_spine_db_path()` (`picker.py:458–483`) is **repo-confined** and
  **deliberately ignores** that env var: *"Three queue tests once assumed
  otherwise, set the env var, and silently measured the developer's real ledger
  — red in the full suite, green alone. If you are here to 'unify' them, read
  that history first."*

`spine/envelope.py:166` calls the divergence out as live and unowned by that
module. I am recording it as **verified-intentional** specifically because it is
the kind of pair an automated duplication pass will keep re-proposing.

### 5.5 Weak / passed-through duplication leads

- **[C]** rv02: `cli.py` (`_spawn`, `_build`) vs `spine/picker.py` both doing
  decomposition/candidate generation. Not verified; the two do sit in the same
  runtime SCC, which makes it plausible.
- **[C]** rv05: `provider_router._deepseek_write_allowed` claimed as "single
  source of truth". Not verified.
- **[V, benign]** `daedalus/mapping/inventory.py` vs `docs/FEATURE_INVENTORY.json`
  hand-maintenance — the module exists precisely to end that duplication.

---

## 6. Where the census misled, for the record

- **UNWIRED is ~unusable.** It flags private helpers used in their own file
  (`render.py`'s `esc`, `_slug`, `_inline`, `_md_blocks`) and module-level
  constants (`CLASS_MEANING`, `_SLUG_RE`). rv01 and rv02 both escalated these to
  "dead code". None of the 155 lines should be actioned without a per-symbol
  grep.
- **Half the reviews report "no data".** rv06, rv08, rv12, rv13 and parts of
  rv09/rv10/rv11 are the cheap model telling you its slice was empty or too thin
  to cross-reference. Effective yield of the 20 reviews for this lane: **three
  usable leads** (status/doctor overlap, `tools/inventory.py`,
  `gate_discrimination.json` missing producer) — all three confirmed real, but
  1-in-7 of the 64 findings.
- **The census could not see `runs/` or `build/`.** Both contain Python that the
  package talks about. The census's blind spots are where two of this
  document's three most important findings live (§2.2, §4.5).

---

## 7. The picture from above, in five sentences

1. This is a **four-headed application** (CLI, HTTP, read-model, intent layer)
   over a **13-module mutually-recursive core** that is only acyclic on paper
   because 38% of its internal imports are deferred into function bodies.
2. The fence (`sensitivity.py` → nothing; `budget.py` → `sensitivity.py` only) is
   **import-clean and correctly shaped as a leaf**, and its real weakness is
   scope, not layering: spend-capable code lives under `runs/` in processes that
   never install the interposer.
3. The artefact graph is **centrally documented in `spine/envelope.py` and
   implemented in fourteen dialects with six mutually-unjoinable id schemes**;
   its one dangerous asymmetry is `runs/spine/gate_discrimination.json`, a
   promotion precondition whose only producer is an uncalled script.
4. True isolation is rarer than it looks — most "islands" are entrypoints — but
   **five dead compat shims**, **four modules callable only from the user's
   un-versioned global settings**, and a **142-file untracked shadow copy of the
   package under `build/`** are all real.
5. The load-bearing duplication is **~2,290 lines across three mutation engines**
   (already diagnosed in `ABSORPTION.md`, and the largest of the three has grown
   49% since) and **3,375 lines across four answers to "is the system OK?"**,
   whose boundaries are asserted in docstrings and enforced nowhere.
