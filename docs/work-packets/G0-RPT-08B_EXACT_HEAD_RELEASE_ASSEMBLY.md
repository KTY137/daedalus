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

A parsed report is still not hard evidence by itself. `gate0_release_verification_blockers` and `assert_gate0_release_report` independently reconstruct the report from the retained mechanical report and evidence index, then recheck the current commit, tree, trust anchors, expiries and owner verifier. A directly constructed or repacked release contract therefore cannot become authoritative merely by containing `closed=true`.

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
- direct contract repackaging;
- replacement of the retained mechanical report or evidence index;
- verification after runtime, workflow or index expiry;
- provenance input removal.

## Automated mutation campaign

`scripts/run_gate0_release_mutations.py` first requires the unmodified focused suite to pass. It then applies each mutant alone, compiles the mutated module, runs the focused tests in a fresh subprocess and restores the original bytes before continuing. A green mutant or invalid mutation seam fails the campaign; CI also refuses a dirty checkout afterward.

The bounded campaign attacks:

1. trusting the input `security_boundary_claimed` value;
2. omitting the mechanical report artifact comparison;
3. removing owner-decision blockers;
4. accepting a claimed release `closed` value;
5. skipping retained-release reconstruction;
6. skipping current evidence blockers and expiry results.

This is focused packet evidence, not a substitute for the later full critical-code mutation score.

## Verification request

The dedicated workflow requests:

- Ubuntu and Windows;
- Python 3.10 and 3.12;
- `PYTHONHASHSEED=0` and `123456`;
- Iron Plan verification and `compileall`;
- all exact-head evidence, assembly and independent-verifier tests;
- a bounded six-mutant campaign on Ubuntu/Python 3.12;
- the repository full suite on Ubuntu/Python 3.12;
- isolated wheel import outside the checkout.

GitHub Actions issue #67 currently prevents repository jobs from reaching Step 1. The latest attempted matrix again produced jobs with no recorded steps or logs. That is infrastructure evidence only and cannot establish a product verdict.

## Remaining boundary

This packet creates deterministic release assembly and verification contracts only. Gate 0 remains open until a final linear candidate has:

- real exact-head workflow/log/artifact evidence;
- protected trust anchors;
- non-expired live runtime envelopes;
- a complete attested fault matrix;
- no effect-inventory blockers;
- exact-head human architecture and security approvals;
- an authenticated owner closure decision;
- a release report that derives `closed=true` and passes independent current-state verification.

Iron Plan: **ALIGNED by scope; exact-head execution required**  
Active gate: **Gate 0**  
Promotion: **not requested**
