# G1-IKARUS-07D3 — runtime invocation binding

## Goal

Compose the authenticated per-call provider ABI from 07D2 with the hardened
executable-object evidence from 07B/07C before any runtime Effect can start.
Payload/target evidence and loaded-object evidence must describe one exact
subject before the broker is allowed to proceed toward durable start.

## Minimal boundary

`daedalus.runtimes.provider_runtime_invocation_binding` intentionally introduces
**no new receipt schema, registry, policy engine or execution layer**. It:

1. re-authenticates the signed `ProviderInvocationABIContract` and canonical
   `ProviderInvocationPayload` using the existing observation-ledger trust root;
2. reuses `bind_provider_runtime_executable(...)` to re-prove the exact loaded
   repository functions, source hashes and code hashes;
3. requires both proofs to agree on provider, adapter, implementation,
   entrypoint, runtime, execution, idempotency identity, Effect Lease, source
   revision, pre-admission receipt, invocation authority/contract/subject and
   fixed invoke/output-evidence targets;
4. returns the already-existing `ProviderRuntimeExecutableBindingReceipt`.

Keeping the existing receipt is deliberate anti-bloat: the signed ABI already
is the payload/target evidence, while the 07C receipt already is executable
object evidence. A third persistent evidence object would duplicate both.

The existing `ProviderObservationBindingLedger` remains the authority-key trust
root. The composition boundary reads its already-normalized private authority
keyring only for the existing ABI verifier call and never returns or persists
key material.

## Deliberate non-claims

This packet does **not** execute a provider. It calls no `grant`, `begin_effect`,
`bind_start`, provider target, process or network API. The reused 07C receipt
continues to state `effect_started=false`, `provider_code_executed=false`,
`provider_execution_allowed=false` and `callback_seam_removed=false`.

Therefore #188 and #278 remain open. The live `run_runtime_provider` callback
ABI is unchanged by this packet.

## Adversarial checks

Focused tests cover semantic payload substitution, Provider-A authority plus
Provider-B pre-admission, forged ABI signatures, repository-source mutation
after executable admission, exact no-Effect behavior on successful composition,
and AST/source review forbidding Effect start, provider execution, callable
resolvers, dynamic loaders, subprocess and network surfaces.

## Next packet

07D4 should call this conjunction **inside `run_runtime_provider` immediately
before durable grant/start** and keep exact replay ahead of executable
resolution. The remaining blocker to deleting production `invoke` and
`output_digests` callbacks is a sealed execution operation that consumes the
authenticated payload without closure/default/global ambient state.

Do not weaken `ProviderExecutableObjectRegistry` merely to fit the current
Claude lambdas. The imported `_invoke_claude_cli` dependency needs an explicit
authenticated dependency/sealed-namespace contract or an adapter refactor before
execution can safely move behind the registry.
