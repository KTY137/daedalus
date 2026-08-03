# G0-RPT-08C — Authenticated Gate-0 Release Assessment

## Objective

Join the previously separate machine-readable Gate report and authenticated exact-head evidence chain without allowing repository code to declare its own success.

This packet verifies an already-derived `GateReport` against one exact `GateEvidenceIndex`, one authenticated `EvidenceTrustBundle`, the current commit, the current Git tree, the protected effect-registry digest and adopted workflow paths. Only after all checks pass may a separately keyed release verifier issue a `Gate0ReleaseReceipt`.

The packet does not derive `security_boundary_claimed=true`, set `closed=true`, create or consume `OwnerApproval`, mutate a checkout, merge or promote.

## Strict GateReport boundary

The legacy `GateReport` constructor and import path remain compatible, but release assembly accepts only its exact canonical wire form:

- exact field membership and schema;
- integer Gate 0 rather than bool/int coercion;
- exact Git revision and registry digest syntax;
- exact booleans with no string coercion;
- canonical sorted unique arrays;
- derived `closed` and blocker fields;
- mandatory matching report digest;
- duplicate-key rejection for untrusted JSON.

This strangler boundary allows existing report producers to migrate without making the permissive legacy loader authoritative for release.

## Assessment order

1. validate the exact canonical Gate report and digest;
2. bind report, evidence index and trust bundle to the exact commit, tree and registry;
3. authenticate the external collector bundle;
4. re-run the complete strict exact-head evidence verifier against current workflow bytes and current time;
5. require `GateReport.closed=true`, no blockers, security-boundary claim and owner-approval enforcement;
6. issue a release receipt only after all prior checks pass.

Receipt verification authenticates the separately scoped `(verifier_id, verifier_key_id)` key first, then re-runs the complete live assessment and compares every retained digest.

## Release receipt

`Gate0ReleaseReceipt` binds:

- exact Gate-report digest;
- exact evidence-index digest;
- exact authenticated trust-bundle digest;
- exact adopted-requirements digest;
- exact source commit and Git tree;
- release-verifier and key identity;
- verification time, passed status, exact provenance and HMAC-SHA256 signature.

Collector and release-verifier keys are distinct capabilities and both are scoped by principal plus key ID. No key material is retained in the repository.

## Adversarial coverage

Builder and separate source-review tests attack:

- bool/string and array coercion in Gate-report JSON;
- extra fields, duplicate keys, forged `closed`, forged blockers and stale report digest;
- malformed or foreign revision, tree and registry bindings;
- open reports and missing genuine owner evidence;
- workflow-definition drift between receipt issue and replay;
- collector and verifier key-scope collisions;
- signature tampering and foreign expected verifier identity;
- receipt reuse with another report, index or bundle;
- future and pre-bundle receipt timestamps;
- unknown receipt fields and recursive duplicate JSON keys;
- accidental construction of Gate closure, OwnerApproval, promotion or merge authority.

## Deliberate remaining boundary

This packet provides contracts and exact local verification only. It cannot generate a real release receipt until the external collector key, release-verifier key, successful exact-head workflow/log/artifact evidence, protected CAS evidence, live runtime attestations, passed fault matrices, genuine human reviews and a genuine owner verifier receipt exist.

A zero-step hosted-run failure is not successful workflow evidence. No release receipt produced from synthetic unit fixtures is valid operational evidence.

Iron Plan: **ALIGNED by scope; exact-head execution required**  
Active gate: **Gate 0**  
Promotion: **not requested**
