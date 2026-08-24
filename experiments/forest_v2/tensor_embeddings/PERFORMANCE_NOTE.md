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

## Post-fix shape measurements

- The same cold 100-candidate encoding sample took 0.839 seconds (about 7.5x
  faster; unvalidated wall-clock).
- Direct `c00`, seed 11, 4,376 candidates: cold flattened-cosine arm 26.395
  seconds; structured arm after the shared projection cache 5.069 seconds.
  This ordering is not a fair latency comparison and must not be cited as a
  tensor speedup.
- The five-seed, two-arm `c00` smoke took 158.446 seconds total.

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
