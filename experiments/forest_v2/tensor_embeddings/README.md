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
| `stats.py` | retrieval metrics and strict diagnostic-report validation; `/2` binds `EVALUATION_PROTOCOL_V2.json` |
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
`results/s09_c00_smoke_v2_invalid.json` retains the first complete current-spec
13-arm `c00` attempt. Its ten failures exposed an over-strict validator that
compared the entire score-sorted tuple positionally even when per-path scores
agreed within `1e-10` and the evaluated top 20 was unchanged. The invalid run
and its 753.704-second cost remain visible; repairing the validator did not
change the frozen inputs or any measured score.
`results/s09_c00_smoke_v2.json` retains the then-corrected `/1` rerun at
implementation revision `8562997667931e847a26776a86e5ba74d10163cb`: all 13
arms, five seeds, and both query variants completed with zero runtime failures.
Its old comparison code nevertheless resampled raw and scrubbed views of the
same `c00` base case as two independent cases. The `/2` report contract rejects
that pseudoreplicated comparison census and first averages variants within a
base case before resampling. The measured arm rows remain negative historical
evidence, but the old interval and `VALID` label are superseded. Structured
contraction, flat cosine, and the algebraically equivalent flat bilinear
control all missed top-20; recency hit at rank 5, BM25 at rank 19, and
Mean-MaxSim hit at rank 4 only for seed 47. The recency order is caller-asserted
rather than externally authenticated.
`PERFORMANCE_NOTE.md` retains the aborted slow paths and unvalidated cost-shape
measurements rather than hiding them.

`results/project_tct_analysis_physics_manifest_v1.json` and
`results/project_tct_analysis_physics_report_v2.json` retain a strictly local
real-repository diagnostic. The source is the exact `project_tct` preimage
`382a27136f77985b6b7481ba8ef5420628c4a465` for commit
`3c6c2fd65f88cb5cc85d13bb6990a6c105086c32`. A benchmark-specific blanket
overlay excludes tests, every device file, and `configs/devices.yaml`; this is
deliberately stricter than the project's egress-policy exceptions. The sorted
universe contains 127 candidates (3,102,496 visible bytes) and three gold
files. All 13 arms, five seeds, and both query views completed with zero
runtime or receipt failures under report `/2`. Manifest ID is
`sha256:3151749a756eb5b8ffe8ebfbd066db519887bedc5d470b754e6d2b256e52f5e7`;
canonical report digest is
`sha256:3b87c1027cf1075a2d819918453141de9f7c8c76581ec39c8a5ddc2288c003c9`.

That run is deliberately unflattering evidence, not a win claim. With only one
base case every bootstrap interval is degenerate. Mean raw/scrubbed MRR was
`1.0` for BM25 and fusion, `0.7208` for late interaction, `0.6579` for
structured contraction, and `0.6450` for flat cosine. Plane permutation also
scored `0.6579`, so this case provides no evidence that named plane labels did
the work. It did change cross-plane ordering, but the s09 query has a uniform
plane vector, so this control only permutes a static per-plane scalar prior;
it cannot identify semantic query-to-plane alignment. Path lexical fell from
`1.0` raw to `0.0` after scrubbing. The query
comes from the answer commit and retains symbol/patch leakage; gold and
isolation were not independently issued. An independent local policy audit
also found that 71 of 127 candidates would be withheld from untrusted egress,
so the manifest retains only paths/digests/metrics and is fixed to
`local_only`. It is a post-hoc `diagnostic_example`, not part of the frozen
primary effect corpus, not tuning authority, and not second-repository
transfer evidence. Its scientific status is `NO_SCIENTIFIC_VERDICT`, despite
the report's purely structural `VALID` status and `INCONCLUSIVE` conclusion.

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
