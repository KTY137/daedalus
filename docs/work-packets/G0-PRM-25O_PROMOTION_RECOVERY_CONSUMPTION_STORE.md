# G0-PRM-25O — Pre-provisioned Promotion Recovery Consumption Store

## Scope

This Work Packet stacks directly on the exact head of PR #163 and separates recovery-consumption schema publication from ordinary ledger construction. It is an additive strangler packet. It does not replace the historical constructor, migrate a production caller, modify the canonical effect registry, issue or consume a new owner decision, cancel or terminalize an Effect Lease, invoke Git, mutate a checkout, merge, promote, or claim Gate-0 closure.

## Explicit store publication

`initialize_promotion_recovery_consumption_store(path)` is the only new publication authority. The parent directory must already exist, must resolve to the same lexical path, and may not be traversed through a symlink. The target must be absent.

The initializer builds the exact schema in a same-directory temporary regular file, applies `synchronous=FULL`, verifies integrity and the complete schema contract, flushes the file, and publishes it with a hard link. It then flushes the published file and, on supported non-Windows hosts, the parent directory entry before returning. Publication therefore refuses rather than replacing an existing target. The temporary name is removed after publication or failure.

Post-publication cleanup is bound to the exact published device/inode. If a later file or directory durability check fails, the initializer unlinks only its own published file and best-effort flushes the cleanup directory entry. A foreign regular file or symlink substituted at the target is preserved instead of being deleted.

The initializer is deliberately not represented as centrally leased production wiring in this packet. Its effect-entrypoint registration and Effect-Lease/runtime/sandbox composition require a later reviewable batch.

## Existing-store-only ledger

`PreprovisionedPromotionRecoveryConsumptionLedger` subclasses the retained ledger so the established consume and read-verification behavior remains available without copying the lifecycle algorithm. Its constructor does not call the historical constructor, create a directory, open SQLite, or execute `_initialize()`.

Admission requires a strict read-only projection of an already initialized regular non-symlink file. The projection binds:

- resolved path and concrete device/inode identity;
- normalized exact table SQL and schema version;
- exact ordered columns, all-column `NOT NULL`, and absence of defaults;
- exact primary-key contract;
- exact unique-index columns, origins, and non-partial state;
- canonical schema digest.

Every subsequent read or write open rechecks that identity and schema. Writer opening uses SQLite URI `mode=rw`; a missing store cannot be created. Read opening uses `mode=ro` with `query_only` confirmed. Pre-open store failures are normalized to the ledger's `PromotionRecoveryConsumptionStateError` boundary rather than leaking a lower-level store exception. No alternate table, database, receipt type, owner-decision issuer, cancellation writer, Git seam, or promotion seam is introduced.

## Adversarial batch prepared

Behavior tests cover malformed non-path inputs, pathless names, explicit initialization, deterministic inspection, normal open, missing-store noncreation, missing-parent noncreation, existing-target preservation, one-use and concurrent publication, malformed and nullable schema drift, post-admission deletion, concrete-file substitution, parent-directory durability invocation and failure rollback, own-publication cleanup, preservation of a racing foreign replacement, read-only inspection, and parent/file symlink redirection.

A separate AST/source review checks authority separation, constructor noninitialization, existing-store-only writer mode and error normalization, query-only inspection, normalized SQL/nullability/default/index verification, publication ordering, file-before-directory durability, no-clobber hard-link use, identity-guarded cleanup, additive compatibility, absence of canonical registry mutation, and signatures without callback or keyword authority smuggling.

Eleven bounded mutants attack normal-open creation, existing-target refusal, target replacement, identity substitution, table-SQL drift, nullability drift, unique-index drift, deletion of a foreign replacement, omitted parent-directory publication durability, removal of explicit pre-open inspection, and leakage of store errors through the ledger boundary. The requested workflow covers Ubuntu and Windows, Python 3.10 and 3.12, two hash seeds, predecessor regressions, Iron Plan, mutation, the full suite, package build, and isolated-wheel import.

## Honest remaining boundary

The historical `PromotionRecoveryConsumptionLedger.__init__` remains unchanged, registered as unguarded, and still creates its parent and schema. No production caller uses the pre-provisioned subclass yet. The explicit initializer and pre-provisioned consumption path are not registered in the canonical effect inventory and are not composed with persisted Effect Leases, Runtime Manifests, current Runtime Conformance Receipts, kill-switch state, or Docker sandbox authority.

A dependent packet must register the new initializer honestly without claiming centralization, then migrate callers one by one before retiring or inventory-demoting the historical auto-initializing path. Consumption must still be upgraded from its local owner-decision guard to the canonical effect lifecycle. Cancellation, promotion-pending forensics, promotion caller migration, historical public bypass retirement, exact-head fault injection, independent human review, and all other release-report blockers remain open.

Exact-head executable verification is pending. On head `34f68ca39293f672bb981d3c2156a508dd2be42d`, workflow run `30899081454` and Iron Plan run `30899081867` ended every job before Step 1 with `steps=null`, no logs, and no artifacts. This is the repository infrastructure failure tracked in issue #67. Such zero-step runs are observations only and are not accepted as test, mutation, packaging, platform, fault-matrix, or Gate evidence.

No OwnerApproval, owner recovery decision, Effect-Lease transition, merge, promotion, automatic action, or Gate transition is requested.

Iron Plan: **ALIGNED BY SCOPE; EXACT-HEAD EXECUTION REQUIRED**  
Iron Gate: **0**  
Promotion: **not requested**
