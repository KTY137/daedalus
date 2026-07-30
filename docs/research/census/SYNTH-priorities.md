---
title: Census synthesis — gaps and priorities
type: synthesis
status: draft
updated: 2026-07-30
lane: gaps-and-priorities
---

# Census synthesis — what is missing, what is half-built, what to do next

Lane: **gaps and priorities**. Structure/coupling and claims-vs-reality are two
other synthesists' jobs and are not attempted here.

Inputs: `runs/eval/census300/_census.json` (300 purposes, 155 `UNWIRED`, 92
`SMELL`), `docs/research/census/reviews/*.md` (20 reviews), the night-shift
record `docs/research/NIGHT_SHIFT_2026-07-30.md`, and
`docs/wiki/feature-backlog.md`.

Everything below is marked **[V]** verified by me in this session, or **[P]**
passed through from an input without independent verification.

---

## 0. Calibration first: the UNWIRED tag is 95.5% noise

The census's `UNWIRED` lines were mechanically checked against the whole tree
(2,000 source/doc files; `.git`, `node_modules`, `build/`, `dist/`, `.captures/`
and the census's own output excluded so the census could not cite itself).

154 unique `(file, symbol)` candidates parsed from the 155 lines. **[V]**

| Verdict | Count | Why it is not a finding |
|---|---:|---|
| Called by production code in another file | 60 | not unwired at all |
| Used normally inside its own file | 51 | private helper — the failure mode the brief predicted |
| A pytest test function or `TestCase` subclass | 33 | collected by pytest, called by nobody by design |
| **The symbol does not exist in the file** | 3 | hallucinated (`render.StatusWord`, `gated_writes._artifact_root_functions`, one more) |
| **Survivor — worth acting on** | **7** | |

**Elimination ratio: 147 of 154 eliminated — 95.5% false positive.** Treat a
future `UNWIRED` line as a search hint with a ~1-in-20 hit rate, never as a
deletion warrant.

Three specific eliminations are worth naming because they were plausible:

- `daedalus/core.py::_gov_discrimination` / `_gov_write_confinement` — both
  called at `core.py:798-799`. **[V]**
- `daedalus/kairos/gated_writes.py::_PromotionLock` / `_provider_receipt` /
  `_artifact_root_for` — all three called (`:944`, `:1224`, `:1161`). The
  census's matching `SMELL` line ("suggesting dead code") is wrong three times
  over. **[V]**
- Every `daedalus/cli.py::_*` subcommand — all dispatched from the argv
  switch at `cli.py:1083-1142`. **[V]**

### The `__all__` claims are hallucinated, and this was checkable in one pass

Four census lines assert an `__all__` entry with no definition
(`containment.JobLimits`, `worktree.remove_tree_no_follow`,
`progress_sources.snapshot_from_bridge`, six names in `gui_catalogue`). I
AST-parsed **every** module in the tree that declares `__all__` — 81 of them —
and resolved each exported name against the module's bindings. **Zero real
defects.** The only two unresolved names, `structcore/__init__.py`'s
`semantic_slice` and `estimate_tokens`, are served by a PEP 562 module-level
`__getattr__` at `structcore/__init__.py:85`. **[V]**

So: 0 for 4 on `__all__`, and the check that settles it costs about forty lines
of `ast`. That check is worth keeping.

### The tag also has false negatives

The census did **not** flag `daedalus/eval/graph_delta.py::specificity` — the
false-alarm arm of the fitness function — which has no caller, no test, and
sits below the module's `if __name__ == "__main__"` block. See item 3. **[V]**

### The 20 cross-file reviews are close to worthless

Six of the 20 (`rv06`, `rv08`, `rv09`, `rv12`, `rv13`, and most of `rv10`,
`rv11`, `rv16`) report that they were given one shard and could not do
cross-file analysis at all. The remainder mostly restate `UNWIRED` and `SMELL`
lines with "verify this" attached. I found **no finding in the 20 reviews that
survived verification and was not already in the census or in NIGHT_SHIFT**.
The structural cause is the same one NIGHT_SHIFT already named for the
100-agent wave: fan-out by file means no two agents share enough context to
disagree. A "cross-file review" that receives one file's slice is a
mis-specified job, not a weak model.

---

## 1. Genuinely unwired code — the 7 survivors

A survivor has no reference from any non-test, non-doc file, and no use inside
its own file beyond the definition.

| File | Symbol | Verdict |
|---|---|---|
| `daedalus/eval/mutate.py` | `SKIP_PATH_PARTS` | dead — see item 2 |
| `daedalus/eval/mutate.py` | `SKIP_FUNCTIONS` | dead — see item 2 |
| `daedalus/eval/mutate.py` | `_is_display_constant` | dead — see item 2 |
| `daedalus/eval/mutate.py` | `_looks_like_a_guard` | dead — see item 2 |
| `daedalus/memory/embeddings.py` | `_embed_batch` (`:433`) | dead compat helper |
| `daedalus/kairos/evolution.py` | `EvolutionaryOrchestrator` | island, confirmed still true |
| `daedalus/langgraph_adapter.py` | `build_graph` | island, zero importers anywhere |

Found by hand, missed by both the census and my automated pass:

- `daedalus/eval/mutate.py::covered_lines` and `::_in_main_block` — also dead.
  My scan scored `covered_lines` as live because `tools/gate_discrimination.py`
  defines a *different* function with the same name (the live one). A
  name-collision blind spot in token-frequency reachability; worth knowing. **[V]**
- `daedalus/eval/graph_delta.py::specificity`, `::commit_shas`,
  `::measure_commit` — reachable only from each other. **[V]**
- `daedalus/wiki/links.py::unlinked_mentions`, `::local_graph`, `::backlinks` —
  re-exported by `daedalus/wiki/__init__.py` and exercised by `tests/test_wiki.py`,
  with **no production consumer** and nothing in `daedalus/web_api.py`. My scan
  counted the `__init__.py` re-export as a consumer; it is not one. **[V]**

---

## 2. Half-built things

### 2a. The generated architecture map already answers this better than the census

`docs/architecture-state.json` is produced by `daedalus.mapping.drift` and
carries a machine list of islands, shims and test-only modules. At its recorded
revision it names 8 islands, 3 shims, 7 test-only, 1 unknown. That file is the
right instrument; the census is not. **[V]**

But it is **stale**: it records head `7955317`, HEAD is `7a5fb07`, and 44 files
under `daedalus/` changed between them. Concretely, at HEAD its classifications
are already wrong in at least one case it names: it lists
`daedalus/compaction.py` as `unknown` / `test_only`, while
`daedalus/health.py` imports it — and commit `5175eba` says compaction was
retired. `daedalus/spine/picker.py:1002` records a real incident where an agent
acted on exactly this stale `compaction.py` entry. **[V]**

### 2b. Confirmed islands and near-islands

- **`daedalus/kairos/evolution.py` — still an island. [V]** Imported only by
  `tests/test_evolution_baseline.py`, `tests/test_kairos_evolution.py`,
  `tests/test_kairos_archive.py`. Backlog is accurate.
- **`daedalus/langgraph_adapter.py` — a true island. [V]** Zero importers in
  the entire tree, including tests. Referenced only in
  `docs/FEATURE_INVENTORY.json` and `docs/architecture-narrative.md`.
- **`daedalus/gui_catalogue.py` — island. [V]** Only `tests/test_gui_catalogue.py`.
  The "AVAILABLE PARTS as a StructCore node kind" idea has no prompt consumer.
- **`daedalus/kairos/shadow_shell.py` — reached only from `evolution.py`
  (itself an island) and `kairos/worktree.py`. [V]**
- **`daedalus/memstore.py` — imported only by council tests. [V]**

Three modules the map lists as islands are **not** islands at HEAD by import:
`preservation.py` (imported by `daedalus/verifier.py`), `skills.py` (by
`daedalus/tools/inventory.py`), `council/publish.py` (by `daedalus/cli.py`).
Islandhood is transitive reachability from an entry point, not "has an
importer", so this is evidence the map is stale rather than proof it is wrong —
but it is another reason to regenerate before acting on it. **[V]**

### 2c. Parsers with no consumer

- **The data layer.** `daedalus/structcore/artifacts.py` exposes one function to
  production — `extract_literals`, called from `graph_delta.py:436` inside a
  `try/except ImportError` — and nothing else. `compare_schema` is tested only;
  `SCHEMA_FROM_CODE` is used nowhere but its own file. It is not wired to the
  index or the forest. **[V]**
- **The DSS score-transfer layer.** `build_forest_hierarchy` is live
  (`structcore/__init__.py`, `forest.py`). But `restrict_scores`,
  `prolongate_scores`, `carry_temporal_scores` and `diffuse_relation_scores` —
  the actual multigrid operations — have **tests and no production consumer**.
  The hierarchy is built and nothing rides on it. **[V]**
- **The wiki query layer.** `backlinks` / `unlinked_mentions` / `local_graph`
  exist, are tested, are re-exported, and reach no surface. **[V]**

### 2d. Features behind flags nobody sets

`DAEDALUS_INDEX_TYPES`, `DAEDALUS_INDEX_WIKI` — both real, both default-off, both
correctly reported by `types_enabled` / `wiki_enabled` / `documents_enabled` in
`structcore/index.py`. `knowledge_links` is now called at `index.py:735` behind
the wiki gate, so the backlog's "fixed 2026-07-30" is accurate. **[V]** Nothing
here is a defect; it is the intended cost posture. Recorded so the next reader
does not re-file it.

---

## 3. The priority order

Ranked by blast radius: wrong result → money → egress → blocks promotion →
untidy. Ten items. Each names a file and the smallest change.

---

### RANK 1 — WRONG RESULT · the write-mode gate's ground truth includes files no agent touched

**File:** `daedalus/offload.py:48-77` (`_SNAPSHOT_SKIP`, `_repo_snapshot`)

`_repo_snapshot` `rglob("*")`s the entire repo root and content-hashes every
file under 400 KB. Its skip set is
`{".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache",
".pytest_cache", ".ruff_cache", ".daedalus_worktrees"}` — no rule for
gitignored trees and no rule for dot-directories generally.

This working tree contains **`.captures/` — 1.2 GB of captured Microsoft Edge
browser profiles**, gitignored, including `Default/Login Data`,
`Default/Login Data For Account` and `Default/Network/Cookies`. **[V]**

The before/after diff of that snapshot becomes `result["wrote"]`, which the code
itself labels *"GROUND TRUTH for callers: which files this task really changed
on disk"* (`offload.py:491`), and which then arms the test gate via
`changed_for_tests` (`offload.py:510`). So:

1. any file a *browser* (or any other process) writes during an offloaded run is
   attributed to the worker;
2. the "write-mode work MUST actually change files — otherwise it's a silent
   no-op" check can be satisfied by churn the agent did not cause;
3. two full hashes of a 1.2 GB tree run per write-mode call.

`tools/mutation_score.py:95` already knows — its comment literally reads
*"`.captures` alone is 1.2 GB"* and it excludes the directory. The knowledge
exists in the repo and did not reach the gate.

**Smallest change:** build the snapshot from `git ls-files -z` (plus explicitly
declared `--paths`) instead of `rglob`, so an untracked tree can never be
attributed to a worker. If that is too large a step, add `.captures` and a
"skip any directory starting with `.` that is not explicitly allowed" rule to
`_SNAPSHOT_SKIP`. A test that plants a file in a gitignored directory during the
run and asserts it does not appear in `result["wrote"]` pins it.

---

### RANK 2 — WRONG RESULT · the mutation corpus's no-go filters never run

**File:** `daedalus/eval/mutate.py:57-150` and `:316-374`

Lines 57–150 are a section headed
`# NO-GO FILTERS — refuse a worthless mutant BEFORE generating it`, with the
comment *"Each rejection is COUNTED and named, so the filter can be audited
instead of trusted."* It defines `SKIP_PATH_PARTS`, `SKIP_FUNCTIONS`,
`_DISPLAY_CALLS`, `GUARD_NAMES`, `_in_main_block`, `_is_display_constant`,
`_looks_like_a_guard` and `covered_lines`.

`generate()` — the only public producer — applies **exactly one** filter,
`trivially_equivalent`, and `generate.last_rejected` can therefore only ever
contain one key. Not one of the six no-go helpers is referenced anywhere in the
tree. **[V]**

Consequences: mutants are generated on `__repr__`, `__str__`, `main`, `render`
and `describe`; log/format string constants are mutated as if they were
behaviour; and `covered_lines` — whose own docstring says a mutant on an
uncovered line is *"a GUARANTEED survivor"* that *"only dilutes the score"* — is
never consulted. Any held-out detection rate measured over this corpus is
measured over a corpus the module's own documentation says should not exist.
Direction of bias is not established here; the point is that the number does not
mean what the docstring says it means.

**Smallest change:** wire the four site-level filters into the `for path, rel,
node, fn_src in sites:` loop at `:344`, incrementing `rejected[<name>]` per
skip. If they are deliberately retired, delete them and correct both the
section header and `docs/wiki/feature-backlog.md:71` ("no-go filters" is
currently listed as *built*). Leaving them defined-but-unused is the worst of
the three options: it reads as a guarantee.

---

### RANK 3 — WRONG RESULT · the fitness function's specificity arm has no entry point

**File:** `daedalus/eval/graph_delta.py:516-604`

`commit_shas`, `measure_commit` and `specificity` are defined **after** the
module's `if __name__ == "__main__":` block at `:511`. They are called by
nothing: not `main()`, not `run()`, not `tests/test_graph_delta.py`, not
`tools/`. **[V]**

`docs/wiki/feature-backlog.md:70` reports "false alarm 0.9% (refs pure-deletion)
and 0.7% (structure-only)" as part of the **built** graph-delta entry. There is
no committed command that regenerates those two numbers and no test that would
notice if the code beneath them broke. A fitness function whose sensitivity arm
is measured and whose specificity arm is unreachable will happily approve a
change that trips every layer.

**Smallest change:** add a `--specificity` branch to `main()` at `:500` that
writes `runs/eval/graph_delta_specificity.json`, plus one test that runs
`specificity(limit=5)` against the repo and asserts the shape of the result.
Then re-stamp the two numbers in the backlog with the receipt path.

---

### RANK 4 — MONEY · budget accounting stops under concurrency

**File:** `runs/budget/ledger.json` writer path (`daedalus/budget.py`,
`daedalus/provider_router.py`) — **[P]** reproduced in NIGHT_SHIFT §4, not
diagnosed, not re-derived here.

Kept at this rank because it is the only item in the list that loses money
silently. NIGHT_SHIFT correctly commissioned a reproducing test rather than a
guessed fix; that test is the smallest next change. One observation that may
narrow it and costs nothing to check: `daedalus/loop.py`'s ledger write uses
`os.replace`, which NIGHT_SHIFT already flags as `PermissionError`-prone on
Windows when a concurrent reader holds the file — if the budget ledger uses the
same read-modify-write-replace shape, forty concurrent writers are a
last-writer-wins race, not a missing call.

---

### RANK 5 — EGRESS · the allow list is a path pattern over an untracked tree

**Files:** `.agentenv/agentenv.json` (`policy.allow`), and the egress path
resolver.

The live policy is `default_deny: true` with
`allow: ["docs/", "/tests/", "test_", ".md", "readme", "daedalus/"]` and
`external_write_lanes: []`. **[V]**

Two exposures share one root cause — the allow list matches **paths**, and the
working tree contains material that is not part of the project:

1. **Known, unchanged:** `runs/council/room.md` is allowed because `.md` is on
   the list and it holds the full cross-vendor transcript.
2. **New:** `.captures/` (1.2 GB, untracked, Edge profiles) contains files
   matching `.md` — e.g.
   `.captures/edge-after/Default/Extensions/…/README.md` — and sits beside
   Chromium `Login Data` and `Cookies` databases. **[V]** I did **not** verify
   that the fence's path resolver can be pointed there; callers pass explicit
   paths and no code path I found enumerates `.captures`. Rank it as a standing
   hazard, not a demonstrated leak.

**Smallest change:** make egress candidacy require the path to be **git-tracked**
before the allow/deny lists are consulted. That is one predicate, it closes the
whole untracked-tree class, and it leaves `room.md` — which *is* tracked — to be
decided on its merits by Cerberus, as already planned. Independently:
`.captures/` at 1.2 GB inside the repo root is a hazard to every tool that walks
the tree, and moving it outside the repo is cheaper than teaching five ignore
lists about it (see Rank 10).

---

### RANK 6 — BLOCKS PROMOTION · the loop's queue is 90% suppressed, right now

**File:** `docs/architecture-state.json`, `docs/FEATURE_INVENTORY.json`

Measured, not inferred — `daedalus.spine.picker.build_queue(repo_root=".")` at
HEAD: **[V]**

```
n candidates: 2   (both source='docref')
notes:
  MAP SUPPRESSED (11 candidate(s) withheld): ... written against 7955317… but HEAD is 7a5fb07…
  INVENTORY SUPPRESSED (7 candidate(s) withheld): ... written against 73454a3… but HEAD is 7a5fb07…
```

Eighteen of twenty candidates are withheld. The suppression is **correct** —
`map_state_trustworthy` fails closed for exactly the reason its own docstring
records — but the effect is that the self-improvement loop is choosing from
docrefs only. This is upstream of "the loop promotes nothing": before the
gate-discrimination receipt matters, there is almost nothing in the queue to
promote.

**Smallest change:** regenerate both (`python -m daedalus.mapping.drift --refresh`
and the inventory generator) as the first act of the next session, and commit
them together with whatever else lands so the stamp matches. See Rank 7 for why
that is harder than it sounds.

---

### RANK 7 — BLOCKS PROMOTION · the freshness stamp is unsatisfiable by construction

**File:** `daedalus/spine/picker.py:877` (`_repo_state_freshness`)

Commit `7a5fb07` is titled *"docs(inventory): re-stamp against the committed
HEAD"*. It changed exactly one file, `docs/FEATURE_INVENTORY.json`, stamping it
with `73454a3` — and by landing, it **became** the new HEAD, `7a5fb07`,
immediately invalidating the stamp it had just written. **[V]**

That is not an oversight, it is a fixed point that does not exist: any workflow
that (a) stamps a generated file with the current HEAD and (b) commits that
file, can never produce a fresh stamp. The inventory's 7 candidates are
therefore withheld permanently under the current process, and the last commit in
the repo is a failed attempt to fix precisely this.

**Smallest change:** relax the freshness predicate from *equality* to
*ancestor-with-no-relevant-diff*: a recorded head is fresh if it is an ancestor
of HEAD **and** `git diff --name-only <recorded> HEAD -- <the paths the
generator scans>` is empty. That makes a doc-only commit non-invalidating, keeps
the fail-closed behaviour for real source drift, and needs no change to the
generators. The alternative — stamping post-commit via a hook — trades one
correctness property for a hook everyone will eventually disable.

---

### RANK 8 — BLOCKS PROMOTION · the gate-discrimination receipt

**File:** `runs/spine/gate_discrimination.json` — **[P]** known, from
NIGHT_SHIFT §7 and the backlog. Needs a green sandbox baseline; not re-derived.

Sequence matters: this is worth regenerating **after** Rank 6, because a
regenerated receipt against a queue with two candidates promotes nothing useful
even if it discriminates perfectly.

---

### RANK 9 — UNTIDY, HIGH VALUE · four islands and one dead helper

All confirmed by whole-tree grep. **[V]**

| File | Symbol(s) | Smallest change |
|---|---|---|
| `daedalus/langgraph_adapter.py` | `build_graph` | delete the module, or state in one line what would call it |
| `daedalus/gui_catalogue.py` | whole module | wire `render_for_prompt` into the GUI prompt path, or retire |
| `daedalus/kairos/evolution.py` | `EvolutionaryOrchestrator` | leave; ADR-015 already declares it a Best-of-N baseline with preconditions |
| `daedalus/memory/embeddings.py` | `_embed_batch` (`:433`) | delete |
| `daedalus/eval/mutate.py` | `covered_lines`, `_in_main_block` | resolve with Rank 2 |

`evolution.py` is listed for completeness, not as work: the backlog and
`docs/adrs/015-ariadne-preconditions.md` both already say what it is. Deleting
an island whose ADR explains it is a regression in understanding.

---

### RANK 10 — UNTIDY · five divergent tree-ignore lists

**Files:** `daedalus/structcore/index.py:62`, `daedalus/mapping/switches.py:38`,
`daedalus/offload.py:48`, `daedalus/structcore/slice.py` (its own list, per its
docstring at `:231`), `tools/mutation_score.py:103`.

Each defines its own skip set; only `mutation_score.py` knows about
`.captures`; only `index.py` skips dot-directories generally. Rank 1 is the
expensive consequence of this divergence, and the next one will be a different
tool walking a different 1.2 GB.

**Smallest change:** one `daedalus/ignore.py` predicate (a module of that name
already exists and is imported by `index.py` as `project_scope`) that all five
consult, with each caller's extra entries passed in. Do this **after** Rank 1,
not instead of it — the safety-critical caller should not wait on a refactor.

---

### Deliberately not ranked

- `MAX_REWRITE_CHARS = 24_000` blocking the four largest modules — real, already
  in NIGHT_SHIFT §4 and the backlog, and it is a design decision (patch-based
  write path) rather than a defect to schedule.
- The 92 `SMELL` lines. Sampled a dozen; they are almost entirely "this module
  has several responsibilities" applied to modules whose docstrings explain why.
  Two are factually wrong in the same way the `__all__` claims are. No item in
  this list came from a `SMELL` line, and I would not commission work from them.
- `cancel.py` `Popen`/`_LIVE` race, `picker.py` band starvation, `loop.py`
  `os.replace`, `docrefs.py` suffix binding, `typegraph.py` `PlainNaming` —
  **[P]** all from NIGHT_SHIFT's confirmed list, all outside what I verified.
  One caution below.

**One NIGHT_SHIFT "CONFIRMED" finding appears to be false.** §3 lists
`memory/embeddings.py` as promising `search_report`, `ingest_report` and
`record_journal_watermark` in its docstring and **not implementing them**. They
are implemented — as *methods*, at `embeddings.py:1402` (`search_report`) and
`:963` (`record_journal_watermark`). **[V]** The claimant appears to have looked
for module-level functions. Do not schedule work to implement them. This is one
sample, but it is a reminder that CONFIRMED means "a second look agreed", which
NIGHT_SHIFT itself says is short of a fact.

---

## 4. What the backlog gets wrong

Line references are to `docs/wiki/feature-backlog.md` as of 2026-07-30.

| Line | Says | Actually | Suggested status |
|---|---|---|---|
| 71-72 | Mutation generator **built** — "six AST operators, deterministic, **no-go filters**, trivial-compiler-equivalence check" | six operators and the equivalence check run; **none of the no-go filters do** (Rank 2) | **partial** — say "no-go filters defined, not wired" |
| 69-70 | Graph delta **built**, "false alarm 0.9% … and 0.7%" | the specificity arm that produces those numbers has no entry point and no test (Rank 3) | keep **built** for the sensitivity arm; mark the false-alarm numbers *unreproducible pending an entry point* |
| 26 | Data layer **partial** — "`structcore/artifacts.py` exists, unwired to the index" | accurate on the index, but understated: `extract_literals` *is* consumed by `graph_delta.py:436`, so the fitness function already depends on it | keep **partial**, add "one function consumed by `eval/graph_delta`" |
| 168-169 | "**`knowledge_links` was unwired** — fixed 2026-07-30, gated behind `DAEDALUS_INDEX_WIKI`" | correct — `index.py:735` calls it behind `_WIKI_ENV` | no change |
| 170-171 | "**`kairos/evolution.py` is an ISLAND**" | correct, still true | no change |
| 170-171 | evolution.py is the **only** island named | the generated map names 8 islands + 3 shims + 1 unknown; `langgraph_adapter.py`, `gui_catalogue.py`, `memstore.py`, `kairos/shadow_shell.py` are confirmed | add the list, or point the reader at `docs/architecture-state.json` |
| 166-167 | Known blockers: "**Ignition** … the gate-discrimination receipt" | true but incomplete — the more immediate blocker is that **18 of 20 queue candidates are suppressed** and one of the two suppressions is unsatisfiable by construction (Ranks 6, 7) | add both |
| 111-115 | Cold start source 2: "`wiki_code_links` already computes both; the query does not exist yet" | accurate — and `backlinks`/`unlinked_mentions`/`local_graph` exist, are tested, and have no production consumer | no change; note the three functions are already there |
| 134-135 | "**Shift / working window** — built" | I did not verify. NIGHT_SHIFT §3b records an agent importing `ShiftManager` from `daedalus.shift` when the class is `Shift` — that is the *agent's* error, not the backlog's | no change; flagged only so nobody re-files it |
| 157-159 | "**Open exposure**: `runs/council/room.md`" | true, and there is a second instance of the same class: the allow list is a path pattern and `.captures/` (untracked, 1.2 GB, browser profiles with `Login Data`) is inside the repo root (Rank 5) | widen the entry to "the allow list matches paths in an untracked tree" |
| 92-101 | Write-lane constraints table | matches NIGHT_SHIFT exactly | no change |

Two entries the backlog is missing entirely and should have:

- **The DSS score-transfer functions are tested and unconsumed** —
  `restrict_scores`, `prolongate_scores`, `carry_temporal_scores`,
  `diffuse_relation_scores`. The hierarchy is built; nothing rides on it. This
  belongs under "the four graphs" as **partial**.
- **The generated map is stale and its own consumer knows it** — worth a
  standing "known blockers" line, because it is the input to the picker's two
  richest candidate sources.

---

## 5. Method notes

- **Grep the tree before believing a reachability claim.** 147 of 154 candidates
  died on one whole-tree pass. The pass took minutes.
- **A token-frequency reachability check has two known blind spots**, both hit
  here: a same-named symbol in another module scores a dead one as live
  (`mutate.covered_lines`), and an `__init__.py` re-export scores an unconsumed
  symbol as consumed (`wiki/links.unlinked_mentions`). Neither is fatal; both
  need to be stated when a number is reported.
- **Prefer the repo's own instrument to a model's.** `daedalus.mapping.drift`
  answers "what is an island" mechanically and transitively. Three hundred agent
  slices answered it worse, at cost, and hallucinated three symbols that do not
  exist. The right use of the census was to *suggest* where to point the
  instrument.
- **Ask the running system, not the document.** The single most decisive fact in
  this report — 2 candidates, 18 withheld — came from calling `build_queue()`
  once. No amount of reading would have produced it.
