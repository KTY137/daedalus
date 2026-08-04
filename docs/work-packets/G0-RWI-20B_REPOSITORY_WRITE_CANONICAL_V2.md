# G0-RWI-20B — Canonical Repository Write Inventory Generation 2

## Scope

This packet stacks on exact parent `f78e4c53fb5ac21d90a34a2fe6cd8f6da679ab14`. It introduces an additive generation-2 strangler that composes the retained generation-1 repository-write inventory with the separately reviewed stdlib delta. The generation-1 import path and behavior remain unchanged.

The packet does not classify any finding as Primary-Checkout-safe, guarded, central, or trusted. It does not execute a filesystem or process effect, issue OwnerApproval, create a PromotionReceipt, merge, promote, or claim Gate-0 closure.

## Stable composition fence

`scan_repository_write_surfaces_v2(...)` performs a base scan, the stdlib-delta scan, and a second base scan. It refuses unless all three projections bind the same source revision, base inventory digest, production-byte digest, and production-file count. It also rejects any source position emitted by both components.

The resulting report is schema `daedalus-gate0-repository-write-inventory/2`. It records both component digests, preserves each finding origin, and reports `canonical_scanner_integrated=true`. The report remains inventory-only and reports `closed=true` only when the combined scanner finds no blocking surface at all.

## Prepared adversarial batch

The batch includes behavior tests for base/delta composition, malformed revisions, cross-scan byte drift, cross-component overlap, deterministic hashing, CLI closure assertions, and an empty-surface control. A separate source review checks authority separation, exact scan order, revision/digest/byte/file-set binding, and the absence of target or guard claims. A bounded mutation campaign attacks each composition fence and false closure.

CI requests Ubuntu and Windows on Python 3.10 and 3.12 with two hash seeds, predecessor regressions, mutation, full-suite execution, package build, and isolated-wheel import.

## Honest remaining boundary

This packet integrates discovery only. Every production finding still requires revision-bound target classification and a concrete guard contract or retirement. The generation-2 digest is not yet a GateReport-v2 release input. Exact-head executable evidence remains pending while repository Actions issue #67 terminates jobs before Step 1 with no logs or artifacts.

No automatic merge or promotion is requested.
