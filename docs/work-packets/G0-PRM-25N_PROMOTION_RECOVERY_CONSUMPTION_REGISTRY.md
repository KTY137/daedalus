# G0-PRM-25N — Promotion Recovery Consumption Registry Integration

## Scope

This packet stacks directly on the reviewed inventory delta at revision
`3bae0f70a2a5964bb91c306d3b43db9ba0cfe3a8`. It performs one narrow strangler
step: the exact recovery-consumption guard, registry rows and scanner hook are
installed in the existing canonical `daedalus.spine.effect_boundary` authority.
It does not centralize either writer, issue an owner decision, cancel an Effect
Lease, invoke Git, mutate a worktree, promote a candidate or close Gate 0.

## Exact canonical delta

The installer adds exactly two ordered rows after the retained promotion rows:

1. `kernel.promotion_recovery_consumption.initialize` targets
   `PromotionRecoveryConsumptionLedger.__init__`, declares one filesystem write,
   has no guard contract and remains `unguarded`. Its anchors bind constructor
   delegation to `_initialize` and schema initialization to `_connect_writer`.
2. `kernel.promotion_recovery_consumption.consume` targets
   `PromotionRecoveryConsumptionLedger.consume`, declares one filesystem write,
   requires the implemented `promotion.owner_recovery_decision` contract and
   remains `local_guards`. Its anchors bind current-decision verification and the
   writer connection.

The constructor is intentionally not relabeled as guarded. The proposed
`promotion.recovery_consumption_store` contract from the sibling descriptor
experiment is not installed because no mechanical implementation exists.

## Scanner integration

The scanner adapter wraps only the canonical private classifier and matches the
exact module, exact class and exactly `__init__` or `consume`. It does not use a
prefix or substring match. `verify_consumption`, `consumed` and other read-only
methods remain excluded. The wrapper retains the existing classifier for every
other target and carries an exact installation marker so conflicting or partial
hooks fail closed.

## Registry consistency

The installer refuses duplicate IDs, partial or conflicting rows, non-suffix
retention, tuple/mapping disagreement, a conflicting guard implementation and a
conflicting scanner hook. After a valid installation it rebuilds the immutable
mapping and refreshes the historical defaults captured by `registry_sha256`,
`begin_effect` and `check_conformance`. Repeating the exact installation is
idempotent.

## Machine-readable report

`inspect_promotion_recovery_consumption_registry` requires a lowercase 40–64
hex source revision and binds it into a canonical report digest. It verifies the
exact rows, guard map and scanner marker. The scoped report remains
`closed=false` with three explicit blockers:

- constructor schema creation is still unguarded;
- consumption is owner-guarded but not inside the persisted Effect-Lease start
  lifecycle;
- Runtime Manifest/ConformanceReceipt, current kill switch and selected Docker
  sandbox are not composed.

This scoped report is integration evidence only; it is not the Gate-0 release
report.

## Adversarial verification prepared

The builder batch covers exact installed rows, guard/default refresh, exact
scanner discovery with a prefix-decoy module, malformed and stale revisions,
non-central bypass refusal, exact idempotency, partial installation and guard
conflict refusal. A separate AST/source review checks authority separation,
exact scanner scope, permanent open status and package initialization order.
Six bounded mutants attack premature centralization, guard removal, scanner
wildcarding, guard-map omission, stale captured defaults and false closure.

The workflow requests Ubuntu and Windows, Python 3.10 and 3.12, two hash seeds,
focused predecessor regressions, Iron Plan verification, mutation, full suite,
package build and isolated-wheel import.

## Honest status

Exact-head executable verification remains pending. Repository GitHub Actions
issue #67 has repeatedly ended hosted jobs before Step 1 with no logs or
artifacts. Such runs are infrastructure observations only and are not accepted
as test, mutation, packaging, platform, fault-matrix or Gate evidence.

No merge, promotion, OwnerApproval, owner recovery-decision issuance, automatic
action or Gate transition is requested.

- Iron Plan: **aligned by scope; exact-head execution required**
- Iron Gate: **0**
- Canonical inventory integration: **implemented; verification pending**
- Effect centralization: **not claimed**
- Promotion: **not requested**
