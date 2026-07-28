# Daedalus Foundation Audit

Date: 2026-07-28

## Verdict

The recovery restored useful StructCore and UI code, but several Phase III
claims exceeded the implementation. The corrected foundation keeps the parts
that have evidence and removes names that pretended an algorithm or security
property existed.

| Area | Audited state |
|---|---|
| Agent shells | One-shot subprocess transport with verified Claude and Codex profiles; generic runtimes are configurable |
| Event/latent bridge | Lossless `TransportRecord` stream plus optional, derived embedding projection |
| Spectral view | Sparse, scoped, read-only graph analysis with size limits; never a proof of conflict-free edits |
| Hyperbolic search | Removed: Euclidean embeddings were only radially projected into a Poincaré ball |
| “Gradient” evolution | Removed: a weighted embedding sum was neither a learned gradient nor connected to a code decoder |
| Evolution | Experimental candidate runner only; failure cannot be selected and latent score cannot promote code |
| Hermes | Removed: no upstream integration existed |
| Frontend | Production UI retained; hard-coded Tailwind/Three/Tauri prototype scaffold removed |
| Packaging | Real packages listed explicitly; CLI and compatibility module imports repaired |
| Architecture records | Aspirational decisions are now Proposed/Experimental instead of falsely Accepted |

## The real forest model

“Codebase as tree, all codebases as forest” remains the product model. The
computational object is deliberately more exact:

* nodes: source files now; symbols, tests, build targets, schemas, documents,
  runtime spans, releases, and domain entities later;
* typed edge layers: imports, calls, data flow, ownership, co-change, knowledge
  references, runtime traces, and version lineage;
* hyperedges: clone families, build targets, transactions, schemas, or changesets
  that relate more than two nodes;
* provenance: parser/backend, repository revision, scope, ignore rules,
  extraction method, confidence, and time interval;
* immutable snapshots: deterministic serialization and a content hash so
  experiments compare the same forest.

`structcore.forest` implements the first version over the existing file index:
imports and co-change stay separate, and clone groups remain hyperedges. It does
not manufacture an embedding, hierarchy, or partition.

## What “MetaCoding” should mean

MetaCoding is movement between abstraction levels with receipts:

1. observe a versioned forest snapshot;
2. select an evidence-backed subgraph and context budget;
3. ask an agent shell for a discrete proposal;
4. apply the proposal in an isolated transaction;
5. measure task-specific fitness, safety invariants, and blast radius;
6. promote explicitly or reject, then store the complete trajectory.

A vector can rank context or candidate actions. It cannot directly “move the
code” unless a trained decoder maps that vector to a concrete diff and the diff
passes the same validation gate as any other proposal.

## Math roadmap with gates

### 0. Evidence substrate

Complete the versioned Forest schema, symbol identities, compile/build targets,
knowledge-document ingestion, and lossless shell records. Add confidence and
source-span evidence to every derived relation.

Gate: deterministic rebuilds, stable IDs across unchanged revisions, and no
derived index without a path back to raw evidence.

### 1. Strong non-neural baselines

Evaluate BM25, graph neighborhood expansion, personalized PageRank, Leiden
communities, spectral sweep cuts, and balanced hypergraph partitioning on
separate relation layers and explicit layer mixtures.

Gate: measure context recall@k, token compression, latency, edit locality, and
cross-partition conflicts. A new method must beat the simplest baseline on held
out tasks; attractive visual clusters do not count.

### 2. Learned structural representations

Start with Euclidean relation-aware graph embeddings. Try hyperbolic geometry
only for a benchmark with demonstrably hierarchical targets, trained with a
hierarchy-aware objective and Riemannian optimization. Multi-relational data
requires relation-specific modeling rather than one universal distance.

Gate: ablation against BM25, PageRank, and Euclidean embeddings; report
retrieval quality, hierarchy distortion, calibration, and compute cost.

### 3. Search over code changes

Treat candidate changes as discrete diffs. Use contextual bandits, Bayesian
optimization, or a learned surrogate only to prioritize proposals. Fitness is a
task-specific vector including baseline-relative tests, static checks,
invariants, changed-test policy, performance, and blast radius.

Gate: candidates run in a real security sandbox; evaluator and policy code are
outside the candidate's write boundary; no self-authored test can be sole proof
of success.

### 4. Genuine latent agent communication

For closed CLIs, normalized text/tool/event transport is the honest interface.
For inspectable open models, add a separate capability that captures internal
hidden states and trains an adapter between explicitly named model/layer/token
representations. Keep a text/audit shadow channel.

Gate: compare against equal-budget text communication on task success,
bandwidth, robustness across model/version changes, interpretability, and
recoverability. Disable the latent channel when the model identity or adapter
calibration changes.

## HEP as a vertical benchmark

HEP is a strong optional stress test because it combines large C/C++ and Python
systems, custom build dictionaries and generated code, configuration,
calibration/schema knowledge, papers, and long-lived operational conventions.
The kernel must remain domain-neutral. HEP-specific parsers, ontologies, and
evaluators belong in a domain pack.

The benchmark should include at least:

* symbol and document retrieval tasks;
* cross-language change-impact prediction;
* compile-command-aware C/C++ indexing;
* test selection and defect localization;
* architecture recovery against maintainer labels;
* safe rewrite tasks scored against a frozen baseline.

## References

* Nickel & Kiela, [Poincaré Embeddings for Learning Hierarchical
  Representations](https://proceedings.neurips.cc/paper_files/paper/2017/hash/59dfa2df42d9e3d41f5b02bfc32229dd-Abstract.html)
* Balazevic et al., [Multi-relational Poincaré Graph
  Embeddings](https://proceedings.neurips.cc/paper_files/paper/2019/hash/f8b932c70d0b2e6bf071729a4fa68dfc-Abstract.html)
* Gottesbüren et al., [The KaHyPar Hypergraph Partitioning
  Framework](https://arxiv.org/abs/2106.08696)
* Clang, [JSON Compilation Database
  Format](https://clang.llvm.org/docs/JSONCompilationDatabase.html)
* Hu et al., [Interlat: Latent Communication between Large Language
  Models](https://arxiv.org/abs/2511.09149)
