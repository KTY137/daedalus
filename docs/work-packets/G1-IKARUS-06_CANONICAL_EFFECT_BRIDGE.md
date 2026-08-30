# G1-IKARUS-06 — Canonical one-shot effect bridge

Status: implementation packet  
Gate: Gate 1 — Renovation ignition slice  
Depends on: G1-IKARUS-04, G1-IKARUS-05  
Master-plan authority: `docs/IKARUS_ARIADNE_MASTER_PLAN.md`, Revision 8

## Purpose

Close the seam between Ikarus' Hermes-like stateless one-shot contract and the
existing Daedalus Mission / Policy / Execution / Evidence kernel without adding
a provider-specific authority or a second effect system.

The useful Hermes behavior retained here is per-call runtime/tool/budget scope.
The implementation is Daedalus-native: one-shot identity and policy-projected
tools are converted into the already canonical `EffectLeaseRequest` and
`EffectExecutionRequest`. Policy evaluation, lease issuance, persisted runtime
trust, provider observation binding and external execution remain owned by the
existing kernel and `daedalus.runtimes.broker`.

## Delivered

- `daedalus/ikarus_effect_bridge.py`
  - binds `OneShotRequest`, `OneShotRuntimeEvidenceBinding` and
    `IkarusToolScopeProjection` by exact digest;
  - emits the canonical `EffectLeaseRequest`, including exact runtime manifest
    and conformance digests;
  - records the one-shot request, runtime evidence, tool projection and the
    tool-policy decision in canonical provenance inputs;
  - maps one-shot wall-time and cost ceilings into `EffectScope` without
    widening them;
  - fixes concurrency at one and requires an explicit kill switch;
  - requires write/egress/secret scopes to name the matching canonical effect;
  - emits a narrowed `EffectExecutionRequest` and refuses broader effects,
    paths, endpoints, secrets or spend;
  - gives the execution exactly the final enabled tool set, never ambient
    runtime/plugin tools.
- focused adversarial tests covering subject substitution, scope/effect
  mismatch, disabled-tool resurrection, timeout/cost widening, execution
  widening and provenance stripping;
- exact-head Python 3.10 / 3.12 CI for this stacked packet.

## Non-goals / authority boundary

This packet does **not**:

- call a model or provider;
- issue a `PolicyDecision`, Effect Lease or `RuntimeBoundEffectAuthorization`;
- load provider adapter Python targets;
- create provider observation authority;
- create a second runtime, tool, workspace, session or scheduler registry;
- claim live-provider statelessness merely because the interface is stateless;
- auto-retry, auto-promote or auto-merge anything.

The current provider executable-target stack still stops at authenticated,
read-only structural verification: its receipt explicitly states that repository
bytes were not executed and provider execution is not allowed. A broker-bound
real Ikarus runtime adapter must therefore wait for the canonical guarded
executable-admission/loader seam rather than bypassing it from Ikarus.

## Acceptance criteria

1. Every emitted lease request is the existing exact `EffectLeaseRequest` type.
2. Runtime manifest/conformance identity comes only from the bound one-shot
   runtime evidence.
3. Tool scope comes only from G1-IKARUS-05's final enabled projection.
4. Wall-time, cost, concurrency, write, egress, secret and kill-switch scope can
   never be broader at execution than at request construction.
5. Scope-bearing writes, egress and secrets require their canonical Effect enum
   member; spend requires an explicit cost ceiling.
6. Ikarus request/runtime/tool-policy digests survive into canonical
   provenance, so later lease/provider evidence can be traced back without a
   parallel database.
7. The bridge imports no process/network/database client and invokes no broker,
   lease issuer or policy authority.
8. Focused tests pass on Python 3.10 and 3.12.

## Next bounded packet

G1-IKARUS-07 should connect one selected provider implementation only after the
canonical executable-target pipeline can produce an execution-admission receipt
for exact repository bytes. That adapter must consume this packet's canonical
effect request, an exact `RuntimeBoundEffectAuthorization`, exact
`EffectExecutionRequest`, provider observation authority/binding ledger, and
content-addressed output evidence through `run_runtime_provider`. Cancellation
then needs to project back into the canonical attempt/effect lifecycle without
implicit re-execution.
