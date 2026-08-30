# G1-IKARUS-07D2 — Authenticated provider invocation ABI

Status: **prepared on serialized Draft #277; non-executing**

Parent work: G1-IKARUS-07D1, #278, #188

## Purpose

07D1 made per-call provider inputs deterministic data instead of Python closure
state. 07D2 binds that canonical payload identity to the already-authenticated
provider invocation subject and to the exact provider executable/output-evidence
targets proven by provider pre-admission.

The contract is intentionally a narrow extension of the existing authority
chain. It does not introduce a second provider registry, policy engine, runtime
kernel, plugin authority or session layer.

## Contract

`ProviderInvocationABIContract` binds:

- exact provider, adapter and implementation identities;
- exact `ProviderInvocationPayload.digest` and payload schema ID;
- exact runtime/effect subject: entrypoint, runtime, execution, idempotency key,
  execution-request digest, Effect Lease digest and source revision;
- parent `ProviderInvocationObservationAuthority.digest`;
- parent observation-authority, invocation-contract, invocation-subject and
  invocation-registry digests;
- exact provider pre-admission receipt digest;
- fixed admitted invoke target plus source digest;
- fixed admitted output-evidence target plus source digest;
- the existing provider authority key ID.

The ABI contract is HMAC-authenticated with the same authority key that verifies
the parent `ProviderInvocationObservationAuthority`. Issuance and verification
first re-authenticate that parent authority through the existing canonical
verifier and then require an exact conjunction among parent authority, payload,
pre-admission evidence and `EffectExecutionRequest`.

This makes the payload/target binding subordinate to the existing authority
rather than an independent execution permission.

## Fail-closed behavior

The boundary refuses:

- payload provider/adapter/subject substitution;
- provider-pre-admission substitution;
- execution-request substitution;
- parent authority/contract/registry substitution;
- signed payload digest substitution;
- invoke-target or output-evidence-target/source substitution;
- unknown/malformed authority keys;
- serialized claim escalation;
- contract subclass/type smuggling.

The payload body remains bounded/deep-frozen by 07D1 and is represented here by
its canonical digest only.

## Explicit non-claims

Every serialized ABI contract keeps these claims false:

- `provider_execution_allowed`;
- `effect_start_authorized`;
- `callback_seam_removed`;
- `broker_invocation_performed`;
- `automatic_reexecution_allowed`;
- OwnerApproval/promotion/Gate transition/closure.

The module contains no callable resolver, dynamic importer, process/network API,
`begin_effect`, provider invocation or broker call.

## Verification

Focused tests cover round-trip/authentication, payload identity sensitivity,
adapter mismatch, signature breakage after payload/target mutation, parent/
pre-admission substitution, execution substitution, claim escalation and type
smuggling. A source-review test rejects dynamic loader/process/network imports,
execution primitives and a public callable-resolver surface.

The unified Ikarus Python 3.10/3.12 workflow includes the new module and tests.
Hosted Actions evidence is counted only when real runner steps execute; zero-step
allocation failures under #67 are not test evidence.

## Remaining #278 / #188 work

This packet authenticates the exact invocation ABI but does **not** yet cut the
production broker over to it. The next bounded step should:

1. require this ABI contract at the pre-effect runtime binding boundary;
2. resolve the already-admitted fixed adapter/output-evidence operations only
   through the guarded executable registry;
3. make exact replay return before adapter resolution/execution;
4. remove production `invoke` and `output_digests` callable parameters from
   `run_runtime_provider`, leaving any compatibility callback path test-only and
   ineligible for runtime-bound recovery;
5. preserve callback-free recovery and STARTED unknown-outcome semantics.

Only after those fences and executable exact-head tests exist should
`provider_execution_allowed` or `callback_seam_removed` change value.
