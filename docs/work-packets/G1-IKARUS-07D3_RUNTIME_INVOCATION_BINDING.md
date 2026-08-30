# G1-IKARUS-07D3 - Runtime invocation binding

## Frozen packet metadata

- Packet ID: `G1-IKARUS-07D3`
- Status: **isolated stacked candidate; non-executing; merge blocked until 07D2
  is green/reviewed or explicitly frozen, exact-head system CI exists, and the
  owner decides**
- Active gate: **Gate 1**
- Classification: `ALIGNED` canonical-kernel composition/security hardening
- Owner: repository owner; merge, promotion, and Gate decisions remain explicit
  owner actions
- Exact implementation base / D2 dependency:
  `94e053c588c10f2ef888182a4a1c9df99b59c849`
- Independent-review remediation base:
  `1c2c97f5ebff63a3bb1a2795d4017c5173348347`
- Other dependencies: 07B executable-object registry, 07C runtime executable
  binding, existing `ProviderObservationBindingLedger`, #278, and #188
- Primary acceptance claim: authenticated ABI and executable evidence must name
  one exact runtime/effect/provider subject before any Effect can start, while
  private trust-root keys remain ledger-owned.

This packet is retained as stacked research candidate evidence, not a second
production truth. The GitHub parent chain has no retained approving review or
executed hosted runner steps. That prerequisite is an explicit merge blocker;
this document does not relabel it green.

## Goal

Compose the authenticated per-call provider ABI from 07D2 with the hardened
executable-object evidence from 07B/07C before any runtime Effect can start.
Payload/target evidence and loaded-object evidence must describe one exact
subject before the broker is allowed to proceed toward durable start.

## Frozen scope

In scope:

- `daedalus/runtimes/provider_runtime_invocation_binding.py`;
- the narrow ledger-owned ABI verification method in
  `daedalus/runtimes/provider_observation.py`;
- `tests/runtimes/test_provider_runtime_invocation_binding.py`;
- `tests/runtimes/test_provider_runtime_invocation_binding_review.py`;
- this Work Packet; and
- the focused-test entry in
  `.github/workflows/g1-ikarus-unified-runtime-admission.yml`.

Forbidden paths and changes:

- no `run_runtime_provider` cutover, callback deletion, or D4 sealed execution;
- no grant, `begin_effect`, `bind_start`, finish, provider target, process, or
  network call;
- no new store, registry, receipt schema, artifact identity, policy, evaluator,
  promotion path, or top-level subsystem;
- no export of original or copied authority/observation key material; and
- no Master Plan, amendment-chain, or owner-approval mutation.

## Minimal boundary

`daedalus.runtimes.provider_runtime_invocation_binding` intentionally introduces
**no new receipt schema, registry, policy engine, or execution layer**. It:

1. re-authenticates the signed `ProviderInvocationABIContract` and canonical
   `ProviderInvocationPayload` through the existing observation-ledger trust
   root;
2. reuses `bind_provider_runtime_executable(...)` to re-prove the exact loaded
   repository functions, source hashes, and code hashes;
3. requires both proofs to agree on provider, adapter, implementation,
   entrypoint, runtime, execution, idempotency identity, Effect Lease, source
   revision, pre-admission receipt, invocation authority/contract/subject, and
   fixed invoke/output-evidence targets; and
4. returns the already-existing `ProviderRuntimeExecutableBindingReceipt`.

Keeping the existing receipt is deliberate anti-bloat: the signed ABI is the
payload/target evidence, while the 07C receipt is executable-object evidence. A
third persistent evidence object would duplicate both.

The existing `ProviderObservationBindingLedger` remains the authority-key trust
root. The composition boundary calls its narrow
`verify_invocation_abi_contract(...)` capability and never reads either private
keyring. Only the ledger-owned method supplies its private keyrings directly to
the existing verifier; neither original mappings nor copies leave the ledger,
are returned, or are persisted by this packet.

## Deliberate non-claims

This packet does **not** execute a provider. It calls no `grant`, `begin_effect`,
`bind_start`, provider target, process, or network API. The reused 07C receipt
continues to state `effect_started=false`, `provider_code_executed=false`,
`provider_execution_allowed=false`, and `callback_seam_removed=false`.

Therefore #188 and #278 remain open. The live `run_runtime_provider` callback
ABI is unchanged by this packet.

## Frozen acceptance matrix and budgets

| Acceptance or refusal | Deterministic evidence | Frozen budget / expected result |
|---|---|---|
| Valid ABI + executable evidence composes | runtime invocation binding focused test | existing 07C receipt; no Effect/provider execution |
| Payload/provider/pre-admission/signature substitution, including an exact ledger with an instance-shadowed verify method, refuses | focused adversarial tests | unbound exact-class verification; refusal before Effect state exists |
| Repository source mutation after admission refuses | focused executable test | refusal before Effect state exists |
| Trust-root keys remain ledger-owned | runtime review AST/source test | no private keyring read, copy, return, or verifier keyring argument in composition module |
| Existing executable authority is reused exactly | runtime review test | no new registry/receipt/authority |
| No callable, loader, process, network, or Effect start | runtime review test | zero forbidden imports/calls |
| Supported interpreter and related-suite evidence | unified Python 3.10/3.12 plus affected legacy suites | each focused job <= 5 minutes; real runner steps required |

The focused local command has a 90-second wall-time budget on the recorded
Windows/Python 3.10 environment. Every case has a budget of zero provider calls,
zero network calls, zero Effect transitions, zero binding-ledger writes, and zero
new store/registry/receipt types.

## Adversarial verification and evidence handoff

Focused tests cover semantic payload substitution, Provider-A authority plus
Provider-B pre-admission, forged ABI signatures, repository-source mutation
after executable admission, exact no-Effect behavior on successful composition,
exact ledger type rejection, and an exact ledger whose instance dictionary
shadows the ABI verifier. AST/source review requires unbound exact-class dispatch
and forbids private keyring access/export, Effect start, provider execution,
callable resolvers, dynamic loaders, subprocess, and network surfaces.

Local independent-review evidence is based on exact remediation base
`1c2c97f5ebff63a3bb1a2795d4017c5173348347`; exact commands and final results
are recorded below after execution. Hosted zero-step allocations remain
infrastructure failures and are not system-CI evidence.

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

The composition module migrates from direct access to
`ProviderObservationBindingLedger._authority_keyring` and the public observation
keyring copy to a ledger-owned verify method. The runtime function signature and
existing `ProviderRuntimeExecutableBindingReceipt` remain unchanged. No
serialized or database schema migration occurs.

## Rollback

Revert the composition module, narrow ledger method, its two focused tests, this
document, and its focused workflow entry together. No data cleanup is required:
the packet writes no binding row and starts no Effect. Preserve the private
key-export and wrong-signing-key reproductions as negative evidence.

## Expected failures

Expected refusals include non-exact ledger/authority/payload/ABI/time objects,
forged signatures even when an exact ledger instance shadows its verifier,
semantic payload substitution, cross-provider pre-admission,
execution/lease/revision drift, repository-source mutation, loaded-object drift,
and every ABI/executable subject mismatch. Review tests fail on bound instance
dispatch, private keyring attributes, copied keyring arguments,
callable/loader/process/network surfaces, or Effect/provider execution calls.

## Review questions

1. Can composition code obtain, copy, return, or persist either ledger keyring?
2. Does the ledger capability verify the exact ABI/parent/payload/pre-admission/
   execution conjunction without becoming a signing or execution oracle?
3. Can any substitution reach executable resolution or an Effect transition?
4. Does the packet reuse the canonical executable registry and receipt without
   minting a competing authority or evidence identity?
5. Are the 07D2 parent review, exact-head Python 3.10/3.12 system results,
   residual risks, and independent approval retained before owner merge?

## Next packet

07D4 may call this conjunction **inside `run_runtime_provider` immediately
before durable grant/start** only after 07D2/07D3 review and system evidence are
green. Exact replay must remain ahead of executable resolution. Deleting the
production `invoke` and `output_digests` callbacks still requires a separately
reviewed sealed execution operation that consumes authenticated payload without
closure/default/global ambient state.

Do not weaken `ProviderExecutableObjectRegistry` merely to fit existing Claude
lambdas. The imported `_invoke_claude_cli` dependency needs an explicit
authenticated dependency/sealed-namespace contract or adapter refactor before
execution can safely move behind the registry.
