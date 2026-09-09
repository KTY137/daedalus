# G2-TENSOR-CENSUS-01 — pre-registration: do plane *labels* carry retrieval information?

`[PRE-REGISTERED 2026-09-09 on origin/main 1fd5e13d, before any campaign was run]`
Classification: `EXPERIMENT`. **Decides nothing. Kills no track. Fires no
criterion for the Project Twin.**

## Why this test and not the Type-plane one

`G2_TYPE_PLANE_FOUR_DEFINITIONS_20260909` measured that this repository holds
**four incompatible definitions of the Type plane**, disagreeing from 0 % to
≈58 % of a corpus. That makes any Type-specific ablation non-portable until an
owner decides what §5's Type plane *is* — which is an amendment-shaped question,
not a measurement.

The `plane_label_permutation` control does not have that problem. It permutes
**all four plane labels at once**, so it asks whether the plane assignment
carries retrieval information *at all*, independently of whether the Type slice
is 2 % or 58 %. Under `infer_plane` the permuted mass is dominated by `code`
(58 %), `knowledge` (19–38 %) and `data` (2–20 %) — planes whose membership none
of the four definitions disputes. The thin Type plane cannot rescue or sink this
comparison.

This is also the closest thing in the tree to plan §14.2, *"degree-preserving
randomized cross-plane edges perform equivalently"*.

## What has actually been run before

The tensor-embeddings arms have been evaluated on **one diagnostic case**, which
`PERFORMANCE_NOTE.md` labels not scientifically evaluable. This is the first
campaign on a real corpus.

## The campaign

**Corpus.** `experiments/forest_v2/s09_eval/taskset_xplane.json` — the committed,
frozen cross-plane task set: **88 cases**, anchor `d849c2a9`, subject the
daedalus repository itself, mean universe 1399 candidates. Anchor and case
parents verified reachable after the 2026-09-03 history rewrite before this was
written. Plane composition is already recorded in the artifact: 58 of 88 cases
span more than one plane, 13 span three.

**Arms.** The full frozen arm census, unchanged — the census check refuses a
tree whose executable arms differ from the frozen list, and this packet does not
touch it.

**Comparisons, in priority order.**

1. **Primary:** `structured_contraction` vs `plane_label_permutation`.
2. Secondary: `structured_contraction` vs `flattened_cosine_same_scalars`, the
   budget-identical reference.
3. Validity, not a result: `identity_contraction` must equal
   `flattened_cosine_same_scalars` within `1e-10`. If it does not, the run is
   reported as **invalid** and no comparison is read from it.

**Metric.** recall@10 primary, MRR@20 secondary, both query variants reported,
`scrubbed` primary.

**Decision rule.** The s10 evaluator's, reused verbatim: CI95 percentile
bootstrap, 10 000 resamples, seed 20260818, equivalence margin ±0.02, paired by
case.

## Reading table — frozen before any run

**`LABELS_CARRY_INFORMATION`** — `structured_contraction` beats
`plane_label_permutation`, CI95 excluding zero. Plane assignment carries
retrieval information. §14.2 does **not** fire on this instrument.

**`LABELS_NULL`** — the CI95 lies **entirely inside** ±0.02. Permuting every
plane label changes nothing measurable, so the labels carry no retrieval
information, and §14.2 fires **for this instrument** under the scope limit below.

**`LABELS_HARM`** — `plane_label_permutation` beats `structured_contraction`,
CI excluding zero. Reported as its own outcome, not folded into a neighbour.

**`INCONCLUSIVE`** — CI includes zero **and** extends past ±0.02: underpowered at
88 cases. Reported as underpowered, never rounded to `LABELS_NULL`. At 88 cases
this is a live possibility, not a formality — the file-level corpora that
produced earlier results ran at 561 and 730.

**`INVALID`** — the identity check fails, an arm raises, or the harness reports a
failure census. No comparison is read.

## Scope limit, binding on every outcome

Under the substitution ban frozen at `3fbdb6a1`, this corpus is **not** the
four-plane Project Twin: its gold is commit history and its planes come from
`infer_plane`, one of the four competing definitions. So even a clean
`LABELS_NULL` cannot be reported as "§14.2 has fired" for the Twin. The most it
licenses is:

> On a file-level retrieval corpus whose planes come from `infer_plane`,
> permuting the plane labels of a tensor-structured retriever changes nothing
> measurable.

The §14 board's **0 of 16 evaluable for the Twin** is not changed by this
document or by its result.

## What would make this wrong

- **88 cases is small.** The `INCONCLUSIVE` branch exists because of it and will
  be used if the interval earns it.
- The harness runs gold and retrievers in one process and is explicitly not a
  security boundary; it is a convenience harness whose own docstring says so.
  That is acceptable for a diagnostic and would not be for a published claim.
- A null could mean the *tensor encoding* discards plane information before the
  kernel ever sees it, rather than that plane labels are worthless. That
  alternative cannot be separated by this run and is recorded, not resolved.

## Committed before measurement

Committed before the campaign runs, so the ordering is checkable in git history.
The five branches, the decision rule, the primary comparison and the corpus are
fixed here and will not be moved after seeing the numbers.
