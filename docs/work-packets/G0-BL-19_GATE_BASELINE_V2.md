# G0-BL-19 — Revision-Bound Gate Baseline v2

## Objective

Replace an informal blocker snapshot with a deterministic Gate-0 baseline that is bound to one exact source commit, one exact source tree and one canonical GateReport-v2. Comparisons must identify newly introduced blockers without allowing a caller to substitute an unpinned baseline or trust a serialized pass/fail claim.

## Baseline contract

`daedalus-gate-baseline/2` binds:

- a bounded baseline identifier;
- Gate 0;
- an exact lowercase 40-hex source revision;
- an exact lowercase 40-hex source-tree revision;
- the canonical Gate report digest and complete artifact digest;
- the effect-registry digest;
- the Event-Store writer-inventory digest;
- the sorted complete blocker set and its digest;
- a canonical UTC creation timestamp.

A baseline can only be created from a current GateReport-v2 carrying writer-inventory evidence. A legacy report or a v2 report with a missing writer-inventory digest is refused.

The baseline digest is tamper-evident, not self-authenticating. Every comparison therefore requires `expected_baseline_sha256` from a separately trusted source. Final release use must retain that pin in authenticated exact-head evidence or an explicit owner-controlled decision; the baseline file cannot authorize itself.

## Monotonicity receipt

`daedalus-gate-monotonicity/2` partitions the blocker sets into:

- retained blockers: baseline intersection current;
- resolved blockers: baseline minus current;
- new blockers: current minus baseline.

The status is derived: `passed` only when `new_blockers` is empty. Missing current writer-inventory evidence is itself a new blocker. The receipt binds both source and tree revisions, the current Gate-report digest and artifact digest, the current registry and writer-inventory digests, every partition and the assessment timestamp.

A separate verifier recomputes the entire receipt from the pinned baseline and current report. Loading a digest-valid receipt does not make it evidence until this recomputation succeeds. `--require-monotonic` refuses a receipt containing any new blocker.

## Interfaces

The pure production modules do not spawn Git, call a network service, modify a repository, write a baseline, create OwnerApproval or close a Gate. `scripts/gate0_baseline.py` provides stdout-only operations:

- `create` — emit a canonical baseline from a GateReport-v2;
- `compare` — emit a monotonicity receipt and optionally return nonzero for regressions;
- `verify` — independently recompute a retained receipt and optionally require monotonicity.

Callers choose whether to redirect stdout into a retained artifact. Refusals use stderr and do not emit partial JSON.

## Adversarial batch

Prepared tests cover:

- exact report, source and tree binding;
- mandatory writer-inventory evidence;
- baseline and blocker-set tampering;
- resolved and retained blockers without regression;
- a new legacy writer as a regression;
- missing current inventory as a regression;
- required external digest pinning;
- forged receipt partitions and current-tree drift;
- derived status and disjoint partitions;
- duplicate keys, non-finite constants, malformed/non-UTF-8 input and bounded loaders;
- stdout-only create, compare and verify behavior;
- schema/runtime agreement;
- a separate source-level review for authority creation and effectful operations.

The mutation campaign attacks missing-inventory admission, unpinned baseline acceptance, omitted new blockers, unconditional pass status, serialized status trust, duplicate-key acceptance, nonrevision trees and skipped receipt recomputation.

## Honest residual boundary

This packet does not select or adopt the canonical Gate-0 baseline. No exact-head GateReport-v2 has yet been generated and pinned, no independent reviewer has approved one, and no authenticated evidence index retains its digest. Git ancestry is deliberately not inferred inside the pure module because adding a production process-spawn path would create another effect boundary; exact ancestry must be retained by the exact-head collector or release workflow.

GitHub Actions issue #67 still prevents jobs from starting. Therefore no focused test pass, mutation kill, full-suite result, supported-platform result, wheel result or generated baseline artifact is claimed.

No OwnerApproval, merge, promotion, checkout mutation or Gate closure is requested.

Iron Plan: **ALIGNED BY SCOPE; CANONICAL BASELINE NOT ADOPTED**  
Iron Gate: **0**  
Promotion: **not requested**
