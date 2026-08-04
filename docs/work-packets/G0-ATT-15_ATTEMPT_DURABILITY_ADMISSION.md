# G0-ATT-15 — Attempt Event-Store Durability Admission

## Objective

Bind the selected persisted isolated-Attempt lifecycle to the canonical Gate-0 Event-Store durability profile without introducing another database, ledger, schema authority or lifecycle facade.

## Selected authority

`AttemptLedger` continues to write through the existing `SpineLedger`. Construction now requires the exact active writer connection to satisfy:

- WAL journal mode;
- `synchronous=FULL` readback;
- at least the canonical busy timeout;
- foreign-key enforcement.

The resulting `Gate0DurabilityStatus` is retained on the lifecycle facade as machine-readable admission evidence.

## Second-writer removal

The predecessor installed `idx_attempt_lifecycle_effect_key` by opening a separate SQLite writer connection. SQLite durability pragmas are connection-local, so that connection could silently remain at `synchronous=NORMAL` even when the lifecycle connection had been hardened.

The index is now installed through the exact admitted `SpineLedger._txn()` seam. Durability admission occurs before this schema write. A durability refusal leaves the Attempt-specific index absent.

## Adversarial specification

Focused tests require:

1. exact connection readback at FULL;
2. hardening of an injected legacy writer before Attempt schema installation;
3. no second `sqlite3.connect()` during Attempt admission;
4. refusal before index creation when durability admission fails;
5. read-only refusal without Attempt schema mutation;
6. source ordering from durability admission to canonical transaction use.

The bounded mutation campaign attacks:

- removal of durability admission;
- restoration of the second writer connection;
- installation of the Attempt index before durability admission.

Every mutant must be killed after a green focused baseline and the source bytes must be restored exactly.

## Honest residual boundary

This packet does not close the complete Event-Store migration. When `AttemptLedger` receives a filesystem path, the legacy `SpineLedger` constructor still performs its generic schema initialization under the repository-wide `synchronous=NORMAL` default before the Attempt facade applies FULL. The Attempt-specific index and all Attempt lifecycle records are admitted, but a later canonical Gate-0 writer factory must select FULL before every production initialization write.

Other Event-Store writers remain outside this packet and must be inventoried and migrated separately. Host power-cut evidence, exact-head CI, supported platform execution, isolated-wheel verification and independent review also remain open.

No Attempt is executed, no Effect Lease is consumed, no OwnerApproval is issued, no checkout is mutated and no promotion is requested.

Iron Plan: **ALIGNED BY SCOPE; GLOBAL WRITER FACTORY AND EXECUTION OPEN**  
Iron Gate: **0**  
Promotion: **not requested**
