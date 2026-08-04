# G0-RWI-20D — Content-Addressed Repository Write Evidence Materialization

## Parent and branch boundary

This additive packet is stacked on exact parent `dc2b582a6620680e490ce80d3a14fa091069fcea` from `g0/repository-write-classification-contract-linear`. Its short-lived branch is `g0/repository-write-evidence-authentication-linear`. It does not change `main`, `experimental`, the canonical effect registry, the repository-write scanner, GateReport, release state, OwnerApproval, promotion, or merge state.

## Purpose

The classification contract in G0-RWI-20C can name evidence by digest and bind it to one exact revision and repository-write surface. This packet adds the next narrow boundary: exact materialization of those named bytes from a content-addressed mapping.

For every declared evidence binding, the materializer requires a `cas:sha256:<digest>` locator, a bounded blob of at most 1 MiB, exact raw SHA-256 equality, strict UTF-8 without BOM or NUL, rejection of non-finite JSON numbers and duplicate keys, exact canonical JSON bytes, the expected envelope schema, exact kind/revision/surface/guard-contract/subject binding, a canonical payload digest, and a kind-specific payload shape. Unexpected blobs and reuse of one locator or blob digest across evidence slots fail closed. Missing blobs remain explicit blockers. Zero evidence bindings can never report complete.

## Supported typed envelopes

The packet validates bounded payload shapes for source anchors, guard-contract evidence, terminal Effect-Lease receipts, positive RuntimeConformance receipts, positive Primary-Checkout-disjointness receipts, and non-reachable retirement receipts. These checks establish byte identity and typed declaration consistency only.

## Non-authority boundary

This packet does not authenticate an external issuer, verify a signature or trust root, replay a receipt against the live Effect-Lease/runtime/checkout/retirement authorities, prove the Primary Checkout unchanged, populate the live inventory, or bind the result into GateReport-v2. Therefore every report permanently states:

- `origin_authenticated=false`;
- `semantic_receipts_verified=false`;
- `evidence_authenticated=false`;
- `gate_report_bound=false`;
- `closed=false`.

`materialization_complete=true` means only that a non-empty declared evidence set was found at its exact CAS locations and its bytes passed this packet's canonical and typed checks. Only that complete state may report `canonical_bytes_verified=true` and `binding_verified=true`; missing or empty reports keep both false. None of these fields establish trust, conformance, promotion authority, or Gate evidence.

## Adversarial batch

Prepared builder coverage includes all six evidence kinds, missing and empty binding sets, unexpected locators, non-byte values, raw digest substitution, noncanonical, duplicate-key and non-finite JSON, oversized blobs, revision/surface/kind/guard/subject substitution after exact blob rebinding, payload digest corruption, false runtime/disjointness claims, reachable retirement laundering, path traversal, reused blobs, partial-report claim laundering, and deterministic classification-bound reporting.

A separate AST/source review checks read-only authority, absence of callback/verifier smuggling, ordering of size/digest/parsing/canonical/payload/semantic fences, explicit handling of every evidence kind, permanent false trust and closure claims, complete-only byte/binding claims, and absence of registry, lifecycle, promotion, merge, or filesystem mutation authority. Fifteen bounded mutants target the highest-risk fences. Author-side isolated stub preparation reports `25 passed` and fifteen mutants killed; this is not exact-head repository evidence. CI requests Ubuntu and Windows on Python 3.10 and 3.12 with two hash seeds, predecessor tests, Iron Plan, full suite, package build, and isolated-wheel import.

## Remaining blockers

External issuer authentication and authoritative semantic receipt verification remain separate dependent packets. The live repository-write inventory still requires exact classifications and materialized evidence. GateReport-v2 binding, canonical caller migration, Runtime Manifest and ConformanceReceipt composition, Docker sandboxing, Primary-Checkout mutation exclusion, and the complete fault-injection matrix remain open. Exact-head executable verification is also pending while repository Actions issue #67 terminates jobs before Step 1 without logs or artifacts.

No OwnerApproval, automatic promotion, merge, or Gate transition is requested.

Iron Plan: **ALIGNED BY SCOPE; EXACT-HEAD EXECUTION REQUIRED**  
Iron Gate: **0**  
Promotion: **not requested**
