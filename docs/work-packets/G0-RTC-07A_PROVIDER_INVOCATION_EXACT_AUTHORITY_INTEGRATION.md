# G0-RTC-07A — Provider Invocation Exact Authority Controlled Integration

## Exact parent and integration source

This packet stacks on `g0/provider-invocation-identity-admission-linear` at
`a758f8ce6c2d77477fc47818071675414dd5deab`. It ports the exact broker,
mutation runner and adversarial test blobs from draft PR #192, exact source head
`8eca58799884890826b96655c41087d7031000ca`, onto the selected provider-
invocation identity line. The source draft is not merged and this packet is not a
collection PR.

The selected parent already contains the signed provider-invocation subject,
composite provider-observation authority, revision-bound registry manifest and
inert authenticated identity projection. This batch changes only the public
runtime broker authority boundary and its verification assets.

## Closed authority bypass

The previous broker admitted non-exact runtime authorization objects as a
compatibility seam. A duck type or subclass can override `grant`,
`begin_effect`, `verify` or `finish_effect`, so that seam can bypass the durable
runtime/effect authority model.

`run_runtime_provider(...)` now requires exact instances of:

- `RuntimeBoundEffectAuthorization`;
- `EffectExecutionRequest`;
- `ProviderObservationAuthority`;
- `ProviderObservationBindingLedger`.

Those exact-type checks occur before registry validation, grant, durable effect
start or provider execution. Missing, partial, duck-typed or subclassed authority
objects fail inside `RuntimeProviderBindingMismatch` without starting an effect.
The persisted runtime terminal fence is mandatory; there is no fallback terminal
path for narrow authorization doubles.

## Replay and observation semantics retained

A new execution still grants and durably starts the Effect Lease before the
provider call, then authenticates and persists the exact provider-observation
binding before external code runs. Exact replay requires the retained binding
store and returns without invoking the provider. Provider exceptions,
cancellation, runtime-trust loss, post-provider unknown outcome and terminal
persistence behavior remain unchanged.

## Controlled integration evidence

The Work Packet records the exact Git blob identities ported from PR #192:

- broker implementation `a0b07085bcb44b4149887b09275dc5675f685c01`;
- bounded mutation runner `52d977b9b9d372aabfca702f3c328ad329d89bf2`;
- exact-authority tests `97419b1d8140ca2621616c710e0b604a72a2784f`;
- real broker fixture tests `316577e5a0bf471770b8b267675acec133f9e8d6`;
- independent authority source review `cdcb726a0e14b182e7fa6f1600d9aaff97bf71e6`.

Blob identity proves only controlled source transfer. It is not executable product
or Gate evidence.

## Adversarial verification requested

The focused matrix requests Ubuntu and Windows on Python 3.10 and 3.12 with two
hash seeds. It includes compile checks, Iron Plan verification, exact Work Packet
JSON validation, builder behavior, independent AST/source counter-review,
malformed authority and registry cases, duck-type and subclass bypasses,
substituted replay storage, provider failure/cancellation, runtime-trust loss,
unknown outcome, terminal persistence failure and the complete provider-
invocation predecessor stack.

Eight bounded mutants target exact-type removal, reordered validation and the
principal broker authority bypasses. Full-suite, package build and isolated-wheel
imports are requested separately.

## Deliberate remaining boundary

This packet does **not** close issue #188. The broker still receives `invoke` and
`output_digests` independently of the authenticated
`ProviderInvocationIdentityProjection`. A dependent packet must require that
projection before `begin_effect`, bind it to the runtime authorization and
observation authority, and resolve the executable adapter only through an exact
revision-bound guarded registry. No production path may retain an arbitrary
callback selected independently by its caller.

Provider-observation store pre-provisioning and one-use durable operation
authority remain on their separate controlled line. This batch does not change
`main` or `experimental`, merge, promote, issue OwnerApproval or
PromotionReceipt, or change a Gate state.

GitHub Actions issue #67 continues to terminate hosted jobs before checkout and
Step 1 with no logs or artifacts. Prepared tests are therefore not represented
as executed hard evidence. Gate 0 remains open.
