# G0-RWI-20I — Exact Structural Python Target Resolution

## Parent and purpose

This packet is stacked on exact parent
`be334863eca4944977f38feaf94ab25fe0671227` from
`g0/repository-tree-reader-linear`.

It adds a conservative Python structural front-end for guard implementation
targets. A canonical `daedalus.module:Qualified.name` is mapped to an exact
repository source snapshot, bound to an expected SHA-256, parsed with the Python
AST without importing or executing code, and resolved to one unique definition
chain.

## Structural contract

The resolver:

- accepts canonical Daedalus module and object identifiers only;
- maps the module deterministically to `daedalus/.../<module>.py`;
- reads through the shared exact repository-tree boundary;
- compares the expected source digest before AST projection;
- parses a module without imports, decorator evaluation, `exec`, or `eval`;
- supports top-level functions, async functions, classes, and methods;
- permits qualified children only beneath classes;
- rejects missing and duplicate definitions rather than choosing one;
- returns exact definition kind, chain kinds, source path/digest/size, and
  start/end positions.

The result claims structural presence only. It permanently reports
`behavior_verified=false` and `executed=false`. It does not replay a guard,
authenticate repository-write evidence, or bind/close a GateReport.

## Adversarial batch

Prepared behavior coverage includes non-executing resolution despite top-level
raises and unknown decorators, top-level async functions, malformed targets,
deterministic module mapping, missing sources, stale digests, invalid syntax,
missing and duplicate definitions, non-class qualified parents, strict digest
shape, changed bytes, and detached result-chain metadata.

A separate AST/source review checks absence of import/execution mechanisms,
digest-before-AST ordering, conservative unique definition chains, permanent
non-behavior claims, and exclusive use of the shared repository-tree reader.
Eight bounded mutants attack target grammar, source binding, missing/ambiguous
definitions, function parents, behavior/execution claim escalation, and chain
detachment.

An isolated module harness reports `26 passed`; all eight bounded mutants were
killed. This is preparatory author-side evidence only, not exact-head repository,
supported-platform, packaging, independent-human, behavioral, or Gate evidence.

Exact-head CI requests Ubuntu and Windows on Python 3.10 and 3.12 with two hash
seeds, predecessor regressions, mutation, Iron Plan verification, full suite,
package build, and isolated-wheel import. GitHub Actions issue #67 continues to
produce zero-step jobs without logs or artifacts.

No merge, promotion, OwnerApproval, or Gate transition is requested.
