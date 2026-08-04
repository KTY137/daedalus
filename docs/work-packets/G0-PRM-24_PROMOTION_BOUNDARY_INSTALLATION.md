# G0-PRM-24 — Promotion Boundary Installation

## Scope

This Work Packet installs the already reviewed promotion-manager audit and
restart-validation stranglers in the live sealed promotion module and adds the
three missing promotion-execution Event-Store surfaces to the canonical effect
inventory. It does not issue OwnerApproval, consume an EffectLease, execute Git,
create a worktree, promote a candidate, merge a branch, or claim Gate-0 closure.

The packet is stacked directly on `G0-PRM-23` at exact parent
`0a676cc6f3944c564acc0a42a9a844b9eeb43a49`.

## Live typed installation

After the sealed `promote_candidates` callable is defined, the module installs:

1. `install_promotion_manager_boundary(globals())`;
2. `install_promotion_manager_replay_boundary(globals())`.

The first installer preserves the canonical `PromotionExecutionLedger` class
and wraps only an already type-admitted ledger instance for one call. The
second selects the strict replay-validating proxy. Import therefore cannot
launder an arbitrary object through the sealed callable's `isinstance` guard
and does not create another Event Store.

Both installer names are deleted from the live module after installation. The
installed state remains private and mechanically inspectable for review and
restart validation.

## Canonical inventory strangler

A narrow `daedalus.spine.promotion_effect_rows` adapter installs exactly three
rows during `daedalus.spine` package initialization:

- `kernel.promotion_execution.open`, bound to the durable Event-Store open and
  unique-start invariant in `PromotionExecutionLedger.__init__`;
- `kernel.promotion_execution.begin`, bound to the canonical `record_intent`
  write;
- `kernel.promotion_execution.complete`, bound to the canonical
  `mark_completed` terminal write.

All rows declare only `filesystem_write`, require `spine.intent_ledger`, and
remain `local_guards`. The adapter refreshes the immutable registry tuple,
registry mapping, and legacy functions' captured default registry objects
before normal callers can observe the package. Duplicate, partial, or
contradictory installation refuses.

This is intentionally a strangler rather than a broad edit of the historical
registry module. Existing import paths remain valid and there is still one
canonical registry authority.

## Honest blocker reduction

The scoped promotion inventory should now contain exactly four blockers:

- `python.promote_candidates: registry.not_central:local_guards`;
- `kernel.promotion_execution.open: registry.not_central:local_guards`;
- `kernel.promotion_execution.begin: registry.not_central:local_guards`;
- `kernel.promotion_execution.complete: registry.not_central:local_guards`.

The previous missing-row and missing-installer blockers are resolved. None of
the four rows may become `central` until a later packet mechanically composes
the persisted EffectLease, exact Runtime Manifest, current
RuntimeConformanceReceipt, kill-switch authority, and selected Docker sandbox
around the actual repository effect.

## Adversarial verification specification

The batch includes:

- behavioral installation and exact-registry tests;
- a separate source-level counter-review;
- malformed repository and stale-revision refusal tests;
- proof that generic `begin_effect` still refuses all local rows;
- six bounded source mutations covering missing or reordered installers,
  premature centralization, stale captured registry defaults, and partial
  registry installation;
- parent promotion-manager and inventory regressions;
- full-suite and isolated-wheel checks;
- Ubuntu and Windows, Python 3.10 and 3.12, and two deterministic hash seeds.

No result is claimed until the exact branch head executes. Repository Actions
issue #67 has repeatedly terminated jobs before Step 1 with no logs. Such runs
are infrastructure observations only and are not treated as tests, mutation
evidence, platform evidence, packaging evidence, or a product-code verdict.

## Remaining dependent work

The next promotion packet must compose the persisted EffectLease, current
runtime-conformance authority and Docker sandbox with the sealed live operation
before changing any row to `central`. Other production entrypoints, fault
campaigns, exact-head release evidence, and independent human review also remain
required before Gate 0 can report `closed=true`.

Iron Plan: **ALIGNED BY SCOPE**  
Active gate: **Gate 0**  
Production centralization: **not claimed**  
OwnerApproval: **not issued**  
Promotion: **not requested**
