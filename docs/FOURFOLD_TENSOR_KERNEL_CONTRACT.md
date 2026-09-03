# Fourfold Double-Category and Semiring Reference Kernel

Status: experimental, revision-bound, non-authoritative  
Branch: `exp/tensor-kernel-contract-01`

## Decision

`TensorView` remains the canonical, deterministic wire/snapshot contract. It is
not promoted into the high-throughput query engine. The new modules are a
regenerable semantic and computational projection over the existing Forest and
`FourfoldSnapshot` authorities:

```text
Forest / FourfoldSnapshot / evidence receipts
                    |
                    | compile (pure, revision-bound)
                    v
Typed boundaries + open components + evidence-bearing 2-cells
                    |
                    | realization under an explicit semiring
                    v
Typed sparse relation blocks + reference contractions
```

Constructing or evaluating any value described here grants no trust, performs
no effect, approves no change, and cannot trigger promotion.

## Implemented packet

### Double-category reference contract

`daedalus/twin/two_category.py` defines:

- `TypedBoundary`: a canonical finite signature partitioned across code, type,
  data, and knowledge ports;
- `BoundaryMap`: a total, plane-preserving vertical migration;
- `OpenFourfoldComponent`: a revision-bound horizontal component expression;
- `Transformation2Cell`: a square between old and new components with rewrite,
  observer-receipt, and invariant references.

Horizontal composition concatenates component factors. Vertical composition
composes boundary maps. A 2-cell can be composed vertically with a successive
transformation or horizontally with a neighboring component transformation.
The implementation pins identity, associativity, and interchange laws in tests.

Verification status is a conservative meet:

```text
rejected < proposed < structurally_checked < evaluator_verified
```

A composite never becomes stronger than either input. `evaluator_verified` is
only an evidence status; it is not owner approval or promotion. Identity cells
use the top element as the neutral algebraic status and do not claim an
external evaluation occurred.

`rewrite_sha256s` is a canonical set of referenced rewrite artifacts. Ordering
inside a rewrite belongs to the content-addressed rewrite artifact itself. This
lets pasting diagrams satisfy strict interchange without pretending that two
arbitrary rewrite sequences are coherent. Explicit rewrite-path equivalence and
`CoherenceReceipt` remain a later packet.

### Semiring reference observers

`daedalus/twin/semiring.py` supplies stdlib-only executable semantics for:

- Boolean path existence;
- natural-number path multiplicity;
- tropical minimum cost;
- evidence provenance.

The evidence observer uses a bounded, normalized disjunctive normal form as the
reference meaning of a future hash-consed evidence DAG. Multiplication means
all evidence atoms are jointly required. Addition means alternative derivations
exist. Absorption canonicalizes `a OR (a AND b)` to `a`.

### Typed relation blocks

`daedalus/twin/relation_blocks.py` stores each relation family in a separate CSR
block whose source and target planes are part of its signature. Every block
binds one repository, one exact source revision, and one exact
`FourfoldSnapshot` digest. Cross-revision contractions fail closed.

This removes per-entry repetition of plane and relation strings while retaining
canonical digests. It is a reference representation, not a new state store.

### Strict Forest/Fourfold relation projection

`daedalus/twin/relation_projection.py` wires one exact Forest/Fourfold subject
into the existing Boolean CSR oracle without introducing another graph schema,
registry or store.

- the Forest content digest must exactly match `FourfoldSnapshot.source_forest_sha256`;
- both endpoint planes must be `complete`, because `TypedRelationBlock` has no
  partial/absent status and therefore cannot safely encode an incomplete plane;
- cross-plane rows come only from verified `FourfoldSnapshot.bindings`;
- same-plane rows come only from directed `ForestEdge` payloads whose canonical
  digest is retained by the plane's `relation_sha256s`;
- retained hyperedges and undirected edges refuse instead of being flattened
  into invented pairwise/directional semantics;
- the adapter is intentionally Boolean-only. Forest weights, multiplicity,
  costs and evidence-bundle algebra remain unsupported until their projection
  semantics are explicit.

Focused tests compare the generated blocks against the direct Forest subject
and compose an admitted same-plane relation with an admitted cross-plane
relation through the existing reference kernel. A legacy partial Fourfold
snapshot is required to refuse rather than silently turning unknown edges into
sparse zeroes.

### Contraction IR

`daedalus/twin/contractions.py` implements three operations:

```text
BlockRef(name)
Compose(left, right, relation)      # semiring matrix product
Hadamard(left, right, relation)     # element-wise semiring product
```

The reference interpreter executes, for example:

```text
(imports @ declares) AND (documents @ mentions_type)
```

with type checks, exact subject binding, deterministic CSR output, and bounded
operation counts. A future GraphBLAS or specialized compiler must match this
interpreter before it can be trusted as an optimization.

## Tests and acceptance boundary

The packet includes executable checks for:

- additive and multiplicative identities, associativity, annihilation, and
  distributivity for all four semirings;
- evidence alternatives, conjunction, absorption, and canonical digests;
- the concrete multi-hop Fourfold query above;
- Boolean existence, natural multiplicity, tropical minimum cost, and evidence
  provenance over the same sparse composition mechanism;
- strict Forest/Fourfold identity and completeness before relation projection;
- direct-Forest equivalence for admitted same-plane and verified cross-plane
  Boolean relations;
- explicit refusal for retained hyperedges and undirected same-plane edges;
- revision and semiring isolation;
- boundary-map and component identities/associativity;
- vertical and horizontal 2-cell composition;
- the double-category interchange law;
- conservative verification status and absence of promotion surfaces.

## Deliberately deferred

This packet does **not** add:

- GraphBLAS, NumPy, PyTorch, GPU, or another runtime dependency;
- a sheaf/Laplacian implementation;
- structural sharing or a persistent block store;
- latent Tucker/RESCAL models;
- automatic edge trust, owner approval, or promotion;
- polygraphic normal forms or coherence receipts;
- a replacement for `TensorView`, Forest, or `FourfoldSnapshot`;
- weighted, natural-count, tropical-cost or evidence-DAG projection from Forest
  payloads whose scalar meaning has not been specified.

The next useful packet is to add this strict relation adapter as a fourth arm in
the existing bounded Forest/preindexed/Tensor cost probe using a fixture whose
endpoint planes are mechanically known complete. Performance remains diagnostic
until repeated equal-budget measurements justify a claim. The kernel should be
removed if it merely renames graph fields and cannot simplify evidence
composition or multi-relation query execution.
