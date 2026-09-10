# Result — six arms repaired; the plane hint turns out to be worth one cell

Status: MEASURED 2026-09-10
Classification: EXPERIMENT (Gate-3 prework; active delivery gate is 1)
Packet: G3-ARM-PLANE-01
Design: `docs/G3_ARM_PLANE_REPAIR_PREREGISTRATION_20260910.md`, frozen before the
run, plus Amendment 1 (six arms, not two) appended before results were read.
Instrument: `experiments/g3_arm_plane/measure.py`; raw `runs/g3_arm_plane/report.json`.

## 1. Verdicts against the frozen table

| arm | verdict |
| --- | --- |
| `embeddings` | **`REPAIRED_CLEAN`** (row 2) |
| `bm25` | **`REPAIRED_WITH_REGRESSION`** (row 3) |

Zero errored trials across 252 cells.

## 2. Per-arm × per-plane × per-rung — never a single mean

`before` = code-only default. `A` = all retrievable planes (the primary repair).
`B` = code + the task's label plane (the sensitivity variant).

| arm | rung | plane | before | A (all) | B (hint) |
| --- | ---: | --- | ---: | ---: | ---: |
| bm25 | 1000 | code | 0.600 | **0.767** | 0.600 |
| bm25 | 1000 | data | 0.000 | 0.000 | **0.500** |
| bm25 | 1000 | knowledge | 0.000 | **0.500** | 0.500 |
| bm25 | 4000 | code | 0.800 | 0.800 | 0.800 |
| bm25 | 4000 | data | 0.000 | **1.000** | 1.000 |
| bm25 | 4000 | knowledge | 0.000 | **1.000** | 1.000 |
| bm25 | 16000 | code | 0.867 | *0.833* | 0.867 |
| bm25 | 16000 | data | 0.000 | **1.000** | 1.000 |
| bm25 | 16000 | knowledge | 0.000 | **1.000** | 1.000 |
| embeddings | 1000 | code | 0.400 | **0.433** | 0.400 |
| embeddings | 1000 | data | 0.000 | **1.000** | 1.000 |
| embeddings | 1000 | knowledge | 0.000 | 0.000 | 0.000 |
| embeddings | 4000 | code | 0.400 | **0.433** | 0.400 |
| embeddings | 4000 | data | 0.000 | **1.000** | 1.000 |
| embeddings | 4000 | knowledge | 0.000 | **1.000** | 1.000 |
| embeddings | 16000 | code | 0.500 | **0.633** | 0.500 |
| embeddings | 16000 | data | 0.000 | **1.000** | 1.000 |
| embeddings | 16000 | knowledge | 0.000 | **1.000** | 1.000 |

## 3. The regression, named to the task

Exactly **two** code-plane cells fall under A, both `bm25`, both −0.333 — one
gold label of three:

| rung | task | before → A |
| ---: | --- | --- |
| 1000 | `slice_semantic_slice` | 0.333 → 0.000 |
| 16000 | `index_build_index` | 0.333 → 0.000 |

Against **seven** code-plane cells that rise, by +0.333 to +1.000
(`projects_resolve_repo_root`, `report_structure_summary`, `web_api_file` for
`bm25`; `web_api_file` ×3 and `projects_resolve_repo_root` for `embeddings`).

Net strongly positive, and the two losses are real. Adding 38 % more documents
at a fixed token budget can push a code answer out of the window; that is the
cost of generality, and row 3 of the frozen table exists so it gets reported
rather than absorbed into a mean.

**Unexplained and stated as such:** code scores *rose* at the smallest budget
(bm25 0.600 → 0.767 at rung 1000). A larger corpus improving code retrieval is
the opposite of the mechanism I predicted. Plausibly BM25's IDF shifting with
corpus composition and re-ranking code chunks — **not measured**, and not
claimed.

## 4. The design question the packet existed to settle

**The plane hint is worth exactly one cell.** Across all 84 non-code cells, A
and B differ in one: `bm25`, rung 1000, `fourfold_articles_csv`
(A = 0.000, B = 1.000). At rungs 4000 and 16000 they are identical everywhere.

So the general variant matches the plane-hinted variant at every realistic
budget. **The repair ships as variant A**, and the arms are never told which
plane the gold labels live in — the information asymmetry described in §1 of the
pre-registration is avoided at a measured cost of one cell at the tightest
budget.

That is the outcome worth having: the honest option was not the expensive one.

## 5. Control

`A2` held exactly. `sunny_garden` holds no non-code documents, so variant A
cannot change it — **no `sunny_garden` task moved, at any rung, for either arm.**
Had one moved, something other than the retrieval universe had changed.

## 6. What shipped

- Six arms now pass `planes=_RETRIEVABLE_PLANES`: `best_of_n`, `bm25`,
  `embeddings`, `local_mutation`, `random_search`, `single_llm_loop`. The
  existing `harness._RETRIEVABLE_PLANES` is reused — no seventh plane rule.
- Seven arms declare `retrieved_planes`, checked against behaviour.
- `bm25`'s docstring corrected. It had promised *"no plane restriction"* while
  inheriting `planes=("code",)` from a default — and in the paragraph directly
  above, it cited the s07 lesson that *"the formula was never the defect, which
  documents to include was"*. **A filter you inherit from a default is still a
  filter.** The arm named the trap and fell in it.

## 7. Limits of the verification, stated

- The four stochastic arms are verified **structurally**, not by a scored
  contrast: at n=14 a before/after on them would mostly measure seeds. The check
  establishes *that they retrieve non-code documents*, not *how much it helps*.
- `single_llm_loop` needs a live provider and errors offline, so its declaration
  **cannot be checked here at all**. It is named in `PROVIDER_DEPENDENT_ARMS`
  rather than skipped silently, and a second such arm has to be added
  deliberately.
- The behavioural check verifies a **non-code universe**, not which specific
  plane. Selection is not universe: `best_of_n` returns one document per run and
  answered the data probe with a better-scoring knowledge document, which is the
  arm working. Two earlier versions of that assertion failed a healthy arm for
  doing its job. It still kills the mutation it exists for — a code-only arm can
  never return a non-code document, verified by reverting `bm25` and watching it
  fail.
- `A7` (no arm silently scores an unreachable task) is met at the **admission**
  boundary, not per-arm: `require_plane_coverage` refuses before any trial when
  no arm reaches a needed plane. With `type` unretrievable by every arm and no
  `type` tasks in the corpus, that is the whole live surface today.

## 8. What this does not claim

- Not a Gate-3 baseline result; nothing here is sealed evidence.
- Not a re-reading of the six existing negatives. `G2-XPLANE-CONFIRM-04` used
  suffix-partitioned retrieval over `black` and `fastapi` and never called
  `_repo_chunks`, so it shares no code path with this defect.
- Not a promotion of anything out of quarantine.

Verification [MEASURED 2026-09-10]: `tests/eval/ tests/test_eval_mint.py
tests/contracts/` — 500 passed, 54 skipped, 28 subtests, 0 failed, staged before
measuring.

Iron Plan: EXPERIMENT
Iron Gate: 1
Evidence: `runs/g3_arm_plane/report.json`; `experiments/g3_arm_plane/measure.py`
