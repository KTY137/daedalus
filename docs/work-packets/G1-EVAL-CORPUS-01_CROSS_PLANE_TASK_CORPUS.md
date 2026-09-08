# G1-EVAL-CORPUS-01 - Cross-plane eval task corpus

Packet ID: `G1-EVAL-CORPUS-01`
Artifact role: `primary`
Status: `built; focused suites green; independent review NOT yet run; not merged`
Active gate: `1`
Classification: `ALIGNED`
Owner: `repository owner`
Base revision: `db38a762991b04cbc96c3cbed5209d6a517fa611`
Dependencies: `none`
Consumers: the Gate-3 harness on `packet/g3-base-01` consumes this corpus; it
is not required to build or verify this packet.
Master-plan authority: `Revision 13`
Promotion: not requested; automatic merge, promotion, and Gate transition are
forbidden. This packet cannot open, enter, or satisfy Gate 3, and it produces
no comparative claim.

## Primary acceptance claim

**One** claim: *the eval task corpus contains tasks whose gold labels live in
the data and knowledge planes, those labels are mechanically derived from the
fixture bytes under a closed grammar rather than chosen by a human, and the
harness reports them as unmeasured instead of scoring them.*

The blocker this addresses (measured 2026-09-06, re-measured here): the frozen
task set built from `daedalus.eval.harness.all_tasks()` had a label-plane
census of `code=27, type=0, data=0, knowledge=0`
[MEASURED 2026-09-08 `runs/g1-eval-corpus-01/census.py` using the real
classifier `packet/g3-base-01@d99e2750:daedalus/eval/gate3/taskset.py`], so the
Gate-3 harness rule R3 refuses every cross-plane comparison. That is a CORPUS
gap. No amount of harness code moves it.

Three claims this packet is forbidden from making:

1. that the new tasks measure the slicer. They do not: every one of them comes
   back as a PLANE-UNINDEXED row with no recall key at all.
2. that this corpus is, or could become, the Gate-3 "public tasks" freeze. It
   is a 19-file fixture-scale smoke set (see Scope).
3. that the four planes are now all represented. The type plane stays at zero,
   deliberately (see Scope).

## Scope

In scope, and nothing else:

* `daedalus/eval/fixtures/fourfold_wiki_app/` - a byte-for-byte packaged copy
  of `examples/fourfold_wiki_app` (19 files) [MEASURED 2026-09-08
  `tests/test_eval_corpus_planes.py::PackagedFixtureTest::test_packaged_fixture_is_byte_identical_to_the_examples_copy`].
* `daedalus/eval/tasks.py` - `FOURFOLD_WIKI_FIXTURE`, the `fourfold_wiki_app`
  branch in `resolve_task_repo`, the `artifact_parsed` label provenance, the
  closed `label_derivation` grammar with `derive_labels`, and four tasks.
* `daedalus/eval/harness.py` - `_repo_chunks(root, *, planes=("code",))` and the
  PLANE-UNINDEXED row, plus its accounting in `run_tier1`/`run_arms`/`run_gate`/
  `snapshot_baseline`.
* `daedalus/eval/report.py` - the `artifact_parsed` provenance note, the
  PLANE-UNINDEXED renderer, and two summary lines that must not read as a
  clean bill of health when nothing was measured (see Contracts).
* `tests/test_eval_corpus_planes.py` (new), additive cases in
  `tests/test_eval_oracle.py`.
* Moving-census re-pins forced by adding files under `daedalus/`:
  `tests/contracts/test_import_scc_hierarchy.py`,
  `experiments/forest_v2/s02_types/test_external_corpora.py`,
  `experiments/forest_v2/README.md`, `docs/evidence/G1-EVAL-CORPUS-01/`.
* `docs/work-packets/` - this document, `index.json`, and its pins.

Explicitly OUT of scope, and why:

* **`documents=True` anywhere.** The product slicer cannot serve a document
  target usefully: `daedalus/structcore/slice.py` emits the FOCUS section only,
  skips the neighbour path for a document (`if symbol and focus_unit is not
  None and not is_doc:` - "a document has no call graph"), and emits linked
  documents as HEADING SKELETONS (`_skeleton` -> `markdown.document_skeleton`,
  in the `documents`/`documented_by` block). Turning documents on would produce
  an arm-A number for prose labels that the code structurally cannot reach.
* **Scoring arm A on a non-code target.** Same reason: it would be a structural
  property presented as a measurement - the `s08` defect of
  `docs/GATE2_FOREST_V2_TRIAGE.md` inverted.
* **Any `index_layers` task field, any change to `_whole_repo_text` or to any
  `cached_index` call.** The compression denominator does not move
  [MEASURED `tests/test_eval_oracle.py::RepoChunksPlanesTest::test_whole_repo_text_is_untouched_by_the_new_parameter`].
* **A new extension->plane registry in `daedalus/structcore/languages.py`.**
  Three classifiers already exist for three different questions
  (`daedalus/twin/extractors/registry.py`, gate3 `taskset._PLANE_EXTENSIONS`,
  gate3 `arms/separate_indices._DATA_EXTENSIONS`); a fourth global one would be
  a second source of truth.
* **A type-plane task.** No artifact of the frozen type-plane extension set
  (`.pyi`, `.proto`, `.graphql`, ...) exists in the fixture. Adding a stub file
  so a census reads four-plane would be plane laundering: the census would move
  while nothing new was measured.
* **The 17 minted quarantine tasks** in `daedalus/eval/minted_tasks.json`, which
  carry an absolute path from another host and ERROR on this machine. They are
  reported-only and were not touched.

## Contracts and behavior

**`label_provenance: "artifact_parsed"`** - labels re-derived by a
deterministic parser over the artifact, under a closed grammar, verified
plane-exclusive by test. NOT verified reachable by `semantic_slice`, and never
scored by arm A. `report._PROVENANCE_NOTE` prints exactly that on every render.

**`label_derivation`** - a closed grammar, four kinds, unknown kind raises
`ValueError`:

| kind | parameters |
| --- | --- |
| `csv_column_values` | `file`, `column` |
| `json_keys` | `file` |
| `json_string_values` | `file` |
| `markdown_section_lines` | `file`, `section`, `min_chars`, `max_lines` |

Every kind then passes the SAME five mechanical filters: dedupe (first
appearance), length >= 4, single line, drop anything that also occurs in a
fixture file of another plane, drop anything that occurs in the task's own
target unit. All comparisons case-sensitive (`harness._recall` is).
`must_include` MUST EQUAL `derive_labels(task)`; a hand-written subset is
refused by test.

**The four tasks** (tier `primary`, provenance `artifact_parsed`, no
`question` - `tier2.builtin_validator_coverage` requires a validator for every
question-bearing task and `tests/test_eval_tier2_integrity.py` asserts the
missing list is empty):

| id | target (plane) | derivation | labels |
| --- | --- | --- | --- |
| `fourfold_articles_csv` | `data/articles.csv` (data) | `json_keys` over `schemas/article.schema.json` | 5 |
| `fourfold_article_schema` | `schemas/article.schema.json` (data) | `csv_column_values` over `data/articles.csv`, column `slug` | 4 |
| `fourfold_adr_consequences_section` | `wiki/ADR/ADR-001-CSV-Storage.md::Consequences` (knowledge) | `markdown_section_lines` over the sibling `Decision` section | 4 |
| `fourfold_security_operations_link` | `wiki/Security.md` (knowledge) | `markdown_section_lines` over the linked `wiki/Operations.md` | 4 |

[MEASURED 2026-09-08 `tests/test_eval_corpus_planes.py::V2DerivationTest`]

Two derivation choices are measurements, not preferences:

* `fourfold_articles_csv` uses `json_keys`, not `json_string_values`. Both
  survive the filters non-empty (5 vs 6 labels), so both were admissible; the
  string-value survivors are the two `$schema`/`$id` URLs plus the generic
  words `object`/`string`, while the key survivors (`$schema`, `pattern`,
  `minLength`, `enum`, `additionalProperties`) are the schema's constraint
  vocabulary [MEASURED 2026-09-08 `runs/g1-eval-corpus-01/probe_derive.py`].
* `fourfold_article_schema` has 4 labels, not 5: the slug `fourfold-overview`
  is dropped by filter 4 because it also occurs in `wiki/CLI.md` (knowledge
  plane). The filter fired on real data; nothing was hand-trimmed.

**`harness._repo_chunks(root, *, planes=("code",))`** - the ONLY retrieval
extension in this packet. The default is byte-identical to the previous
behaviour [MEASURED `tests/test_eval_oracle.py::RepoChunksPlanesTest::test_default_is_exactly_the_code_plane`].
`"data"` yields one whole-file chunk per `.csv`/`.json` minus `fourfold.json`;
`"knowledge"` yields one chunk per `markdown.DocSection`, labelled
`rel::anchor`. `"type"` and any unknown plane RAISE - never a silent fall back
to the code universe.

**`harness._plane_unindexed_row`** - `plane_unindexed=True`, a `reason`, and NO
recall keys (absent, not zero), mirroring `_focus_withheld_row`'s contract:
any aggregator that forgets to filter fails with `KeyError` rather than
averaging a placeholder. Triggered BEFORE slicing when the target extension is
in the data tuple or `doc_spec_for(target)` is not None. Everything else stays
ERRORED - a primary task targeting `pyproject.toml` still fails the gate
loudly [MEASURED `tests/test_eval_oracle.py::PlaneUnindexedRowTest::test_an_unindexable_non_plane_target_is_still_ERRORED`].

`run_tier1`/`run_arms` count `n_plane_unindexed` and name the ids, and exclude
those rows from `by_provenance`; `run_gate` reports them and never fails on
them; `snapshot_baseline` skips them; `report` renders a PLANE-UNINDEXED
section in all three renderers.

**Two report lines corrected, found by running the CLI on the new corpus.**
`python -m daedalus.eval --project fourfold_wiki_app --arms` printed
`SLICE-RECALL MISSES: none -- every labelled symbol was reachable in its slice`
and `C never tied or beat A's recall on this task set` on a run in which
nothing was sliced and no arm ran. Both `else` branches now require at least
one healthy row and otherwise print an explicit `n/a - no task produced a
measured slice` / `no arm was compared`. This is in scope because this packet
is what makes an all-unmeasured run reachable
[MEASURED `tests/test_eval_oracle.py::PlaneUnindexedAggregationTest::test_an_all_unmeasured_run_does_not_print_a_clean_bill_of_health`,
and the measured-run wording is pinned unchanged by
`test_a_measured_run_still_prints_the_old_summary_lines`].

## Acceptance matrix

| # | Claim | Check | Result |
| --- | --- | --- | --- |
| A1 | packaged fixture is byte-identical to `examples/` | `test_packaged_fixture_is_byte_identical_to_the_examples_copy` (19 files) | PASS |
| A2 | fixture lives inside the installable eval package | `test_fourfold_fixture_is_part_of_the_installable_eval_package` | PASS |
| A3 | fixture planes are disjoint and cover the tree | `V1PlaneExclusivityTest` (3 tests) | PASS |
| A4 | the manifest declares nothing outside the walked universe | `test_manifest_declares_nothing_outside_the_walked_universe` | PASS |
| A5 | `must_include == derive_labels(task)` for all four | `test_every_committed_label_set_is_exactly_the_derived_one` | PASS |
| A6 | unknown kind refused; hand-written subset refused | `test_unknown_kind_is_refused`, `test_a_hand_written_subset_is_refused` | PASS |
| A7 | no label occurs in its own target unit | `V3NonVacuityTest` | PASS |
| A8 | twin oracle sees `Security.md -links_to-> Operations.md` and both `#slug` nodes | `V4TwinOracleTest` | PASS |
| A9 | corpus shape rules (provenance <-> derivation, no question, no non-`.py` `hand_reachable` target) | `V5CorpusShapeTest` | PASS |
| A10 | `_repo_chunks` default byte-identical; `whole_repo_tokens` denominator unmoved | `RepoChunksPlanesTest` | PASS |
| A11 | `planes=("type",)` / unknown raise | `test_unknown_and_type_planes_raise` | PASS |
| A12 | data/knowledge chunks exist; `fourfold.json` never a chunk | `FourfoldFixtureChunksTest` | PASS |
| A13 | plane-unindexed rows carry no recall/arm keys | `PlaneUnindexedRowTest` | PASS |
| A14 | a `.toml` target still ERRORS and still fails the gate | `test_an_unindexable_non_plane_target_is_still_ERRORED` | PASS |
| A15 | aggregation counts, excludes, reports; forgetting to filter raises | `PlaneUnindexedAggregationTest` | PASS |
| A16 | gate reports and does not fail; baseline skips | same class | PASS |
| A17 | reports render ASCII with the new section; zero rows add no section | same class | PASS |
| A18 | import-graph census re-pinned, components unchanged | `tests/contracts/test_import_scc_hierarchy.py` | PASS |
| A19 | s02 corpus pin re-measured from two identical runs | `experiments/forest_v2/s02_types/test_external_corpora.py` | PASS |
| A20 | registry re-rendered and consistent | `tools/index_work_packets.py --check`, `tests/contracts/test_work_packet_index.py` | PASS |
| A21 | an all-unmeasured run prints `n/a`, never "no misses"; a measured run is unchanged | `test_an_all_unmeasured_run_does_not_print_a_clean_bill_of_health`, `test_a_measured_run_still_prints_the_old_summary_lines` | PASS |

Commands and results: see Evidence below.

### The measured census, before and after

Classifier: the real Gate-3 one, read-only from
`packet/g3-base-01@d99e275061f9044c946185449ec3b4ee7831dcee`
(`daedalus/eval/gate3/taskset.py`), copied into
`runs/g1-eval-corpus-01/g3probe/` and never imported by production code.

| Census | Before | After |
| --- | --- | --- |
| primary-only (what `build_frozen_taskset` freezes) | `code=10, type=0, data=0, knowledge=0` | `code=10, type=0, data=2, knowledge=2` |
| all tasks incl. quarantine | `code=27, type=0, data=0, knowledge=0` | `code=27, type=0, data=2, knowledge=2` |

[MEASURED 2026-09-08 `.venv/Scripts/python.exe runs/g1-eval-corpus-01/census.py`,
retained as `docs/evidence/G1-EVAL-CORPUS-01/census.log.gz`]

**Correction to this packet's own brief.** The brief quoted `code=27` as the
frozen census. Measurement says 27 is the census over ALL tasks; the frozen set
is primary-only (`filter_primary_tasks` excludes the 17 quarantine-tier minted
tasks), so the frozen census was `code=10`. Both numbers moved on the data and
knowledge axes by the same +2/+2, so the blocker is addressed either way, but
the number recorded here is the measured one.

## Migration and rollback

Additive. No existing task, label, baseline entry or number changes:
`daedalus/eval/baseline.json` is untouched (the four new tasks never reach it -
`snapshot_baseline` skips plane-unindexed rows), `_whole_repo_text` is
untouched, and `_repo_chunks`'s default output is byte-identical.

Rollback is `git revert` of the single commit. Two things do NOT roll back
automatically and must be re-measured if the fixture is removed: the
`CENSUS_MODULES`/`CENSUS_EDGES` pins (490/1943) and the s02 kernel corpus pin
(490 files / `c2e4150f...`). Both are moving censuses of the tracked tree, and
both are re-measured by running the commands named in Evidence.

Migration risk that was measured and avoided: `daedalus.eval.tasks` importing
`daedalus.eval.harness` (the shape the design sketch assumed) enlarges the
existing `(daedalus.eval, harness, report, tier2)` import cycle to five members
and moves `CURRENT_COMPONENTS_SHA256` from `841a5a97...c2140a78` to
`b45b3cc6...bfa9cbdb` [MEASURED 2026-09-08
`runs/g1-eval-corpus-01/what_if_edge.py`]. The two data-plane tuples are
therefore defined in `tasks` and imported by `harness`; the fixture walk takes
`_IGNORE_DIRS` from `daedalus.structcore.index`, the original that
`harness._IGNORE_DIRS` mirrors (both sets measured identical, 23 entries).

## Evidence, expected failures and review

All commands run from the packet worktree with the repository venv
(`C:/Users/Administrator/Desktop/projects/daedalus/.venv/Scripts/python.exe`),
offline, no provider call, `runs/budget/ledger.json` untouched.

Baseline before any code change (rebased onto `db38a762`):

```
python -m pytest -q -p no:cacheprovider <the 13 focused suites>
-> 1 failed, 316 passed, 2 skipped, 466 subtests passed
   FAILED tests/contracts/test_import_scc_hierarchy.py::test_observation_contract_breaks_the_next_cross_domain_scc
   (assert 490 == 485 -- the WIP commit's packaged fixture already moved the census)
python -m pytest -q -p no:cacheprovider experiments/forest_v2/s02_types/test_external_corpora.py
-> 1 failed, 7 passed  (corpus_pin 490 != 485)
```
[`runs/g1-eval-corpus-01/baseline-focused.log`, `baseline-s02.log`]

After:

```
python -m pytest -q -p no:cacheprovider <the same 13 focused suites + tests/test_eval_corpus_planes.py>
-> 362 passed, 2 skipped, 494 subtests passed in 90.25s
python -m pytest -q -p no:cacheprovider experiments/forest_v2/s02_types/test_external_corpora.py
-> 8 passed
```
[`runs/g1-eval-corpus-01/after-focused.log`, `after-s02.log`]

A second, wider sweep of the 23 other test files that import `daedalus.eval`
or `daedalus.structcore.markdown` ran green after the change (`445 passed,
4 skipped, 25 subtests passed`,
`runs/g1-eval-corpus-01/after-related.log`). No baseline was captured for that
sweep, so it is stated as "green after", not as "no regression versus a
measured baseline".

The FAILED/ERROR line diff between baseline and after is: two baseline
failures, zero after, none new. Both baseline failures were the moving censuses
this packet re-measures.

Retained evidence, with SHA256s in
`docs/evidence/G1-EVAL-CORPUS-01/acceptance.json`: both complete s02 probe runs
(identical except `wall_seconds`/`root`; canonical non-timing SHA256
`b6e04216e2355df1c990bf017c73e7e1892de01037068d8f43f173034739f281`), the
comparison log and the census log.

**Expected failures, recorded before they can be spun as successes:**

1. Every one of the four new tasks is UNSCORABLE today. Tier 1 and all three
   arms return PLANE-UNINDEXED; `by_provenance` for a run over only these
   tasks is `{}`, not a bucket of zeros [MEASURED
   `test_run_tier1_counts_and_excludes_them`]. The census moves; no number
   about retrieval quality moves, because none was produced.
2. The type plane stays at 0. See Scope.
3. `harness._bm25_tokenize` splits on non-identifier characters, so a
   hyphenated slug (`revision-atomicity`) is never a single BM25 token and a
   prose line never is either [MEASURED `test_no_label_is_a_single_bm25_token`].
   A future BM25 arm over these planes will have to match multi-token labels;
   that is a property of the labels, stated now rather than discovered later.
4. The 17 minted quarantine tasks still ERROR on this host (absolute path from
   another machine). Untouched, reported-only.
5. Non-`.py` fixture files are not declared in `[tool.setuptools.package-data]`,
   so a built wheel ships the fixture's five `.py` files but not its CSV/JSON/
   Markdown [UNVERIFIED - no wheel was built in this packet; the test asserts
   on-disk location only, exactly as the `sunny_garden` test does].

**Deferred to a packet stacked on `packet/g3-base-01`, and named as deferred:**
the gate3-side wiring - the `dict`->`Task` bridge, `corpus_planes` on the arms,
the runner refusal when a requested plane has no retrieval universe, and a
label digest in `FrozenTaskSet`. None of it exists on this branch and this
packet neither provides nor claims it. Whether a Gate-3 BM25 arm over
`planes=("code","data","knowledge")` can actually score these labels is
UNVERIFIED: the chunks exist and are tested, the arm does not.

**Review status:** builder verification only (section 10 step 4). Independent
review (step 5), adversarial verification (step 6) and system CI (step 7) have
NOT been run for this packet. No owner decision requested.
