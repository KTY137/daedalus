# G0-PRM-25E — Read-only Promotion Effect-Lease Replay Projection

## Scope

This packet adds one package-internal, read-only projection over the existing persisted Effect-Lease execution rows for the exact `PromotionEffectCapability` introduced by G0-PRM-25C. It is stacked on the read-only promotion-execution projection from G0-PRM-25D.

The projection opens the retained SQLite database with `mode=ro`, enables and reads back `query_only`, and selects only the exact lease/execution identity carried by the capability. It does not call the ledger writer connection factory, grant a lease, begin or finish an effect, invoke Git, open a worktree, issue OwnerApproval, execute promotion, or change the canonical effect registry.

## Exact binding

Before a retained terminal is exposed, the projection verifies:

- the persisted lease digest, ID, request, policy, registry, entrypoint, exact JSON bytes, issuance and expiry;
- the execution ID, idempotency key, lease digest, exact execution request digest and canonical JSON bytes;
- the start receipt field set, canonical timestamps, digest and database columns;
- the terminal receipt field set, canonical output digests, start binding, state, timestamp and digest;
- absence of terminal material for a `STARTED` execution;
- uniqueness of the selected lease and execution subject.

`None` means no retained execution start exists. `STARTED` is projected only as pending reconciliation and grants no automatic re-execution. A terminal result contains the exact retained `EffectTerminalReceipt`.

## Adversarial batch

The packet prepares tests for absent, granted-only, pending and terminal states; writer-factory bypass; changed execution and lease bytes; pending rows with terminal material; duplicate terminal JSON keys; terminal-state substitution; unknown states; malformed capability input; and a separate AST/source authority review.

The bounded mutation campaign attacks read-only opening, query-only readback, exact request-byte binding, terminal-state binding and ambiguous execution identity refusal.

## Remaining boundary

This packet does not yet compose the top-level Effect-Lease lifecycle with the promotion-execution lifecycle. A dependent packet must ensure a fresh top-level start precedes the live promotion mutation, reconcile both persisted projections without automatic re-execution, and terminalize the top-level effect only from an exactly bound promotion terminal. The canonical promotion row remains `local_guards` until that live composition, runtime/sandbox requirements and the rest of Gate 0 are mechanically closed.

Exact-head execution remains pending because repository GitHub Actions issue #67 currently terminates jobs before Step 1. Zero-step runs are infrastructure observations only and are not verification evidence.

No merge, OwnerApproval, promotion or Gate transition is requested.
