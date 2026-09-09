# G2-XPLANE-CONFIRM-03 - the redesign the KILL points at: calibration instead of round-robin

Packet ID: `G2-XPLANE-CONFIRM-03`
Artifact role: `primary`
Status: `PRE-REGISTERED; the arm is specified here and NOT YET IMPLEMENTED`
Active gate: `1`
Classification: `EXPERIMENT`
Owner: `repository owner`
Base revision: `cc4725ba1b5b6f8f6a3e5b4e7e2c9a1d0f8b3c22`
Dependencies: `G2-XPLANE-CONFIRM-01, G2-XPLANE-CONFIRM-02`
Master-plan authority: `Revision 13`
Promotion: not requested. This packet cannot open, enter or satisfy any gate.

## Why this exists

`CONFIRM-02` fired this programme's first KILL on 14.1: `fusion_rrf` is
significantly **inferior** to plain `bm25` (-0.0806, CI95 [-0.1013, -0.0598]).
Plan §14 says a kill result means *"stop or redesign"*, and `CONFIRM-02`'s own
recommendation was redesign, on a specific measured ground:

> Fusion's deficit against plain BM25 is **uniform across both strata**
> (difference -0.0101). It is not a plane-crossing failure at all.

A uniform deficit points at the combination step, not at the planes. This
packet builds the arm that tests that diagnosis.

## The diagnosis, read out of the code rather than inferred

Two facts from `experiments/forest_v2/s11_fusion/fusion_retrievers.py`:

1. `_partition` assigns every candidate to **exactly one** plane bucket
   (`plane_of(cand.path)`), so the per-plane rankings are **disjoint sets of
   documents**, not competing opinions about the same documents.
2. `_rrf_combine` adds `1.0 / (rrf_k + rank)` using **rank position only** -
   its own docstring says it "never recomputes a score" and "only combines
   rank positions".

Reciprocal Rank Fusion is designed to reconcile several rankings *of the same
corpus*. Applied to disjoint partitions it is not fusing anything: it
degenerates into **round-robin interleaving**, taking each plane's #1, then
each plane's #2, and so on. A document that is the best of four weak matches in
a small plane is promoted above a document that is the second-best of two
hundred strong matches in a large one, because rank is all that survives.

That is a sufficient explanation for a deficit that is uniform across strata,
and it predicts the deficit would persist even on single-plane queries - which
is exactly what `CONFIRM-02`'s control stratum shows (-0.0710).

## Primary acceptance claim

> An arm that uses the same per-plane scoring but replaces round-robin rank
> interleaving with a **score-calibrated global ordering** recovers the loss
> against `bm25`, without partitioning away the global candidate pool.
>
> The claim of this packet is the protocol and the arm's specification, both
> fixed before implementation. The arm is parameter-free by design so that it
> cannot be tuned toward the metric.

## Scope

**In scope**

- `experiments/forest_v2/s11_fusion/fusion_retrievers.py` - ONE added class,
  `PlaneCalibratedRetriever`, and nothing else in the file.
- `experiments/forest_v2/s11_fusion/test_fusion_retrievers.py` - tests for the
  new class only; existing tests are extended, never rewritten.
- this document and its result document.

**Forbidden paths** - a diff touching these invalidates the packet

- `_partition` and `_score_plane` (the arm must differ in the combination step
  ONLY, or it tests two changes at once).
- `experiments/forest_v2/s09_eval/taskset*.py` and the frozen task-set JSONs.
- `experiments/forest_v2/s09_eval/taskset.py::PLANE_BY_SUFFIX`.
- `experiments/forest_v2/s10_kill/**` - the evaluator does not move while an
  arm it judges is being added.
- anything under `daedalus/`. Plan §13 forbids a production import of
  `forest_v2` and none is created.

## Contracts and behavior

### The new arm, specified before it is written

`PlaneCalibratedRetriever`, to live beside the existing three in
`experiments/forest_v2/s11_fusion/fusion_retrievers.py`.

1. Partition the candidate universe by plane, **reusing `_partition`
   unchanged**.
2. Score each plane's documents with **the existing `_score_plane`,
   unchanged** - so per-plane IDF and per-plane length normalisation are
   identical to `separate_indices_bm25` and to what `fusion_rrf` already
   computes. This is deliberate: the arm must differ from `fusion_rrf` in the
   COMBINATION STEP ONLY, or it tests two things at once.
3. Instead of RRF, standardise each plane's scores **within that plane** to
   zero mean and unit variance, and rank all documents globally by the
   standardised score.
4. Ties and degenerate planes: a plane with fewer than two scored documents, or
   zero variance, contributes its documents with a standardised score of 0.0.
   Documents absent from their plane's ranking (BM25 score zero) are omitted,
   exactly as `_rrf_combine` omits them today.
5. Return the same `RETURN_K` as the other arms.

**No tunable parameter is introduced.** There is no weight, no `k`, no
plane prior. Standardisation is fully determined by each plane's own score
distribution. This is a design constraint, not an implementation detail: the
tasksets it will run against have already been measured with other arms, so any
knob would be an invitation to fit.

### What stays frozen

Both existing tasksets (`fastapi` n=561, `black` n=730) are re-used
**unmodified**, with their recorded digests. The builder, `PLANE_BY_SUFFIX`,
`_partition`, `_score_plane`, the metric, the bootstrap, the seed, the margin
and pre-image isolation are all unchanged. The only new thing in the tree is
one class and its combination step.

## The hypotheses

**H7 (primary).** `plane_calibrated` beats `bm25` on the cross-plane stratum of
**both** subjects: CI95 excluding zero from above in each. This is the loss
`fusion_rrf` suffers, and recovering it is the point of the redesign.

**H8 (the diagnosis test).** `plane_calibrated` beats `fusion_rrf` on both
subjects. If calibration is what RRF was throwing away, this must hold; it is a
weaker and more direct test than H7 because it isolates the combination step.

**H9 (registered because it refutes me).** If **H8 fails** - calibration is no
better than round-robin - then the diagnosis in `CONFIRM-02` is **wrong**, the
"uniform deficit implies the combination step" reasoning does not survive, and
the honest conclusion becomes that per-plane partitioned scoring is itself the
problem regardless of how it is combined. That would strengthen 14.1's KILL
rather than answer it, and `CONFIRM-02`'s redesign recommendation would have to
be withdrawn.

### Readings, fixed now

| H7 | H8 | reading |
| --- | --- | --- |
| holds | holds | the diagnosis is right and the redesign works. 14.1's KILL applies to `fusion_rrf` specifically, not to using the planes. An amendment proposal should replace the RRF arm, not the prior. |
| fails | holds | calibration beats RRF but still loses to BM25. The combination step was *a* problem, not *the* problem. 14.1's KILL stands and the partitioning itself is implicated. |
| fails | fails | H9. The diagnosis is refuted, `CONFIRM-02`'s recommendation is withdrawn, and the KILL proposal strengthens to cover partitioned per-plane retrieval as such. |
| holds | fails | incoherent on its face - it would mean beating BM25 while not beating the arm BM25 already beats. Treat as evidence of a harness or adapter defect and discard the run rather than report it. |

## Acceptance matrix

### Analysis plan, fixed before the data

1. Implement the arm exactly as specified above. Commit it **before** running
   it, so the ordering is checkable in history.
2. Re-run the harness on **both** frozen tasksets with all four fusion arms.
3. Adapt each through `to_s10`; report s10 verdicts and the stratified probe.
4. Run the stratified probe twice per subject; require byte-identical output.
5. Primary test: H7 on the cross-plane stratum of both subjects. Then H8.
6. Report `plane_calibrated` against **every** existing arm, including
   `recency_prior` and `path_lexical`, in absolute MRR - so a reader can see
   whether the new arm is merely re-deriving a baseline.
7. No re-cutting, no re-tuning. If the arm underperforms, that is the result.

### Declared threat, and it is the serious one here

**These tasksets have already been measured.** I know how `fusion_rrf`,
`bm25`, `code_only_bm25` and `separate_indices_bm25` score on both subjects.
Adding an arm under those conditions is exactly the situation in which implicit
tuning happens, and no pre-registration fully removes it.

The mitigations are structural rather than promissory: the arm is
**parameter-free**, it reuses `_partition` and `_score_plane` **unchanged** so
only the combination differs, and its specification is committed here before
implementation. What remains unmitigated is my choice of *which* combination to
try, which was informed by having seen the results. That is stated rather than
waved away, and it is why H8 - not H7 - is the honest test: H8 asks only
whether the diagnosis was right, and a negative answer is registered above as
refuting me.

## Migration and rollback

Nothing to migrate. One class is added to an `experiments/` module that no
production code imports; the plan forbids production imports of `forest_v2`
and none is created.

Rollback is deleting the class, its registration and this document. Both frozen
tasksets and every prior measurement are untouched, since the protocol forbids
modifying the builder, the plane rule, `_partition` or `_score_plane`.

A negative result is not rolled back. If H8 fails, that finding is the most
valuable thing this packet can produce and it stays in the tree.

## Evidence, expected failures and review

- **The arm may simply re-derive `bm25`.** Standardising within disjoint
  partitions and ranking globally is closer to pooled scoring than RRF is; if
  it converges on the same ordering, H7 and H8 could both "hold" trivially.
  Acceptance step 6 exists to catch this: if `plane_calibrated`'s MRR equals
  `bm25`'s to three decimals on both subjects, it is reported as a
  re-derivation, not a result.
- **Z-standardisation assumes comparable score distributions.** BM25 scores are
  not normal and a plane with a few extreme matches will have its ordinary
  matches pushed down. This is a real weakness of the specified arm and it is
  recorded now, not after seeing whether it helped.
- **Two subjects are still not a corpus.** Gate 2's obligations - license
  audit, deterministic Twin rebuilding, cross-repository alignment, motif
  provenance - remain untouched by this packet as by its two predecessors.
