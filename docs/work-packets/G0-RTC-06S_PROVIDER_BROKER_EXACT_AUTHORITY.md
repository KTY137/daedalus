# G0-RTC-06S — Exact Runtime Provider Broker Authority Boundary

## Exact parent and purpose

This packet stacks directly on `g0/provider-observation-authority-linear` at
`1449f1a0a802171b173bf0ab130b2713d515d22b`. It is deliberately separate from
the provider-observation authority implementation so that the public-boundary
repair remains small and reviewable.

The parent packet introduced an authenticated provider-observation authority and
retained start binding. Its initial compatibility seam still allowed a
non-`RuntimeBoundEffectAuthorization` object to reach the public broker. Because
Python duck types and subclasses can override `grant`, `begin_effect`, `verify`
or `finish_effect`, that seam was an effectful policy bypass rather than a safe
compatibility adapter.

## Boundary rule

`run_runtime_provider(...)` now accepts only exact instances of:

- `RuntimeBoundEffectAuthorization`;
- `EffectExecutionRequest`;
- `ProviderObservationAuthority`;
- `ProviderObservationBindingLedger`.

The exact-type check occurs before registry validation, lease grant, effect
start, provider execution or terminal persistence. No private effectful helper
or alternative broker path is added. The existing public import path remains
unchanged.

After the exact subject check, the broker still performs the established order:
registry/runtime binding, durable grant, durable start, authenticated retained
provider-observation binding, inert replay decision, provider callback, runtime
reverification, output-evidence materialization and terminal runtime fence.

## Adversarial coverage prepared

The builder suite was migrated away from a permissive fake authorization and now
uses the real persisted runtime trust, runtime-bound lease and effect ledger
fixture. Prepared tests cover:

- successful completion and retained binding;
- exact inert replay;
- duck-typed and subclassed runtime authorization rejection;
- subclassed execution, observation authority and binding ledger rejection;
- missing authority or ledger before grant;
- substituted empty binding store on replay;
- foreign entrypoint, non-central wiring, runtime mismatch and malformed registry;
- provider failure and cancellation;
- trust loss before and after evidence extraction;
- post-provider unknown outcome;
- terminal persistence failure.

A separate source/AST review checks exact type comparisons, absence of the old
compatibility seam, boundary ordering, pre-provider persistence and retained
recovery derivation.

Eight bounded mutants attempt to restore duck typing, permit subclasses, omit
observation authority or ledger checks, skip all pre-provider binding, skip
fresh binding persistence, skip retained replay binding and skip fresh authority
verification.

CI requests Ubuntu and Windows on Python 3.10 and 3.12, two hash seeds, focused
runtime/effect/recovery regressions, mutation, the full suite, package build and
isolated-wheel import.

## Evidence boundary

No source inspection, generated test, or LLM statement is hard evidence. The
exact branch has not been executed in the automation environment. GitHub Actions
issue #67 continues to fail hosted jobs before Step 1 with no logs or artifacts;
a repeated pre-step failure is infrastructure evidence only.

This packet does not complete Gate 0 and does not authorize merge, promotion,
OwnerApproval, PromotionReceipt or any Gate transition.
