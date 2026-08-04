# G0-RWI-20K — Authenticated Repository Write Guard Behavior Attestation

## Scope

This packet stacks on exact parent `5f07c2fbd2956557f626c7d2efeb2b8c4352ff0a` and adds one read-only authentication contract for externally produced guard-behavior results. It does not change `main`, `experimental`, the canonical effect registry, production callers, GateReport-v2, release state, OwnerApproval, promotion, or merge state.

The attestation binds one exact guard-structure report, its source revision, classification digest and record-set digest, plus an exact harness identity/digest and runtime-manifest digest. Every structural guard contract must have a unique non-vacuous case set containing at least one `allow` and one `refuse` expectation. Every observed outcome must equal its expected outcome.

## Authentication boundary

The wire format is bounded strict canonical JSON. Duplicate keys, non-finite values, BOM/NUL input, malformed identifiers, duplicate case identities, invalid case digests, noncanonical timestamps, excessive TTL, unknown keys, bad signatures, future/expired attestations, stale revisions, changed structure reports, changed record sets, changed harnesses, changed runtime manifests, contract substitution, missing negative coverage and failed cases all refuse.

Signature verification happens before expected-subject comparison. The authority key is externally provisioned; no production key or live attestation is committed.

## Non-authority boundary

Authentication is not execution. This packet does not import or invoke a guard, replay the harness, prove Docker isolation, validate the runtime manifest, establish RuntimeConformance, authenticate the remaining receipt classes, bind GateReport-v2, or close Gate 0.

The report therefore fixes:

- `guard_behavior_attestation_authenticated=true`;
- `positive_and_negative_vectors_complete=true`;
- `guard_execution_replayed=false`;
- `guard_contract_semantics_verified=false`;
- `runtime_conformance_verified=false`;
- `semantic_receipts_verified=false`;
- `evidence_authenticated=false`;
- `gate_report_bound=false`;
- `closed=false`.

No LLM statement is accepted as evidence.

## Adversarial batch

Prepared behavior coverage includes deterministic issue/parse/verify, multiple contracts, exact positive/negative coverage, failed outcomes, contract substitution, signature-first behavior, unknown and substituted keys, stale revision/authority/harness/runtime bindings, changed structural report, future/expiry/TTL faults, duplicate identities, strict canonical wire handling, digest substitution and malformed types.

A separate AST/source counter-review checks absence of process/import/filesystem authority, signature-before-binding order, exact non-vacuous coverage, permanent false semantic/runtime/Gate claims, bounded strict parsing, signed-subject completeness and signatures without callback or executor smuggling.

Ten bounded mutants attack trust escalation, signature bypass, contract-set bypass, allow/refuse-vacuity bypass, failed-case bypass and noncanonical-wire acceptance.

An isolated local stub harness reported `23 passed` behavior tests and `7 passed` source-review tests; all ten bounded mutants were killed. This is preparatory author-side evidence only and is not exact-head repository, supported-platform, packaging, runtime, independent-human, semantic, or Gate evidence.

## Remaining blockers

A dependent packet must independently replay the exact harness and bind the replay to an authenticated Runtime Manifest and current RuntimeConformanceReceipt. Effect-Lease, Primary-Checkout-disjointness and retirement semantics remain open. The complete semantic projection must then be bound into GateReport-v2 and the release verifier.

Live classification/evidence population, canonical caller migration, Docker sandboxing, Primary-Checkout mutation exclusion and the complete fault-injection matrix also remain open. GitHub Actions issue #67 continues to terminate hosted jobs before Step 1 with no logs or artifacts; zero-step runs are infrastructure observations only.

No OwnerApproval, automatic promotion, merge, or Gate transition is requested.

Iron Plan: **ALIGNED BY SCOPE; EXACT-HEAD EXECUTION REQUIRED**  
Iron Gate: **0**  
Promotion: **not requested**
