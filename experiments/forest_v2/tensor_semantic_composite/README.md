# Semantic composite tensor experiment

This Gate-0 package answers one narrow architecture question: frozen semantic
encoders can be combined without training a new LLM. Their vectors are kept in
separate, ordered blocks and then used as the feature axis of the existing
plane × role × feature tensor construct.

Status: **EXPERIMENT / contract-and-construct only / no scientific verdict**.

The frozen protocol is [EXPERIMENT_SPEC.json](EXPERIMENT_SPEC.json), whose
current domain-separated canonical-JSON digest is
`sha256:7338880c92ed1cd4e389baef55ae33f648882b83166212d37df3d43835013b46`.
A real `CompositeSpaceSpec` must bind exactly that exported Packet-002 digest;
a changed protocol requires a code/schema review and cannot silently reuse the
old space ID.

## What is implemented

- `contracts.py`: strict immutable encoder manifests, identity projections,
  gapless block spaces, space-bound vector digests, redacted per-vector cost /
  execution receipts, composite vectors and aggregate receipts. Derived vectors
  retain source egress classification plus its policy-receipt digest.
- `backend.py`: a pure, offline composer that accepts complete precomputed
  vector material, verifies it fail-closed, concatenates weighted blocks and
  scores only matching blocks.
- `test_contracts.py` and `test_backend.py`: canonical round trips,
  substitution/tower/digest/dimension/missingness attacks, algebraic identity,
  canonical tensor compatibility and runtime-boundary checks.

The backend does **not** expose `embed(text)`. That would hide model execution,
egress, tower selection and cost. An authorized caller must run each frozen
encoder outside this package, retain independent execution/cost evidence, and
provide a `VectorReceipt`, the source vector and the identity-projection output
vector for every required block.

## Score semantics

Producer vectors must be within `1e-6` of unit norm. After validating their
space-bound digests and identity projection, the composer re-normalizes each
block once in reference float64. For those block-unit vectors and amplitude
weights `alpha_e`, composition is:

`F(x) = direct_sum_e alpha_e * E_e(x)`.

The backend score is exactly:

`sum_e alpha_e^2 * dot(E_e(q), E_e(d))`.

The existing tensor encoder normalizes the complete filler by the constant
`sqrt(sum alpha_e^2)`, so the corresponding tensor score is the same weighted
fusion divided by `sum alpha_e^2`. Tests require equality within `1e-10`.
This is a correctness null, not evidence that ensembles beat a singleton.

## Running the isolated tests

From the repository root:

```powershell
python -B -m pytest experiments/forest_v2/tensor_semantic_composite -q
```

No real model is downloaded or invoked. The test vectors are small synthetic
fixtures kept in process. The main tensor packet and production kernel are not
modified by this package.

See [WORK_PACKET.md](WORK_PACKET.md) for authority, privacy, controls, budget
fairness and future projection-head gates.
