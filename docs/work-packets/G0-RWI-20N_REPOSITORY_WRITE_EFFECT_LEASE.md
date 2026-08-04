# G0-RWI-20N — Repository Write Effect-Lease Semantic Replay

## Parent and branch boundary

This Work Packet is based on exact parent `01befb3c1b9af411a1d82fa0a0295edb138b169b` from `g0/runtime-effect-replay-linear` and is developed on the short-lived branch `g0/repository-write-effect-lease-replay-linear`. It is additive and read-only. It does not modify `main`, `experimental`, the canonical effect registry, production callers, GateReport-v2, release state, OwnerApproval, promotion, or merge state.

## Exact semantic subject

`verify_repository_write_effect_leases(...)` replays the complete repository-write runtime-conformance predecessor, independently re-materializes the same CAS evidence, and checks the classification/materialization/runtime/origin digest chain before inspecting any Effect-Lease state.

Every production-reachable classification must remain `central` and retain exactly one `EFFECT_LEASE_RECEIPT`; non-production rows may retain none. Every retained payload must be strict canonical JSON and bind the exact revision, surface, evidence subject, terminal receipt digest, entrypoint and terminal state.

The supplied effect-subject map must equal the exact retained terminal-receipt set. Each value carries one exact `NonRuntimeEffectAuthorization` or `RuntimeBoundEffectAuthorization` plus one exact `EffectExecutionRequest`. The verifier delegates only to the existing read-only persisted replay projections. It then binds the retained lease, execution request, start receipt, terminal receipt, state, entrypoint and source revision.

For runtime-bound subjects, the signed capability's runtime-conformance receipt must equal the already verified runtime receipt for the same repository-write surface, and the replay must retain the authenticated runtime identity and trust-record digest.

## Fail-closed restart boundary

A persisted lease without a start and a `STARTED` execution are not authority to execute. Both states refuse with an explicit no-automatic-reexecution decision. The verifier has no grant, begin, finish, revoke, retry, provider, process, filesystem-write, repository-mutation, promotion, or merge authority.

## Machine report boundary

The new report can establish `effect_lease_semantics_verified=true` only after exact live replay. It permanently retains:

- `guard_contract_semantics_verified=false`;
- `primary_checkout_disjointness_verified=false`;
- `retirement_semantics_verified=false`;
- `semantic_receipts_verified=false`;
- `evidence_authenticated=false`;
- `gate_report_bound=false`;
- `closed=false`.

Therefore this packet cannot close Gate 0.

## Adversarial batch

Prepared behavior coverage includes exact terminal replay, missing-start and pending-start refusal, terminal-digest substitution, entrypoint substitution, terminal-state substitution, exact subject-set enforcement, stale revision, predecessor materialization detachment, absence of writer authority, malformed subjects, and one-shot mapping behavior.

A separate AST/source counter-review checks authority separation, exact public signature, predecessor-before-effect ordering, exclusive use of the read-only replay APIs, no-reexecution refusal, exact terminal/entrypoint/revision/subject fences, runtime-conformance joining, frozen data-only results, and permanently false complete-Gate claims.

Eight bounded mutants attack missing-start refusal, pending-start refusal, terminal identity, entrypoint identity, terminal state, subject-set equality, predecessor materialization binding, and false Gate closure.

CI requests Ubuntu and Windows on Python 3.10 and 3.12 with two hash seeds, focused predecessor regressions, malformed/stale/bypass tests, mutation, Iron Plan verification, the full suite, package build, and isolated-wheel import.

## Executable evidence status

The automation environment can create and review repository objects but has no executable private-repository checkout. Local syntax checks performed outside the exact repository are preparatory only and are not product, platform, packaging, mutation, independent-review, or Gate evidence.

Repository GitHub Actions issue #67 has repeatedly terminated hosted jobs before Step 1 with `steps=null`, no logs, and no artifacts. Such runs are infrastructure observations only. Exact-head execution remains required.

## Remaining dependent work

The selected linear stack still needs authenticated guard-behavior replay, Primary-Checkout-disjointness semantics, retirement semantics, live classification/evidence population, GateReport-v2 and release-verifier binding, canonical caller migration, Docker sandbox composition, Primary-Checkout mutation exclusion, and the complete fault-injection matrix.

No OwnerApproval, automatic promotion, merge, or Gate transition is requested.
