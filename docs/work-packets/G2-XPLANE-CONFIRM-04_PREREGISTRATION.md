# G2-XPLANE-CONFIRM-04 - plane as a FEATURE, not as a partition

Packet ID: `G2-XPLANE-CONFIRM-04`
Artifact role: `primary`
Status: `PRE-REGISTERED; the arm is specified here and NOT YET IMPLEMENTED`
Active gate: `1`
Classification: `EXPERIMENT`
Owner: `repository owner`
Base revision: `5734feefb1c0dd0c58e0e6f6d4f0a8e2c3b6d5a1`
Dependencies: `G2-XPLANE-CONFIRM-01, -02, -03`
Master-plan authority: `Revision 13`
Promotion: not requested. This packet cannot open, enter or satisfy any gate.

## Why this exists

`CONFIRM-03` refuted its own diagnosis and left a sharper one in its place:

> Two structurally different combination strategies — rank-only interleaving
> and distribution-based calibration — share nothing but the partition, and
> lose to a single pooled BM25 index by almost exactly the same margin
> (-0.0810 and -0.0817 on `black`). The evidence now points at **partitioning
> the index by plane at all**, not at how the partitions are recombined.

And it named what nothing has tested:

> **every** arm measured so far partitions the index. A pooled index that
> carries plane as a *feature* is a different hypothesis and nothing here
> tests it. "The planes do not help retrieval" is still not the demonstrated
> claim.

This packet tests it, and is therefore the packet that can retire the question
either way.

## What partitioning actually costs, read from the code

`_score_plane` computes, over **one plane's candidates only**:

- `df` / `idf` — so a term's rarity is measured inside its plane, not the corpus
- `avgdl` — so document length is normalised against that plane's average

Pooled `bm25` computes both globally. Partitioning therefore changes **two**
things at once, and every arm so far has taken both or neither. That
confounding is the reason this packet exists: it separates them.

`avgdl` is the half that plane genuinely predicts. Prose files are long, code
files are short; a global `avgdl` systematically penalises the plane whose
documents are longer. `idf` is the half partitioning destroys: a term's
corpus-wide rarity is the signal BM25 is built on, and computing it inside a
small plane makes a locally-common term look rare.

## Primary acceptance claim

> An arm with **global IDF** (identical term statistics to pooled `bm25`) and
> **per-plane document-length normalisation** uses plane information without
> partitioning the index, and is the first test of whether the planes carry
> retrieval value at all once the partition is removed.

## Scope

**In scope**
- `experiments/forest_v2/s11_fusion/fusion_retrievers.py` — ONE added class
- `experiments/forest_v2/s11_fusion/test_fusion_retrievers.py` — its tests
- this document and its result document

**Forbidden paths** — a diff touching these invalidates the packet
- `_partition`, `_score_plane`, `_rrf_combine`, `_standardise_within_plane`,
  and all four existing retriever classes
- `experiments/forest_v2/s09_eval/taskset*.py`, the frozen task-set JSONs, and
  `PLANE_BY_SUFFIX`
- `experiments/forest_v2/s10_kill/**`
- anything under `daedalus/`

## Contracts and behavior

### The new arm, specified before it is written

`PooledPlaneLengthRetriever`, name `pooled_plane_length`.

1. Score over the **whole universe as one index**: one `df`/`idf` table
   computed across every candidate, exactly as pooled `bm25` does. **No
   partition is used for scoring.**
2. Compute `avgdl` **per plane** (`plane_of(path)`), and normalise each
   document's length against its own plane's average rather than the global
   one. A plane with no scored documents contributes nothing; a document whose
   plane is unknown uses the global `avgdl`.
3. `BM25_K1` and `BM25_B` keep their existing module constants. **No new
   parameter is introduced** — the only new input is `avgdl_of(plane)`, which
   is measured from the universe, not chosen.
4. Rank globally by score, ties broken by path, return `RETURN_K`, tally
   returned planes like every other arm.

The arm therefore differs from pooled `bm25` in **exactly one term** of the
BM25 denominator. That is the whole design: a single-variable test of "does
plane information help when it is not used to partition".

### What stays frozen

Both task sets (`fastapi` n=561, `black` n=730) re-used unmodified with their
recorded digests. Metric, bootstrap, resamples, seed, margin, pre-image
isolation, and every existing arm unchanged. `single_plane_control_target` is
still 30 and still too small — carried forward deliberately, as in `CONFIRM-02`
and `-03`, because changing the instrument and the subject together is what
plan §14 forbids.

## The hypotheses

**H10 (primary).** `pooled_plane_length` beats `bm25` on the cross-plane
stratum of **both** subjects: CI95 excluding zero from above in each.

**H11.** It beats both partitioned arms — `fusion_rrf` and
`plane_calibrated` — on both subjects. If plane information is useful at all,
using it without destroying global IDF must be at least as good as using it
with.

**H12 (registered because it closes the question against the prior).** If
**H10 fails**, then across four arms and two repositories no use of plane
information has beaten a plain pooled index, and the honest reading of 14.1's
KILL widens from "partitioned per-plane retrieval fails" to **"plane-conditioned
retrieval, as instrumented here, provides no measurable retrieval benefit"**.
That is materially stronger than anything claimed so far and would be the
substantive basis for the §15 amendment proposal.

### Readings, fixed now

| H10 | H11 | reading |
| --- | --- | --- |
| holds | holds | the planes DO carry retrieval value; partitioning was the whole defect. 14.1's KILL applies to the partitioned instantiation, and the amendment proposal should replace the retriever, not the prior. |
| holds | fails | incoherent on its face — beating `bm25` while losing to an arm `bm25` beats. Treat as a harness or adapter defect, discard the run, re-register. |
| fails | holds | plane helps *relative to partitioning* and still not in absolute terms. The partition is confirmed as harmful; the planes remain unproven. |
| **fails** | **fails** | **H12.** Four arms, two repositories, no benefit. The strongest available evidence for the amendment proposal. |

## Acceptance matrix

### Analysis plan, fixed before the data

1. Implement the arm as specified; **commit it before running it**.
2. Re-run the harness on both frozen task sets with all five fusion arms.
3. Compare with `probe_arm_comparison`, cross-plane and control strata, against
   `bm25`, `fusion_rrf`, `plane_calibrated` and `separate_indices_bm25`.
4. Run every probe **twice**; require byte-identical output before reporting.
5. Primary test: H10 on the cross-plane stratum of both subjects. Then H11.
6. **Re-derivation guard.** This arm is one term away from pooled `bm25`. If
   its MRR equals `bm25`'s to three decimals on both subjects, report it as a
   re-derivation rather than a result, and say the per-plane `avgdl` made no
   difference.
7. **MRR floor.** As before: below 0.20 raw MRR on either subject the run is
   reported untrustworthy and H10/H11/H12 are recorded as not answered.
8. No re-cutting, no re-tuning. If the arm underperforms, that is the result.

## Migration and rollback

Nothing to migrate. One class in an `experiments/` module that no production
code imports; plan §13 forbids a production import of `forest_v2` and none is
created. Rollback is deleting the class, its tests and these documents; the
frozen task sets and every prior measurement are untouched by construction.

A negative result is **not** rolled back. Under H12 it is the most valuable
thing this packet can produce.

## Evidence, expected failures and review

- **The arm may be indistinguishable from `bm25`.** Per-plane `avgdl` differs
  from global `avgdl` only as much as plane length distributions differ. On a
  code-heavy subject like `black` (knowledge:code file ratio 0.14) that gap may
  be small, and acceptance step 6 exists to call that a re-derivation instead
  of a finding.
- **Length normalisation may be the wrong half.** The reasoning above says
  `avgdl` is what plane predicts and `idf` is what partitioning destroys. That
  is an argument, not a measurement, and H10 failing would falsify it.
- **My record on this thread.** I have now been wrong twice in a row with a
  pre-registration attached: the pooled-estimate framing in the ceiling
  write-up, and the combination-step diagnosis that `CONFIRM-03` refuted. H12
  exists so that a third wrong guess still produces a usable result rather than
  another redesign.
- **Two subjects are still not a corpus**, and Gate 2's Twin-rebuilding,
  cross-repository alignment and motif-provenance obligations remain untouched.
