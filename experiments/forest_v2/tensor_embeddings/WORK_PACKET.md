# Work Packet — tensor-product embeddings

Packet ID: `EXPERIMENT-TENSOR-EMBEDDINGS-001`<br>
Classification: `EXPERIMENT`<br>
Active delivery gate: Gate 0 (later-gate research prework; no production promotion)<br>
Base revision: `870bfdf7dc8d49322ef62d9803482f0d0b47b2fa`<br>
Owner request: `conversation-2026-08-24-tensor-embeddings`<br>
Frozen: 2026-08-24<br>
Expiry: 2026-10-31

## Primary claim

A role/filler tensor-product representation with a pre-registered, separable
plane/role contraction kernel can rank revision-bound software artifacts more
accurately than cosine over the exact same stored scalars. The claim is about
retrieval proposals only. It grants no authority to an embedding, changes no
Project Twin binding, and promotes nothing.

The comparison deliberately includes an identity-kernel ablation. A full
Frobenius contraction under identity kernels must equal cosine over the
flattened tensor. If it does not, the implementation is wrong. Any benefit must
therefore come from retained axes and the declared contraction, not from
calling a reshaped vector a tensor.

Interpretation boundary: with canonical flattening, the primary numerator is
exactly

`vec(Q)^T * (K_plane ⊗ K_role ⊗ I_feature) * vec(D)`.

It is a bilinear 512-vector score. Because the two frozen kernels are symmetric
positive definite, it is also an ordinary dot product after a fixed shared
linear transform. The empirical claim is therefore only that the frozen
plane/role **structure prior** can beat *plain* cosine. This packet makes no
tensor-versus-vector representation-class superiority claim.

## Frozen representation

Each artifact is encoded as a third-order tensor

`T[plane, role, feature] = sum_i weight_i * p_i ⊗ r_i ⊗ f_i`.

- Plane axis: exactly `code`, `type`, `data`, `knowledge`.
- Role axis: `path`, `symbol`, `content`, `neighbor`.
- Feature axis: 32 deterministic signed-hash features. The frozen offline
  backend is `signed-subword-hash-shared-word-p4-s4/2`: each unique lexical
  token, its four-character prefix and its four-character suffix are
  count-sketched into one **role-independent filler space**; all four roles
  have weight `1.0`.
- Document plane: one-hot and revision-bound by its input artifact.
- Plane-unspecified query: uniform unit vector across the four planes.
- Storage forms: dense, exact CP factors, and an exact CP-to-Tensor-Train
  conversion. CP/TT are compression representations of the same tensor, not
  extra evidence and not separate retrieval arms.
- Normalization: global L2 after role/filler binding.
- Primary kernel: the literal matrices in `EXPERIMENT_SPEC.json`; they are
  frozen before a real retrieval run.

Primary scoring is the normalized separable contraction

`sum Q[p,r,f] * K_plane[p,q] * K_role[r,s] * D[q,s,f]`.

The normalization uses the conservative declared bound
`sqrt(||K||_1 * ||K||_inf)` for each kernel, rather than computing its exact
spectral norm, so scores remain finite and bounded. Secondary scoring is
fiber-wise **Mean-MaxSim**/late interaction; ColBERT's published operator uses
the sum, while division by the fixed query-fiber count leaves within-query
ranking unchanged.

## Inputs and authority

- Preferred structured input: `forest-v2-node-card/2` plus its resolvable
  provenance book.
- Evaluation input: s09 `QueryView` and the exact shared `Candidate` universe.
- Sources, source revisions, card IDs and Forest/Fourfold digests remain
  authoritative. Tensor indexes are regenerable projections.
- Every encoded/indexed source carries an explicit binding class:
  `caller_asserted`, verified budget-visible content, verified query content,
  or a Node Card whose provenance reference resolved in its supplied book.
  An asserted digest never silently becomes verified merely because an index
  content-addresses the assertion.
- Persisted `/2` indexes carry the budget-visible role fields and exact checked
  source evidence needed to replay their source binding. They accept only the
  frozen hashing backend, recompute every stored tensor, and bind the frozen
  contraction kernel. This proves internal consistency, not that an external
  repository or issuer supplied those bytes.
- No tensor similarity becomes a trusted `CrossPlaneBinding`; it may only be
  emitted as a proposal with source locators and representation identity.

## Evaluation authority

- `benchmark.py` is an in-process diagnostic convenience harness. It accepts
  only the exact audited experiment arms and can emit `INCONCLUSIVE` or
  `NO_SCIENTIFIC_VERDICT`, never `ADVANCE`/`KILL`.
- Diagnostic report `/2` binds `EVALUATION_PROTOCOL_V2.json`; its aggregate
  bootstrap first averages raw/scrubbed views within each base case and then
  resamples base cases. Variant-specific intervals remain separate.
- `sealed_eval.py` structurally validates content-addressed input, ranking,
  gold, and isolation manifests without executing a retriever. Content hashes
  prove integrity, not issuer identity or truth. Until an owner-controlled
  external trust chain anchors the exact taskset/case census, pre-gold ranking
  commitment, independently issued gold and isolation attestations, score and
  artifact-cost receipts, A4 equality, and second-repository transfer, this
  path is also `NO_SCIENTIFIC_VERDICT` only.
- There is currently no scientific Decision API anywhere in this experiment.
  Adding one, an equivalence margin, or a decision truth table changes this
  frozen protocol. `ADVANCE`/`KILL` could be considered only after both an
  owner-recorded plan/Work-Packet amendment and the external trust chain above
  exist; neither may be inferred from a smoke run or self-asserted JSON
  booleans.
- No complete current-`/2`, independently isolated held-out baseline campaign
  exists yet. All current outputs are structural/diagnostic or superseded
  historical evidence and remain `NO_SCIENTIFIC_VERDICT`.

## In scope

- strict, versioned tensor/spec/kernel/document/index contracts;
- deterministic hashed filler backend and a protocol for precomputed semantic
  filler vectors;
- Node Card and s09 Candidate/query adapters;
- dense, CP and Tensor-Train materialization and contraction;
- flattened cosine, identity contraction, structured contraction, plane/role
  permutation controls, and MaxSim;
- content-addressed, tamper-evident experiment index persistence;
- read-only/stdout-only CLI for encode/build/search/benchmark; canonical index
  bytes are the persistence format, while an authorized caller owns storage;
- synthetic role-binding construct test;
- real s09 historical retrieval comparison under the existing byte/candidate
  budget, including BM25 and existing controls;
- retained raw results, paired uncertainty and negative findings.

## Forbidden

- edits to `daedalus/memory/embeddings.py`, `memory/vectors.db`, policy,
  evaluators, the event journal, promotion, Master Plan, or amendment chain;
- a production import from `daedalus/` into this experiment or vice versa;
- network calls, model downloads, subprocesses, or explicit filesystem writes
  by runtime modules; documented Python invocations use `-B` so the interpreter
  does not create bytecode-cache files around an otherwise inert CLI;
- treating tensor scores as verification;
- changing the kernel, feature budget, metric, corpus or seeds after reading a
  measured result;
- claiming TT compression is useful unless bytes and latency are measured;
- hiding a loss, inconclusive interval, collision, malformed input or failed
  run.

## Frozen budgets and controls

- same `Candidate` objects and `Candidate.text()` byte cap for every arm;
- same feature tensor and `4 * 4 * 32 = 512` dense scalars for primary tensor
  contraction and flattened cosine;
- at most 65,536 candidates per case/index, at most 65,536 UTF-8 bytes per
  role field, and at most 262,144 bytes of replayable source evidence;
- feature-hash seeds: `11, 23, 47, 89, 131`;
- query variants: `raw` and `scrubbed` where the task set supplies them;
- cutoffs: s09's `1, 5, 10, 20`;
- primary metric: per-case reciprocal rank / aggregate MRR;
- secondary metrics: Recall@k, first-hit coverage, stored scalar/byte count,
  and non-authoritative wall-clock shape;
- baselines: flattened cosine over the identical tensor, identity contraction,
  BM25, random, path lexical, recency prior, and the existing s11 fusion arm
  when the corpus supports it;
- negative controls: plane-label permutation, role-label permutation, and
  uniform all-to-all kernels;
- stochastic reporting: five frozen hash seeds; paired bootstrap uses 10,000
  resamples with seed `20260824`.

## Acceptance matrix

| ID | Acceptance condition | Evidence |
| --- | --- | --- |
| A1 | Strict contracts reject unknown keys, wrong ranks/shapes, non-finite values, stale spec IDs and tampered digests. | focused unit/adversarial tests |
| A2 | Encoding and canonical serialization are byte-deterministic for every frozen seed. | repeated-process digest tests |
| A3 | Dense, CP and TT materialization agree within `1e-10` on 100 seeded tensors. | equivalence/property tests |
| A4 | Identity tensor contraction equals flattened cosine within `1e-10`. | algebraic regression tests |
| A5 | Structured contraction preserves role/plane binding on the frozen synthetic construct while cosine cannot separate its bag-equivalent decoy. | construct benchmark; explicitly not an effect claim |
| A6 | Primary tensor and cosine arms consume identical inputs and exactly 512 dense scalars. | budget receipt and harness assertions |
| A7 | Index load detects any mutated spec, frozen kernel, source binding/evidence, role field, factor or digest; it replays frozen-backend tensors, and duplicate source IDs with different content refuse. | persistence mutation tests |
| A8 | CLI exposes no write flag, opens no path for writing, and emits canonical bytes only on stdout. | AST/monkeypatch refusal tests |
| A9 | The package performs no network, subprocess or production-store operation and no production module imports it. | AST/import review and tests |
| A10 | Diagnostic/structural comparison retains every arm, seed, `(case_id, variant)` score, failure and paired interval, but exposes no Decision API; a scientific claim would require both the owner-amended protocol and external trust chain listed above. | raw JSON manifests + strict validators |

## Research kill criteria

These criteria apply only to a complete, isolation-valid, input-valid and
budget-equal run. Isolation, budget, schema or input failures classify the run
as `INVALID`/`BLOCKED` with `NO_SCIENTIFIC_VERDICT`; they are never evidence
for a tensor `KILL`.

Stop any production-integration proposal when one or more holds:

1. structured contraction does not beat flattened cosine on held-out data under
   equal scalar and input-byte budgets;
2. permuting plane or role labels performs equivalently, showing the named
   structure is not doing the work;
3. an apparent gain disappears against BM25/recency/s11 fusion or after query
   scrubbing;
4. extra feature collisions, context bytes, stored scalars or tuning explain
   the gain;
5. CP/TT storage or query cost worsens the quality/cost frontier;
6. results do not transfer to a second, revision-pinned repository;
7. source revision, input digest, model/filler identity or failure evidence
   cannot be replayed.

## Rollback and handoff

Rollback is deletion of this experiment directory and its unpromoted branch;
no migration is needed because no production schema or store changes. Retained
results may be added as reviewed static fixtures with `apply_patch`; the CLI
itself never writes them. Handoff must report exact commands, task/corpus
digests, all failures, raw results, residual risks and the explicit statement
`automatic promotions: 0`.
