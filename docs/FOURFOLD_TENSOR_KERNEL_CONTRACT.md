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

The bounded relation cost probe now also exercises this strict adapter as a
fourth diagnostic arm. Its test fixture mechanically marks only the Code and
Knowledge endpoint planes complete while preserving their exact nodes, retained
relation digests and Forest identity. Direct Forest, preindexed Forest,
`TensorView`, and strict Boolean CSR arms are built from the same complete
Fourfold construction basis and must return the same result subject before any
cost numbers are emitted. Those measurements remain diagnostic-only.

The schema-v5 diagnostic uses the Boolean CSR blocks' existing shared row axis
and `row_offsets` for the row-support query instead of rebuilding source sets by
iterating every stored entry. A focused regression makes `iter_entries()` fail
on this probe path. This is a measurement-harness correction that reuses the
existing CSR representation; it does not add a query index, cache, public API,
or backend.

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
- result identity across direct Forest, preindexed Forest, generic `TensorView`,
  and strict Fourfold Boolean CSR diagnostic arms on the same complete fixture;
- direct use of the existing CSR shared-row support for the bounded Boolean
  relation probe, without an `iter_entries()` rescan;
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

The corrected row-support probe changes the bounded CSR observation but does
not reverse the architecture decision: on its exact hosted run, the CSR arm
remained slower than direct Forest and preindexed Forest for this simple query,
while being cheaper than the generic `TensorView` arm. The next useful work is
therefore a concrete composition/evidence task where the existing relation
blocks simplify semantics or execution; otherwise contain/prune the kernel.
Do not add a backend merely because one could be added, and do not infer
comparative superiority from diagnostic timings.