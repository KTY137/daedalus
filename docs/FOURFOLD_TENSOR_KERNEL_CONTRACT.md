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
reference semirings. Composition, slicing and whole-block scalar reduction are
performed directly by bounded `TypedRelationBlock.matmul()`,
`TypedRelationBlock.hadamard()`, `TypedRelationBlock.slice()` and
`TypedRelationBlock.reduce()`. A separate contraction/reduction plan
AST/interpreter is deliberately not retained unless a concrete consumer later
demonstrates that such a plan representation adds capability without
duplicating validation, budgeting, result identity, or execution authority.

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

`slice()` is the canonical axis-subset operation. It canonicalizes requested
labels by the existing typed-axis order, rejects unknown or duplicate labels,
preserves the exact `ProjectionSubject`, `RelationSignature` and semiring, and
returns the existing immutable block when both axes are unchanged. It creates
only a short-lived local column-position remap while projecting CSR; it does not
introduce a persistent label index, second slice representation, or new result
authority. When a same-plane block shares one axis object and the requested row
and column subsets are identical, the sliced block preserves that shared axis
identity.

`reduce()` is deliberately narrower than an axis-wise aggregation API. It folds
only the retained sparse values, in canonical CSR order, with the canonical
semiring addition and the existing `max_operations` budget. Implicit sparse
zeroes are the additive identity and are not materialized. The result is a pure
scalar observer of the exact block subject; no derived vector/result object is
retained. Axis-wise reduction remains deferred until a concrete consumer
requires a revision-bound axis-plus-values identity that can be owned without
creating a parallel result hierarchy.

## Strict Forest/Fourfold relation projection

`daedalus/twin/relation_compiler.py` is the sole implementation owner for
Forest/Fourfold relation admission and sparse-block materialization. It compiles
one exact Forest/Fourfold subject into the canonical typed CSR oracle without
introducing another graph schema, registry or store. The public
`boolean_relation_block_from_fourfold` function in
`daedalus/twin/relation_projection.py` is retained only as the historical
single-relation Boolean call shape and delegates directly to
`compile_relation_blocks`; it owns no independent admission, diagnostics or
materialization semantics.

The canonical compiler enforces:

- Forest content digest must equal `FourfoldSnapshot.source_forest_sha256`.
- Both endpoint planes of an explicitly materialized relation must be
  `complete`; sparse zeroes cannot stand for unknown partial/absent facts.
- Cross-plane rows come only from verified `FourfoldSnapshot.bindings`.
- The legacy Forest-to-Fourfold adapter refuses an undirected cross-plane
  `ForestEdge` instead of inventing a directed verified binding from endpoint
  storage order.
- Same-plane rows come only from directed `ForestEdge` payloads whose canonical
  digest is retained by the source plane.
- Retained hyperedges and undirected edges refuse instead of being flattened
  into invented pairwise/directional semantics.
- Boolean, natural and `evidence-dag` observers are admitted only under the
  explicit scalar-admission contract above. Tropical/weighted projection stays
  refused until an explicit cost contract exists.

Discover-all compilation and explicit signature selection share that one owner.
Retained hyperedges and undirected `ForestEdge` records are refused whenever the
selected relation would require lossy pairwise/directional flattening; an
explicitly unrelated selection may prune such source evidence without
materializing it. Explicit signature selection also prunes unrelated directed
same-plane edges before relation hashing, so affected-signature work should
reuse that seam rather than add a second compiler or digest/index owner.
The Boolean compatibility facade does not broaden or narrow these decisions: it
requests exactly one signature with `BooleanSemiring()` and returns the
compiler-produced block.

The compiler reuses canonical Fourfold plane/node tuples where possible and
skips Forest relation hashing when the authoritative retained relation set is
empty. These are containment/gardening changes, not a second lookup/index layer.
Keeping the small public compatibility facade avoids an unnecessary API break;
it is not a second projector.

## Revision-bound delta boundary

A `TypedRelationBlock` is bound to one exact `ProjectionSubject`, including the
source revision and Fourfold digest. A block from one revision therefore cannot
be patched in place and still claim the old subject identity after a semantic
delta. Same-signature/same-axis shape does not relax that boundary: composition
between blocks from different subjects fails closed.

The current Forest/Fourfold delta surfaces do not provide a canonical,
persistent digest-to-edge/signature authority suitable for a trusted sparse
block patch path. Adding a Tensor-owned digest index, accepting caller-trusted
digests, or retaining a second incremental relation compiler would create a
parallel trust/graph authority. Incremental block application is therefore
deferred until an authoritative revision transition can produce a
candidate-subject-bound result without weakening provenance or duplicating the
canonical relation compiler.

## Directed relation and reverse-query boundary

`RelationSignature(source_plane, relation, target_plane)` is directional.
Generic matrix transposition is not relation-semantic inversion: transposing a
block would swap endpoints while leaving a relation name such as `imports`
unchanged, which would misstate the underlying Fourfold relation unless an
explicit inverse relation contract existed.

Reverse traversal is already owned where it is semantically a query orientation.
StructCore maintains `import_edges_reverse` for callers/dependents views and
safety/context consumers; those reverse maps answer incoming-neighbour queries
over existing directed evidence rather than minting new relation truth. On the
Forest/Fourfold side, reverse adjacency is synthesized only for explicitly
undirected edges; directed edges and Fourfold bindings retain their original
source/target orientation.

Consequently the sparse reference kernel does not add a generic
`TypedRelationBlock.transpose()`, a CSC/reverse-block cache, a Tensor `incoming()`
API, synthetic inverse relation names, or an inverse-relation registry. A future
reverse relation capability must be justified by an explicit semantic inverse
contract or reuse an existing query owner; mathematical convenience alone is
not sufficient.

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
composition, typed algebra, evidence semantics, canonical slicing/reduction,
and workloads where those properties simplify or improve execution. Otherwise
the kernel should be contained or pruned rather than expanded with
GraphBLAS/GPU/backend layers.

## Acceptance boundary

Executable checks cover:

- semiring identities, associativity, annihilation/distributivity and bounded
  scalar contracts;
- evidence alternatives/conjunction/absorption and canonical digests;
- canonical relation-compiler scalar admission: Boolean existence, natural
  unit-per-semantic-coordinate path counting, and evidence-bundle alternatives;
- direct sparse multi-hop Fourfold composition via `matmul()` + `hadamard()`;
- deterministic canonical `slice()` order, subject/signature preservation,
  unknown/duplicate-label refusal, full-block reuse, same-plane shared-axis
  reuse, and canonical empty slices;
- bounded whole-block `reduce()` semantics for the canonical reference
  semirings, including empty-block identity and operation-limit refusal;
- Boolean existence, natural multiplicity, tropical minimum cost and evidence
  provenance over the same CSR mechanism;
- exact Fourfold subject/revision binding and typed-axis compatibility;
- strict Forest/Fourfold identity/completeness before relation projection;
- direct-Forest equivalence for admitted same-plane and verified cross-plane
  Boolean relations;
- explicit refusal for undirected cross-plane legacy edges before they can be
  upgraded into directed verified Fourfold bindings;
- explicit refusal for retained hyperedges and undirected same-plane edges;
- deterministic canonicalization and bounded CSR construction/contraction;
- double-category identity/associativity/interchange laws;
- absence of trust, promotion and effect surfaces.

## Deliberately deferred

This experiment does **not** add:

- GraphBLAS, NumPy, PyTorch, GPU or another runtime dependency;
- a new contraction/reduction-plan DSL/interpreter after G1-TENSOR-01CV pruning;
- axis-wise reduction or a `TypedVector`/derived-result hierarchy without a
  concrete revision-bound consumer;
- generic relation transpose, synthetic inverse relation names, an inverse
  relation registry, or a Tensor-owned reverse traversal index;
- trusted/in-place delta application, a Tensor-owned digest-to-edge index, or a
  second incremental relation compiler;
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
