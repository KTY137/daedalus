# G0-PRM-25F — Promotion Dual-Lifecycle Reconciliation Projection

## Scope

This packet composes the two existing strict read-only projections for the promotion Effect-Lease execution and the persisted promotion-execution lifecycle. It classifies retained restart state without granting, beginning, finishing, reconciling, invoking Git, opening worktrees, issuing OwnerApproval, or authorizing automatic execution.

It is stacked on G0-PRM-25E and keeps the canonical promotion registry row at `local_guards`.

## Reconciliation matrix

The projection exposes five inert dispositions:

- `fresh`: neither lifecycle has a retained start;
- `effect-only-pending-reconciliation`: the top-level effect start exists but the promotion-execution start does not;
- `promotion-pending-reconciliation`: both starts exist and promotion execution has no terminal;
- `effect-terminalization-required`: promotion execution is terminal but the top-level effect remains started;
- `complete`: both terminals exist and match exactly.

Every disposition returns `automatic_execution_allowed == false`. A promotion-execution start without its top-level effect start, a top-level effect terminal without promotion completion, reversed start chronology, reversed terminal chronology, and any terminal mapping mismatch fail closed.

## Exact terminal mapping

The read-only projection derives, but does not persist, one exact expected top-level terminal:

- promotion `succeeded` → effect `COMPLETED`, outputs bound to the promotion receipt and report digests, detail bound to the promotion receipt digest;
- promotion `refused` → effect `CANCELLED`, no output digests, detail bound to the promotion receipt digest;
- promotion `faulted` → effect `FAILED`, no output digests, detail bound to the promotion receipt digest.

The expected terminal contract validates canonical SHA-256 material, sorted unique outputs, and a disposition-consistent retained-state shape.

## Adversarial review

The packet prepares a full state-matrix test, ordering and bypass tests, outcome-substitution tests, malformed expected-terminal and disposition-smuggling tests, an independent AST/source authority review, and a seven-mutant campaign targeting automatic replay, missing effect starts, reversed ordering, premature terminals, terminal substitution, and successful-outcome mapping.

## Remaining live boundary

This packet does not wire the live Kairos promotion entrypoint. A later packet must persist the top-level effect start before the promotion-execution start and terminalize it immediately after the promotion terminal. Any nonterminal restart remains reconciliation-only.

The review also records a concrete unresolved authority question: `NonRuntimeEffectAuthorization.finish_effect(COMPLETED)` requires live unexpired and unrevoked lease authority. If promotion has already succeeded and the process crashes before the top-level effect terminal is written, a later reconciliation cannot honestly record `COMPLETED` after lease expiry through the current facade. The live composition must either make terminalization failure-safe within the original authority window or introduce an explicit, separately reviewed reconciliation authority. It must not bypass the facade or forge a terminal.

Exact-head execution remains pending because repository GitHub Actions issue #67 currently terminates jobs before Step 1. Zero-step runs are infrastructure observations only and are not verification evidence.

No merge, OwnerApproval, promotion, central registry migration, or Gate transition is requested.
