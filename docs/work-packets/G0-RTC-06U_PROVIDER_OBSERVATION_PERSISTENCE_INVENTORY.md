# G0-RTC-06U — Provider Observation Persistence Inventory Delta

## Exact parent and purpose

This packet stacks directly on `g0/provider-observation-authority-linear` at
`1449f1a0a802171b173bf0ab130b2713d515d22b`. It addresses the discovery portion
of issue #189 without modifying the provider-observation runtime or claiming
that any persistence path is guarded.

The provider-observation binding ledger currently has effectful behavior in its
constructor, connection helper, schema initializer, fresh-start binding path,
nominal read path, replay path and recovery path. A ledger that authenticates
another effect cannot remain invisible merely because its writes are internal
infrastructure.

## Revision-bound fail-closed delta

`scan_provider_observation_persistence(...)` reads only the fixed production
source `daedalus/runtimes/provider_observation.py`, rejects a symlinked source,
binds the exact source bytes and caller-supplied lowercase commit revision, and
requires exactly one occurrence of every known mutation anchor. Missing or
duplicated anchors refuse instead of silently reducing the inventory.

The eleven retained rows cover:

- implicit constructor bootstrap;
- default SQLite read-write-create connection;
- parent-directory creation;
- schema creation;
- fresh-binding connection, writer transaction, rollback, insert and commit;
- a nominal `load` path that can create an empty SQLite file;
- replay and recovery through `require_bound`, which transitively inherit that
  create-capable read path.

Every row is emitted as `inventory_only`, `blocking=true`, without a guard
contract and without Primary-Checkout target proof. The report hard-codes
`closed=false`, `canonical_inventory_integrated=false`,
`guard_contracts_complete=false`, and
`primary_checkout_mutation_excluded=false`.

## Prepared adversarial verification

Builder tests cover the exact production source, deterministic content-addressed
reporting, all eleven path labels, malformed revisions, missing/non-UTF-8/invalid
sources, missing and duplicate anchors, source-byte drift, symlink refusal and
machine CLI exit semantics. A separate AST review proves the scanner itself has
read-only discovery authority and cannot claim closure, guarding, canonical
integration or checkout exclusion. Six bounded mutants attack false closure,
false integration, false guarding, rollback/recovery-anchor removal and symlink
acceptance.

CI requests Ubuntu and Windows on Python 3.10 and 3.12 with two hash seeds,
focused tests, mutation, predecessor provider-observation regressions, the full
suite, package build and isolated-wheel import.

## Remaining implementation boundary

This packet is not canonical registration and does not close issue #189. The
next dependent work must separate read-only opening from explicit bootstrap,
move persistence behind exact effect authority, bind targets to isolated
workspaces, compose the rows into the canonical inventory, and execute the full
SQLite/filesystem fault matrix. Nominal recovery reads must not create or repair
a missing database.

No source inspection or LLM statement is hard evidence. Exact-head execution
remains unavailable while GitHub Actions issue #67 terminates jobs before Step 1
without logs or artifacts. No merge, promotion, OwnerApproval, PromotionReceipt
or Gate transition is authorized.
