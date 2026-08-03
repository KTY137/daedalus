# G0-RPT-08A — Exact-Head Evidence Index

## Objective

Add a strict, content-addressed evidence index for the future Gate-0 release
report without changing the existing report's closure semantics yet. The index
binds every retained claim to one exact candidate commit and Git tree.

This is an additive preparation packet for issue `G0-RPT-08`. It does not fetch
GitHub, authenticate an owner, execute runtimes, or set `GateReport.closed`.

## Retained evidence

The index records:

- exact candidate commit and tree revisions;
- Iron Plan and effect-registry digests;
- required exact-head workflow runs, conclusions, logs and artifacts;
- content-addressed package/report/inventory artifacts;
- expiring live runtime-envelope references;
- fault-matrix digests and scenario identities;
- architecture/security review records with assurance labels and unresolved
  findings;
- a reference to a separately authenticated OwnerApproval and its verifier
  receipt.

The owner record is not an OwnerApproval verifier. Both referenced digests must
come from the existing authenticated owner boundary before this index can be
used by a later release-report integration.

## Derived blockers

`GateEvidenceIndex.mechanical_blockers()` derives required-membership blockers.
`strict_mechanical_blockers()` adds the adversarial invariant that every
retained item, including optional evidence, must be coherent. Extra failed,
stale, foreign, future-dated, or mismatched evidence is not silently ignored.

The strict verifier rejects:

- current commit or tree mismatch;
- expired or future-dated index evidence;
- missing, failed, expired or foreign workflows;
- missing or foreign artifacts;
- artifact locators that do not address the claimed content;
- offline, failed, expired or foreign runtime evidence;
- missing, failed or foreign fault matrices;
- model-only reviews used as hard review evidence;
- unresolved or changes-requested reviews;
- missing or foreign owner-decision references;
- ambiguous duplicate identities;
- naive verification timestamps.

## Assurance boundary

A model review may be retained as `model-opinion`, but it cannot satisfy a
required hard review perspective. This packet currently requires a clean human
review to satisfy architecture or security review requirements. Deterministic
tools remain separate evidence and do not masquerade as architecture review.

## Deliberate remaining blockers

This packet does not complete issue `G0-RPT-08`. Later packets must still:

- populate the index from authenticated GitHub/API and artifact-store reads;
- bind the exact workflow-definition digest and required workflow set adopted
  for release;
- verify the owner capability rather than merely reference its verifier receipt;
- connect trusted live runtime envelopes from `G0-RTC-06`;
- retain the index itself in CAS;
- integrate the strict blocker list into `GateReport`;
- require the exact current-head report at promotion/release boundaries;
- establish the adopted monotonic baseline;
- obtain exact-head CI, independent review, and explicit owner closure.

## Work Packet boundary

- no network or provider invocation;
- no filesystem mutation outside tests;
- no OwnerApproval creation;
- no promotion or merge;
- no `closed=true` claim;
- no Gate-1 or Gate-2 activation.

Iron Plan: **ALIGNED**  
Active gate: **Gate 0**  
Promotion: **not requested**
