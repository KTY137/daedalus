# G0-PRM-25H — Sealed Promotion Effect Entry Preparation

## Scope and parent

This Work Packet is stacked directly on deterministic terminal reconciliation:

- parent branch: `g0/promotion-effect-terminal-reconcile-linear`;
- parent revision: `beae21ff90dfcd8203296f1fc9b35ed8c4112934`;
- parent draft PR: `#151`.

It prepares the outer entry boundary that must run before the existing Kairos
promotion lifecycle can reach any repository mutation. It does not call the live
promotion function, accept a promotion callback, terminalize a newly executed
promotion, or change canonical registry wiring.

## Entry state machine

`prepare_promotion_effect_entry()` accepts only one exact
`PromotionEffectCapability` and one selected canonical
`PromotionExecutionLedger`. It returns one immutable action:

| Persisted state | Entry action |
|---|---|
| exact lease absent, promotion absent, this call creates exact effect start | `execute_promotion` |
| exact start already exists, promotion absent or pending | `pending_reconciliation` |
| promotion terminal, effect still started | reconcile deterministically, then `replay_promotion_report` |
| exact cross-ledger terminal already exists | `replay_promotion_report` |
| failed or cancelled top-level effect before promotion start | `replay_effect_terminal_without_report` |
| promotion exists before exact lease persistence | refuse contradiction |
| lease digest or ID collides with another persisted authority | refuse contradiction |

Only the caller whose canonical `begin()` returns `execute=true` may receive
`execute_promotion`. Even then, a strict post-start cross-ledger inspection must
show the exact returned start receipt and no promotion start. A competing or
restarted caller whose `begin()` returns `execute=false` is routed to a
non-executing action.

## Lease-presence boundary

Before invoking the canonical grant path, the entry protocol performs a narrow
read-only presence check:

- SQLite is opened with `mode=ro` and `query_only=ON`;
- the lookup is by exact lease digest or exact lease ID;
- absence is distinguished from exact presence;
- digest/ID collisions and multiplicity fail closed;
- no database or row is created by the probe.

If no exact lease is persisted, the protocol independently verifies that no
promotion start already exists. This prevents a missing or deleted lease row
from being treated as fresh authority over retained repository-effect state.
Full lease authentication and exact execution validation still occur in the
canonical grant/begin path and strict replay projections.

## Authority separation

The entry module accepts no report, outcome, terminal time, path, provider or
callable. It contains no Git, Docker, worktree, sandbox or live-promotion call.
Its only authority-bearing operations are the existing canonical
`capability.grant()` and `capability.begin()` methods, in that order. It never
calls finish or promotion completion.

`PromotionEffectEntryResult` exposes no execution method. Its sole permission
indicator, `permits_promotion_execution`, is true only for the exact
`execute_promotion` action validated against this call's persisted start
receipt.

## Adversarial batch

Builder and independent source-review tests cover:

- the sole executable state;
- retained promotion before lease persistence;
- pending restart without grant or begin;
- exact begin race with `execute=false`;
- retained report replay without entry write;
- deterministic terminal reconciliation routing;
- pre-promotion failed terminal replay;
- promotion-start race after a fresh effect start;
- read-only absent/exact/collision presence probing;
- absence of callbacks, live promotion and terminal writers;
- strict grant-before-begin and post-start ordering.

The bounded mutation runner attacks retained-promotion refusal, grant/start
ordering, replayed-start execution, post-start promotion races, lease identity
collisions and pending-state re-execution.

## Honest migration state

The existing `promote_candidates` implementation remains unchanged and the
canonical promotion row remains `local_guards`. A dependent packet must add the
matching exit protocol that terminalizes only from the exact retained promotion
completion or a bounded pre-promotion failure. A later small strangler adapter
may then consume both protocols around the existing implementation while
preserving the current import path.

No merge, automatic promotion, OwnerApproval issuance or Gate transition is
requested.

## Verification boundary

Exact-head focused, malformed-state, mutation, full-suite, platform and
isolated-wheel execution is requested by the dedicated workflow. GitHub Actions
issue `#67` remains an external infrastructure blocker while jobs terminate
before Step 1 with no logs or artifacts. Zero-step runs are not product or Gate
evidence.
