# G0-PRM-25G — Promotion Effect Terminalization Authority

## Scope

This packet adds one separately reviewed restart-only authority for the durable
crash window between a retained promotion-execution terminal and its outer
Effect-Lease terminal. It stacks on exact parent
`fcba87ca67ac1ef394bf12615468223c8d104b6e` and does not wire the live Kairos
entrypoint, centralize the promotion registry row, issue OwnerApproval, invoke
Git, create a worktree, merge, or promote.

## Authority boundary

`reconcile_promotion_effect_terminal(capability, promotion_ledger)` first runs
the canonical strict cross-ledger projection. It writes only when that
projection returns `effect-terminalization-required`: the outer Effect-Lease
start exists, the exact promotion start and terminal exist, and the outer
terminal is absent.

The terminal outcome, outputs and detail digest are not caller inputs. They are
copied only from `ExpectedPromotionEffectTerminal`, which is itself derived
from the exact retained promotion receipt:

- `succeeded` → `COMPLETED`, with promotion receipt/report digests as outputs;
- `refused` → `CANCELLED`, with no outputs;
- `faulted` → `FAILED`, with no outputs.

This path deliberately does not re-check current lease expiry or revocation.
That exception grants no execution authority: the external repository effect
has already terminalized in the canonical promotion Event Store, and the only
permitted write is exact outer bookkeeping against its already-retained start.

## Idempotency and contradiction handling

A retained `complete` projection replays without a write. Fresh, effect-only
pending and promotion-pending states refuse. After a write, the strict
projection runs again and the returned receipt digest must equal the retained
terminal digest. If another reconciler wins the writer race, only an exact
`complete` reprojection is accepted; a substituted or contradictory terminal
still refuses.

## Adversarial batch

Prepared evidence covers all three terminal outcomes, pending-state bypass,
concurrent exact terminalization, contradictory post-write state, retained
receipt substitution, malformed authority types, one-writer AST review, and
six bounded source mutations. The requested matrix remains Ubuntu/Windows,
Python 3.10/3.12 and deterministic hash seeds, followed by the full suite and
isolated-wheel packaging.

## Remaining dependent boundary

A later narrow packet must place the outer Effect-Lease start before the live
promotion start, route the retained terminal through immediate normal
completion, and route restart `effect-terminalization-required` state through
this authority. Effect-only and promotion-pending states must remain
reconciliation-only and must never trigger automatic re-execution. Runtime
conformance and Docker-sandbox composition remain required before the canonical
promotion row can become `central`.

Exact-head execution is pending. Repository Actions issue #67 has repeatedly
terminated hosted jobs before Step 1; zero-step runs are infrastructure
observations only and are not product, mutation, packaging, platform or Gate
evidence.

No merge, promotion, OwnerApproval issuance or Gate transition is requested.
