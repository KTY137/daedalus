# ADR-020 — Forest and Fourfold authority boundary

Renumbered 2026-08-22 from `docs/adr/ADR-0001-FOREST-FOURFOLD-AUTHORITY.md`; the
`docs/adr/` namespace was merged into `docs/adrs/`. See `docs/adrs/README.md`.

Status: proposed for independent review  
Date: 2026-08-01  
Gate: 0 — Canonical Kernel  
Authority: derived decision record; cannot override the Iron Plan

## Context

Daedalus needs one coherent representation of a repository across Code, Type,
Data, and Knowledge planes. The existing `KnowledgeForest` is the immutable
compiled graph IR for one source revision. `FourfoldSnapshot` partitions and
summarizes verified Forest evidence by constitutional plane.

Polyglot extractors introduce a serious architectural risk: Python, Rust, Java,
C++, ROOT, data, and knowledge adapters could each become an independent graph
or truth store. A second risk is treating parser output, model output, or a
Fourfold projection as equivalent to source-derived verified facts.

## Decision

1. Authoritative source and candidate trees remain content-addressed source
   artifacts.
2. `KnowledgeForest` remains the only compiled graph authority for one source
   revision.
3. `FourfoldSnapshot` is an immutable semantic projection over one exact
   `KnowledgeForest`; it is never a writable graph authority.
4. Extractor output is staged observation. It becomes Forest content only after
   deterministic validation of source identity, extractor identity, node and
   relation contracts, evidence locators, and revision consistency.
5. `GraphProposal`, model rationale, embeddings, parser success, and suffix
   discovery are hypotheses. None may be inserted directly into verified
   Forest edges or `FourfoldSnapshot.bindings`.
6. Cross-plane bindings represented by Fourfold must correspond to eligible
   verified cross-plane Forest relations with the same endpoints, relation,
   source revision, assurance, and evidence identity.
7. Cache, database, vector index, graph backend, language server index, SCIP
   index, Clang compilation database, ROOT dictionary, and runtime metadata are
   regenerable evidence or query backends. They do not become competing
   authority.
8. Publication is atomic: extractor results stage first; Forest validation and
   Fourfold projection complete before either new revision is published.

## Authority matrix

| Concern | Authority | Derived or staged form |
| --- | --- | --- |
| source bytes and file modes | immutable source artifact | source bundle manifest |
| repository revision | Git tree/content bundle identity | caller-facing revision label |
| syntax observations | source bytes plus versioned extractor evidence | `ExtractorResult` |
| graph nodes and relations | validated `KnowledgeForest` | graph database/index projection |
| plane membership | verified Forest projection rules | `PlaneSnapshot` |
| cross-plane fact | verified Forest relation and evidence | `CrossPlaneBinding` |
| proposed change | `GraphProposal` artifact | UI explanation/model rationale |
| runtime state | Mission/Policy/Execution/Evidence spine | dashboard/chat view |
| promotion | explicit owner decision | status badge or PR state |

## Required invariants

- One node ID belongs to at most one Fourfold plane in a snapshot.
- Every snapshot, plane, binding, extractor result, and evidence locator binds
  one exact source revision or content bundle.
- Fourfold cannot introduce an endpoint absent from its source Forest.
- Fourfold cannot upgrade an unverified or proposed Forest relation.
- A changed source bundle invalidates cached extractor and projection results.
- A stale review, verification report, or owner decision cannot promote a new
  head revision.
- An incomplete extractor does not cause an empty-success complete plane.
- Query backends may be deleted and rebuilt without loss of authoritative data.

## Consequences

### Positive

- Polyglot adapters can evolve independently without creating parallel truth.
- The same trust boundary applies to Tree-sitter, language servers, Clang,
  ROOT dictionaries, SQL/HDF5 readers, and future latent discovery.
- Graph proposals and source materialization remain clearly separated.
- A Fourfold snapshot can be reconstructed and audited from source, extractor
  receipts, Forest identity, and evidence.

### Costs

- Extractor output needs explicit validation and evidence contracts.
- Forest/Fourfold equivalence must be checked mechanically.
- General-repository compilation cannot publish planes incrementally.
- Rich language-server or compiler facts need adapters rather than direct
  storage as a second graph.

## Rejected alternatives

### Fourfold as the primary mutable graph

Rejected because it would duplicate Forest authority and allow projections or
proposals to become source truth.

### One graph per language or plane

Rejected as authoritative storage. Language-specific indices may exist only as
reconstructable staged evidence/query backends.

### Trust parser or language-server output directly

Rejected because parsing success proves syntax recognition, not semantic or
cross-plane correctness, and because parser versions and build context affect
results.

### Use an LLM to reconcile conflicts

Rejected as a truth boundary. Models may propose explanations or repairs;
deterministic or independently controlled verification decides promotion.

## Verification requirements

Before this ADR can be accepted:

- implement a Forest/Fourfold equivalence verifier;
- test missing, extra, reversed, stale-revision, and evidence-repacked bindings;
- test mixed-revision extractor results;
- test deletion and rebuild of query/index backends;
- obtain independent architecture and security review;
- bind the final review and owner decision to the exact PR head SHA.

## Review triggers

Revisit this decision only through the Iron Plan amendment protocol if Daedalus
changes its canonical graph IR, source identity model, promotion boundary, or
number of semantic planes.
