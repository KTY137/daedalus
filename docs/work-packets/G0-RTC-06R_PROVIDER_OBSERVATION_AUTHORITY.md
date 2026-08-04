# G0-RTC-06R — Authenticated Provider Observation Authority Binding

## Exact parent and scope

This packet stacks directly on `g0/runtime-post-provider-unknown-linear` at exact
parent `370e931baef8f254f22e55698feb5794ed22d685`. It addresses issue #186 without
changing `main`, `experimental`, automatic promotion, OwnerApproval, merge state,
or any Gate state.

The packet selects the explicit independent observation-authority model. A
short-lived HMAC-authenticated authority binds one provider identity and one
exact observation-verification key set to the exact entrypoint, runtime,
execution ID, idempotency key, execution-request digest, Effect-Lease digest,
source revision, authority identity, and key identity.

## Pre-invocation durable binding

For an exact `RuntimeBoundEffectAuthorization`, the broker requires both the
signed authority and a configured `ProviderObservationBindingLedger`. After the
effect start is durable and before the provider callback is invoked, the broker:

1. authenticates the authority against the ledger's configured authority trust
   root and observation key set;
2. verifies the entrypoint, runtime, execution, lease, revision and authority
   lifetime;
3. persists a canonical start-bound record in SQLite under `BEGIN IMMEDIATE`;
4. authenticates the persisted record with a separate record HMAC.

If any of those steps fails, the provider callback is not invoked. A newly
started effect receives a local `FAILED` terminal because the external provider
has not run. Exact replay never creates a new binding: it loads and authenticates
the retained record and remains inert.

The compatibility seam for non-exact narrow test doubles is retained while
production callers migrate. Runtime-bound recovery still requires the exact
authorization type and therefore cannot use that seam as recovery authority.

## Recovery derivation

`reconcile_runtime_provider_unknown(...)` no longer accepts
`expected_provider_id`, an observation keyring, or an expected source revision
from its caller. It authenticates the runtime replay and the retained
provider-observation record, then derives:

- the expected provider identity;
- the allowed observation issuer key IDs;
- the exact observation key material through the retained key-set digest and
  ledger configuration;
- the source revision.

Provider, issuer, key material, entrypoint, runtime, execution, idempotency key,
start receipt, lease, and revision substitutions refuse before a terminal writer
is reached. The recovery API has no provider callback and cannot re-execute or
automatically reconcile an effect.

## Adversarial verification prepared

Prepared builder coverage includes signed authority issuance and verification,
future/expired/overlong authorities, provider and key-set substitution, exact
SQLite round-trip, conflicting records, HMAC tampering, malformed and
noncanonical rows, missing bindings, pre-invocation persistence, inert replay,
wrong provider, wrong issuer ID, wrong issuer key material, wrong runtime,
entrypoint, execution, idempotency key, lease, start receipt and revision, forged
runtime capability, terminal re-reconciliation refusal, and malformed registry
rows inside the boundary error domain.

A separate AST/source review checks callback ordering, lack of caller-supplied
provider/keyring recovery inputs, retained-provider derivation, exact record
authentication, malformed-registry normalization, and absence of provider,
network or process execution authority in the new module.

Eight bounded mutants target skipped authority verification, skipped durable
binding, key-set digest bypass, persisted-record HMAC bypass, retained-authority
substitution, provider substitution, issuer substitution and provider derivation
from the observation.

CI requests Ubuntu and Windows on Python 3.10 and 3.12 with two hash seeds,
affected runtime/effect/recovery regressions, mutation, Iron Plan verification,
the full suite, package build, and isolated-wheel import.

## Evidence and remaining boundary

No LLM statement or source inspection is hard evidence. The automation
environment cannot execute the exact private checkout. GitHub Actions issue #67
has repeatedly terminated hosted jobs before Step 1 with `steps=null`, no logs
and no artifacts; any repetition is infrastructure evidence only.

This packet does not complete Gate 0. Canonical caller migration, Docker sandbox
evidence, Primary-Checkout mutation exclusion, complete fault-injection
coverage, complete semantic receipt composition, GateReport-v2 binding and a
`closed=true` release report remain separate dependent work.

No OwnerApproval, automatic promotion, merge, or Gate transition is requested.
