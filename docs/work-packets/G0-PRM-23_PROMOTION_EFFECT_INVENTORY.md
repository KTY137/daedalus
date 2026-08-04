# G0-PRM-23 — Promotion Effect Inventory

## Scope

This packet adds a read-only, revision-bound projection of the exact promotion-related rows that Gate 0 still requires in the canonical effect registry. It does not modify the live promotion path, issue OwnerApproval, consume an EffectLease, invoke Git, create a worktree, merge a branch, or promote automatically.

The packet is stacked on exact parent `3deec36a260994cdf3c498ce36be2077c7f645f1` and includes the typed manager-audit correction carried on the dependent line.

## Required production boundaries

The inventory requires exactly four rows:

1. `python.promote_candidates` bound to the public sealed promotion callable with filesystem-write, process-spawn and repository-mutation effects plus the intent-ledger, worktree-containment and owner-approval guards;
2. `kernel.promotion_execution.open` bound to `PromotionExecutionLedger.__init__`, which opens a writable canonical Event Store, enforces durability and installs the promotion uniqueness index;
3. `kernel.promotion_execution.begin` bound to `PromotionExecutionLedger.begin` and its canonical Event-Store intent write;
4. `kernel.promotion_execution.complete` bound to `PromotionExecutionLedger.complete` and its canonical Event-Store terminal write.

The initial three-row draft omitted the constructor even though it can create or modify the SQLite store before `begin` is called. Adversarial review therefore added the open row rather than treating construction as inert setup.

A row is accepted only when its ID, target, ordered effect tuple, ordered guard tuple and `central` wiring match exactly. Duplicate IDs refuse the report before projection.

## Source binding

The report binds the exact source bytes for the public promotion module and promotion-execution ledger. It requires:

- the live public module to install both the manager-audit and restart-replay boundaries;
- `PromotionExecutionLedger.__init__` to retain `open_gate0_spine_writer` and `_install_single_start_invariant`;
- `begin` to retain the canonical `record_intent` call;
- `complete` to retain the canonical `mark_completed` call.

Missing files, path escape, symlinks, non-regular files, oversized files, non-UTF-8 source and syntax errors fail closed. The report digest covers the exact source revision, canonical registry digest, findings, source digests and derived closed state.

## Honest current result

The current branch is expected to remain open. The inventory should report:

- `python.promote_candidates` is still `local_guards`;
- the manager-audit installer is not yet invoked by the public promotion module;
- the restart-replay installer is not yet invoked by the public promotion module;
- `kernel.promotion_execution.open` has no canonical registry row;
- `kernel.promotion_execution.begin` has no canonical registry row;
- `kernel.promotion_execution.complete` has no canonical registry row.

This packet therefore prevents implemented modules, constructor side effects or unit tests from being mistaken for production wiring.

## Adversarial verification

Prepared checks cover current blocker projection, an exact synthetic closed configuration, target/effect/guard substitution, duplicate registry identities, removed constructor/begin source anchors, malformed revisions, missing repositories, deterministic rebuild, stale-revision verification and stdout-only CLI behavior.

The bounded mutation runner attacks:

1. acceptance of non-central wiring;
2. omission of missing registry rows;
3. omission of guard mismatches;
4. omission of source-anchor failures;
5. omission of the effectful ledger-open requirement;
6. forced `closed=true`.

A separate counter-review requires all four rows and all constructor/start/terminal anchors. The dedicated workflow requests Python 3.10 and 3.12 on Ubuntu and Windows with deterministic hash seeds, the focused suite, manager regression and mutation campaigns, full suite and isolated-wheel import.

## Remaining dependent work

A later narrow packet must install the two manager boundaries in the live promotion module and register open/begin/complete without yet claiming centralization. A subsequent packet must compose the persisted EffectLease, Runtime Manifest, current RuntimeConformanceReceipt and Docker sandbox before any promotion row can honestly become `central`.

Gate 0 remains open. No owner capability is created, no repository effect is executed and no promotion or merge is requested.
