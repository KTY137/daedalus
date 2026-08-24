# Tensor-product embeddings experiment

Status: **isolated EXPERIMENT**, active Gate 0. It is not wired into Daedalus
product memory, graph authority, policy, evaluation authority, or promotion.
Every search result is labeled `unverified-retrieval-proposal`; automatic
promotions are zero.

The tested object is a `4 x 4 x 32` tensor:

```text
artifact/query
  -> plane factor       code | type | data | knowledge
  -> role factors       path | symbol | content | neighbor
  -> filler vectors     32-d signed lexical/subword count sketch
  -> T[p,r,f]           lossless CP, dense, or Tensor-Train storage
  -> score              flat cosine | structured contraction | Mean-MaxSim
```

The primary comparison is deliberately budget-identical:

- flattened cosine sees all 512 entries of the tensor;
- identity contraction must equal that cosine within `1e-10`;
- structured contraction sees the same entries and applies only the frozen
  plane and role matrices in `EXPERIMENT_SPEC.json`;
- CP, dense, and TT preserve one canonical binary64 materialization; they are
  storage forms, not separate evidence arms.

The structured numerator is exactly

`vec(Q)^T (K_plane ⊗ K_role ⊗ I_feature) vec(D)`.

Tensor notation makes the named axes and factored execution explicit, but this
linear score is also a bilinear operation on an ordinary 512-vector. The frozen
kernels are symmetric positive definite, so the numerator is an ordinary
vector dot product after one fixed linear transform. The experiment therefore
tests a frozen plane/role **structure prior against plain cosine**. It does not
test or claim that tensors are intrinsically superior to vectors.

Read `RESEARCH.md` for the distinction between Tensor Product
Representations, ColBERT-style late interaction, tensorized knowledge-graph
embeddings, and Tensor Train compression. `WORK_PACKET.md` freezes the claim,
budgets, controls, acceptance conditions, and kill criteria.

Category theory is an explanatory dagger-compact interpretation of the chosen
inner-product spaces and contraction diagram. There is no implemented source
grammar/category, monoidal functor, or DisCoCat pipeline.

## Modules

| Module | Responsibility |
| --- | --- |
| `contracts.py` | strict, versioned, content-addressed tensor/spec/kernel contracts |
| `algebra.py` | dense/CP/TT materialization, cosine, contraction, MaxSim, explanations |
| `encoding.py` | offline role/filler encoder, Node Card and s09 adapters |
| `index.py` | caller-owned canonical index bytes, replayable source evidence, frozen-kernel binding, and proposal-only search |
| `storage.py` | measured scalar/canonical-byte receipts for CP, dense and TT |
| `retrievers.py` | eight tensor/control arms with score and input receipts |
| `baseline_retrievers.py` | BM25, deterministic random, path, recency, and plane-wise RRF baselines |
| `arm_census.py` | frozen 13-arm executable/report census |
| `stats.py` | retrieval metrics and strict diagnostic-report validation |
| `benchmark.py` | in-process, equal-input five-seed diagnostic harness |
| `sealed_eval.py` | self-addressed, gold-separated reports plus full manifest-bundle recomputation; no trust claim |
| `cli.py` | stdin-only input and canonical JSON stdout; no filesystem writer |

## Verification

From the repository root:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q -p no:cacheprovider experiments/forest_v2/tensor_embeddings
```

The suite includes 100 seeded CP/dense/TT equivalence cases, identity-cosine
equivalence, malformed/tampered contracts, index mutation, cache/input
receipts, CLI boundary checks, report recomputation, and the retained smoke
result.

## Stdout-only CLI

Inspect the frozen coordinate system and kernel:

```powershell
python -B -m experiments.forest_v2.tensor_embeddings spec
```

Run the non-empirical role-binding construct:

```powershell
python -B -m experiments.forest_v2.tensor_embeddings benchmark --synthetic
```

`encode`, `build`, `search`, and real `benchmark` consume JSON on stdin. Role
fields are capped at 65,536 UTF-8 bytes each, source evidence at 262,144 bytes,
and an index/evaluation case at 65,536 documents. Use
`python -B -m experiments.forest_v2.tensor_embeddings --help` for their flags.
There is intentionally no `--out`/`--write`; stdout bytes are the transport,
and an authorized caller decides whether they are stored. `-B` suppresses
CPython's interpreter-managed bytecode cache; the package itself never opens
or mutates a path.

## Current evidence

`results/s09_c00_smoke.json` retains a historical negative smoke run from the
superseded role-salted v1 hashing backend. Both arms missed top-20. The current
validator intentionally rejects that file because its spec digest predates the
shared role-independent filler space. It has no eligibility manifest and is
therefore diagnostic historical evidence, never a scientific verdict.
`PERFORMANCE_NOTE.md` retains the aborted slow paths and unvalidated cost-shape
measurements rather than hiding them.

The complete 13-arm comparison matrix is executable, including BM25, lexical,
recency, plane-wise RRF, permutation controls, and both query variants. There
is still no complete current-`/2`, independently isolated held-out campaign or
second-repository transfer run. Current output is algebraic/structural or
historical diagnostic evidence only and carries `NO_SCIENTIFIC_VERDICT`.

No production integration should be proposed until a complete, independently
isolated held-out corpus run passes every acceptance condition and beats the
named lexical, recency, fusion, and permutation controls under equal budgets.
The included self-addressed manifests establish integrity only. They cannot
authenticate who produced an isolation/gold receipt. There is currently no
scientific Decision API in `benchmark.py`, `stats.py`, or `sealed_eval.py`:
they emit or accept only diagnostic/structural outcomes. `ADVANCE` or `KILL`
could be considered only after an owner-recorded plan/Work-Packet amendment
and an externally controlled trust chain anchor the frozen inputs, independent
gold/isolation evidence, receipts, and transfer evidence. Neither requirement
is fabricated inside this experiment.
