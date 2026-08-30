# G1-IKARUS-07S — Serialize provider admission onto the canonical effect bridge

Status: integration packet  
Gate: Gate 1 — Renovation ignition slice  
Master-plan authority: `docs/IKARUS_ARIADNE_MASTER_PLAN.md`, Revision 8

## Purpose

Collapse the two active Ikarus delivery lines into one reviewable dependency chain instead of growing sibling runtime/effect authorities.

Before this packet, the Hermes-parity work had split into:

- `G1-IKARUS-04 -> 05 -> 06`: stateless one-shot request, canonical policy-bound tool scope, and canonical Effect bridge;
- `G1-IKARUS-07A -> 07B -> 07C -> 07C1`: provider executable pre-admission, guarded loaded-object evidence, pre-effect provider/executable binding, and ambient dependency hardening.

The provider line was independently based on `main`. This packet starts exactly from `G1-IKARUS-06` head `5ffbb1125f55c50b0d4f914efd53ba2dcf4191ac` and selectively ports the reviewed provider-line files byte-for-byte from `G1-IKARUS-07C1` head `b2d44883c3184ec6dd91e4ff0954568750058b5b`.

No provider implementation or trust-boundary logic is rewritten by the serialization itself.

## Containment / gardening result

The selective port adds only the existing provider-admission modules, focused tests, work packets, and their dedicated workflows. Relative to `G1-IKARUS-06`, it is one commit and zero commits behind at creation time. This gives Ikarus one linear review path:

`one-shot -> tool policy -> canonical effect request -> provider pre-admission -> executable evidence -> pre-effect binding`

The older sibling Draft PRs remain useful review/evidence records; this packet does not merge, close, rewrite, or delete them.

## Important blocker discovered during serialization

The current loaded-object registry deliberately refuses closures/default-bound ambient state. The real Claude provider on `main`, however, currently enters `run_runtime_provider(...)` with two per-call lambdas that close over objective/workspace/model/timeout/invocation evidence. Therefore the present registry evidence cannot honestly be treated as the executable ABI for the real provider merely by adding a sealed namespace around the stored functions.

Before the production broker callback seam is removed, Daedalus needs one explicit authenticated invocation ABI that:

1. binds the exact per-call payload and its digest into the already signed provider invocation subject;
2. selects a fixed admitted adapter target rather than a caller-supplied closure;
3. defines output-evidence extraction as part of the same authenticated adapter contract;
4. keeps replay inert and recovery callback-free;
5. preserves provider-specific arguments without smuggling ambient objects or a second provider registry;
6. remains subordinate to the canonical `RuntimeBoundEffectAuthorization`, `EffectExecutionRequest`, provider observation authority, and Effect lifecycle.

Until that contract exists, `provider_execution_allowed=false` and `callback_seam_removed=false` remain the correct claims of 07A/07B/07C/07C1.

## Integrated verification

`.github/workflows/g1-ikarus-unified-runtime-admission.yml` executes one Python 3.10/3.12 matrix across both halves of the serialized chain: one-shot/effect bridge/runtime conformance plus provider pre-admission/object-registry/pre-effect-binding and independent source-review regressions.

Hosted results count only when real steps execute. A zero-step runner allocation failure remains infrastructure evidence under #67, not a product pass or failure.

## Hermes provenance boundary

The repository still pins and mechanically validates Hermes `v2026.8.19` / v0.20.5 for the code concepts already adapted. Hermes released v0.20.6 (`v2026.8.27`) after that pin; refreshing source-level provenance for the new release is separate research work and must not silently change this packet's existing evidence subject.

## Authority boundary

This packet does not execute a provider, grant an Effect Lease, start an Effect, remove broker callbacks, mint OwnerApproval, merge a PR, promote a candidate, or transition a Gate. It reduces branch/architecture fragmentation and creates one integration test surface for the already-reviewed Ikarus runtime-admission work.
