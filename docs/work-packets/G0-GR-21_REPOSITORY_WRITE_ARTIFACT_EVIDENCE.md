# G0-GR-21 — Repository-Write Artifact Evidence Contract

## Exact parent and narrow role

This packet stacks directly on `g0/gate-report-repository-write-v3-linear` at
`3f88ac508c7c4a9e065a4f9fd34d91e6f27532a2`. It adds one canonical artifact
contract required by the next evidence-index and release-verifier packets. It
does not modify the legacy `GateEvidenceIndex`, trust bundle,
`Gate0ReleaseReceipt`, OwnerApproval, PromotionReceipt, merge state or Gate
state.

## Bound identities

`RepositoryWriteArtifactEvidence` binds:

- artifact and source revision identity;
- exact source-tree revision;
- exact GateReport-v3 digest;
- logical repository-write inventory digest;
- scanned production-byte digest;
- production file count and supported inventory generation;
- canonical failure-set digest and count;
- artifact byte digest and content-addressed locator;
- construction time and exact `ContractProvenance`.

The locator digest must equal the artifact-content digest. Provenance must bind
the report, inventory, scan-input, failure-set and artifact-content digests. A
subclassed or duck-typed provenance container refuses.

## Exact report comparison

`report_binding_blockers(...)` accepts only an exact `GateReportV3`. It compares
the report digest, source revision, inventory and scan-input digests, file count,
generation, derived canonical failure-set digest and failure count. Every
substitution becomes a deterministic blocker; no caller supplies a pass/fail
boolean.

The artifact contract may legitimately bind a report that is still blocked. It
is evidence identity, not release authority.

## Prepared adversarial verification

Behavior tests cover exact round trip, canonical contract digest, report
substitution across every logical dimension, locator/content contradiction,
missing provenance inputs, exact provenance type, strict integer domains,
malformed or foreign contract payloads and independent artifact-dimension digest
sensitivity. A separate AST/source review proves that the module has no network,
filesystem-write, process, effect, release, approval or promotion authority.

Eight bounded mutants attack locator matching, exact provenance, generation,
artifact-content provenance binding, exact report type, inventory comparison and
failure-set/count comparisons. CI requests two hash seeds on Ubuntu and Windows
with Python 3.10 and 3.12, focused tests, the mutation campaign, predecessor
GateReport-v3 tests, full suite, package build and isolated-wheel import.

## Remaining trust boundary

This packet does not fetch the artifact locator or independently hash the
artifact bytes. It retains a claimed content digest under exact provenance; a
later authenticated collector and trust-bundle verifier must prove the bytes and
signing authority. The retained source-tree revision is not compared with
current Git HEAD here.

The legacy evidence index does not yet require this artifact contract, and the
release receipt still accepts the older evidence shape. Those are separate short
packets under issue #194.

No source inspection or LLM statement is hard evidence. Exact-head execution
remains unavailable while GitHub Actions issue #67 terminates jobs before Step 1
without logs or artifacts. No automatic merge, promotion, OwnerApproval,
PromotionReceipt or Gate transition is authorized.
