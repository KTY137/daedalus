# G1-IKARUS-07D3 — runtime invocation binding

## Goal

Compose the authenticated per-call provider ABI from 07D2 with the hardened
executable-object evidence from 07B/07C before any runtime Effect can start.
This packet closes the gap where payload/target evidence and loaded-object
evidence were individually strong but not yet consumed as one conjunction.

## Boundary

`daedalus.runtimes.provider_runtime_invocation_binding` requires exact instances
of the canonical runtime authorization, Effect execution request, signed
`ProviderInvocationObservationAuthority`, canonical `ProviderInvocationPayload`,
signed `ProviderInvocationABIContract`, observation binding ledger, guarded
executable registry and exact pre-admission receipt.

The boundary:

1. re-authenticates the 07D2 ABI using the existing observation ledger's
   configured provider-authority and observation trust material;
2. reuses 07C to authenticate the nested observation authority and re-prove the
   registered loaded executable objects against repository source and bytecode;
3. requires both proofs to name the same provider, adapter, implementation,
   entrypoint, runtime, execution, idempotency identity, Effect Lease, source
   revision, invocation authority/contract/subject, fixed invoke target and fixed
   output-evidence target;
4. returns a deterministic, non-authorizing conjunction receipt containing the
   ABI/payload/executable evidence digests and the verified target code digests.

No key material is returned or persisted by the new boundary. The existing
`ProviderObservationBindingLedger` remains the trust root; the code reads its
already-normalized authority keyring only inside the same-package verifier call.

## Deliberate non-claims

This packet does **not** execute a provider and does not make the guarded object
registry an execution authority. It calls no `grant`, `begin_effect`,
`bind_start`, provider target, process or network API. The receipt therefore
keeps all of the following false:

- `effect_lease_granted`
- `effect_started`
- `provider_start_persisted`
- `provider_code_executed`
- `provider_execution_allowed`
- `callback_seam_removed`
- `broker_invocation_performed`
- automatic replay/re-execution, promotion and Gate-transition claims

Consequently #188 and #278 remain open. The live `run_runtime_provider` callback
ABI on `main` is not changed by this packet.

## Adversarial checks

Focused tests cover:

- semantic payload substitution after ABI issuance;
- Provider-A authority plus Provider-B pre-admission/registry substitution;
- forged ABI signatures;
- repository source mutation after executable admission;
- exact no-Effect/no-provider behavior on a successful binding;
- receipt claim escalation;
- AST/source review prohibiting Effect start, provider execution, callable
  resolver, dynamic loader, subprocess and network surfaces.

## Next packet

07D4 should consume `bind_provider_runtime_invocation(...)` *inside* the broker
immediately before durable grant/start, then introduce one sealed provider
execution operation whose implementation identity is the already-admitted
fixed target. Exact replay must branch before that operation is resolved or
invoked. Only when the sealed operation can consume the authenticated payload
without ambient closure/default/global state should production
`invoke`/`output_digests` callback parameters be removed.

Do not weaken `ProviderExecutableObjectRegistry` to make the current Claude
closures fit. The current imported `_invoke_claude_cli` dependency needs an
explicit authenticated dependency/sealed-namespace contract or a provider
adapter refactor before execution can safely move behind the registry.
