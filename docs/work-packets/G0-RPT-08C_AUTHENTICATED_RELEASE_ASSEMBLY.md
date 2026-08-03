# G0-RPT-08C — Authenticated exact-head Gate-0 release assembly

## Objective

Compose the local machine-readable Gate report, the exact-head evidence index and the authenticated collector trust bundle into one deterministic Gate-0 release decision.

This packet is stacked after `G0-RPT-08B — Authenticated Evidence Trust Bundle`. It supersedes the unbundled sibling draft #85. It does not collect evidence, deploy a collector key, authenticate an OwnerApproval, merge, promote or claim Gate-0 closure.

## One release authority path

The public assembler accepts the canonical local `GateReport`, the exact `GateEvidenceIndex`, one HMAC-authenticated `EvidenceTrustBundle`, the exact checkout root and adopted workflow paths, the external collector keyring and identity, and the live commit/tree/time.

It accepts no raw `trusted_*` digest sets. Before deriving a report it authenticates the bundle and rechecks commit, tree, evidence index, workflow identities and bytes, retained evidence sets and lifetime.

`Gate0ReleaseReport` binds the exact commit and Git tree, original mechanical Gate-report digest, derived canonical Gate-report payload, evidence-index digest, trust-bundle digest, strict exact-head blockers and provenance. Provenance inputs must equal the exact retained identity set; both missing and extra digests are refused. Untrusted mappings must also use the exact canonical nested arrays and values rather than merely normalizing to the same object.

## Derived closure semantics

The caller-provided `GateReport.security_boundary_claimed` value is ignored. The technical security claim becomes true only when the local report has no technical blocker other than the unset security claim, every non-owner strict exact-head evidence check passes under the authenticated bundle, the mechanical Gate report is a required content-addressed artifact, and report/index registry identities agree.

The authenticated owner closure decision remains separate. A technically complete nested Gate report may therefore be closed while the release stays `closed=false` with `owner-decision:missing`.

The final release `closed` value is derived only from reconstructed local and exact-head blockers. Strict parsing recomputes the nested report, blocker array and closure value.

## Independent current-state verification

A serialized report is not authority merely because it parses or says `closed=true`. The verifier checks release/report/index/bundle identities, reconstructs the original report at its retained generation time, compares the complete canonical wire, authenticates the bundle against current workflow bytes, rechecks live commit/tree/trust lifetime/evidence expiries, and refuses a previously closed release that is no longer current.

## Adversarial coverage

Focused tests cover valid authenticated closure, absence of raw trust-set injection, invalid collectors and foreign revisions, caller-forced claims, missing owner closure, local runtime failure, failed optional workflows, model-only reviews, report artifact substitution, registry recombination, forged derived values, reduced or expanded provenance, non-canonical wire ordering, direct repackaging, bundle expiry, workflow drift, report/bundle substitution and timezone-naive verification.

A separate AST counter-review checks that authentication precedes mechanical projection and release construction, no effectful or promotion call appears, closure is derived only from the complete blocker union, and the verifier reconstructs before rechecking current state. This remains model-generated review support, not human or owner evidence.

## Bounded mutation campaign

The campaign first requires the unmodified parent trust-bundle and release suites to pass. It then applies one mutant at a time, compiles it, runs the focused suite in a fresh subprocess and restores exact source bytes.

Mutants remove trust-bundle authentication, trust the caller security claim, omit the report-artifact comparison, remove owner blockers, accept claimed closure, accept expanded provenance, accept non-canonical release wire, skip retained-report reconstruction, skip current blockers/expiry, and accept trust-bundle substitution. A survivor, invalid seam or dirty checkout fails the job.

## Verification request

Dedicated CI requests Ubuntu and Windows, Python 3.10 and 3.12, two hash seeds, Iron Plan, JSON-schema parsing, compileall, parent trust-bundle tests, release and counter-review tests, the ten-mutant campaign, the full suite and isolated-wheel import.

Issue #67 currently terminates repository jobs before Step 1 without logs. Such runs are infrastructure observations only and cannot establish product, package, platform or mutation evidence.

## Remaining boundary

Gate 0 remains open until a final linear candidate has real protected exact-head evidence, non-expired live runtime envelopes, the complete attested fault matrix, no effect-inventory blocker, exact-head human architecture/security review, an authenticated owner closure decision and a release report that derives and independently verifies `closed=true`.

Iron Plan: **ALIGNED by scope; exact-head execution required**  
Active gate: **Gate 0**  
Promotion: **not requested**
