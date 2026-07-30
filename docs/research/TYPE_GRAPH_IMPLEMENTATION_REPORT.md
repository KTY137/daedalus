# The type/data-structure graph: what was built, what it refuses, what is still open

2026-07-30 · `daedalus/structcore/` · plan:
[`TYPE_GRAPH_AND_KNOWLEDGE_SPACE_PLAN.md`](TYPE_GRAPH_AND_KNOWLEDGE_SPACE_PLAN.md), Teil A
(Stufe 1, Python only) · status: **built, tested, NOT committed** (working tree only)

## Read this paragraph before any other

**No thermometer failed. No test was skipped. No test is currently red.** 426 tests over
nine files pass (407 + 19, run in two invocations, raw numbers below), including the three
regression thermometers the plan called non-negotiable. Four things must be said in the
same breath, because each of them makes a claim above weaker than it sounds:

1. **The adversarial invariant hunt found a real violation of invariant I5** — three
   distinct false-edge paths through `from module import *` — and it was **fixed** inside
   `typegraph.py` and pinned with 19 tests. One related case is **still open by
   construction** (an explicit binding in a file that also stars an *invisible*, outside-
   the-repo module still resolves; refusing it would mean refusing every explicit binding
   in any file that has a star import).
2. **Thermometer T1's off-vs-on comparison is structurally blind to an UNGATED leak.** Per-
   file extraction is deliberately not gated, so a leak on the extraction side appears
   identically in both builds and every byte-identity assertion passes. That case is caught
   only by the *absolute* assertions sitting next to each identity assertion. A RED
   injection proved it: 25 failures fired, and **not one of them was a byte-identity
   assertion**. Deleting the absolute half as "redundant" would delete the only half that
   sees an ungated leak.
3. **The hub-cap fan-in tables are INHERITED, not re-measured here.** They were measured
   once, on 2026-07-29, against a 143-file snapshot of `daedalus/`, before the layer
   existed. Nothing in the test suite freezes them. The cap *value* (64) is in the code and
   is exercised by tests; the *distribution that justifies it* is not.
4. **The tree moved under the measurements.** A second agent system (Codex) was editing
   `daedalus/` throughout this run, and during the build phase `typegraph.py` itself was
   transiently broken (`NameError: json`) and transiently non-deterministic (rows ordered
   out of a `set`) while a sibling lane edited it. Both are gone as of this pass — I re-ran
   the whole suite and re-measured determinism myself — but every absolute count in this
   report is a **snapshot of a moving tree** (156 Python files today, 143 at
   pre-measurement time), not a frozen baseline. The frozen baselines live in the fixture
   corpus, which no other agent touches.

Verdict on keeping it: **safe to keep** — reasoning at the end, not here.

---

## 1. What was built

Everything is stdlib-only. No new dependency. `typing.get_type_hints` is never called
(it executes imports — an egress violation in this codebase).
Line counts below are [MEASURED 2026-07-30, `git diff --numstat` against `HEAD` = 7a5fb07].

| File | Change | Role |
|---|---|---|
| `daedalus/structcore/parse.py` | **+958 / −0** (pure append) | Extraction: `TypeDecl`, `FieldDecl`, `ParamDecl`, `SignatureDecl`, `AliasImport` → `PyTypeFacts`; annotation *normalization* (`normalize_annotation`, `flatten_union`, `split_generic`, `union_id`, …). New hot path `python_units_imports_and_types()` — **one** `ast.parse`, three walks. `extract_units` / `_units_from_tree` / `python_units_and_imports` untouched (the 0 deletions is the proof). |
| `daedalus/structcore/typegraph.py` | **new, 1139 lines** | Whole-repo resolution: two passes (register every declaration, then resolve annotations) over a **new `types_by_file` table**, producing `has_field` / `field_type` / `inherits` / `consumes` / `produces` / `alias_of` edges in a `type:` / `field:` node namespace, plus a coverage record. Imports nothing but `.parse`. |
| `daedalus/structcore/index.py` | +168 / −10 | Three gated keys `types` / `type_nodes` / `type_edges`; `types_enabled()`; `+types` in `_scope_key` at all three call sites; per-file extraction on the cached parse path, whole-repo resolution serial in the parent. |
| `daedalus/structcore/perfile.py` | +48 / −4 | `FileAnalysis.type_facts`; `ANALYSIS_VERSION` **3 → 5**. |
| `daedalus/structcore/cache.py` | +91 / −2 | Hand-written positional codec for `type_facts`; `_SCHEMA` **1 → 2**. |
| `daedalus/structcore/forest.py` | +180 / −4 | Node kinds `type` / `field`, one relation layer per published relation. `module_ids` does **not** grow — type ids live in a separate `type_ids` set. (The 4 deleted lines are docstring.) |
| `daedalus/structcore/dss.py` | +77 / −5 | Hardening: `build_context_plan` validates node **KIND**, not just membership; `_relation_adjacencies` filters diffusion to file-kind endpoints. |
| `daedalus/structcore/__main__.py` | +23 / −1 | `--types` flag and a coverage summary that prints the **refusals**, not just the edge count. |
| `daedalus/structcore/markdown.py` | +385 / −13 | Teil B / K1 backend: Obsidian-flavored `[[wikilink]]` parsing and resolution. **Unwired** — see §7. |
| `daedalus/structcore/__init__.py` | +23 / −1 | Public exports: `types_enabled` (stage 3) plus, in this chronicle pass, `TYPE_NODE_KIND`, `FIELD_NODE_KIND`, `RELATIONS`, `DEFAULT_HUB_CAP`, `TypeGraph`, `resolve_type_graph`, `type_node_id`, `field_node_id`, `is_type_node_id`. The extractor's records (`PyTypeFacts` and friends) stay unexported, exactly as `CodeUnit` is — `parse` is an internal producer, not public vocabulary. |
| `tests/fixtures/typegraph/` | new, 16 files + README | The adversarial fixture corpus: one named hazard per file. |
| `tests/test_typegraph_*.py`, `tests/test_markdown_wikilinks.py` | new, 9 files, 6769 lines | The suite. |

Versions, all bumped in the same working tree as the change that needs them:
`ANALYSIS_VERSION = 5` · `cache._SCHEMA = 2` · `TYPE_FACTS_VERSION = "1"` (extractor) ·
`TYPE_GRAPH_VERSION = "1"` (resolver — separate on purpose: a resolution fix does not
change what was extracted, and a reader must be able to tell which half produced a number).
[MEASURED 2026-07-30, read out of a live build]

### The gate, and why the default is OFF

`types=True` / `DAEDALUS_INDEX_TYPES=1` / `--types`; default **off**. Not because the
layer moves a denominator (it does not — that is what the thermometers prove) but because
the moment `forest.py` reads `type_nodes`, the forest gains nodes and relation layers and
therefore a different `content_sha256` [MEASURED: `347b9ffe…` → `c36aeb2e…`]. Every
consumer that hashes or counts the forest would move for a feature nobody asked for.
Flipping the default is a deliberate re-baselining decision.

**Extraction is deliberately NOT gated.** Gating it would put the flag on the wrong side
of a content-keyed disk cache: a layer-OFF-warmed row served to a layer-ON build yields
`count: 0`, `n_edges: 0`, `attempts: 0` — no error, no exception, no log line. That failure
was **reproduced** during the build phase, which is why the decision is load-bearing rather
than a preference. `ExtractionIsNotGated::test_file_key_carries_no_types_segment` is the
tripwire that fires first if anyone moves it.

---

## 2. The six invariants: mechanism, test, verdict

### I1 — `type`/`field` are forest nodes ONLY, never `CodeUnit`s, never in `all_units`, never seen by a clone pass

*Why it matters:* `all_units` feeds `renamed_clusters` — an exact match on an abstracted
fingerprint, **no threshold, no max_cluster**, reported in the *precise* tier. The repo's
~176 dataclasses would have produced identical fingerprints per field count and been
published as high-confidence "renamed clones".

**Enforced** structurally, three ways: the extraction diff has **0 deletions** (the unit
predicate is the same bytes it was); `TypeDecl`/`FieldDecl`/`SignatureDecl`/`ParamDecl`
carry **no `source` and no `loc` field**, so a leak into `all_units` raises `AttributeError`
in `clones.fingerprint` instead of publishing clusters; and `index.py` routes
`a.type_facts` only into `type_facts_by_rel`, never into `all_units`.

**Tested:** `UnitsAreUntouched` (units byte-identical through the new entry point vs both
old entry points), `test_a_type_record_is_not_shaped_like_a_code_unit` (reads
`dataclasses.fields`, so it cannot go vacuous), `T1DuplicationIsByteIdentical` +
`T1DuplicationIsByteIdenticalOnANonEmptyTree`, `TheCatastropheIsReal::
test_three_dataclasses_as_units_become_one_renamed_cluster` (feeds three dataclasses to
`clones.renamed_clusters` **as** CodeUnits and measures the false cluster appearing: count
3, kind `renamed`, names Alpha/Beta/Gamma — so the number T1 protects is in the record).

**Verdict: HOLDS.** Red-verified: admitting `ast.ClassDef` to the unit predicate fires 13
failures in the parse suite and 44/25 in the thermometer file (gated/ungated injection).

### I2 — `SymbolResolver.defs_by_file` stays untouched; resolution uses a separate `types_by_file`

*Why it matters:* `resolve` takes the FIRST match on a name collision (a class `Foo`
displaces a function `Foo`), and `callees` resolves EVERY identifier token — field names
like `path`, `root`, `name`, `line`, `source` are in no stopword list and would become CALL
edges in `slice_text`. Second order: `context_plan._symbol_names` reads `defs_by_file`
whole into the BM25 corpus, so field names would systematically down-weight the
dataclass-rich files by length normalization.

**Enforced:** `typegraph.py` imports only `__future__`, `builtins`, `dataclasses`, `typing`
and `.parse` — it *cannot* reach `graph.py`. `build_resolver` is still called with exactly
`all_units + doc_units`.

**Tested:** `T2DefsByFileIsByteIdentical` (+ the second-tree variant), `TheResolverIsUntouched`,
`TheResolverTableIsSeparate` (snapshots `defs_by_file` and re-asserts equality after two
resolves; inspects `typegraph.py`'s own AST for any `build_resolver` / `SymbolResolver` /
`defs_by_file` reference — via AST rather than grep, precisely because the docstrings name
those members on purpose), `test_every_name_in_the_table_came_from_extract_units`,
`test_the_six_generic_identifiers_are_not_resolvable`, and the **T3** class for the second
order: `lexical_seed_scores` byte-identical for seven objectives, plus
`test_a_field_name_query_matches_nothing_it_should_not`.

**Verdict: HOLDS**, verified independently by the implementer, by the thermometer lane and
by the adversarial hunt (which additionally checked a query built entirely of field names:
`"field path root name line source module"` — byte-identical output).

### I3 — `type` never joins `FILE_NODE_KINDS`; a type node is never a packable context item

*Why it matters:* `_estimated_tokens` would invent a cost (`loc * 8`) for a node with no
bytes on disk, and the token accounting becomes fiction.

**Enforced, and upgraded from a config default to a structure during this run.** Before:
the only thing preventing it was `DSSConfig.unknown_relation_weight = 0.0`. Now
`build_context_plan` raises `KeyError "not a packable node kind"` for a known id whose kind
is not in `FILE_NODE_KINDS`, while still raising `"unknown Forest node ID"` for a typo —
two distinct errors, so a regression in the first lock becomes a stack trace instead of a
fabricated 8-token cost.

**Tested:** `test_type_and_field_are_not_file_node_kinds` (asserts the frozenset literally),
`ATypeNodeCannotBePacked`, `TheHierarchyIgnoresTypeNodes` (hierarchy byte-identical on/off),
`test_the_phantom_cost_this_guard_prevents_is_real` (records that `_estimated_tokens`
*would* have returned 8 — the number the guard prevents is in the record).

**Verdict: HOLDS.** Note the behaviour change this implies: `build_context_plan` now raises
for a non-file-kind node where it previously packed it. Nothing inside `dss` can trigger it
(diffusion is file-only), so it is a second lock, not a live path.

### I4 — type nodes never enter `modules`, `import_edges` or `_graph_nodes`; the fence's denominator stays code-only

*Why it matters:* 333 type nodes in the denominator would lower `fenced_dominance.fraction`,
the stand-down threshold would stop firing, and every task would stay on the premium lane.
That costs real money for a false reason.

**Enforced:** `forest.py` writes to no index key and does not widen `module_ids`; node ids
live in a `type:` / `field:` + `#` namespace and are refused if they collide with a module
id or fall outside the namespace; the layer's own file count is **nested** as
`types.n_files` so it cannot collide with the index's top-level `n_files`.

**Tested numerically, not just by name:** `TheFenceDenominatorCannotMove`,
`TheFileHalfDoesNotMove`, and the adversarial hunt's own probe — `fenced_dominance` is
byte-identical under **13 fence spellings across four repos**, including non-trivial
fractions on a frozen center-scoped snapshot (0.1376 kairos, 0.1074 spine, 0.7987 tests/,
0.1111 synthetic), so the probe is demonstrably not vacuous
[INHERITED 2026-07-30, adversarial hunt, a throwaway probe script — NOT in the test suite,
so nothing re-runs it; the suite's own `TheFenceDenominatorCannotMove` covers the set
identity but not those four fractions]. Four dedicated forest tests
pin that a type id named in the import layer, the document layer, `co_change` or a clone
hyperedge produces **no** edge. Chronicle re-measurement [MEASURED 2026-07-30]: with the
layer on, exactly three keys are added and of the 17 shared keys exactly one moves —
`scope_key`, which is the gate doing its job; `imports` stays at 122 edges either way.

**Verdict: HOLDS.**

### I5 — unresolved OR ambiguous → NO edge, counted

*Why it matters:* deterministic and arbitrary are not the same thing. `resolve` taking the
first sorted import produces a *stably reproduced false edge*.

**Enforced:** there is no tie-break anywhere in `_Resolver`. Zero candidates → `unresolved`;
more than one → `ambiguous`. Two import bindings that DISAGREE are refused even when only
one of the two modules is visible; agreeing `if TYPE_CHECKING` duplicates still resolve.
Builtins and external declarations are counted in their **own** buckets, never folded into
`unresolved`, and `attempts` is asserted to equal the sum of the six buckets.

**Tested:** `AmbiguityIsRefusedAndCounted`, `UnresolvedIsCountedNotGuessed`, `RefuseToGuess`,
`ItSaysWhatItRefusedToDo`, `CoverageIsHonest`,
`test_no_refused_site_produced_an_edge` (checked **per site** — `(module, line, nominal)` —
not per name, because `Result` is legitimately ambiguous in one file and resolved in
another, so a name-level check would have been vacuous), plus `PositiveControls` so that
"refuse everything" cannot pass.

**Verdict: VIOLATED, FOUND, FIXED — see §5.** As it now stands: holds, and the fix is
pinned by `tests/test_typegraph_star_imports.py` (19 tests).

### I6 — the hub cap is measured and published BEFORE the layer becomes a DSS channel; the foundation ships a LENS

**Enforced:** none of the six relation names appears in `dss.DEFAULT_RELATION_WEIGHTS`, and
`_relation_adjacencies` filters diffusion to file-kind endpoints — so the type relations
cannot produce a channel *by effect*, not merely by name. The cap (`DEFAULT_HUB_CAP = 64`)
applies to `consumes`/`produces` only; `has_field`/`inherits`/`alias_of` are declaration
structure, bounded by declaration count.

**The number, and its honesty:** 64, chosen off a **measured plateau** — see the plan's
invariant 6, now carrying the full distribution. On `daedalus/` the cap **suppresses
nothing** (max fan-in 33 vs cap 64), because in a resolve-only graph the eight hub types
(`str`, `None`, `Any`, `dict`, `int`, `Path`, `bool`, `float`) never arrive: not one of
them is *declared* here. The index publishes `hub_cap`, `hub_suppressed_edges` and
`edges_before_hub_cap` **anyway**, so a reader can tell "nothing was dropped" from "85% was
dropped".

**Tested:** `HubCap` (rebuilds at `hub_cap=2` and asserts both suppression AND reporting —
which is how a cap that is inert on this repo is still proven to work), `TheLensIsNotAChannel`
(two files that share a type and import nothing produce zero channels; every channel dict
byte-identical on/off), `test_relations_are_disjoint_from_dss_weights`.

**Verdict: HOLDS**, with the caveat in the opening paragraph: the *justifying distribution*
is inherited, not re-measured, and is not frozen by any test.

### Stufe 1 = Python only [M8]

`coverage.languages` reports `{"python": "supported", "javascript": "not_supported"}` —
a **string** per language, never a numeric zero, because a zero would claim "we looked and
found nothing" where "we did not look" is the truth. Asserted by type against `daedalus/`
(which ships JavaScript) and against a mixed py/js/ts/go tree.

---

## 3. Raw test results

Every number below is a literal pytest tail line from this pass [MEASURED 2026-07-30].
No full-suite run was performed (another agent system is running tests concurrently in the
same tree; the constraint for this run forbade it). Nothing outside the type-graph and
wikilink files was run.

```
$ python -m pytest tests/test_typegraph_parse.py tests/test_typegraph_resolve.py \
      tests/test_typegraph_index.py tests/test_typegraph_forest.py \
      tests/test_typegraph_fixture.py tests/test_typegraph_regression.py \
      tests/test_typegraph_determinism.py tests/test_markdown_wikilinks.py -q
407 passed, 1703 subtests passed in 157.87s (0:02:37)

$ python -m pytest tests/test_typegraph_star_imports.py -q
19 passed, 5 subtests passed in 4.36s
```

Per file (collected counts, `--collect-only -q`):

| File | Tests | Covers |
|---|---:|---|
| `tests/test_typegraph_fixture.py` | 20 | baseline tripwires: the corpus + the pre-layer index/resolver state |
| `tests/test_typegraph_parse.py` | 67 | extraction and normalization |
| `tests/test_typegraph_resolve.py` | 95 | resolution, refusals, hub cap, namespace, coverage |
| `tests/test_typegraph_index.py` | 64 | index blocks, gate, cache round trip, additivity |
| `tests/test_typegraph_forest.py` | 53 | forest layers, packability, lens-not-channel |
| `tests/test_typegraph_regression.py` | 30 | **the three thermometers** |
| `tests/test_typegraph_determinism.py` | 43 | D1–D5 determinism and refusal counters |
| `tests/test_typegraph_star_imports.py` | 19 | the I5 fix (§5) |
| `tests/test_markdown_wikilinks.py` | 35 | OFM wikilink parsing/resolution (Teil B) |
| **total** | **426** | 0 failed, 0 errors, **0 skipped** |

**Failures seen EARLIER in this run and no longer present** (recorded so the record is not
prettier than the history): during the verify phase, 8 tests in
`test_typegraph_resolve.py` / `test_typegraph_index.py` were red, and a determinism probe
produced three different digests across `PYTHONHASHSEED` 0/1/12345. Cause: a sibling lane
was rewriting `typegraph.py` live — `NameError: name 'json' is not defined`, then
`[_keyed[k] for k in set(_keyed)]`, then `list(set(unresolved_sample))[:25]` (worse than an
ordering bug: the truncation means *which* rows get published varies per process). All
three are gone in the current file; the sibling's own `sorted(set(...))` two lines below
proved it was a one-word slip. This pass re-ran everything and re-measured determinism.

### Determinism, measured rather than asserted

Seven fresh interpreters over six `PYTHONHASHSEED` values including `random`, plus one run
forced onto the parallel scan path, produce **one** sha256 over a payload that names each
ordered thing separately (`type_edge_order`, `field_child_order`, `union_ids`,
`language_key_order`, `forest_content_sha256`, `forest_node_order`, `forest_edge_order`,
plus the whole `types` block). On mismatch the test reports the JSON path of the first
difference and maps it to the line of code whose iteration leaked.

RED verification of the determinism suite
[INHERITED 2026-07-30, verify phase; breaks reverted, source files sha256-restored, not
re-run here]: **13 breaks injected one at a time, 11 fired.**
The 2 that did not are documented in the module docstring as findings rather than hidden:
(a) deleting the early return after the `sites_any` counter changes nothing, because bare
`Any` has empty `members` and the `if not ann.members` branch two lines down already
refuses — the operative guard is in `parse.py`, and the two tests that break `parse.py`
instead both fire; (b) iterating a `set` over union members changes nothing, because the
final sort by `(source, target, attributes)` screens member order off from output — and
breaking *that* sort fires 5 failures.

---

## 4. The three regression thermometers — verdicts

All three build the SAME tree twice, layer OFF then ON, in one process, and assert
byte-identity of a pre-existing artifact.

| # | Artifact | Invariant | Verdict |
|---|---|---|---|
| **T1** | `index["duplication"]` (all four sub-blocks separately) | I1 | **GREEN** — never fired against real code |
| **T2** | `build_resolver(...).defs_by_file` (+ `imports_by_file`) | I2 | **GREEN** |
| **T3** | `context_plan.lexical_seed_scores` — the real entry point `plan_context` calls, against the real built index, no mock | I2, second order | **GREEN** |

Because the fixture corpus's `duplication` block is **completely empty** by construction
(every function is below every clone pass's `min_loc`), off-vs-on there compares two empty
dicts. So the thermometers additionally run against a second, generated tree (4 files,
three same-arity dataclasses + one real duplicate function) whose `duplication` block is
non-empty in `unit_clusters`. T3 carries an explicit non-vacuity test (`_symbol_names`
returns >10 names, so the BM25 corpus is really populated rather than degraded to
path-terms) and a ranking-observability test (more than one module scores, so
`_normalise_max` cannot hide a re-ranking behind `{x: 1.0}`).

**RED verification** — four leaks injected into a backed-up `index.py`, one at a time,
each run against the whole thermometer file
[INHERITED 2026-07-30, verify phase; the injections were reverted and are NOT re-runnable
from the tree as it stands — the numbers below are that lane's raw pytest lines, not this
pass's]:

| Injection | Result |
|---|---|
| A: type decls → `all_units`, only when `types=True` | **44 failed**, 21 passed |
| B: type decls → `all_units`, **unconditionally** | **25 failed**, 27 passed — *and not one failure was a byte-identity assertion* |
| C: type+field names → `defs_by_file`, only when `types=True` | **64 failed**, 22 passed |
| D: type+field names → `defs_by_file`, **unconditionally** | **50 failed**, 26 passed |

No case produced "no test fired". `index.py` was restored and byte-compared (sha256
`cd33092dd436cd85…`), and a grep for the injection markers returns 0.

**Residual limit of T3, stated rather than papered over:** it cannot see a leak that changes
only documents scoring exactly zero for all seven objectives. The second tree's
`test_a_field_name_query_answers_nothing` covers that case where field names are unique by
construction; on the fixture corpus it is a residual gap.

---

## 5. What the adversarial hunt found

### FINDING 1 — CRITICAL, invariant I5 — **FIXED**

`typegraph._Resolver._star_candidates` / `_resolve` treated a **single star-import
candidate as a resolution**. Three demonstrated false edges, each reproduced on a
two-or-three-file repo. The per-repo counts in (A) and (B) are
[INHERITED 2026-07-30, adversarial-hunt measurement, not re-run in this pass]; the
blast-radius zero is re-asserted by a live test in every suite run:

- **(A) `__all__` ignored.** `lib.py` declares `__all__ = ['Public']` and also
  `class Hidden`; `user.py` does `from lib import *` and annotates `b: Hidden`. The layer
  emitted `consumes user.py → type:lib.py#Hidden`. `Hidden` is a `NameError` at that site.
  **85 files in this repository declare an `__all__`.**
- **(B) leading underscore.** A star never binds `_Private` absent `__all__`. The edge was
  emitted anyway. **81 files here declare an underscore-prefixed type.**
- **(C) invisible star.** A file that stars both a visible in-repo module and an external
  package resolved the annotation to the visible one with `ambiguous == 0` — i.e. the
  answer was a property of the environment, which is the identical argument the code
  already accepts for the `try/except ImportError` pair.

This also contradicted `parse.py`'s own published contract (">=2 star imports means
AMBIGUOUS: no edge"), so it was a divergence from a written rule, not merely a missed case.

**The fix:** a star can prove an AMBIGUITY, never a BINDING. Star candidates are still
generated (two stars that both declare a name is a provable ambiguity, and naming the
candidates makes the gap actionable), but a candidate reached *only* through a star returns
`AMBIGUOUS` with its candidate listed, and an explicit binding that DISAGREES with a star
candidate is refused too. Counted as `ambiguous` rather than `unresolved` so the candidate
survives into `ambiguous_sample`.

**Blast radius, measured: zero.** No file under `daedalus/` uses `import *` (0 of 155 at fix
time; `TheBlastRadiusIsMeasured::test_no_file_under_daedalus_uses_a_star_import` pins it, so
the cost has to be re-argued if one ever appears). The only star-import file in the tree is
the fixture `ambiguous_result_star_import.py`, whose two stars both declare `Result` and
which therefore was and remains ambiguous — every captured fixture literal is unchanged.

### RESIDUAL 1 — **STILL OPEN, by construction, not a regression**

An **explicit** binding in a file that ALSO stars a module outside the repo still resolves.
The unseen module's exports cannot be enumerated. Refusing it would mean refusing every
explicit binding in any file that has a star import. Documented in `_star_candidates`'
docstring.

### BLOCKER — recovering the star path needs shared, cache-coupled code

To resolve stars honestly the layer needs `__all__`, which is a bare module-level
assignment that `parse.py` deliberately does not record. The minimal patch is three parts
that must land in ONE commit or not at all: (i) `PyTypeFacts.exports` +
`has_dunder_all` populated from a literal `__all__` (anything computed sets
`has_dunder_all=True` with empty `exports`, which must then **refuse**, not permit);
(ii) `ANALYSIS_VERSION` 5 → 6 in the same commit, because it changes what a cached row
means; (iii) `cache._enc_facts`/`_dec_facts` extended positionally and `_SCHEMA` 2 → 3.
**Do not slip parts of this in separately.**

### Everything else the hunt attacked, and held

I2, I3, I4 and I6 held under every attack constructed, including **forged index blocks**
[INHERITED 2026-07-30, adversarial hunt; the forged-block refusals are also pinned by
`TheGatesRefuseRatherThanRepair` in `tests/test_typegraph_forest.py`, which runs green in
this pass]: a `type_nodes` row claiming `kind: "source_file"` is refused; a row whose id is a plain path
(`kind_zoo.py`, `sneaky/path.py`) is refused by the namespace check; a `type_edges` row
forged to be file→file is refused by the forest endpoint gate; a type layer cannot smuggle
rows into the reserved `imports` layer. I1 held over a **497-file byte-identity sweep** of
units and import records [INHERITED 2026-07-30, adversarial hunt; the suite's own sweep in
`UnitsAreUntouched` covers the 16 fixture files, not 497].

### Two observations that are NOT this layer's bugs, but are now reachable through one more flag

- **`index.resolution_context(root)` called WITHOUT a key** falls back to the bare-root
  `_RESOLVER_CACHE` entry, so with the layer on (key `root+types`) it returns `None` and
  `context_plan._symbol_names` silently degrades to an empty BM25 symbol corpus. Identical
  pre-existing behaviour for `+docs`; every in-repo caller passes `key=idx["scope_key"]`,
  so nothing is broken today. It is the same "degrade silently" shape the review flagged.
- **`cache._decode` turns `py_imports`' nested tuple of names into a list**, so
  `_decode(_encode(a)) != a` for any file with imports. Pre-existing, blessed by cache.py's
  own comment as shape-compatible, and inert (the whole index is byte-identical warm vs
  cold, asserted). The new `type_facts` codec explicitly re-tuples every tuple field and
  does not inherit the asymmetry.

---

## 6. What the layer reports about itself

[MEASURED 2026-07-30, `build_index("daedalus/", types=True)`, serial scan, 156 Python files.
Snapshot of a tree being edited concurrently — not a frozen baseline.]

**Structure:** 333 type declarations · 1734 fields · 2067 nodes · 2599 edges
(`has_field` 1734, `field_type` 102, `inherits` 34, `consumes` 339, `produces` 390,
`alias_of` 0).

**Resolution buckets** (`attempts` == sum of the six is asserted by a test):

| Bucket | Count | Meaning |
|---|---:|---|
| `resolved` | 864 | an edge was emitted |
| `builtin` | 5605 | `str`, `int`, … — counted, never folded into `unresolved` |
| `external` | 619 | declared outside the repo |
| `unresolved` | 24 | **refused and named** in `unresolved_sample` |
| `ambiguous` | 0 | — |
| `vocabulary` | 0 | typing/ABC words with no binding at all |
| **`attempts`** | **7112** | |

The 24 unresolved are honest gaps, not failures: the bulk are module-level aliases written
as a bare assignment (`AgentEvent = Union[...]` in `adapters/events.py`,
`PromptMode = Literal[...]` in `adapters/subprocess_adapter.py`) which `parse.py` refuses
to mint as a declaration, because at module level `X = ...` is usually a constant. Widening
detection to "bare assignment whose RHS is a Union/Optional/Literal/generic subscript"
would recover them — but that is a `parse.py` change and therefore cache-key coupled
(needs an `ANALYSIS_VERSION` bump in the same commit).

**Annotation coverage:** returns 2330/2410 = **96.7 %** (plan baseline 97 %
[INHERITED 2026-07-29] — holds) · params 3822/4161 = **91.9 %** · fields 1500/1734 =
**86.5 %**. Sites total 8398 (annotated 7745, missing 653, `Any` 188, `Any` nested 674,
`None` 266, no member 465, union 169, **unparsed 0**). `dropped_keys` **646** — the number
of times a `dict[K, V]` key type was dropped, published rather than discarded, so nobody
reads a `str` number as a total when it is a lower bound.

**Guards:** `hub_cap` 64 · `hub_suppressed_edges` 0 · `hub_suppressed_types` [] ·
`duplicate_declarations` 0 · `files_truncated` [] · `truncated` false ·
`structural_matches` 1 (`min_members` 2 / `max_matches` 25) · `structural_overmatched` [] ·
`future_annotations_files` 138 · `languages` `{"python": "supported", "javascript":
"not_supported"}`.

**Additivity:** exactly three keys added; of 17 shared keys exactly one moves (`scope_key`).
Forest 157 → 2224 nodes (`source_file` 157 unchanged, +333 `type`, +1734 `field`) and
122 → 2721 edges (`imports` stays 122).

**Cost** [INHERITED, stage-3 measurement, not re-measured here]: +0.48 s extraction over
152 files (≈3.1 ms/file, **cache MISS only**) and +0.28 s resolution.

---

## 7. Teil B / K1: the wikilink backend is built and UNWIRED

`markdown.py` parses `[[Note]]`, `[[Note#Heading]]`, `[[Note|alias]]`, `![[embed]]`,
`[[code:path#symbol]]`, `[[type:Name]]` — and does **not** parse the same syntax inside a
fence or inline code. Resolution (`wiki_lookup`, `resolve_wiki_target`,
`resolve_wiki_links`, `knowledge_links` → `KnowledgeLinks`) keeps doc→doc, doc→code and
deferred type refs in separate buckets and refuses to guess: unresolved targets are dropped
and counted; a target matching more than one file (bare-name collision, or a path readable
both vault-root-relative and document-relative) emits **no** link and counts as `ambiguous`
— which is exactly the thermometer B-M2 demanded; `[[type:]]` / `[[vault:]]` count as
`deferred`, never as unresolved. 35 tests green.

**`internal_links` — what `index.py` actually consumes — is deliberately unchanged.** So no
existing document edge moves, and no new edge exists either: wiki edges reach no caller.
Two decisions belong to whoever wires it: (1) the wiring itself is an `index.py` edit; (2)
`n_links_unresolved` in the module entry should become three keys
(`unresolved` / `ambiguous` / `deferred`) rather than one sum — collapsing them re-merges
three claims this module deliberately keeps apart. Note also that `documents_enabled` is
still default-off (B-C3), so none of this executes in the web path until a knowledge
endpoint asks for `documents=True` per call.

---

## 8. Open questions

1. **Commit hygiene.** Nothing here is committed. The parse/perfile/cache trio
   (`ANALYSIS_VERSION` 5, `_SCHEMA` 2) MUST land as one commit — a partial landing serves
   stale cache rows to new code and returns empty type blocks with no error. Memory records
   commit hygiene as an already-open CRITICAL in this repo; this change is exactly the
   shape that makes it bite.
2. **Is the hub cap allowed to stay unfrozen?** The value is in the code and tested; the
   distribution that justifies it is a one-off measurement, inherited and not re-run. If
   the cap is ever going to gate a DSS channel, the fan-in measurement should become a
   script under `eval/` that a test can re-run, not a paragraph.
3. **`field_type` is a seventh relation name not in the plan's fixed list.** It is
   `REL_FIELD_TYPE`, so renaming is a one-line change — but *someone must decide* whether
   the plan's vocabulary is normative. Same question for `instantiates`, which is not built
   (it needs the call graph) and whose absence is pinned by a test.
4. **`consumes`/`produces` attach to the FILE node, not to a function node**, because
   functions are not forest nodes today; the function identity travels in
   `attributes.function` / `function_ref`. If a future lane makes functions first-class
   forest nodes, these edges must be re-pointed, and every consumer that read the file-level
   source will move.
5. **Recovering `import *` honestly** requires the three-part `__all__` patch in §5. Should
   it be built, or should star imports stay a permanently reported gap? Blast radius today
   is zero.
6. **`resolution_context` without a key degrades silently** with `+types` exactly as it does
   with `+docs` (§5). Worth turning into a loud failure, in its own lane.
7. **Consumer benefit is unmeasured.** The layer is a lens with no routing influence — the
   state the plan asked for, but the A/B comparator (fixed token budget, random-edge control
   arm, n-floor for "treatment never applied") is unbuilt, and until it exists nobody may
   claim the layer helps.
8. **The default stays OFF until someone re-baselines.** Turning it on changes the forest's
   `content_sha256` and therefore every DSS receipt and every forest-hashing consumer.
9. **`daedalus/structcore/artifacts.py` and `tests/test_artifacts.py`** appeared untracked
   in this working tree during this run. Not part of this lane, not touched, not imported
   by anything here — flagged so they are not attributed to it.

---

## 9. Verdict: is this safe to keep in the tree right now?

**Yes — safe to keep, with two conditions and one honest limitation.**

The evidence, not the optimism:

- All three regression thermometers are green against real code and were **red-verified
  four ways** against injected leaks. The layer is additive: three keys added, one key
  moved (the scope key, by design), `imports`/`duplication`/`defs_by_file`/`fenced_dominance`
  byte-identical.
- The default is **OFF**. A build that does not ask for `types=True` gets, by construction,
  the exact index and forest it got before — not by a flag test but because the resolution
  and publication code never runs. The only unconditional change is per-file *extraction*,
  which is guarded by `ANALYSIS_VERSION 5` + `_SCHEMA 2` and is asserted byte-identical warm
  vs cold.
- The one real invariant violation found (I5, star imports) is **fixed and pinned**, and
  its blast radius on this repo is measured at zero.
- The fence denominator — the one that costs money if it moves — was checked *numerically*
  under 13 fence spellings on four repos with non-trivial fractions, not merely by asserting
  a set difference.

**Condition 1: land the cache trio atomically.** `parse.py` + `perfile.py` (`ANALYSIS_VERSION`)
+ `cache.py` (`_SCHEMA`) in one commit. Splitting them is the documented silent-empty-block
failure.

**Condition 2: do not flip the default to ON as a side effect.** That is a re-baselining
decision with a measured consequence (forest `content_sha256` moves), and it must be taken
deliberately, with the eval baselines re-cut in the same breath.

**Limitation, repeated because it is the thing most likely to be forgotten:** T1's off/on
comparison cannot see an *ungated* leak — only the absolute assertions beside it can. If a
later cleanup deletes those as redundant, this foundation loses its most important tripwire
and nothing will fail to tell you.

Nothing needs to be reverted before the loop runs against this tree.
