# G0-RTC-06V — Pre-provisioned Provider Observation Binding Store

## Exact parent and boundary

This packet stacks on exact revision `8c3429119a6eeffdf81ef553aa3886ee73477e44` from `g0/provider-observation-persistence-inventory-linear`. It addresses only the explicit-store foundation identified by issue #189. It does not modify `main` or `experimental`, register a canonical effect entrypoint, migrate the runtime broker, issue OwnerApproval, merge, promote, or change a Gate state.

The historical `ProviderObservationBindingLedger` remains available without a rename. The new `PreprovisionedProviderObservationBindingLedger` is an additive strangler that reuses the retained authority, row-authentication and binding algorithm while refusing implicit initialization and repair.

## Store subject and isolation

`ProviderObservationStoreTarget` binds the absolute database path, one isolated attempt root, the Primary-Checkout root and one exact source revision. The attempt and Primary-Checkout roots must be existing real directories and must be disjoint. The target parent must already exist below the attempt root. Symlink traversal, path redirection, non-regular targets and hard-link aliases refuse.

The initialized SQLite database contains an exact metadata row binding the target digest, source revision and schema digest. Reopening the same bytes through a stale revision or a different target subject therefore refuses rather than relabeling the store.

## Explicit publication and normal operation

`initialize_provider_observation_binding_store(...)` creates the exact schema in a same-directory temporary file, verifies it, flushes it, publishes it through a no-clobber hard link, removes the temporary alias, flushes the published file and directory, and then reopens it read-only for final verification. Failure cleanup removes the target only when it is still the exact inode published by this call.

Ordinary construction requires the exact pre-existing store. Writer connections use SQLite URI `mode=rw`; replay/load connections use `mode=ro` with `PRAGMA query_only=ON`. Missing stores are never recreated. Pre-existing journal, WAL or shared-memory sidecars refuse rather than being adopted as an unverified state extension.

## Adversarial corrections

The initial implementation exposed two defects during counter-review:

1. Final inspection ran while the temporary hard-link alias still existed, contradicting the single-link invariant. The temporary alias is now removed before inspection.
2. The first schema authenticated shape but did not persist the revision-and-target subject. An exact metadata table now binds `target_sha256`, `source_revision` and `schema_sha256`; stale subject substitution fails closed.

A further review fence rejects hard-link aliases and pre-existing SQLite sidecars.

## Prepared verification

Builder coverage exercises initialization, exact inspection, no-clobber behavior, missing-store noncreation, pre-existing-parent requirements, Primary-Checkout overlap, stale revision metadata, malformed schema, symlink and hard-link redirection, SQLite sidecars, admitted-inode replacement, authenticated bind/replay, read-only replay opening, deletion without recreation, and post-publication cleanup.

A separate AST/source review checks absence of provider/effect/promotion authority, constructor noninitialization, exact `ro`/`rw` connection modes, read-only replay routing, no-clobber publication order, schema-writer isolation, revision metadata binding, Primary-Checkout fences, sidecar refusal and identity-bound cleanup. Eleven bounded mutants target the principal isolation, metadata, open-mode, replay and publication bypasses.

Ubuntu and Windows on Python 3.10 and 3.12 with two hash seeds, focused predecessor regressions, mutation, full-suite, package build and isolated-wheel import are requested. These commands are prepared, not represented as executed evidence. GitHub Actions issue #67 currently stops hosted jobs before checkout/Step 1 with no logs or artifacts.

## Remaining dependent work

This packet does not close issue #189. A dependent packet must register bootstrap and durable binding as exact guarded effect entrypoints, compose persisted Effect-Lease, Runtime Manifest, RuntimeConformanceReceipt, kill-switch and Docker-sandbox authority, migrate the broker and recovery path one caller at a time, retire the auto-initializing compatibility path, integrate the canonical inventory, and execute the complete open/begin/select/insert/commit/rollback/close fault matrix. Gate 0 remains open.
