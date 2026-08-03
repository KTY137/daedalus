# G2-PREP-TS01 — Tree-sitter structural assurance remains partial

## Purpose

This non-authoritative Gate-2 preparation packet corrects the assurance
vocabulary of the optional Tree-sitter adapters. It is intentionally branched
from the selected Gate-0 release-assessment line so the correction can be
reviewed independently while Gate 0 remains blocked on exact-head CI and
operational evidence.

It does not start Gate 2 authoritatively, publish a Forest, construct a trusted
FourfoldSnapshot, create cross-plane bindings, alter production execution,
merge, promote or close any gate.

## Finding

The adapter documentation and repository probe already state that Tree-sitter
produces structural parser evidence only. However, a syntax-error-free parse
previously returned `ExtractorResult.status == "complete"`.

That result does not establish:

- compiler-resolved definition/reference identity;
- type identity or type-checker agreement;
- data lineage or schema conformance;
- knowledge-claim truth;
- verified cross-plane bindings;
- complete repository coverage.

Because `ExtractorResult` is a reusable contract outside the probe script, the
stronger status was an assurance overclaim even though the aggregate report
used the safer label `structural-parser-evidence-only`.

## Correction

Every successful Tree-sitter parse now returns `status="partial"` and retains a
`structural-only` warning diagnostic. A malformed parse remains `partial` but
also records `syntax-errors`. Limit violations and content-identity failures
remain fail-closed as before.

Extracted structural symbols and their evidence digests are preserved. The
change narrows only the assurance claim; it does not discard useful staged
observations.

A future compiler/SCIP-oriented frontend may emit stronger evidence only after
its own exact revision, coverage, provenance and semantic-resolution contracts
are implemented and independently verified. Tree-sitter output alone must never
be upgraded to trusted semantic completeness.

## Adversarial verification requested

The packet provides two complementary test surfaces:

1. the real optional Rust, Java and C++ grammars assert that clean parses remain
   `partial`, malformed parses add `syntax-errors`, and structural symbols stay
   deterministic;
2. a dependency-free fake parser exercises the same public adapter when optional
   grammar wheels are absent and an AST counter-review rejects any successful
   assignment of `status="complete"`.

The bounded mutation changes the sole successful `status="partial"` assignment
to `"complete"`, requires a green baseline, requires the focused tests to kill
the mutant and verifies source restoration.

Dedicated CI requests Ubuntu and Windows, Python 3.10 and 3.12, two hash seeds,
real optional grammar packages, Iron Plan verification, compile-all, focused
contract/malformed/assurance tests, mutation execution, full repository pytest
and an isolated-wheel import.

## Independent review boundary

This correction follows the explicit master-plan rule that incomplete polyglot
semantics may report only `partial` and may never claim trusted completeness.
The review is model-assisted source analysis, not hard evidence, owner approval
or a Gate-2 exit receipt.

## External verification blocker

GitHub Actions issue #67 remains active: hosted jobs terminate before Step 1
with no step records or logs. Such failures cannot establish a product verdict.
This PR remains draft until commands execute against its exact head.

## Gate state

- Active authoritative gate: Gate 0
- Gate-2 status: preparation only
- Promotion: not requested
- Gate closure: not claimed
