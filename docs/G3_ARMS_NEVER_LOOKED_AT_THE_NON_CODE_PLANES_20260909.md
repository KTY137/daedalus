# The Gate-3 baseline arms score 0.00 on non-code tasks because they never look

> ## REPAIR COMPLETED [MEASURED 2026-09-10]
>
> The defect described in this diagnostic was repaired on 2026-09-10 by packet
> G3-ARM-PLANE-01. **Six arms** (best_of_n, bm25, embeddings, local_mutation,
> random_search, single_llm_loop) now pass `planes=_RETRIEVABLE_PLANES` to
> `harness._repo_chunks`. Measured result, **for the two deterministic arms
> only** — `bm25` and `embeddings`: data 0.000 → 1.000 and knowledge
> 0.000 → 1.000, at budgets 4000 and 16000. Two `bm25` code-plane cells
> regressed by −0.333; seven code-plane cells rose.
>
> The other four repaired arms were **not scored**. Three are stochastic and one
> (`single_llm_loop`) needs a live provider, so they are verified structurally —
> the check establishes that they retrieve non-code documents, not how much it
> helps them. Saying "0.000 → 1.000 on affected arms" would claim a measurement
> that was never taken on four of the six.
>
> **This document records the evidence that motivated the repair.** The diagnosis
> in §1–§2 describes behavior that *existed on 2026-09-09 and was confirmed*. The
> repair result is in `docs/G3_ARM_PLANE_REPAIR_RESULT_20260910.md`. What was
> measured in this file remains true; what it describes in present tense no longer
> is. Cross-link to the repair result when reading this.

Status: MEASURED 2026-09-09 (DEFECT REPAIRED 2026-09-10)
Classification: EXPERIMENT (Gate-3 prework; active delivery gate is 1)
Follows from: `docs/G3_ORIGIN_EFFECT_RESULT_20260909.md` §4, which named this as
the leading unverified explanation and the obvious next measurement. It is now
verified.

## 1. The measurement

`daedalus.eval.harness._repo_chunks(root, planes=...)` over the packaged
`fourfold_wiki_app` fixture, which supplies all four non-code tasks in the
Gate-3 primary tier:

| `planes=` | chunks returned |
| --- | ---: |
| `("code",)` — **the default** | 10 |
| `("knowledge",)` | **15** |
| `("data",)` | **2** |

The non-code documents are there. `_repo_chunks` retrieves them on request.

And the arms do not request them:

- `arms/bm25.py:86` — `harness._repo_chunks(task.repo_root)`, no `planes`.
- `arms/embeddings.py:204` — `_repo_chunks(task.repo_root)`, no `planes`.

Both therefore retrieve the code-only default universe. Scored against gold
labels that live in a CSV, a JSON schema and Markdown pages, they return 0.00 —
not because the task is hard, but because the answer was never in the pile they
searched.

Probed directly on `fourfold_articles_csv` (target `data/articles.csv`, gold
labels `$schema`, `pattern`, `minLength`, `enum`, which live in
`schemas/article.schema.json`, a data-plane sibling):

| arm | score | what it actually returned |
| --- | ---: | --- |
| `bm25` | 0.00 | `src/knowledge_hub/search.py::search_articles` — Python |
| ~~`separate_indices`~~ | ~~0.00~~ | **STALE — see the correction below; this row was produced by my probe passing `label_plane="code"`. With the true plane it scores 1.00.** |

**Corrected 2026-09-09:** this section first reported that `separate_indices`
also returned only Python. That was a bug in my probe — it passed
`label_plane="code"` for data/knowledge tasks — not a property of the arm.
Given the true plane, `separate_indices` scores **1.00 on all four** at rungs
4000 and 16000. It is therefore the *control*: same tasks, same budget, same
fixture, answered perfectly by an arm that consults the plane. That makes the
`bm25`/`embeddings` zeros a statement about those two arms rather than about
the tasks.

`code_only_graph` errors on all four. That is correct behaviour for a
declaredly code-only baseline and is not a defect.

## 2. What this means

**Every non-code number `bm25` and `embeddings` have produced is a structural
zero.** Not a measurement of retrieval difficulty; an arithmetic consequence of
searching the wrong corpus. No better method and no plane-conditioning can move
it, because the document containing the answer is never a candidate.

Scoped deliberately to those two arms. `separate_indices` consults the plane and
scores 1.00 on the same tasks, so this is a defect in two arms, not a property
of the baseline set.

This is the s08 defect in mirror image. `GATE2_FOREST_V2_TRIAGE.md` records
that s08 compared cross-plane fusion against four separate indices on 600
queries whose gold labels were 100% code documents — a setup where no
cross-plane retriever can win — and the artifact was reported as a finding,
firing a plan §14 kill criterion on a question the setup could not ask. Here the
labels are non-code and the *retrievers* are code-only. Same impossibility,
opposite end.

## 3. The guard built from the s08 lesson does not catch this

`FrozenTaskSet.require_cross_plane()` exists precisely so that "a structurally
impossible comparison must not be run and then reported as a finding" (its own
docstring). It **passes** on this task set — measured.

It passes because it checks that the gold **labels** span at least two planes.
It does not, and structurally cannot, check that the **arms** can retrieve those
planes: `FrozenTaskSet` knows nothing about arms.

So the guard admits a comparison in which half the tasks are unanswerable by
construction. The check it performs is real; the gap is that label diversity was
treated as sufficient for a cross-plane comparison when retrievability is the
other half of the condition.

## 4. Consequences, ordered

1. **Corrected 2026-09-09.** This list first said the four non-code tasks
   "cannot discriminate between these arms" and that 8 of 14 primary tasks are
   constants. Both are retracted. Those four tasks discriminate *sharply* —
   they separate an arm that consults the plane (`separate_indices`, 1.00) from
   two that do not (`bm25`/`embeddings`, 0.00). That is the opposite of
   carrying no information; it is the cleanest signal in the tier.
2. Any past or future cross-plane claim resting on **`bm25` or `embeddings`**
   is void as instrumented — not wrong, *uninformative*, which is worse to
   report as a number because it looks like evidence. A claim resting on
   `separate_indices` is not implicated.
3. The six existing negatives on plane-conditioned retrieval are **not**
   retroactively explained by this. They were measured on other corpora and
   instruments. This does raise a specific question about them — whether any of
   them scored a non-code plane through a code-only universe — and that question
   is now worth asking directly of each. It is a question, not a re-reading.

## 5. What to do, and what deliberately is not being done here

**Done in this packet:** the measurement above, and a plane-coverage admission
check, `gate3/coverage.py`, called from `run_comparison` before any trial runs.

(An earlier version of this sentence claimed a 0.00 from never looking "can no
longer" be misread. Nothing called the module at the time, so that was untrue.
It is wired now, and the honest form is that the check exists and runs — not
that misreading has become impossible.)

**Deliberately NOT done here:** changing `bm25` and `embeddings` to request the
task set's label planes. That is the actual repair, and it changes the measured
behaviour of two frozen baselines. Plan §10 puts a baseline change in its own
Work Packet with its own acceptance matrix and before/after evidence; folding it
into a diagnostic commit would be exactly the co-evolution §13 forbids. It is
recorded as the next packet, with the measurement it must produce:
per-arm × per-plane scores before and after, at the same three budget rungs, so
the size of the correction is visible rather than asserted.

## 6. Independent verification, 2026-09-09

An adversarial pass re-ran the decisive experiment: wrap `harness._repo_chunks`
so the call `bm25` and `embeddings` *already make* returns the task's label
plane, touching neither arm's `run` code. At rung 4000 **all eight cells move
0.00 → 1.00**. At rung 1000 four of eight move — budget genuinely binds there —
and at 16000 all eight do.

The causal story in §1–§2 is confirmed, with one refinement to carry into the
repair packet: **the size of the correction is budget-dependent**, and reporting
the 4000 result alone would overstate it.

The same pass refuted the separate, weaker claim that the tier is constant —
see §4 and the retraction box in `G3_ORIGIN_EFFECT_RESULT_20260909.md`.

Iron Plan: EXPERIMENT
Iron Gate: 1
Evidence: `_repo_chunks` plane census above; `arms/bm25.py:86`;
`arms/embeddings.py:204`; `runs/g3_origin_effect/report.json`
