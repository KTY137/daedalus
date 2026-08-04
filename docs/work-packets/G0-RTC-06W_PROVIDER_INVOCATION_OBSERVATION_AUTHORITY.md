# G0-RTC-06W — Signed Provider Invocation Observation Authority

## Exact parent and purpose

This packet stacks on exact revision `0c437da95838f34b0cc1eb038d6886aa614e7548` from `g0/provider-invocation-subject-r2-linear`. It addresses the next non-executing portion of issue #188: binding the exact adapter invocation subject into authenticated provider-observation authority without changing the broker or introducing another callback path.

The existing `ProviderObservationAuthority` and `ProviderInvocationSubject` remain intact. `ProviderInvocationObservationAuthority` is an additive composite that signs both nested objects, one invocation-contract ID and one revision-bound invocation-registry digest with the provider-observation authority key.

## Exact subject binding

Construction requires exact nested types. Before signing, the composite checks that provider ID, entrypoint, runtime, execution ID, idempotency key, execution-request digest, lease digest and source revision are identical across the observation and invocation subjects. The invocation subject independently carries adapter ID, adapter artifact digest and adapter-config digest.

`invocation_contract_sha256` is derived deterministically from the invocation-contract ID, the complete invocation-subject digest and the invocation-registry digest. The composite signing digest covers the complete nested provider-observation authority, the complete invocation subject, contract ID and registry digest.

Verification normalizes the authority keyring, authenticates the nested provider-observation authority first, then authenticates the composite signature, and finally compares the exact expected invocation subject, contract ID and registry digest. A valid provider authority therefore cannot be paired with an independently selected adapter subject or registry revision.

## Deliberate non-executing boundary

This module imports no provider client, callback type, process/network API, dynamic loader, SQLite store, broker or recovery implementation. It does not resolve an adapter, invoke external code, start or finish an effect, persist authority, grant an Effect Lease, promote, merge or change a Gate state.

A later packet must construct a revision-bound registry whose only production invocation path consumes this signed composite. The current broker's independently supplied `invoke` and `output_digests` callbacks remain an explicit blocker.

## Prepared adversarial verification

Builder tests cover exact round-trip verification, every adapter/runtime/execution/lease/revision expectation substitution, composite and nested signature substitution, contract and registry mismatch, stale shared revision before signing, contract-digest sensitivity, exact deserialization and malformed/unknown keyrings.

A separate AST/source review verifies the absence of execution authority, exact nested types, complete shared-subject comparisons, signing coverage, nested-first verification order, keyring normalization, exact outer/nested shapes and a minimal public export surface. Nine bounded mutants target cross-subject acceptance, signature bypass, expected subject/contract/registry bypass, contract-digest detachment, shape relaxation, subclass acceptance and keyring-normalization removal.

Ubuntu and Windows on Python 3.10 and 3.12 with two hash seeds, predecessor tests, full suite, package build and isolated-wheel import are requested. These commands are prepared, not represented as executed evidence. GitHub Actions issue #67 currently terminates jobs before checkout/Step 1 and yields no logs or artifacts.

## Remaining work

Issue #188 remains open. The next dependent packets must implement an immutable revision-bound invocation registry, bind that registry digest into runtime manifest/conformance authority, replace the broker's loose callbacks with registry resolution, persist the composite authority before provider execution, and make recovery derive the exact invocation contract from retained authenticated state without a caller-supplied callback. Gate 0 remains open.
