# G2-PREP-ROOT01 — ROOT metadata evidence remains partial

## Purpose

This non-authoritative Gate-2 preparation packet narrows the assurance claim of
the optional Uproot adapter. It is a separate batch from Tree-sitter assurance
because binary Data-Plane metadata has different failure and provenance
boundaries.

It does not read event arrays, publish an authoritative Data Plane or Forest,
create trusted cross-plane bindings, alter production execution, merge, promote
or close any gate. Gate 0 remains the active authoritative gate.

## Finding

The adapter intentionally inventories only ROOT object classes and TTree/RNTuple
field metadata. It disables Uproot object and array caches and never reads event
payloads. Nevertheless, a metadata scan without warnings previously returned
`ExtractorResult.status == "complete"`.

Metadata alone does not establish:

- payload readability or event-level validity;
- array lengths, nullability, ranges or domain invariants;
- semantic type identity beyond serialized type-name strings;
- producer, transformation or dataset provenance;
- data lineage or correspondence to source-code and knowledge claims;
- complete file or repository semantics.

The reusable extractor contract therefore overstated the assurance supplied by
the implementation.

## Correction

Every successful metadata inventory now returns `status="partial"` and retains a
mandatory `metadata-only` warning. Existing per-object field-inspection warnings
remain and precede that diagnostic. Failed opens, source identity mismatches and
resource-limit violations remain fail-closed.

The mandatory limitation diagnostic is included in the canonical report digest.
Object, field, relation and evidence identities remain deterministic and usable
as staged Data-Plane observations.

A later payload-aware Data-Plane frontend may make a stronger claim only when it
binds exact revision, file identity, schema coverage, payload checks,
provenance/lineage and the relevant policy/evidence contracts. Uproot metadata
inventory alone must never become trusted semantic completeness.

## Independent counter-review finding

The first correction still assumed that a successfully opened ROOT file could
always enumerate its object directory. A malformed streamer or directory can
allow `uproot.open()` to succeed and then make `classnames()` raise. That path
previously escaped as an unstructured exception.

The adapter now converts enumeration failure into the canonical fail-closed
`root-metadata-enumeration-failed` report and closes the file in the surrounding
`finally` block. The dependency-free fake reader proves both the failure status
and close behavior. This is model-assisted review support, not an independent
human approval or hard Gate evidence.

## Adversarial verification requested

The packet adds:

1. real Uproot/Numpy fixture tests requiring clean metadata inventory to remain
   partial while retaining objects, fields and deterministic relations;
2. a dependency-free fake Uproot file proving both the successful partial result
   and fail-closed object-directory enumeration when optional packages are absent;
3. an AST counter-review rejecting any successful `status="complete"`
   assignment;
4. a bounded mutation changing the sole successful partial assignment to
   complete, with green-baseline, killed-mutant and byte-restoration checks.

Dedicated CI requests Ubuntu and Windows, Python 3.10 and 3.12, two hash seeds,
real ROOT dependencies, Iron Plan verification, compile-all, focused malformed
and assurance tests, mutation execution, full repository pytest and an isolated
wheel import.

## Independent review boundary

This correction applies the master-plan requirement that incomplete polyglot
and Data-Plane semantics report only `partial`. Model-assisted review is not
hard evidence, owner approval or a Gate-2 exit receipt.

## External verification blocker

GitHub Actions issue #67 remains active: hosted jobs terminate before Step 1
with no step records or logs. Such failures cannot establish a product verdict.
This packet remains draft until exact-head commands execute.

## Gate state

- Active authoritative gate: Gate 0
- Gate-2 status: preparation only
- Promotion: not requested
- Gate closure: not claimed
