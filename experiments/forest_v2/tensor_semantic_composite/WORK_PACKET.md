# Work Packet — frozen semantic encoder direct sum

Packet ID: `EXPERIMENT-SEMANTIC-COMPOSITE-002`  
Classification: `EXPERIMENT`  
Active delivery gate: Gate 0 (contract/construct only)  
Base revision: `d6eeb8c3205b18e95a27ff4328a2a0b58ea81246`  
Owner request: `conversation-2026-08-24-semantic-tensor-composite`  
Frozen: 2026-08-24  
Expiry: 2026-10-31

## Plan relation

This is an **isolated experiment aligned with the Master Plan boundaries**, not
a plan change. It uses the existing tensor experiment only as a canonical
algebra/encoding construct. It adds no production entrypoint, authority,
artifact identity, graph authority, event store, evaluator or promotion path.

## Frozen dependencies and scope

- Design authority: `docs/IKARUS_ARIADNE_MASTER_PLAN.md` at base revision
  `d6eeb8c3205b18e95a27ff4328a2a0b58ea81246`.
- Tensor construct dependency: Packet 001 at the same revision; canonical JSON
  digest of its `EXPERIMENT_SPEC.json` is
  `sha256:231660e61439ee8b6afd5f1a9607be5bdf7da974ad05747e0ccddfd649ed5350`.
- Python: repository-supported Python 3.10+, stdlib runtime; pytest is test-only.
- Exact in-scope paths are this directory's `__init__.py`, `contracts.py`,
  `backend.py`, `EXPERIMENT_SPEC.json`, `README.md`, `WORK_PACKET.md`,
  `test_contracts.py` and `test_backend.py`. Any other path is out of scope.

Baseline before this packet: Packet 001 offered a generic precomputed filler
whose identity bound only a vector table; it did not bind model/checkpoint,
tokenizer, query/document tower, projection, execution/cost receipt, block
layout or egress inheritance. The retained real `project_tct` diagnostic used
only the frozen hash backend and concluded `INCONCLUSIVE` /
`NO_SCIENTIFIC_VERDICT`; no real semantic-composite baseline exists.

## Colleague question and answer

A new LLM does **not** need to be trained to test a semantic tensor space.
Several frozen vector encoders can be placed in disjoint feature blocks:

`F(x) = direct_sum_e alpha_e * unit(E_e(x))`.

Only coordinates produced by the same encoder are compared. For two complete
inputs with fixed weights:

`dot(F(q), F(d)) = sum_e alpha_e^2 * cos(E_e(q), E_e(d))`.

After the existing tensor encoder applies its constant filler normalization,
the score is divided by `sum_e alpha_e^2`. With the same plane/role kernel,
the same identity holds per encoder tensor. Thus **Direct Sum versus weighted
score fusion is a null/bug test, not an effect claim**. A mismatch above
`1e-10` invalidates the implementation.

Direct sum safely isolates unrelated coordinate systems; it does not align
them. Learned linear or low-rank projections may become a later experiment
only after frozen singleton/direct-sum/fusion runs demonstrate complementary
errors on development repositories. Packet 002 permits identity projections
only. Encoder fine-tuning or training a new LLM is outside this packet.

## Frozen construct

- Every block embeds a complete immutable `EncoderManifest`: exact query and
  document checkpoint digests, tokenizer and revision, templates,
  preprocessing, pooling, truncation, dtype, native dimension, adapter,
  shared-space evidence and license evidence.
- Every block has an identity `ProjectionManifest`. It has equal source/output
  dimensions, an empty parameter artifact and no training record.
- Blocks are ordered, gapless, unique and have positive amplitude weights at
  most one. No padding, truncation or cross-block coordinate comparison exists.
- Float32 producers may deviate from unit norm by at most `1e-6`; after receipt,
  digest and identity verification the composer deterministically re-normalizes
  each accepted block in reference float64. The aggregate vector ID binds those
  exact normalized coordinates. There is no global composite re-normalization.
- Every non-empty input must have exactly one `VectorReceipt` and source/output
  vector per block. Missing or extra blocks, a non-unit/zero/non-finite vector,
  source/tower/dimension/digest mismatch, or identity mutation refuses the
  complete composition.
- An actually empty RoleField is an explicit all-zero composite with zero
  encoder calls. It is not a substitute for an encoder failure.
- Receipts are content-addressed but remain
  `caller_supplied_unverified`/`retrieval_proposal_only`. Their hashes prove
  internal integrity, not issuer identity or factual truth.
- Numeric vector digests are bound to the originating encoder/projection space;
  identical numbers from unrelated spaces intentionally have different IDs.
- Runtime code is stdlib-only and accepts precomputed values. Network, model
  execution/download, filesystem I/O, subprocesses and fallback encoders are
  absent and contractually forbidden.

## Authority and privacy

Sources and revision-bound candidate trees remain authoritative. Composite
vectors are regenerable proposal projections. They never verify a source,
mint a trusted cross-plane binding, or authorize a write.

Embeddings inherit the egress classification of their source bytes. Filtering
must occur before tokenization/model invocation. The retained `project_tct`
diagnostic is `local_only`, so its full candidate universe may not be sent to a
hosted embedding API. Packet 002 stores neither raw source nor real semantic
vectors; its only vectors are synthetic test fixtures supplied in memory.
Every block receipt, aggregate receipt and serializable composite vector carries
the same egress classification and policy-receipt digest. Those caller-supplied
digests remain unverified; a real run stays blocked until a policy-controlled
local executor independently issues them.

## Claim classes and budget fairness

1. **Direct Sum versus score fusion** uses the exact same encoder outputs,
   calls, inputs and weights. It is an algebraic identity test.
2. **Ensemble versus singleton** is not automatically budget-equal. Report a
   preregistered quality/cost frontier or freeze a total compute cap; output
   dimension alone is not a compute proxy.
3. **Projection versus unprojected fusion** belongs to a future packet with
   frozen base encoders and projection cost/parameters reported separately.

Future receipts must separate query and index-build cost and bind at least:
model/tokenizer/templates, calls and tokens per encoder/role/tower, consumed
byte windows and truncation, active/total parameters, FLOPs or MACs, projection
cost, storage/scoring operations, hardware, peak memory and wall-time shape.
Self-issued receipts cannot satisfy the independent-evidence gate.

## Required controls before any effect claim

- every encoder singleton;
- direct sum and its exact weighted score-fusion null;
- strongest singleton selected on development data only;
- uniform and development-frozen weights;
- duplicated-strongest score-fusion null (outside the unique-block space) and
  a dimension-matched random block;
- joint query/document block permutation and document substitution attack;
- BM25, existing hash tensor/fusion, path/role/plane ablations;
- all-encoder/no-routing as primary; routing experiments separated;
- same candidates, byte windows and no failure-based candidate drops;
- raw/scrubbed views averaged within base case before resampling;
- a second revision-pinned repository evaluated once without retuning.

## Construct budget and expected failures

The current positive construct is capped at two synthetic encoders (dimensions
2 and 3), two amplitude weights (`0.5`, `1.0`), one query, one document, one
non-empty role per artifact, zero external/model/network/filesystem/subprocess
calls, and equality tolerance `1e-10`. Adversarial tests may instantiate
one-block singleton controls and the implementation caps remain 8 encoders,
8,192 scalars per block and 16,384 total scalars. Test runtime is a shape
measurement, not scientific evidence.

Expected and retained failures are: missing/extra blocks, zero/non-finite or
wrong-space vectors, q/doc tower substitution, stale IDs, non-empty input
relabeled as null, egress relabeling, and any direct-sum/fusion delta above
`1e-10`. A real model campaign, hosted `project_tct` encoding, trained
projection, effect verdict and production integration are expected to remain
blocked in Packet 002.

## Migration, rollback and review questions

There is no migration: no production code imports this package and no existing
artifact is rewritten. Rollback is deletion/reversion of exactly the in-scope
directory; Packet 001, sources, evidence and production state remain intact.

Review must answer: Are encoder/tower identities reproducible? Can any missing
block fall back? Are raw and composed vector digests space-bound? Does egress
classification and its policy-receipt digest propagate unchanged? Does score
revalidate original materials rather than trust a replaceable result wrapper?
Do Direct Sum/fusion and tensor/fusion identities hold at `1e-10` after
float64 block normalization? Is every claim still construct-only?

## In scope

- strict content-addressed manifests, spaces, vectors and receipts;
- offline precomputed-vector verification and direct-sum composition;
- corresponding-block scoring and the weighted-fusion identity oracle;
- explicit canonical-null handling;
- synthetic algebra, mutation and runtime-boundary tests;
- compatibility construct using the existing tensor encoder and
  `PrecomputedFillerBackend` without changing either.

## Forbidden

- editing or importing this path from `daedalus/` production code;
- production persistence, network/model clients, dynamic model downloads,
  `trust_remote_code`, filesystem writes or subprocesses;
- silent zero-fill, padding, truncation, fallback, block drop or cross-space dot;
- remote encoding of denied or `local_only` sources;
- gold-aware weights/routing or selection on the test repository;
- trained projections under the identity `/1` schema;
- treating a digest as an independent producer attestation;
- `ADVANCE`, `KILL`, Decision, trusted-edge or promotion APIs.

## Acceptance matrix

| ID | Acceptance condition | Evidence |
| --- | --- | --- |
| S1 | Strict loaders reject unknown/missing/duplicate keys, stale IDs, invalid UTF-8, bool-as-number, NaN/Inf and noncanonical dimensions. | contract/adversarial tests |
| S2 | Encoder, identity-projection, space, backend, vector and receipt bytes round-trip canonically and deterministically. | round-trip tests |
| S3 | Block layouts are gapless/unique and bind the exact experiment digest, encoder, projection, dimension, offset and weight. | layout mutation tests |
| S4 | Vector substitution, q/doc tower swap, cross-space reuse, digest/dimension mismatch, non-unit/zero vector and identity mutation refuse. | material attacks |
| S5 | Every non-empty composition requires exactly all frozen blocks; empty input has a distinct zero-call null. | missing/extra/null tests |
| S6 | Direct-sum dot equals `sum(alpha^2 * block_dot)` within `1e-10`. | algebraic null test |
| S7 | Packet 001's isolated tensor encoding over the composite filler equals normalized per-encoder tensor score fusion within `1e-10`. | cross-packet experiment construct test |
| S8 | Runtime imports no network/model/subprocess module and exposes no embedding fallback, Decision, trusted-edge or promotion API. | AST/import boundary test |
| S9 | No real effect run or scientific verdict occurs before exact manifests, independent receipts, budget protocol and second repo are frozen. | currently BLOCKED by design |

## Current result

Packet 002 currently establishes only contracts and algebraic construct tests.
It contains no real encoder, no `project_tct` semantic vectors, no comparison
campaign and therefore **no scientific verdict**. A green null test says the
composition is internally coherent; it says nothing about retrieval quality.
