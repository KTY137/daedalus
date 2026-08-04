# G0-PRM-25P — Promotion Recovery Consumption Store Inventory Delta

## Scope

This packet stacks directly on exact parent `27e8527c1eb811399f8d7ed2d60321ac37db1e9c` from PR #164. It is deliberately preparatory and inert. It does not initialize a store, consume an owner recovery decision, cancel or terminalize an Effect Lease, invoke Git, mutate a checkout, merge, promote, or modify the canonical effect registry.

## Exact inventory delta

The packet declares exactly one newly introduced filesystem-writing production surface:

- `kernel.promotion_recovery_consumption_store.initialize` → `daedalus.kernel.promotion_recovery_consumption_store:initialize_promotion_recovery_consumption_store`.

The row is Python, declares only `filesystem_write`, has no fabricated guard contract, and remains explicitly `unguarded`. Exact source anchors bind same-directory temporary-file creation, SQLite schema construction, no-clobber hard-link publication, file durability and parent-directory durability.

## Exact scanner contract

The proposed static-scanner hook matches only module `daedalus.kernel.promotion_recovery_consumption_store` and function `initialize_promotion_recovery_consumption_store`. Prefix modules, suffixed functions and the read-only inspector are excluded. The canonical scanner is not changed in this packet.

## Adversarial batch prepared

Builder tests cover canonical hashing, the exact row, exact anchors, malformed near-misses and the current registry/scanner gap. A separate source review checks that the inventory module imports no effect or registry authority, cannot install rows, cannot execute initialization, cannot claim centrality or closure, retains the full blocker set and uses exact scanner equality. Seven bounded mutants attack false registry/scanner integration, hidden unguarded status, fabricated guards, removed effects, wildcard scanner matching and blocker removal.

The workflow requests Ubuntu and Windows, Python 3.10 and 3.12, two hash seeds, focused predecessor regressions, Iron Plan verification, mutation, full suite, package build and isolated-wheel import.

## Honest remaining boundary

A dependent packet must perform a normal reviewed integration of the exact row and scanner hook. The initializer will still remain a Gate-0 blocker until it is composed with a persisted Effect Lease, current RuntimeConformanceReceipt, kill-switch state and Docker sandbox. Production callers must then migrate one at a time to the pre-provisioned ledger before the historical auto-initializing constructor can be retired or inventory-demoted.

Exact-head executable verification remains pending because repository GitHub Actions issue #67 continues to end hosted jobs before Step 1 with no logs or artifacts. Zero-step runs are infrastructure observations only and are not accepted as test, mutation, packaging, platform, fault-matrix, Iron Plan or Gate evidence.

No OwnerApproval, owner recovery decision, Effect-Lease transition, merge, promotion, automatic action or Gate transition is requested.

Iron Plan: **ALIGNED BY SCOPE; EXACT-HEAD EXECUTION REQUIRED**  
Iron Gate: **0**  
Promotion: **not requested**
