# G0-PRM-25A — Promotion Execution Row Descriptors

## Scope

This packet defines the three exact non-central effect rows needed for the promotion execution ledger without changing the canonical registry yet. It is an intentionally narrow preparation step stacked on exact parent `6765b139ab53dc07881d9c187243599755df8bdc`.

The packet does not import or mutate `daedalus.spine.effect_boundary`, issue OwnerApproval, consume an EffectLease, open SQLite, invoke Git, create a worktree, merge a branch or promote automatically.

## Exact descriptors

The descriptor tuple is ordered and closed over exactly:

1. `kernel.promotion_execution.open` → `PromotionExecutionLedger.__init__`;
2. `kernel.promotion_execution.begin` → `PromotionExecutionLedger.begin`;
3. `kernel.promotion_execution.complete` → `PromotionExecutionLedger.complete`.

Each descriptor has:

- surface `python`;
- exactly one `filesystem_write` effect;
- exactly one `spine.intent_ledger` guard contract;
- wiring `local_guards`;
- explicit notes that EffectLease, runtime conformance and Docker sandbox composition are still absent.

`central` wiring is rejected by the descriptor contract. This is inventory preparation, not a trust-boundary promotion.

## Import-cycle-free materialization

The descriptor module deliberately does not import the canonical effect boundary. Instead, `materialize_promotion_execution_rows` accepts the canonical `EntrypointSpec` constructor plus surface, effect and wiring mappings from the caller. This allows the next strangler packet to materialize the rows inside `effect_boundary.py` after the enums and contract class exist but before functions bind `ENTRYPOINTS` as their default registry.

The materializer:

- requires the exact descriptor identity and order;
- rejects duplicate or reordered identities;
- rejects incomplete enum mappings;
- returns a new immutable tuple;
- performs no module-level mutation or external effect.

## Adversarial verification prepared

Focused tests cover exact IDs and targets, ordered materialization, canonical enum conversion, deterministic output, duplicate/reordered descriptor refusal, widened effects, changed guards, premature centralization and incomplete mappings.

A separate source review proves that the module neither imports nor mutates the canonical registry and that the materializer is dependency-injected and pure. The bounded mutation campaign attacks premature centralization, effect widening, guard removal, descriptor-set bypass and omission of the effectful ledger constructor.

## Honest remaining boundary

The canonical registry remains unchanged in this packet. A dependent `G0-PRM-25B` packet must materialize the descriptors inside `daedalus.spine.effect_boundary` before registry-default bindings are created, rebuild `REGISTRY_BY_ID`, and prove that gate reporting now sees the three rows as `local_guards` rather than missing.

Even after registration, Gate 0 remains open. The rows cannot become `central` until the persisted EffectLease, exact Runtime Manifest, current RuntimeConformanceReceipt and Docker sandbox are mechanically composed.

Iron Plan: **ALIGNED BY SCOPE**  
Active gate: **Gate 0**  
Canonical registry modification: **not performed**  
Effect centralization: **not claimed**  
Promotion: **not requested**
