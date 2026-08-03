# G0-WP-03A — Effect Entry-Point Centralization

## Status

`ALIGNED`, Gate 0, local integration candidate. This packet does not claim
Gate-0 closure, promotion readiness, or complete effect-surface coverage.

## Integration boundary

The candidate preserves the accepted Iron Plan revision-3 ancestry, starts
from `g0/effect-entrypoint-centralization@30b4f9c`, and retains
`g0/fault-matrix-foundation@514dbeb` through a two-parent merge. Gate-2 and
knowledge-correlation branches are deliberately excluded.

The implemented production slice is exactly `python.offload`. It requires a
persisted, scope-bound Effect Lease before live provider or filesystem work.
The broader inventory remains open: one central entry point is evidence for
the migration pattern, not evidence that all effectful call paths are covered.

## Terminal-integrity repair

Every execution persists `STARTED` before the external effect. After the
effect, output evidence and terminal persistence now share an explicit
finalization boundary:

- a canonical output publishes `COMPLETED` with its output digest;
- provider errors publish `FAILED`, and cancellation publishes `CANCELLED`;
- a non-canonical provider result publishes `FAILED` before the serialization
  error escapes;
- if terminal persistence itself fails, a typed
  `EffectReconciliationRequired` error exposes the exact execution and start
  receipt while the durable `STARTED` row remains replay-inert.

The last case is intentionally indeterminate. It must be reconciled against
the external system; it must never be retried as if no effect happened. No
second ledger or recovery store is introduced.

## Executable evidence

The combined local chain runs owner approval, effect leasing, runtime and
sandbox contracts, sealed promotion, leased offload, effect-boundary checks,
attempt handling, routing, rollback, write guards, replay, and the fault
matrix. JUnit receipts must be stored outside the repository and bound to the
exact candidate SHA.

Two adversarial cases are load-bearing:

1. the provider proves it ran and returns a non-JSON value; the execution ends
   `FAILED` and replay does not call the provider again;
2. the provider proves it ran and terminal storage fails; the caller receives
   `EffectReconciliationRequired`, the ledger retains `STARTED`, and replay is
   inert.

## Remaining blockers

The Gate-0 report now carries `noncentral_entrypoints` as an explicit blocker
set. `LOCAL_GUARDS`, `INVENTORY_ONLY`, `UNGUARDED`, and `ABSENT` rows can no
longer disappear into diagnostics while a report claims closure. The current
registry has 50 rows; only `python.offload` is `CENTRAL`, so the report remains
closed regardless of other green evidence.

- migrate and independently test every remaining effectful entry point;
- add an operator-controlled reconciliation operation for indeterminate
  executions without weakening replay prevention;
- execute real Docker and live Claude, Codex, and Ollama conformance/fault
  probes rather than treating mocked contract tests as host evidence;
- produce exact-head CI, package-boundary, architecture, security, and owner
  closure receipts.
