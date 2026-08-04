# G0-RWI-20C — Revision-Bound Repository Write Classification Contract

**Gate:** 0  
**Parent:** `g0/repository-write-canonical-v2-linear` at `acd663f87908442f2fa53f11ce70807ba06ac3f3`  
**Branch:** `g0/repository-write-classification-contract-linear`  
**Authority:** preparatory classification contract only

## Purpose

Generation 2 makes potential repository-writing Python surfaces visible, but it does not say where a write can land, whether a production route can reach it, or which mechanical contracts actually guard it. This packet defines the strict revision-bound declaration shape needed for that next review. It does not install declarations into the effect registry, authenticate receipts, prove Primary-Checkout disjointness, bind GateReport-v2, or close Gate 0.

## Contract

Each declaration binds the exact inventory surface, source revision, target disposition, guard disposition, production reachability, named guard contracts, and immutable evidence locators with SHA-256 digests. A declaration cannot substitute a surface absent from the bound inventory, repeat a surface, use a stale revision, or target a different inventory digest.

A candidate `central` declaration requires all of:

- a disjoint target (`checkout_external` or `non_repository`);
- at least one named guard contract;
- guard-contract evidence;
- an Effect-Lease receipt;
- a RuntimeConformanceReceipt;
- a Primary-Checkout disjointness receipt.

A `retired` declaration requires `production_reachable=false`, no guard contracts, and a retirement receipt. The converse is also enforced: `production_reachable=false` is admitted only with the explicit `retired` disposition. A reviewer therefore cannot suppress every reachable non-central blocker merely by toggling the reachability flag. `primary_checkout`, `unknown`, and every reachable non-central classification remain explicit candidate blockers.

## Non-authority boundary

The report permanently emits `evidence_authenticated=false`, `primary_checkout_target_proven=false`, `gate_report_bound=false`, and `closed=false`. `classification_ready=true` means only that every inventory row has a blocker-free candidate declaration. It is not release evidence and cannot upgrade any route to `central` or `trusted`.

The module imports no effect registry, Effect-Lease writer, runtime writer, promotion authority, Git/process API, SQLite API, or filesystem writer. The canonical generation-2 inventory and all generation-1 import paths remain unchanged.

## Prepared adversarial batch

Focused tests cover missing and complete candidate sets, stale source revision, stale inventory digest, exact surface substitution, duplicate rows, malformed primitive types, tampered inventory derived fields, evidence-revision drift, central evidence-family omission, disjoint-target evidence, reachability laundering, retirement constraints, report partition/count invariants, non-iterable normalization, strict CLI behavior, and schema parity.

A separate AST/source review checks the absence of effect, registry, filesystem, process, promotion, and lifecycle authority; hard-coded false assurance claims; the four mandatory central evidence families; the explicit non-reachability/retirement fence; and stale/substitution refusal. Seven bounded mutants attack false closure, forged authentication, forged Primary-Checkout proof, omitted Effect-Lease evidence, stale-inventory acceptance, duplicate-surface acceptance, and reachability laundering.

The requested CI matrix is Ubuntu and Windows on Python 3.10 and 3.12, two hash seeds, focused predecessor regressions, mutation, Iron Plan verification, full suite, package build, and isolated-wheel import.

## Honest remaining boundary

This packet supplies no classifications for the live repository and verifies no evidence locator. A dependent packet may populate and independently verify the exact-head classification set only after the parent inventory is executable and retained. Later packets must authenticate every receipt, prove target-root disjointness against the live Primary Checkout, migrate or retire every reachable non-central route, bind the exact classification digest into GateReport-v2 and the release verifier, and execute the complete runtime/fault matrix.

The pre-correction draft had an author-side isolated stub result of `19 passed` and `6` bounded mutants killed. That result does not cover the current reachability correction and is not exact-head repository, platform, packaging, runtime, or Gate evidence. GitHub Actions issue #67 continues to stop jobs before Step 1 with `steps=null`, no logs, and no artifacts; current exact-head execution is pending.

No OwnerApproval, merge, promotion, automatic action, registry migration, or Gate transition is requested.
