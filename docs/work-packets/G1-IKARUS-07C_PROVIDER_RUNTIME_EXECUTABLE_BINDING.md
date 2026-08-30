# G1-IKARUS-07C — Provider runtime executable pre-effect binding

Status: draft implementation packet  
Parent: `G1-IKARUS-07B_PROVIDER_EXECUTABLE_OBJECT_REGISTRY`  
Primary blockers advanced: #188, #247  
Master-plan authority: `docs/IKARUS_ARIADNE_MASTER_PLAN.md` Revision 8

## Purpose

Bind the already-authenticated provider identity and the already-admitted
provider executable objects to one exact runtime/effect subject **before** the
runtime broker is allowed to start an Effect.

This packet is a narrow prerequisite for replacing the remaining production
`invoke` / `output_digests` callback seam in `run_runtime_provider`. It does not
add another runtime, scheduler, provider registry, policy engine, session store,
or execution authority to Ikarus.

## Inputs

`bind_provider_runtime_executable(...)` accepts only exact canonical boundary
types:

- `RuntimeBoundEffectAuthorization`;
- `EffectExecutionRequest`;
- `ProviderObservationAuthority`;
- `ProviderObservationBindingLedger`;
- `ProviderExecutableObjectRegistry`;
- `ProviderExecutablePreAdmissionReceipt`;
- the verification instant.

It accepts no provider callback and no caller-selected output-evidence callback.

## Contract

Before returning a binding receipt, the boundary must:

1. reject duck-typed or subclassed authority/registry subjects;
2. bind request entrypoint, lease entrypoint, runtime identity, execution ID,
   idempotency key, lease digest and source revision to the pre-admission
   receipt;
3. authenticate the signed provider-observation authority through the existing
   `ProviderObservationBindingLedger.verify_authority(...)` read-only path;
4. prove that the authenticated provider ID is the exact provider ID named by
   the pre-admission subject;
5. reverify the registered executable object targets, repository source bytes
   and loaded bytecode through `ProviderExecutableObjectRegistry`;
6. bind the resulting executable admission to the same provider, adapter,
   implementation, runtime, execution, lease and source revision;
7. retain the authenticated invocation-authority / invocation-contract /
   invocation-subject digests in the returned receipt.

All refusals happen before this module grants a lease, starts an Effect, binds a
provider start, or executes provider code.

## Explicit non-authority claims

The receipt permanently reports false for:

- effect lease granted;
- effect started;
- provider start persisted;
- provider code executed;
- provider execution allowed;
- callback seam removed;
- broker invocation performed;
- automatic re-execution;
- owner approval, promotion, Gate transition, or closure.

This packet therefore cannot be cited as live Hermes runtime parity by itself.
It proves only the missing pre-effect identity/executable conjunction required
for the broker cutover.

## Adversarial coverage prepared

Focused tests cover:

- successful pre-effect binding without an Effect row or provider call;
- valid provider-A authority plus registered provider-B executable subject;
- forged observation-authority signature;
- repository source mutation after executable admission;
- subclassed runtime authorization and pre-admission subjects;
- serialized receipt authority escalation;
- source review for callbacks, dynamic loading, process/network execution,
  Effect start/grant, and observation-start persistence.

The focused workflow targets Python 3.10 and 3.12 and includes the prior 07A/07B
regressions plus the exact runtime-provider authority review. Repository issue
#67 remains authoritative for CI availability: a zero-step Actions failure is
not product-test evidence.

## Next dependent packet

`G1-IKARUS-07D` should perform the actual broker cutover, not create a parallel
broker:

1. make `run_runtime_provider` consume this exact pre-effect binding path before
   `authorization.begin_effect(...)`;
2. make the guarded executable registry the only production source of the
   admitted `invoke` and output-evidence functions;
3. remove raw `invoke` / `output_digests` parameters from the production broker
   signature, retaining any callback fixture only behind an explicitly test-only
   helper that cannot enter runtime-bound recovery;
4. keep exact replay inert and require the retained authenticated observation
   binding without resolving or executing the provider again;
5. prove provider-A authority plus provider-B executable refuses before
   `begin_effect` and before any provider code executes.

Only after that cutover, exact-head CI, replay/recovery review and platform/full
suite evidence may #188 be considered for closure. Live Ikarus/Hermes runtime
parity and comparative superiority remain separate, evidence-gated claims.
