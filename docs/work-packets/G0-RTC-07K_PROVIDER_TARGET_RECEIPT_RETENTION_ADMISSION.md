# G0-RTC-07K — Provider Target Receipt Retention Persisted-Lease Admission

## Purpose

This Work Packet composes the signed receipt-retention preflight with the existing read-only Effect-Lease replay projection. It answers one narrow question without performing the retention effect:

> Does this exact, signed, revision-bound receipt-retention request have one exact persisted non-runtime Effect Lease, and are all concrete state targets still outside the Primary Checkout and mutually non-aliasing?

The answer is encoded in `ProviderTargetReceiptRetentionAdmissionReceipt`. The receipt is admission evidence only. It is not execution authority.

## Exact parent

- Parent branch: `g0/provider-target-receipt-retention-preflight-linear`
- Parent revision: `1125e68b8ad02d9a1a193bf9392cfaf1f9213088`
- Parent PR: #218
- This PR: #222

No commit in this packet targets `main` or `experimental` directly.

## Ordered verification

The admission verifier performs the following sequence:

1. Rejects non-exact execution, authorization, retention-ledger, lease, lease-request, policy and Effect-Lease-ledger types.
2. Snapshots the exact execution, lease, request and policy digests.
3. Replays the signed retention preflight and binds it to the current receipt, inventory, authority, execution and lease identities.
4. Requires one exact `provider.target_receipt_retention` allow decision with evidence equal to the signed preflight evidence.
5. Resolves the Primary Checkout, retention root, Event Store, receipt CAS and Effect-Lease store without accepting symlink components.
6. Binds the Event Store and CAS to the exact repository-relative scope paths under the retention root.
7. Proves pairwise path and filesystem-identity disjointness for the protected stores and verifies single-link regular state files and existing SQLite companions.
8. Reads the exact persisted lease and execution through `inspect_effect_execution`, which opens the Effect-Lease store read-only and query-only.
9. Repeats the concrete topology verification and requires the same resolved identities.
10. Replays the signed preflight a second time and requires the same preflight digest.
11. Rechecks the guard and every live subject digest.
12. Emits a strict canonical admission receipt.

The two preflight fences catch a stale repository revision or changed inventory before the admission result is returned. The two topology fences catch path replacement, symlink substitution, hard-link aliasing and protected-store movement across persisted replay.

## Persisted execution states

The receipt reports only the exact read-only projection:

- `not_started`: the signed lease is uniquely persisted and the exact execution has no durable start.
- `started`: one exact durable start exists and requires later reconciliation. No automatic retry or re-execution is authorized.
- `COMPLETED`, `FAILED` or `CANCELLED`: one exact terminal receipt is retained and bound to the exact start receipt.

A terminal provider-target retention write is not inferred from the Effect terminal state in this packet. The future central entrypoint must bind retention-ledger artifacts and Event-Store state explicitly.

## Claims deliberately kept false

The admission receipt permanently reports:

- `retention_write_performed=false`
- `automatic_reexecution_allowed=false`
- `canonical_entrypoint_registered=false`
- `gate_transition_authorized=false`
- `closed=false`

The packet does not grant, start, finish or revoke an Effect Lease. It does not call `ProviderTargetReceiptLedger.retain`. It does not execute a provider, promote a candidate, create OwnerApproval, merge a PR or close Gate 0.

## Adversarial verification prepared

The focused builder tests cover not-started, pending-start and terminal replay projections; first and second signed-preflight refusal; malformed scope paths; concrete CAS substitution; guard detachment; hard-link aliases; Primary Checkout overlap; non-exact replay values; and strict wire claim rejection.

A separate AST review verifies the no-writer boundary, exact authority types, double-fence ordering, exact guard evidence, topology controls, live subject binding and permanent non-authority claims. A Draft 2020-12 schema constrains all fields and state-dependent receipt combinations. A bounded mutation campaign targets the preflight fences, topology fences, guard equality, replay exactness, hard-link check, path bindings, disjointness and forbidden authority claims.

The workflow requests focused tests on Ubuntu and Windows with Python 3.10 and 3.12 under two hash seeds, predecessor regressions, mutation tests, the full suite, package build and isolated-wheel import.

## Remaining dependent boundary

The next dependent packet must register the exact production entrypoint and guard contract centrally, begin the persisted retention Effect Lease immediately before mutation, handle retained `STARTED` state without automatic re-execution, call the retention ledger only after `execute=true`, and bind the CAS/Event-Store result to the exact Effect terminal receipt. Fault injection must cover every intent, CAS, Event-Store and Effect-Lease window before any release-report closure claim is possible.

## External verification status

Repository-hosted GitHub Actions has an existing infrastructure incident tracked in #67: jobs have repeatedly ended before Step 1 with `steps=null` and no logs or artifacts. Such a run is external infrastructure evidence only and is never accepted as builder, review, mutation, full-suite, packaging or platform product evidence.
