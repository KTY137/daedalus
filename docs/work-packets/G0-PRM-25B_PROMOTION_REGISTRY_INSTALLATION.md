# G0-PRM-25B — Promotion Registry Installation

## Scope and exact parent

This Work Packet is stacked directly on the inert descriptor packet:

- parent branch: `g0/promotion-ledger-inventory-linear`;
- parent revision: `ed2d07933326aea57e74c0aebd9a0cd070d0e4d6`;
- parent draft PR: `#143`.

The packet performs one narrow strangler step. It materializes the three exact
promotion-execution descriptors with the canonical types owned by
`daedalus.spine.effect_boundary`, appends them to that module's immutable
registry projection during package initialization, and refreshes only the
historical functions whose defaults captured the prior tuple or mapping.

It does not add a second registry authority, execute an effect, issue an
OwnerApproval, invoke Git, create a worktree, merge a branch, or promote a
candidate.

## Exact installed rows

The canonical registry gains exactly:

- `kernel.promotion_execution.open` →
  `PromotionExecutionLedger.__init__`;
- `kernel.promotion_execution.begin` →
  `PromotionExecutionLedger.begin`;
- `kernel.promotion_execution.complete` →
  `PromotionExecutionLedger.complete`.

Every row remains `local_guards`, declares only `filesystem_write`, and requires
`spine.intent_ledger`. Exact source anchors bind durable Event-Store opening,
the one-start invariant, `record_intent`, and `mark_completed`.

Partial installation, conflicting row material, duplicate canonical IDs, a
registry tuple/mapping disagreement, and an unexpected descriptor identity set
all refuse. Repeating the exact installation is idempotent and repairs only
captured immutable defaults.

## Honest scoped result

The promotion inventory is still open. The prior three `registry.missing`
findings become exact `registry.not_central:local_guards` findings. Together
with the retained `python.promote_candidates` row, the expected scoped blocker
set is exactly:

- `python.promote_candidates`;
- `kernel.promotion_execution.open`;
- `kernel.promotion_execution.begin`;
- `kernel.promotion_execution.complete`.

No row is upgraded to `central`. The next dependent packet must compose the
persisted EffectLease, exact Runtime Manifest, current
RuntimeConformanceReceipt, current kill-switch generation and selected Docker
sandbox before such an upgrade can be considered.

## Adversarial verification definition

The packet adds builder tests and a separate source-level counter-review for:

- exact installed identities, targets, effects, guards, anchors and migration
  statement;
- one canonical tuple and immutable mapping;
- refreshed defaults for `registry_sha256`, `begin_effect` and
  `check_conformance`;
- generic effect-start refusal while the rows remain local;
- partial and conflicting installation refusal;
- inventory transition from missing rows to four local-guard blockers;
- package-initialization ordering before export projection.

A bounded mutation campaign attacks skipped package installation, partial-row
acceptance, identity substitution, anchor removal and stale captured defaults.
The workflow also retains the parent descriptor and promotion-inventory
mutations, the typed manager-wiring regressions, the complete test suite,
packaging, an isolated wheel and Ubuntu/Windows on Python 3.10 and 3.12 with two
hash seeds.

No successful verification is claimed before those commands execute against
the exact branch head. Repository issue `#67` currently causes hosted jobs to
terminate before their first step and without logs. Such runs are infrastructure
observations only; they are not test, mutation, packaging, platform or Gate
evidence.

Iron Plan: **ALIGNED BY SCOPE**  
Active gate: **Gate 0**  
Canonical registry rows: **installed as local guards**  
Gate closure: **not claimed**  
OwnerApproval: **not issued**  
Promotion: **not requested**
