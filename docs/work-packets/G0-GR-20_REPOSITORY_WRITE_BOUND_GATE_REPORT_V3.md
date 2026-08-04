# G0-GR-20 — Repository-Write-Bound Gate Report v3

## Exact parent and strangler boundary

This packet stacks directly on `g0/provider-observation-authority-linear` at
`1449f1a0a802171b173bf0ab130b2713d515d22b`. It responds to issue #194 with an
additive `GateReportV3`; the existing GateReport-v2 implementation and import
path remain unchanged.

The packet changes reporting and monotonic comparison only. It does not modify
the current release verifier, evidence index, trust bundle, baseline adoption,
OwnerApproval, PromotionReceipt, merge state or any Gate state.

## Why v3 is necessary

GateReport-v2 binds the effect-entrypoint conformance matrix, runtime failures,
fault results, caller-reported Primary-Checkout mutations and the Event-Store
writer inventory. It does not bind the canonical repository-write inventory.
Consequently, v2 alone cannot prove that syntax-discovered production
filesystem, SQLite or process mutation surfaces are all registered, guarded and
target-isolated.

GateReport-v3 adds mandatory fields for:

- canonical repository-write inventory digest;
- scanned production-byte digest;
- production file count;
- exact supported inventory generation;
- deterministic blocker rows for every retained repository-write finding.

Missing inventory identity, missing byte identity, a non-positive file count,
any generation other than `2`, scanner refusal, or any repository-write finding
is a derived report blocker. A legacy v2 payload cannot be parsed or laundered as
v3.

## Builder and monotonicity

`build_gate0_report_v3(...)` first derives the existing v2 report, then invokes
`scan_repository_write_surfaces_v2(...)` itself. Callers cannot provide an
inventory digest or an empty failure list. Scanner refusal produces missing
identity plus an explicit `inventory-refused` blocker and diagnostic.

`assert_monotonic_v3(...)` accepts only exact `GateReportV3` subjects and treats
a newly discovered repository-write finding as a regression. It deliberately
does not compare a v3 report with a v2 baseline, because absent v3 evidence must
not be interpreted as an empty inventory.

## Interfaces and adversarial verification

The strict loader rejects extra or missing fields, duplicate keys, non-finite
JSON constants, malformed UTF-8, oversized reports, invalid types, unsorted or
duplicate rows, digest mismatches and noncanonical derived fields. The JSON
Schema mirrors the exact runtime shape.

The stdout-only CLI emits a discovery report with
`security_boundary_claimed=false`. It has no argument capable of asserting a
security boundary and returns distinct blocked and malformed exit codes.

Prepared verification includes builder and live-inventory behavior tests, schema
parity, legacy-v2 refusal, malformed and stale-revision identity cases, strict
loader tests, scanner refusal, repository-write monotonic regression, a separate
AST/source counter-review and eight bounded mutants attacking closure,
mandatory identities, generation, failure propagation, scanner refusal, wire
binding and monotonicity.

## Remaining release boundary

This packet does not close issue #194. The current `Gate0ReleaseReceipt`,
authenticated evidence index and trust bundle do not yet require the v3 report or
bind the repository-write artifact. The adopted baseline remains on v2. The
caller-supplied source revision is canonical and included in the report digest,
but this module does not independently resolve Git HEAD or prove that the label
names the scanned tree. That exact revision/tree proof belongs in the release
collector and verifier.

The repository-write inventory remains discovery evidence. Its findings still
require exact registration, guard contracts and Primary-Checkout target proof.
Issue #189's provider-observation persistence delta also remains to be composed
into the canonical inventory.

No source inspection or LLM statement is hard evidence. Exact-head execution
remains unavailable while GitHub Actions issue #67 terminates jobs before Step 1
without logs or artifacts. No automatic merge, promotion, OwnerApproval,
PromotionReceipt or Gate transition is authorized.
