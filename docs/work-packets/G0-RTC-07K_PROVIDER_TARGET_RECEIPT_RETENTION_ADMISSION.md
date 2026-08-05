# G0-RTC-07K — Provider Target Receipt Retention Persisted-Lease Admission

## Purpose

This Work Packet composes the signed receipt-retention preflight with the existing read-only Effect-Lease replay projection. It answers one narrow question without performing the retention effect:

> Does this exact, signed, revision-bound receipt-retention request have one exact persisted non-runtime Effect Lease, and are the concrete mutation targets still bound to the expected live stores outside the Primary Checkout?

The answer is encoded in `ProviderTargetReceiptRetentionAdmissionReceipt`. The receipt is admission evidence only. It is not execution authority and cannot be used as a substitute for re-running admission immediately before a later durable start.

## Exact parent

- Parent branch: `g0/provider-target-receipt-retention-preflight-linear`
- Parent revision: `1125e68b8ad02d9a1a193bf9392cfaf1f9213088`
- Parent PR: #218
- This PR: #222

No commit in this packet targets `main` or `experimental` directly.

## Ordered verification

The admission verifier performs the following sequence:

1. Rejects non-exact execution, authorization, retention-ledger, lease, lease-request, policy and Effect-Lease-ledger types.
2. Binds the lease, request and policy IDs, digests, effects, scopes, runtime fields, idempotency namespace and kill-switch generation.
3. Snapshots the exact execution, lease, request and policy digests.
4. Replays the signed retention preflight and binds it to the current receipt, inventory, authority, execution and lease identities.
5. Requires one exact `provider.target_receipt_retention` allow decision with evidence equal to the signed preflight evidence.
6. Resolves the Primary Checkout, retention root, Event Store, receipt CAS, receipt-CAS `objects` target and Effect-Lease store without accepting symlink components.
7. Requires an exact writable `SpineLedger` and binds its declared path to the main database of its already-open SQLite connection using only `PRAGMA database_list`.
8. Requires the receipt-CAS `objects` target to be the exact direct child of the scoped CAS root.
9. Proves path and device/inode disjointness for protected stores, single-link regular state files, and non-aliasing SQLite WAL, SHM and journal companions.
10. Reads the exact persisted lease and execution through the query-only replay projection.
11. If the execution is unstarted, verifies current lease signature, registry binding, expiry and live kill-switch generation.
12. Repeats the complete concrete topology verification and requires equal path/device/inode identities.
13. Replays the signed preflight a second time and requires the same receipt and guard.
14. Reads the persisted execution a second time and requires the exact same replay projection.
15. If the execution remains unstarted, repeats live authorization verification.
16. Rechecks every live subject digest and emits a strict canonical admission receipt.

The two preflight fences catch stale repository revision, inventory or authority changes. The two topology fences catch same-path inode replacement, symlink substitution, hard-link aliasing, CAS-target movement and Event-Store path/connection detachment. The two replay reads catch concurrent durable starts or terminal transitions. The two live checks prevent an expired, revoked, invalidly signed or kill-switch-stale unstarted lease from being reported as admissible.

## Persisted execution states

The receipt reports only an exact read-only projection:

- `not_started`: the signed lease is uniquely persisted, the exact execution has no durable start, and current live authority verifies on both sides of the second replay.
- `started`: one exact durable start exists and requires later reconciliation. Current expiry is not retroactively applied to historical execution evidence, and no automatic retry or re-execution is authorized.
- `COMPLETED`, `FAILED` or `CANCELLED`: one exact terminal receipt is bound to the exact start receipt.

A terminal Effect state does not prove that provider-target receipt retention completed correctly. The future central entrypoint must separately bind the retention-ledger CAS artifact, canonical Event-Store state and Effect terminal receipt.

## Claims deliberately kept false

The admission receipt permanently reports:

- `retention_write_performed=false`
- `automatic_reexecution_allowed=false`
- `canonical_entrypoint_registered=false`
- `gate_transition_authorized=false`
- `closed=false`

The packet does not grant, start, finish or revoke an Effect Lease. It does not call `ProviderTargetReceiptLedger.retain`. It does not execute a provider, promote a candidate, create OwnerApproval, merge a PR or close Gate 0.

## Adversarial review findings resolved

Independent review found and corrected the following gaps before the dependent execution packet was started:

- Comparing only resolved path strings missed same-path inode replacement. Topology snapshots now preserve path, device and inode identities.
- An unstarted persisted lease could be observed without current cryptographic and kill-switch validation. Live authorization is now checked twice.
- Persisted execution state was read once. It is now read twice and must remain exactly equal.
- `SourceTreeStore.objects` was the actual CAS write target but was not independently bound. It is now required as the exact direct child of the scoped CAS root.
- An exact `SpineLedger` instance could still be read-only. The retention ledger must expose a writable Spine.
- `SpineLedger.path` could be reassigned away from the live SQLite connection. The verifier now authenticates the connection's main database with one read-only `PRAGMA database_list` query and compares filesystem identity.

## Adversarial verification prepared

Focused behavior tests cover unstarted, started and terminal projections; current-authority refusal; first and second stale-preflight refusal; persisted-state change between reads; same-path CAS replacement; declared Event-Store path versus live connection mismatch; malformed scopes; CAS and object-target substitution; read-only Spine; guard and authority detachment; hard-link aliases; Primary Checkout overlap; non-exact inner objects and replay values; and strict wire claim rejection.

A separate AST review verifies the no-writer boundary, pins the SQLite inspection to exactly one read-only `PRAGMA database_list`, checks exact authority and topology types, double-fence ordering, guard evidence, live subject binding and permanent non-authority claims. A Draft 2020-12 schema constrains all fields and state-dependent receipt combinations. A 21-mutant bounded campaign targets preflight, topology, live-connection, persisted replay, live lease, hard-link, CAS-target and unsupported authority-claim bypasses.

The workflow requests focused tests on Ubuntu and Windows with Python 3.10 and 3.12 under two hash seeds, predecessor regressions, mutation tests, the full suite, package build and isolated-wheel import.

## Remaining dependent boundary

The next dependent packet must register the exact production entrypoint and guard contract centrally, re-run admission immediately before mutation, begin the persisted retention Effect Lease, handle retained `STARTED` state without automatic re-execution, call the retention ledger only after `execute=true`, and bind the CAS/Event-Store result to the exact Effect terminal receipt. Fault injection must cover every intent, CAS, Event-Store and Effect-Lease window before any release-report closure claim is possible.

## External verification status

Repository-hosted GitHub Actions has an existing infrastructure incident tracked in #67: jobs have repeatedly ended before Step 1 with `steps=null` and no logs or artifacts. Such a run is external infrastructure evidence only and is never accepted as builder, review, mutation, full-suite, packaging or platform product evidence.
