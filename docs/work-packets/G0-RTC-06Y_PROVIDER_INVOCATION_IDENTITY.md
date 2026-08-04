# G0-RTC-06Y — Authenticated Provider Invocation Identity Projection

## Exact parent and scope

This packet stacks on `g0/provider-invocation-registry-manifest-linear` at
`f2c7de5c65ba49f3a6de11dd1d5a26f89fa49f7b`. It composes the signed
invocation-observation authority from G0-RTC-06W with the revision-bound
registry manifest from G0-RTC-06X. It does not modify the broker, execute a
provider, start or finish an Effect Lease, persist recovery state, change
`main` or `experimental`, merge, promote, or issue OwnerApproval.

## Authentication and resolution order

`project_provider_invocation_identity(...)` accepts exact typed authority,
registry and execution subjects. It authenticates the nested
provider-observation authority and composite invocation signature against the
fixed invocation-contract ID and the digest of the supplied registry manifest.
Only after authentication succeeds does it compare the source revision and
resolve the exact provider descriptor.

The registry resolution binds provider, adapter, implementation, artifact,
configuration, entrypoint, runtime and source revision. The signed subject also
binds execution ID, idempotency key, execution-request digest and Effect-Lease
digest.

## Inert projection

The returned `ProviderInvocationIdentityProjection` content-addresses the
authority, nested observation authority, invocation contract, subject, registry,
descriptor, execution request, lease, artifact and configuration. It records
the exact provider, adapter, implementation, entrypoint, runtime, execution and
revision identities.

The wire format permanently reports
`runtime_effect_authorized=false` and `provider_execution_allowed=false`. Those
values are not constructor fields and cannot be caller-escalated. The projection
has no callback, `invoke`, `execute`, provider client, dynamic loader, network,
process, filesystem-write, recovery, promotion or Gate authority.

## Adversarial verification prepared

Builder tests cover exact round-trip, registry implementation substitution,
a valid signed registry whose descriptor does not match the signed subject,
foreign signed contract IDs, stale execution, invalid composite signatures
before registry resolution, exact type boundaries, malformed wire shapes and
authority-escalation attempts.

A separate AST/source review checks absence of execution/effect primitives,
authentication-before-resolution order, use of the fixed contract ID and live
registry digest rather than authority-derived expectations, complete projection
binding, permanent false execution claims and absence of Gate or promotion
claims. Nine bounded mutants target those boundaries.

CI requests two hash seeds on Ubuntu and Windows with Python 3.10 and 3.12,
predecessor tests, Iron Plan verification, mutation, full suite, package build
and isolated-wheel import.

## Remaining boundary

This packet does not close issue #188. The exact broker-authority sibling must be
integrated into this selected line, and the production broker must require this
identity projection before `begin_effect`. The independent `invoke` and
`output_digests` callback seam must then be removed in favor of one guarded
revision-bound executable registry. Durable observation binding and recovery
must retain the invocation contract and descriptor digests.

GitHub Actions issue #67 continues to terminate hosted jobs before checkout and
Step 1, so prepared tests are not represented as executed evidence. No automatic
merge, promotion, OwnerApproval, PromotionReceipt or Gate transition is
authorized.
