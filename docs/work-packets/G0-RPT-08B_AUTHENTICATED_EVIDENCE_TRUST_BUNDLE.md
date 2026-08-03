# G0-RPT-08B — Authenticated Evidence Trust Bundle

## Objective

Remove candidate-controlled raw trust-set injection from the normal exact-head release-verification path without creating a second Gate authority.

`GateEvidenceIndex` remains the canonical retained evidence view and `evidence_verifier.assert_strict_exact_head()` remains the mechanical verifier. This packet adds a short-lived external authentication envelope which supplies that verifier's trust sets only after the envelope, exact index, exact repository revision/tree and adopted workflow paths have all been rechecked.

## Contract

`EvidenceTrustBundle` binds:

- exact `GateEvidenceIndex.digest`;
- exact source commit and Git tree;
- adopted evidence-requirements digest;
- protected Iron Plan and effect-registry digests;
- complete canonical workflow, artifact, runtime, fault and review trust identities;
- the separately verified owner-receipt digest when present;
- collector identity and key identity;
- issuance, expiry and exact provenance;
- one HMAC-SHA256 signature produced with an external collector key.

No secret is stored in the repository. The packet does not create or simulate an OwnerApproval.

## Workflow-definition binding

Each retained workflow record is paired with a `WorkflowDefinitionAnchor` containing:

- logical workflow ID;
- adopted repository-relative path under `.github/workflows`;
- complete canonical workflow-evidence digest;
- SHA-256 of the exact YAML bytes.

Verification requires an independently supplied adopted ID-to-path mapping. The mapping must exactly match retained workflow identities. Paths are component-normalized, confined to `.github/workflows`, YAML-only, non-symlinked, existent regular files inside the exact checkout. Current bytes are rehashed at verification time. This prevents a candidate from satisfying an adopted workflow ID with a different trivial workflow file.

## Fail-closed verification order

1. authenticate the collector key and signature;
2. recheck issued/expiry time;
3. bind collector, index, commit, tree, requirements, plan and registry;
4. bind adopted workflow IDs to adopted paths and current exact bytes;
5. require exact equality for every retained evidence trust set;
6. derive all arguments to the existing strict verifier from the authenticated bundle;
7. retain all normal mechanical blockers, including missing OwnerDecision.

A bundle with no OwnerDecision may be authenticated as a truthful partial observation, but it cannot pass strict Gate verification.

## Adversarial coverage

Builder and separate source-review suites cover:

- unknown key and signature tampering;
- future, expired and overlong bundles;
- foreign collector, commit, tree, index, plan/registry and evidence sets;
- workflow-byte drift and workflow-path substitution;
- path traversal, non-YAML paths, symlinks and missing files;
- exact provenance rather than subset provenance;
- duplicate JSON keys, string-as-array repackaging and non-object roots;
- absence of merge, promotion, `closed=true` or OwnerApproval construction;
- strict-verifier invocation only after bundle authentication.

## Deliberate remaining boundary

This packet provides the authenticated contract and local exact-checkout verifier. It does not deploy the collector key, fetch GitHub logs/artifacts, inspect protected CAS, generate a real release bundle, create human review evidence, create OwnerApproval, integrate `GateEvidenceIndex` into `GateReport`, merge, promote or close Gate 0.

A later release-assembly packet must use externally controlled key material and authenticated source reads. GitHub Actions runs which terminate before Step 1 remain infrastructure observations and cannot be signed as successful workflow evidence.

Iron Plan: **ALIGNED by scope; exact-head execution required**  
Active gate: **Gate 0**  
Promotion: **not requested**
