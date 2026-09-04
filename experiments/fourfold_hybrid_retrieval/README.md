# Fourfold hybrid retrieval experiment

Status: **contained EXPERIMENT**, Gate 1, proposal-only.

This packet implements the missing architectural seam identified by the
Tensor/Fourfold diagnostics:

```text
natural-language query
    -> existing BM25 + exact-identity index
    -> lexical seed nodes
    -> logical typed relation paths
    -> physical relation-block adjacency indices
    -> evidence-bearing graph expansion
    -> reciprocal-rank fusion
    -> unverified retrieval proposals
```

BM25 is not treated as a competitor that Tensor algebra must replace. It is a
physical access path used by the logical Fourfold query layer.

## Implemented boundary

`relations.py`

- compiles one exact `KnowledgeForest` + `FourfoldSnapshot` pair;
- refuses a mismatched Forest digest or omitted Forest nodes;
- retains repository ID, source revision, Forest digest and Fourfold digest;
- creates one deterministic `TypedRelationBlock` per
  `(source_plane, relation, target_plane)`;
- preserves many-to-many endpoints instead of `dict[str, str]` overwrite;
- merges duplicate Forest/Fourfold evidence without counting one semantic edge
  twice;
- treats blocks as regenerable indices, never as graph authority.

`planner.py`

- represents paths with `RelationStep`, `PathExpression` and `ContractionPlan`;
- supports forward and reverse traversal;
- combines path results through `union` or `intersection`;
- compiles logical steps to forward/reverse hash adjacency indices;
- names the physical strategies (`adjacency_lookup`, `sparse_hash_join`,
  `set_union`/`set_intersection`);
- retains bounded evidence derivations and rejects cross-revision/catalog drift.

`retrieval.py`

- reuses the frozen pure-stdlib s07 `BM25Index`;
- indexes Node Cards rather than flattening the whole repository into one
  tensor;
- obtains seed nodes in the plan's start plane;
- executes the typed graph plan for every retained seed;
- fuses direct target-plane BM25 results and graph-derived results through RRF;
- emits a revision-bound, proposal-only receipt with seeds, branches and
  evidence digests.

## Example: a real multi-hop Fourfold query

```python
plan = ContractionPlan(
    name="imported-type-document-consistency",
    combine="intersection",
    paths=(
        PathExpression(
            name="declared_type",
            steps=(
                RelationStep(RelationSignature("code", "imports", "code")),
                RelationStep(RelationSignature("code", "declares", "type")),
            ),
        ),
        PathExpression(
            name="documented_type",
            steps=(
                RelationStep(
                    RelationSignature("code", "documents", "knowledge")
                ),
                RelationStep(
                    RelationSignature("knowledge", "mentions_type", "type")
                ),
            ),
        ),
    ),
)
```

The logical question is:

```text
(imports @ declares) INTERSECT (documents @ mentions_type)
```

The executor can answer it through relation-specific indices while retaining
the concrete evidence path for every result.

## Verification

From the repository root:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -q tests/twin/test_fourfold_hybrid_retrieval_experiment.py
```

The focused tests cover:

- deterministic Forest/Fourfold compilation;
- many-to-many relation preservation;
- logical multi-hop intersection;
- physical index strategy selection;
- evidence retention;
- mismatched-type rejection;
- BM25 seed retrieval plus graph reranking;
- proposal-only receipts;
- Forest/Fourfold digest mismatch refusal.

## Deliberately not implemented

This packet does not add:

- a production retrieval API;
- a vector database or learned embedding backend;
- an automatic natural-language route generator;
- a new store, scheduler, evaluator or promotion path;
- GraphBLAS/GPU execution;
- a benchmark-superiority claim.

The next admissible experiment is a frozen benchmark matrix comparing direct
BM25, four independent relation indices, this hybrid, and the same hybrid with
semantic multi-vector Node Cards on exact lookup, paraphrase, cross-plane
consistency and impact-analysis tasks under equal context-token budgets.
