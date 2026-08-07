# G0-RTC-06Z — Provider Observation Store Operation Guard Contract

## Exact parent and boundary

This packet stacks on exact revision `4e105dc5b976aa4d3b1c8601592c5a4d08895b18` from `g0/provider-observation-preprovisioned-store-linear`. It adds the non-executing guard-contract layer required before issue #189 can migrate the pre-provisioned initializer and binding writer into canonical effect entrypoints.

It does not register those entrypoints, verify or begin an Effect Lease, open SQLite, initialize a store, bind a row, migrate the broker, recover an execution, merge, promote or change a Gate state.

## Exact operation subject

The contract has exactly two operation names:

- `initialize-store` maps only to `provider.observation-store.initialize`;
- `bind-provider-start` maps only to `provider.observation-store.bind-start`.

`ProviderObservationStoreOperationSubject` binds the operation and entrypoint, exact `ProviderObservationStoreTarget` digest and source revision, local store execution and persisted Effect-Lease digests, and the isolated target-relative path. For a provider-start binding it also binds the provider-observation authority digest, recomputed provider start-receipt digest, Runtime Manifest digest and RuntimeConformance digest. Initialization rejects all provider-runtime fields.

The target-relative path is not accepted from the caller. It is derived mechanically from `target.path` relative to `target.attempt_root`, normalized as a repository-style path, and required to be the sole writable path in both `EffectExecutionRequest` and `EffectLease.effect_scope`. The operation rejects a read-only lease, a runtime-bearing local lease, kill-switch mismatch, stale revision, extra network/tool/secret/cost scope, or any operation/entrypoint mismatch.

## Signed guard authority

`ProviderObservationStoreOperationAuthority` signs the complete operation subject, authority identity, key identity, nonce and a validity interval no longer than fifteen minutes. Verification normalizes the keyring, authenticates the HMAC, enforces the validity interval and compares the exact expected authority and subject. Only then may `authorize_provider_observation_store_operation(...)` return an allowed `GuardDecision` carrying the authority and subject digests.

This decision is one guard contract, not an Effect Lease. The central effect path must still verify the actual lease signature, persisted lease record, runtime requirements where applicable, kill switch and idempotent begin receipt before any store mutation. This packet intentionally provides no one-use authority-consumption ledger.

## Adversarial corrections

The first draft bound target, execution and lease digests but did not force the target-relative path to equal the execution and lease writable scopes. An authority could therefore have signed three individually valid but differently scoped objects. The contract now derives `store_scope_path` from the target and requires exact singleton equality in both scopes.

The initial unrelated-scope test attempted to create a request rejected by the request schema itself, so it never exercised the contract. The test now uses `object.__setattr__` against an already valid frozen exact request to model a validation-bypass mutation and verifies that the contract still refuses the unexpected network scope.

## Prepared adversarial verification

Builder tests cover both operations, exact round-trip authority and guard decision, initialization/provider-field separation, complete bind authority, stale revision, wrong entrypoint, target-path mismatch in both request and lease, explicit schema-bypass scope mutation, provider start-receipt tampering and subject mismatch, authority signature, expiry, expected-subject substitution, exact parsing, maximum TTL and malformed keyrings.

A separate AST/source review checks the absence of SQLite/effect/promotion authority, closed operation mapping, target-relative path derivation, exact local lease and request scope comparisons, provider authority and receipt binding, complete signature coverage, verification ordering and guard-decision ordering. Nine bounded mutants target operation mapping, lease mismatch, target-path detachment, unrelated scope, start-receipt tamper, incomplete provider authority, signature bypass, expiry bypass and allowed-decision emission without verification.

Ubuntu and Windows on Python 3.10 and 3.12 with two hash seeds, predecessor tests, full suite, package build and isolated-wheel import are requested. These commands are prepared, not represented as executed evidence. GitHub Actions issue #67 currently terminates jobs before checkout/Step 1 and yields no logs or artifacts.

## Remaining dependent work

A dependent packet must add the two operations to the canonical effect-entrypoint registry, compose this decision with actual persisted Effect-Lease verification and begin/finish receipts, add durable one-use authority consumption, make the pre-provisioned initializer and binding writer reachable only through those entrypoints, migrate production callers, retire the historical auto-initializing path and execute the complete SQLite fault-injection matrix. Issue #189 and Gate 0 remain open.
