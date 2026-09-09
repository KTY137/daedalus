# The Gate-3 baseline arms score 0.00 on non-code tasks because they never look

Status: MEASURED 2026-09-09
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
| `separate_indices` | 0.00 | `src/knowledge_hub/search.py` — Python |

`separate_indices` builds per-plane indices of its own and *still* returned only
Python here, so it reaches the same structural zero by a different internal
route. Its cause is not yet diagnosed and is not claimed to be the same one.

`code_only_graph` errors on all four. That is correct behaviour for a
declaredly code-only baseline and is not a defect.

## 2. What this means

**Every non-code number these baselines have ever produced is a structural
zero.** Not a measurement of retrieval difficulty; an arithmetic consequence of
searching the wrong corpus. No better method, no larger budget and no
plane-conditioning can move it, because the document containing the answer is
not a candidate.

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

1. The Gate-3 primary tier's four non-code tasks cannot discriminate between
   these arms. Combined with the four `sunny_garden` tasks pinned at 1.00
   (previous result), **8 of 14 primary tasks are constants**.
2. Any past or future cross-plane claim resting on these baselines is void as
   instrumented — not wrong, *uninformative*, which is worse to report as a
   number because it looks like evidence.
3. The six existing negatives on plane-conditioned retrieval are **not**
   retroactively explained by this. They were measured on other corpora and
   instruments. This does raise a specific question about them — whether any of
   them scored a non-code plane through a code-only universe — and that question
   is now worth asking directly of each. It is a question, not a re-reading.

## 5. What to do, and what deliberately is not being done here

**Done in this packet:** the measurement above, and a plane-coverage admission
check so that a 0.00 produced by never looking can no longer be silently read as
a 0.00 produced by looking and failing.

**Deliberately NOT done here:** changing `bm25` and `embeddings` to request the
task set's label planes. That is the actual repair, and it changes the measured
behaviour of two frozen baselines. Plan §10 puts a baseline change in its own
Work Packet with its own acceptance matrix and before/after evidence; folding it
into a diagnostic commit would be exactly the co-evolution §13 forbids. It is
recorded as the next packet, with the measurement it must produce:
per-arm × per-plane scores before and after, at the same three budget rungs, so
the size of the correction is visible rather than asserted.

Iron Plan: EXPERIMENT
Iron Gate: 1
Evidence: `_repo_chunks` plane census above; `arms/bm25.py:86`;
`arms/embeddings.py:204`; `runs/g3_origin_effect/report.json`
