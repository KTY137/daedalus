# G2-TENSOR-CENSUS-01 — result: plane labels carry nothing, and the structure's value reverses with the query

`[MEASURED 2026-09-09 on origin/main 1fd5e13d]`
Pre-registration: `G2_TENSOR_CENSUS_01_PREREGISTRATION_20260909.md`, committed at
`371bd5a1` **before** any campaign ran.
Classification: `EXPERIMENT`. **Kills no track. Fires no criterion for the
Project Twin.**

## Run validity — the gate the frozen table put first

| check | scrubbed | raw |
| --- | --- | --- |
| harness `status` | **`VALID`** | **`VALID`** |
| runtime failures | **0** | **0** |
| `identity_contraction` vs `flattened_cosine` | drift **0.0**, tol `1e-10` | drift **0.0** |
| cases | 88 / 88 | 88 / 88 |
| mean universe | 1423 | 1423 |
| benchmark wall time | 3030 s | 3084 s |

The first attempt at this campaign was `BLOCKED / NO_SCIENTIFIC_VERDICT` with
1200 failures and its comparisons were **withheld unread**. These are the runs
the frozen table permits reading.

## Primary comparison — do plane labels carry information?

`structured_contraction` vs `plane_label_permutation`.

| variant | metric | structured | permuted | Δ | CI95 | verdict |
| --- | --- | ---: | ---: | ---: | --- | --- |
| **scrubbed** (primary) | **recall@10** (primary) | 0.08828 | 0.08497 | **+0.0033** | [−0.0106, +0.0170] | **`LABELS_NULL`** |
| scrubbed | MRR@20 | 0.10836 | 0.11993 | −0.0116 | [−0.0351, +0.0104] | `INCONCLUSIVE` |
| raw | recall@10 | 0.14113 | 0.14725 | −0.0061 | [−0.0247, +0.0117] | `INCONCLUSIVE` |
| raw | MRR@20 | 0.19065 | 0.21059 | −0.0199 | [−0.0492, +0.0073] | `INCONCLUSIVE` |

**On the pre-registered primary variant and primary metric the verdict is
`LABELS_NULL`**: the interval lies entirely inside ±0.02, so randomly permuting
all four plane labels changes retrieval by nothing measurable.

The other three rows are `INCONCLUSIVE` — intervals that include zero *and*
extend past the margin. At 88 cases that is the honest reading and it is not
rounded toward the primary's answer. **No row in the primary comparison favours
the true labels.** Three of four point estimates are negative.

## Secondary comparison — and a reversal worth more than the verdict

`structured_contraction` vs `flattened_cosine_same_scalars`, the
budget-identical reference seeing the same 512 entries flat:

| variant | metric | structured | flat | Δ | CI95 | excludes 0 |
| --- | --- | ---: | ---: | ---: | --- | --- |
| scrubbed | recall@10 | 0.08828 | 0.09973 | **−0.0114** | [−0.0229, −0.0002] | **yes, worse** |
| scrubbed | MRR@20 | 0.10836 | 0.13029 | **−0.0219** | [−0.0381, −0.0064] | **yes, worse** |
| raw | recall@10 | 0.14113 | 0.12455 | +0.0166 | [−0.0014, +0.0360] | no |
| raw | MRR@20 | 0.19065 | 0.16321 | **+0.0274** | [+0.0093, +0.0470] | **yes, better** |

**The sign flips with the query variant, and both ends are significant.**
Applying the plane/role structure *hurts* when the query has been scrubbed of
the answer's own tokens, and *helps* when it has not.

That is a mechanism claim, and it is the most interesting thing this campaign
produced: the structure appears to **amplify lexical overlap between query and
document rather than contribute information independent of it**. A raw commit
message names the files it changed; scrubbing removes exactly those tokens. A
method that gains from the first and loses from the second is behaving like a
weighting over lexical match, not like a semantic prior.

**Stated as a hypothesis, not a finding.** One subject, one encoding, 88 cases,
and the two variants are not independent samples — they are two views of the
same 88 commits. It would be tested by a query set that is not derived from the
commit message at all.

## A label my analyser applied where it does not belong

`read_census.py` prints `LABELS_HARM` on the scrubbed secondary rows and
`LABELS_CARRY_INFORMATION` on the raw MRR row. **Those labels are wrong here.**
The five branches were defined for the *primary* comparison; applied
mechanically to the secondary they name the wrong thing.

The correct statements are the ones in the table above: structured is
significantly inferior to its own flat reference on scrubbed, and significantly
superior on raw MRR. Recorded rather than silently relabelled — the tool applied
the frozen rule faithfully and the rule simply did not cover this comparison.
The defect is in the branch names, not in the result.

## Binding scope limit

Quoted unchanged from the pre-registration:

> On a file-level retrieval corpus whose planes come from `infer_plane`,
> permuting the plane labels of a tensor-structured retriever changes nothing
> measurable.

This does **not** license "§14.2 has fired". Under the ban frozen at `3fbdb6a1`
the corpus is not the four-plane Project Twin: its gold is commit history and
its planes come from `infer_plane`, one of the **four competing definitions**
`G2_TYPE_PLANE_FOUR_DEFINITIONS` measured. The §14 board's **0 of 16 evaluable
for the Twin** is unchanged.

**The alternative this run cannot exclude**, declared in advance and still open:
a null could mean the *tensor encoding* discards plane information before the
kernel ever sees it, rather than that plane labels are worthless.

## Where this sits

Sixth independent negative on plane-conditioned retrieval, and the first from a
**non-lexical** method — the specific gap the previous five left open:

| measurement | instrument | result |
| --- | --- | --- |
| 12 plane-using arms vs pooled BM25 | lexical | all negative |
| resolver vs annotation-only control | lexical | ≤ 2.37 pp |
| Twin ingestion of a real repository | compiler | `INFEASIBLE_CONTRACT` |
| production type extraction coverage | compiler | 3.40 % / 1.60 % |
| Type-plane ablation, symbol corpus | lexical | `TYPE_NULL` |
| **plane-label permutation, tensor arms** | **non-lexical** | **`LABELS_NULL`** |

"It only failed because BM25 is lexical" is now measured rather than assumed,
and it does not survive. The reversal above sharpens *why*: the non-lexical arm
still behaves lexically.

## What this does not claim

- The tensor arms are not judged as an implementation. Both runs are clean:
  zero failures, exact kernel identity at `1e-10`.
- 88 cases is small, and six of eight rows are `INCONCLUSIVE`. That is reported,
  not rounded away.
- The harness runs gold and retrievers in one process and says so itself.
  Acceptable for a diagnostic, not for a published claim.
- No amendment is proposed. Six negatives are a pattern; §14 demands replicated
  budget-equal experiments on the object it names.

## Reproduction

```
python experiments/forest_v2/tensor_embeddings/run_xplane_census.py <repo> --variant scrubbed
python experiments/forest_v2/tensor_embeddings/read_census.py census_scrubbed.json census_raw.json
```
Corpus: committed `taskset_xplane.json`, anchor `d849c2a9`, subject daedalus
itself. Rule: CI95 percentile bootstrap, 10 000 resamples, seed 20260818, margin
±0.02, paired by case, seeds averaged within a case first.
