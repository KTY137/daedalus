# Retained cost and smoke evidence

Classification: **EXPERIMENT**, Gate 0. These developer-box timings are shape
observations, not a validated latency benchmark and not a production claim.
Automatic promotions: `0`.

No complete current-`/2`, independently isolated held-out baseline campaign
exists. This file contains historical and diagnostic cost evidence only; it
cannot support a scientific superiority, `ADVANCE`, or `KILL` decision.

The primary structured numerator is algebraically the flattened bilinear score
`vec(Q)^T (K_plane ⊗ K_role ⊗ I_feature) vec(D)`. Because the frozen
kernels are symmetric positive definite, it is also a dot product after a fixed
linear vector transform. Any timing difference below concerns these concrete
factored implementations and caches, not an intrinsic tensor-versus-vector
speed advantage.

## Aborted cost probes

On 2026-08-24, the first s09 `c00` smoke attempts used exhaustive interior
3/4/5-character n-grams and dense normalization/scoring. The visible pre-image
universe contained 4,376 candidates and 37,467,921 bytes after the common s09
per-candidate cap. The following runs were interrupted without producing a
quality result:

- isolated s09 harness, two tensor arms plus standard baselines: more than
  150 seconds for one case;
- non-isolated diagnostic harness, same arms/baselines: more than 120 seconds;
- direct cold encoding of the complete universe: more than 60 seconds.

A `cProfile` sample over the first 100 candidates (1,144,530 visible bytes)
took 6.341 seconds. Most time was repeated subword expansion and dense CP
materialization. This negative cost evidence caused no corpus, label, kernel,
feature dimension, seed, or observed ranking to be changed; no scored result
existed. The exact hash feature family was then finalized in the frozen spec
as word + four-character prefix + four-character suffix, and CP norms/scores
were evaluated directly from factors.

The first complete-census attempt at implementation revision
`601616c40bcddefaf300c65f7abe51d3d8d637e6` was also interrupted after more
than eight minutes without a report. It used the same real `c00` universe,
both frozen query variants, all 13 arms, and all five seeds. Inspection found
that the independent flattened-bilinear control recomputed the identical
query-side Kronecker transform once per candidate. That run is retained here
as negative implementation-cost evidence; it produced no ranking result and
caused no change to the frozen claim, kernel, corpus, labels, feature
dimension, or seeds. The implemented response caches only query-constant
bilinear and MaxSim state and skips products containing exact zero factors;
differential tests require bit-identical scores and receipts.

## Post-fix shape measurements

- The same cold 100-candidate encoding sample took 0.839 seconds (about 7.5x
  faster; unvalidated wall-clock).
- Direct `c00`, seed 11, 4,376 candidates: cold flattened-cosine arm 26.395
  seconds; structured arm after the shared projection cache 5.069 seconds.
  This ordering is not a fair latency comparison and must not be cited as a
  tensor speedup.
- The five-seed, two-arm `c00` smoke took 158.446 seconds total.
- After prepared-query caching and exact CP/TT zero pruning, one unprofiled
  seed over a 100-candidate `c00` prefix took about 1.41 seconds for all eight
  tensor/control arms combined on the same developer box. This is a cost-shape
  observation only; the prefix substitutes a present path as gold and cannot
  be cited as retrieval evidence.

The explicit tensor and baseline LRUs retain at most 20,000 candidates while
the frozen correctness cap permits 65,536. Above the cache capacity, repeated
sorted full-corpus scans can thrash and lose warm-hit benefits. This does not
change scores or budgets, but large-corpus latency remains unvalidated and no
production cost claim is permitted.

## Retained current-spec invalid run

At implementation revision
`c735f415c863a269e0f28be79543f8e309bf230c`, the complete 13-arm, five-seed,
raw-plus-scrubbed `c00` diagnostic finished in 753.704 seconds. It correctly
emitted `INVALID` with ten retained tensor/vector-equivalence failures and
`NO_SCIENTIFIC_VERDICT`; the compact evidence is
`results/s09_c00_smoke_v2_invalid.json`.

Forensic replay of seed 11/raw found that the structured and flattened
bilinear score maps agreed for every one of 4,376 paths within `1e-10`; the
maximum absolute difference was `5.551115123125783e-17`, and their evaluated
top 20 was identical. The old validator nevertheless zipped the two complete
score-sorted tuples and rejected the first roundoff near-tie reorder at rank
2,311. Fixing that validator defect changes no score, corpus, label, kernel,
seed, or evaluated ranking: score equality is now checked by path, while only
the metric-visible top-20 order must be identical. The invalid report remains
retained rather than overwritten.

## Retained historical diagnostic output (superseded)

`results/s09_c00_smoke.json` is the raw report from the final five-seed run of
the earlier role-salted filler backend (`spec_digest` `sha256:5ac3be...`). The
current shared-filler spec is intentionally different, so the current strict
validator rejects this artifact. It has no sealed eligibility manifest and is
**not scientifically evaluable**.

The operator log recorded the following context, but these claims are not
cross-bound inside the report and must not be treated as replay receipts:

- s09 task-set digest
  `sha256:c3ef36f19ebaaf953ef8c26615295dfe7e845a89ec68b50ffb5c933df96d8c33`;
- case `c00`, pre-image revision
  `3627c99208c0c592e8a0ac9acbd70ccd86bceaef`;
- 4,376 candidates and 37,467,921 visible bytes;
- frozen seeds `11, 23, 47, 89, 131`;
- report corpus digest
  `sha256:639e051df325ad27d0be96faf285073431b7711c7da03461ee3b33dc69f6a626`.

Within that superseded diagnostic, both flattened cosine and structured
contraction missed every gold item in
the top 20 for all five seeds. The paired MRR delta is `0.0` with interval
`[0.0, 0.0]`. Retaining the miss is negative evidence; it is neither
superiority, a research kill, nor validation of the current `/2` encoder.

The named budget-equal arms are executable, but a complete current `/2`
real-data campaign running all of them, an independent isolation/gold trust
anchor, and second-repository transfer evidence remain outstanding. Until
those artifacts exist, the only honest current status is
`NO_SCIENTIFIC_VERDICT`.
