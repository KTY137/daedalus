# G0-PRM-25M — Promotion Recovery Consumption Effect Row Descriptors

## Scope

This packet inventories the two filesystem-writing Python surfaces introduced by
`PromotionRecoveryConsumptionLedger`:

- `kernel.promotion_recovery_consumption.open` binds the constructor and durable
  store initialization;
- `kernel.promotion_recovery_consumption.consume` binds authenticated one-use
  decision consumption.

The descriptors are inert. They do not import or mutate the canonical effect
registry, add a guard contract to the policy map, open a database, authenticate a
decision, cancel an Effect Lease, invoke Git, merge, promote or issue owner
authority.

## Exact local contracts

The open row requires `promotion.recovery_consumption_store`. Its anchors bind
the constructor to `_initialize` and initialization to `_connect_writer`.

The consume row requires both
`promotion.owner_recovery_decision` and
`promotion.recovery_consumption_store`. Its anchors bind the public consumption
method to fresh `verify_promotion_recovery_decision` projection and to the
writer connection used for `BEGIN IMMEDIATE`.

Both rows:

- use the Python surface;
- declare only `filesystem_write`;
- remain `local_guards`;
- carry no runtime, sandbox, Effect-Lease or central-wiring claim.

These two guard-contract names are intentionally not installed by this packet.
The dependent registry-installation packet must add them to the canonical
implemented-contract map and install the rows in one ordered, reviewable change.
Until then the descriptors are preparation, not production conformance.

## Pure materialization

`materialize_promotion_recovery_consumption_rows(...)` accepts the canonical
`EntrypointSpec`, `GuardAnchor`, surface/effect/wiring mappings by dependency
injection. It returns fresh immutable rows and has no registry parameter or
mutation path. Identity order, exact targets, guards, anchors, effects and
non-central wiring are checked before materialization and once at module import.

## Adversarial review correction

A separate source review found that the first draft checked anchor shape and
uniqueness but did not prove that a caller-supplied typed descriptor retained the
exact anchor tuple for its identity. Such a descriptor could have materialized a
valid-looking row with a substituted local guard callsite. The descriptor now
compares its anchor tuple against identity-specific constants. Behavior tests
cover non-empty and reordered substitutions, the source review recognizes full
`ImportFrom` module paths, and the mutation campaign attacks removal of the exact
anchor equality check.

## Adversarial batch

Prepared checks cover:

- exact two-row identity, target, effect, guard and anchor subjects;
- deterministic pure materialization through injected canonical stand-ins;
- reordered, duplicated and partial descriptor refusal;
- target, surface, effect, guard, wiring and typed-valid anchor substitution;
- incomplete canonical enum mappings and untyped factories;
- independent import-aware AST/source review proving no canonical registry
  import, update, effect start, persistence or recovery writer authority;
- six bounded mutants attacking premature centralization, effect widening,
  owner-guard substitution, exact-set bypass, anchor omission and exact-anchor
  substitution acceptance;
- focused parent-regression, full-suite, package, isolated-wheel,
  Ubuntu/Windows, Python 3.10/3.12 and two-hash-seed jobs.

Exact-head executable verification is pending. Repository issue #67 still ends
hosted Actions jobs before Step 1 with no logs; those runs are not test,
mutation, package, platform or Gate evidence.

## Remaining boundary

A dependent packet must install these exact descriptors, add the two exact
implemented guard contracts, refresh captured registry defaults and prove the
machine-readable inventory reports both rows honestly as `local_guards`.
Cancellation authority remains a separate later packet and must verify the
persisted consumption plus a fresh cross-ledger projection immediately before
terminalizing the exact retained effect start.

No OwnerApproval, owner recovery decision, merge, promotion or Gate transition
is requested.
