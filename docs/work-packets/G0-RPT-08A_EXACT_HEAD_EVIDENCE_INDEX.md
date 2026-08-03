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

## Strict wire boundary

Untrusted JSON must enter through `load_gate_evidence_index()` or
`parse_gate_evidence_index()`. The strict boundary rejects duplicate keys,
strings repackaged as arrays, malformed nested records and non-object roots
before dataclass construction.

## Derived blockers

`GateEvidenceIndex.mechanical_blockers()` derives required-membership blockers.
It is intentionally structural only and is not release authority.

`strict_mechanical_blockers()` adds both adversarial coherence checks and
external trust anchors. Every retained record, including optional evidence,
must be coherent. The externally adopted requirements digest prevents a
candidate from shrinking the required workflow, artifact, runtime, fault or
review set. Protected Iron-Plan and registry digests are also external inputs.

Every hard evidence class must appear in an independently obtained exact digest
set:

- complete workflow-evidence record from the authenticated CI read;
- complete artifact-evidence record from verified CAS/artifact metadata;
- runtime-envelope digest from the trusted live-runtime index;
- fault-matrix digest from retained deterministic execution evidence;
- complete review-evidence record from the review system;
- owner-verifier receipt digest from the authenticated owner boundary.

Empty trust sets fail closed. A caller cannot turn a locally constructed
canonical object into hard evidence merely by serializing it.

The strict verifier rejects:

- untrusted adopted requirements, Iron Plan or registry;
- current commit or tree mismatch;
- expired or future-dated index evidence;
- untrusted, missing, failed, expired or foreign workflows;
- untrusted, missing or foreign artifact records;
- artifact locators that do not address the claimed content;
- untrusted, offline, failed, expired or foreign runtime evidence;
- untrusted, missing, failed or foreign fault matrices;
- untrusted review records;
- model-only reviews used as hard review evidence;
- unresolved or changes-requested reviews;
- missing, foreign or untrusted owner-verifier receipts;
- ambiguous duplicate identities;
- malformed wire shapes and duplicate JSON keys;
- naive verification timestamps.

## Assurance boundary

A model review may be retained as `model-opinion`, but it cannot satisfy a
required hard review perspective. This packet currently requires a clean human
review to satisfy architecture or security review requirements. Deterministic
tools remain separate evidence and do not masquerade as architecture review.

The trust-set arguments are an integration seam, not a substitute for
verification. The later collector must derive them from authenticated APIs,
verified CAS reads, signed/runtime evidence, and the real OwnerApproval verifier;
it must never accept them from the candidate repository itself.

## Deliberate remaining blockers

This packet does not complete issue `G0-RPT-08`. Later packets must still:

- populate the index and trust sets from authenticated GitHub/API and
  artifact-store reads;
- bind the exact workflow-definition digest in each workflow record;
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
