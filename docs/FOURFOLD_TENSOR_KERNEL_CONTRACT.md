# Fourfold Tensor Reference Kernel

Status: experimental, revision-bound, non-authoritative  
Branch: `exp/tensor-kernel-contract-01`

## Decision

Fourfold/Forest remain semantic and compiled-IR authority. `TensorView` and the
sparse relation kernel are regenerable computational projections over one exact
revision; they are not a fifth plane, graph authority, state store, scheduler,
or promotion surface.

The smallest executable sparse authority is now `TypedRelationBlock` itself.
Boolean/natural/tropical/evidence semantics are supplied by the canonical
reference semirings, and composition is performed directly by bounded
`TypedRelationBlock.matmul()` and `TypedRelationBlock.hadamard()`. A separate
contraction-plan AST/interpreter is deliberately not retained unless a concrete
consumer later demonstrates that such a plan representation adds capability
without duplicating validation, budgeting, or execution authority.

Constructing or evaluating any value described here grants no trust, performs
no effect, approves no change, and cannot trigger promotion.

## Double-category reference contract

`daedalus/twin/two_category.py` defines bounded typed boundaries, plane-preserving
boundary maps, open Fourfold components, and transformation 2-cells. Horizontal
and vertical composition are deterministic and tests pin identity,
associativity, interchange, and conservative verification-status composition.

Verification status is a conservative meet:

```text
rejected < proposed < structurally_checked < evaluator_verified
```

`evaluator_verified` remains evidence status only. It is not OwnerApproval or a
PromotionReceipt.

## Semiring reference observers

`daedalus/twin/semiring.py` supplies stdlib-only reference semantics for:

- Boolean path existence;
- natural-number path multiplicity;
- tropical minimum cost;
- bounded evidence provenance.

The evidence observer uses normalized bounded alternatives/conjunctions as the
reference meaning of a future optimized evidence representation. No optimized
backend may redefine the persisted algebra.

The canonical multi-relation compiler in `daedalus/twin/relation_compiler.py`
has an explicit scalar-admission contract over already-normalized semantic
facts. One deduplicated semantic relation coordinate is admitted as `True` for
the Boolean observer and as the unit `1` for the natural observer. Multiple
Forest or verified-binding evidence bundles supporting that same coordinate do
not increase the natural input scalar; natural multiplicity is produced by
semiring composition of distinct semantic paths. Under the evidence observer,
those bundles instead become the canonical alternative conjunctions of one
`EvidenceValue`. A protocol backend may implement the same named algebra, but
persisted values and operations remain checked against the canonical reference
semantics for that name.

This contract does not reinterpret `ForestEdge.weight`. Tropical compilation
therefore remains refused until a separate, explicit non-negative cost
projection is defined.

## Typed sparse relation blocks

`daedalus/twin/relation_blocks.py` stores each relation family as a typed CSR
block. Every block binds one repository, one exact source revision and one exact
`FourfoldSnapshot` digest. Axes include their Fourfold planes; cross-subject,
cross-revision, wrong-semiring and incompatible-axis operations fail closed.

`matmul()` and `hadamard()` are the executable reference composition operations.
They enforce bounded operation counts directly while emitting canonical CSR,
so callers do not need a second interpreter to preflight and then repeat the
same traversal.

## Strict Forest/Fourfold relation projection

`daedalus/twin/relation_projection.py` projects one exact Forest/Fourfold subject
into the Boolean CSR oracle without introducing another graph schema, registry
or store.

- Forest content digest must equal `FourfoldSnapshot.source_forest_sha256`.
- Both endpoint planes must be `complete`; sparse zeroes cannot stand for
  unknown partial/absent facts.
- Cross-plane rows come only from verified `FourfoldSnapshot.bindings`.
- Same-plane rows come only from directed `ForestEdge` payloads whose canonical
  digest is retained by the source plane.
- Retained hyperedges and undirected edges refuse instead of being flattened
  into invented pairwise/directional semantics.
- This strict one-relation adapter is Boolean-only; it does not infer scalar
  meaning from Forest weights or evidence packaging.

The separate canonical multi-relation compiler may use Boolean, natural, or
`evidence-dag` observers only under the explicit scalar-admission contract
above. It likewise refuses retained hyperedges and undirected `ForestEdge`
records whenever discover-all or an explicitly selected relation would require
lossy pairwise/directional flattening. An explicitly unrelated selection may
prune such source evidence without materializing it. The compiler does not
broaden the strict adapter or authorize weighted/cost projection.

The adapter reuses canonical Fourfold plane/node tuples where possible and skips
Forest relation hashing when the authoritative retained relation set is empty.
These are containment/gardening changes, not a second lookup/index layer.

## Contraction-plan experiment pruned (G1-TENSOR-01CV)

The former `daedalus/twin/contractions.py` added `BlockRef`, `Compose`,
`Hadamard`, `ContractionPlan`, and `ReferenceContractionInterpreter` around the
same `TypedRelationBlock` operations. The interpreter repeated subject/axis/
semiring checks and separately counted operation work before delegating to
`matmul()`/`hadamard()`. It was not exported from `daedalus.twin` and therefore
created a parallel execution/budget abstraction without a required product
surface.

G1-TENSOR-01CV removes that 280-line module and its 377-line dedicated
interpreter-budget test file. The retained multi-hop Fourfold regression now
executes the same two matrix compositions and Hadamard intersection directly
through `TypedRelationBlock`, preserving the actual sparse semantics while
removing the duplicate plan/interpreter layer. This is a deletion/containment
result, not a new tensor feature or benchmark claim.

## Diagnostics and falsification

Bounded diagnostics compare direct Forest, preindexed Forest, generic
`TensorView`, and strict Fourfold Boolean CSR on exact shared subjects. Reports
are explicitly `authority=diagnostic-only` and `claim=none`; their numbers do
not authorize architectural promotion.

Current evidence continues to falsify a general-purpose CSR-query-engine claim:
for the simple and held-out workloads exercised so far, preindexed Forest is
materially cheaper than the strict CSR path. The useful Tensor/CSR scope remains
composition, typed algebra, evidence semantics, and workloads where those
properties simplify or improve execution. Otherwise the kernel should be
contained or pruned rather than expanded with GraphBLAS/GPU/backend layers.

## Acceptance boundary

Executable checks cover:

- semiring identities, associativity, annihilation/distributivity and bounded
  scalar contracts;
- evidence alternatives/conjunction/absorption and canonical digests;
- canonical relation-compiler scalar admission: Boolean existence, natural
  unit-per-semantic-coordinate path counting, and evidence-bundle alternatives;
- direct sparse multi-hop Fourfold composition via `matmul()` + `hadamard()`;
- Boolean existence, natural multiplicity, tropical minimum cost and evidence
  provenance over the same CSR mechanism;
- exact Fourfold subject/revision binding and typed-axis compatibility;
- strict Forest/Fourfold identity/completeness before relation projection;
- direct-Forest equivalence for admitted same-plane and verified cross-plane
  Boolean relations;
- explicit refusal for retained hyperedges and undirected same-plane edges;
- deterministic canonicalization and bounded CSR construction/contraction;
- double-category identity/associativity/interchange laws;
- absence of trust, promotion and effect surfaces.

## Deliberately deferred

This experiment does **not** add:

- GraphBLAS, NumPy, PyTorch, GPU or another runtime dependency;
- a new contraction-plan DSL/interpreter after G1-TENSOR-01CV pruning;
- a sheaf/Laplacian implementation;
- structural sharing or a persistent block store;
- latent Tucker/RESCAL models;
- automatic edge trust, OwnerApproval or promotion;
- polygraphic normal forms or coherence receipts;
- a replacement for `TensorView`, Forest or `FourfoldSnapshot`;
- weighted/tropical projection that reinterprets Forest payload weights without
  an explicit scalar cost contract.

A future plan/compiler layer must be justified by a concrete consumer and must
reuse the canonical block semantics and budget authority rather than recreate
them. A future optimized sparse backend must be observationally equivalent to
the stdlib reference kernel before it can be considered for use.
