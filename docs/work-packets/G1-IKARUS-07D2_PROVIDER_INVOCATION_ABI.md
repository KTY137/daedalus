# G1-IKARUS-07D2 - Authenticated provider invocation ABI

## Frozen packet metadata

- Packet ID: `G1-IKARUS-07D2`
- Status: **prepared candidate; non-executing; merge blocked pending retained
  parent review, exact-head system CI, and owner decision**
- Active gate: **Gate 1**
- Classification: `ALIGNED` canonical-kernel security/evidence hardening
- Owner: repository owner; merge, promotion, and Gate decisions remain explicit
  owner actions
- Exact implementation base: `e5f55840a12dcfb1a50935c6080f06306a8854a8`
- Serialized D2 head before independent-review remediation:
  `94e053c588c10f2ef888182a4a1c9df99b59c849`
- Independent-review remediation base:
  `1c2c97f5ebff63a3bb1a2795d4017c5173348347`
- Parent work: `G1-IKARUS-07D1`, #278, and #188
- Primary acceptance claim: one authenticated canonical payload and admitted
  target tuple is bound to one already-authenticated provider invocation subject
  without granting execution authority.

The local remediation remains an isolated candidate. Drafts #277 and #295 have
no retained approving review or executed hosted test steps, so this packet does
not claim that its dependent-build prerequisite is green. That missing evidence
must be resolved or explicitly frozen as a documented blocker before merge.

## Purpose

07D1 made per-call provider inputs deterministic data instead of Python closure
state. 07D2 binds that canonical payload identity to the already-authenticated
provider invocation subject and to the exact provider executable/output-evidence
targets proven by provider pre-admission.

The contract is intentionally a narrow extension of the existing authority
chain. It does not introduce a second provider registry, policy engine, runtime
kernel, plugin authority, or session layer.

## Frozen scope

In scope:

- `daedalus/runtimes/provider_invocation_abi.py`;
- `tests/runtimes/test_provider_invocation_abi.py`;
- `tests/runtimes/test_provider_invocation_abi_review.py`;
- this Work Packet; and
- the focused-test entry in
  `.github/workflows/g1-ikarus-unified-runtime-admission.yml`.

Forbidden paths and changes:

- no broker, provider adapter, `EffectLedger`, Effect grant/start/finish,
  recovery, promotion, policy, or evaluator change;
- no new store, registry, receipt family, artifact identity, or execution
  entrypoint;
- no callable resolution, provider/process/network invocation, or ambient
  payload capture; and
- no Master Plan, amendment-chain, or owner-approval mutation.

## Contract

`ProviderInvocationABIContract` binds:

- exact provider, adapter, and implementation identities;
- exact `ProviderInvocationPayload.digest` and payload schema ID;
- exact runtime/effect subject: entrypoint, runtime, execution, idempotency key,
  execution-request digest, Effect Lease digest, and source revision;
- parent `ProviderInvocationObservationAuthority.digest`;
- parent observation-authority, invocation-contract, invocation-subject, and
  invocation-registry digests;
- exact provider pre-admission receipt digest;
- fixed admitted invoke target plus source digest;
- fixed admitted output-evidence target plus source digest; and
- the existing provider authority key ID.

The ABI contract is HMAC-authenticated with the same authority key that verifies
the parent `ProviderInvocationObservationAuthority`. Issuance snapshots and
normalizes the supplied canonical authority keyring once, re-authenticates the
parent against that snapshot, and derives the signing key only by the
authenticated parent key ID. There is no separate caller-supplied signing
secret. Verification applies the same snapshot-before-use rule and exact
conjunction among parent authority, payload, pre-admission evidence, and
`EffectExecutionRequest`.

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
- unknown, malformed, or foreign authority keyrings;
- serialized claim escalation; and
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
`begin_effect`, provider invocation, or broker call.

## Frozen acceptance matrix and budgets

| Acceptance or refusal | Deterministic evidence | Frozen budget / expected result |
|---|---|---|
| Valid ABI round-trip authenticates one exact subject | `test_authenticated_invocation_abi_round_trips_and_verifies` | no network/provider execution; pass |
| Issuer has no detached signing secret | `test_issue_uses_only_the_authenticated_canonical_authority_keyring` plus review AST | zero returned contracts for a foreign canonical keyring; pass |
| Stateful mapping cannot switch the signing key after authentication | `test_issue_snapshots_stateful_authority_keyring_before_authentication` | source mapping read once; emitted contract verifies against that snapshot |
| Payload/adapter/parent/pre-admission/execution substitution refuses | focused ABI tests | refusal before any Effect; pass |
| Signed payload/target mutation refuses | focused ABI tests | signature refusal; pass |
| Claim escalation and type smuggling refuse | focused ABI tests | strict parse/type refusal; pass |
| No loader, callable, process, network, or Effect surface | ABI review tests | zero forbidden imports/calls; pass |
| Supported interpreter evidence | unified Python 3.10/3.12 job | each focused job <= 5 minutes; real runner steps required |

The focused local command has a 60-second wall-time budget on the recorded
Windows/Python 3.10 environment. Every case has a budget of zero provider calls,
zero network calls, zero Effect transitions, zero durable writes, and zero new
authority/store/registry objects.

## Verification and evidence handoff

Focused tests cover round-trip/authentication, canonical signing-key selection,
payload identity sensitivity, adapter mismatch, signature breakage after
payload/target mutation, parent/pre-admission substitution, execution
substitution, claim escalation, and type smuggling. A source-review test rejects
dynamic loader/process/network imports, execution primitives, detached signing
secrets, and a public callable-resolver surface.

Local independent-review evidence is based on exact remediation base
`1c2c97f5ebff63a3bb1a2795d4017c5173348347`; exact commands and final results
are recorded below after execution. The unified Ikarus Python 3.10/3.12 workflow
includes the module and tests. Hosted Actions evidence is counted only when real
runner steps execute; zero-step allocation failures under #67 are not evidence.

### Local remediation evidence - 2026-08-30

Environment: Windows, CPython 3.10.11, branch
`review-fix/pr296-trust-boundary`, committed remediation candidate based on exact
`1c2c97f5ebff63a3bb1a2795d4017c5173348347`; `PYTHONDONTWRITEBYTECODE=1`,
pytest plugin autoload disabled, and no remote mutation.

- Four focused 07D2/07D3 test files, final rerun: `23 passed in 5.99s`.
- Unified affected runtime-admission suite: `179 passed in 84.34s`.
- Observation/broker/recovery compatibility subset: `44 passed in 18.95s`.
- `git diff --check`: clean.

These are local builder/remediation results, not Linux/Python 3.12 system CI and
not owner promotion evidence. The exact final commit identity is recorded in the
review handoff rather than embedded in self-identifying commit content;
independent review remains required before any merge decision.

## Migration and compatibility

This is an additive evidence contract. Callers of
`issue_provider_invocation_abi_contract(...)` migrate by deleting the detached
`authority_secret` argument; the function derives the only admissible signing
key from the authenticated canonical authority-keyring snapshot. No serialized
schema, database row, or existing receipt requires migration.

## Rollback

Revert the ABI module, its two focused test files, this document, and its focused
workflow entry together. No durable data cleanup is required because the packet
creates no store and performs no Effect. Retain the wrong-key issuance failure
and independent-review findings as negative evidence even if rolled back.

## Expected failures

Expected refusals include malformed/unknown/foreign authority keyrings,
malformed mappings, invalid parent authority, payload/adapter/
execution/pre-admission substitution, signed target mutation, extra/missing
serialized fields, positive false-claim escalation, and subclass smuggling.
Stateful mappings are snapshotted once; later changes cannot switch the signing
key after parent authentication.

## Review questions

1. Can any issuance path select signing bytes independently of the authenticated
   parent key ID and canonical keyring snapshot?
2. Does every serialized positive claim remain covered by signature and exact
   subject conjunction?
3. Can malformed/stateful mappings, subclasses, or duplicate serialized keys
   cross the boundary?
4. Did the patch add any Effect, provider execution, registry, store, receipt,
   policy, promotion, or evaluator authority?
5. Are exact-head Python 3.10/3.12 system results and an independent approving
   review retained before owner merge?

## Remaining #278 / #188 work

This packet authenticates the exact invocation ABI but does **not** cut the
production broker over to it. A later bounded packet may require the contract at
the pre-effect runtime boundary, keep exact replay ahead of adapter resolution,
and remove production callbacks only after a separately reviewed sealed
execution operation exists. Only after those fences and exact-head evidence
exist may an execution or callback-removal claim change value.
