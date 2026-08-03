# G0-RPT-08B — Exact-head Gate-0 release assembly

## Objective

Compose the local Gate-0 blocker projection with the externally anchored exact-head evidence index without introducing a manual `closed` or security-boundary override.

This packet is stacked after `G0-RPT-08A`. It does not fetch GitHub, publish artifacts, authenticate an owner, merge, promote, or claim Gate-0 closure.

## Authority and derivation

`Gate0ReleaseReport` binds:

- the exact candidate commit and Git tree;
- the original mechanical `GateReport` digest;
- the derived canonical Gate report payload;
- the exact `GateEvidenceIndex` digest;
- every strict evidence blocker;
- canonical provenance over all three identities.

The input value of `GateReport.security_boundary_claimed` is ignored. The release assembler derives it as true only when:

1. the local report has no technical blocker other than the unset security claim;
2. all non-owner exact-head evidence checks pass;
3. the retained mechanical report is a required, content-addressed artifact in the exact evidence index;
4. report and index registry identities agree.

The owner closure decision remains separate. A technically complete report can therefore claim the implemented security boundary while the release remains `closed=false` because the authenticated owner decision is missing or untrusted.

`Gate0ReleaseReport.closed` is derived only from the union of the reconstructed Gate-report blockers and exact-head evidence blockers. The wire format retains `closed` and `blockers`, but strict parsing recomputes and compares both values.

## Fail-closed cases

Focused tests cover:

- empty external trust sets despite a caller-supplied security claim;
- missing owner decision after otherwise complete technical evidence;
- local runtime-conformance failure despite green external evidence;
- stale Git tree;
- report/index registry recombination;
- mechanical report artifact substitution;
- failed optional workflow evidence;
- model-opinion architecture review in place of a human pass;
- nested Gate-report field tampering;
- forged release `closed` or blocker arrays;
- provenance input removal.

The intended focused mutations are:

1. trust the input `security_boundary_claimed` value;
2. omit the mechanical report artifact comparison;
3. ignore optional failed evidence;
4. remove the owner-decision blocker;
5. stop checking the exact Git tree;
6. accept claimed `closed` without recomputation.

Each mutation must be killed before the packet can become reviewable evidence.

## Verification request

The dedicated workflow requests:

- Ubuntu and Windows;
- Python 3.10 and 3.12;
- `PYTHONHASHSEED=0` and `123456`;
- Iron Plan verification and `compileall`;
- all exact-head evidence and release tests;
- the repository full suite on Ubuntu/Python 3.12;
- isolated wheel import outside the checkout.

GitHub Actions issue #67 currently prevents repository jobs from reaching Step 1. A zero-step failure is infrastructure evidence only and cannot establish product success or failure.

## Remaining boundary

This packet creates the deterministic release-assembly contract only. Gate 0 remains open until a final linear candidate has:

- real exact-head workflow/log/artifact evidence;
- protected trust anchors;
- non-expired live runtime envelopes;
- a complete attested fault matrix;
- no effect-inventory blockers;
- exact-head human architecture and security approvals;
- an authenticated owner closure decision;
- a release report that actually derives `closed=true`.

Iron Plan: **ALIGNED by scope; exact-head execution required**  
Active gate: **Gate 0**  
Promotion: **not requested**
