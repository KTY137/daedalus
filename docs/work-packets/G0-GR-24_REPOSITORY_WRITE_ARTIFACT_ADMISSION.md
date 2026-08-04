# G0-GR-24 — Atomic Repository-Write Artifact Admission

## Exact parent and scope

This Work Packet is stacked on exact parent `f45363057d9321cd72aadf9a2c5736f690b0b00e` from `g0/repository-write-artifact-cas-resolver-linear`. It advances issue #194 with one additive, read-only composition boundary. It does not change `main` or `experimental`, merge, promote, issue OwnerApproval, create a PromotionReceipt, alter a Gate state, or mutate the Primary Checkout.

## Atomic admission boundary

`admit_repository_write_artifact(...)` accepts only the exact artifact evidence, exact `GateReportV3`, exact revision-bound CAS root, fixed identifiers, and one admission timestamp. The API exposes no caller-supplied artifact bytes, resolution receipt, verification receipt, callback, provider, signer, release object, or arbitrary keyword authority.

One invocation performs the following ordered sequence:

1. require the exact typed artifact, report, and CAS-root subjects;
2. resolve the exact `artifact-locator:sha256` through the read-only local CAS resolver;
3. pass only `resolved.content` to the strict inventory-byte verifier;
4. compare source revision, source-tree revision, artifact-evidence digest, content digest, and GateReport-v3 digest across both predecessor receipts;
5. issue a canonical admission receipt binding the report, artifact evidence, content, inventory, CAS root, resolution receipt, verification receipt, time, and provenance;
6. construct an immutable result that independently rechecks the retained bytes and complete receipt chain.

The caller therefore cannot pair bytes from one resolution with verification evidence from another call.

## Adversarial verification prepared

The builder batch covers exact success and round-trip serialization, stale CAS revision, substituted CAS bytes, foreign GateReport-v3, exact-type refusal, detached predecessor receipts, missing provenance inputs, and Primary-Checkout mutation exclusion. A separate adversarial harness substitutes individually valid verifier receipts with changed source revision, source-tree revision, artifact-evidence digest, content digest, or GateReport-v3 digest and requires refusal before an admission receipt is accepted.

The independent AST/source review requires exactly one resolver call before exactly one verifier call, proves that the verifier receives only `resolved.content`, rejects callback and loose-authority channels, checks both predecessor receipt-digest bindings, and rejects process, network, database, Git, merge, promotion, or OwnerApproval authority. The bounded mutation campaign contains nine mutants targeting exact input types, cross-receipt revision/evidence/content/report detachment, and omission of the verification-receipt digest from the immutable result check.

CI requests Ubuntu and Windows, Python 3.10 and 3.12, two hash seeds, predecessor regressions, the full suite, package build, and isolated-wheel import.

## Deliberate boundary

Admission is not origin authentication or release authority. This packet does not authenticate a signer or trust bundle, compare the retained source-tree revision with authenticated current Git HEAD, update the evidence index, replace the legacy release contract, or issue `Gate0ReleaseReceipt`. It does not discharge any canonical repository-write finding.

Issue #194 remains open. Provider-observation persistence paths from issue #189 remain blockers until they are canonically registered, guarded, target-isolated, and represented in the exact release-bound inventory. Docker sandbox evidence, complete fault injection, and Gate-wide Primary-Checkout mutation exclusion remain separate dependent work.

## Evidence state

Prepared tests and source review are not represented as executed evidence. The automation runtime has repository mutation access but no executable exact private checkout. GitHub Actions issue #67 has repeatedly terminated hosted jobs before checkout and Step 1 with no logs or artifacts. Any recurrence is infrastructure evidence only and cannot satisfy builder, review, mutation, packaging, platform, or Gate criteria.

No merge, automatic promotion, OwnerApproval, PromotionReceipt, issue closure, or Gate transition is authorized.
