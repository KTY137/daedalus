# G0-ES-16 — Canonical Event-Store Writer Factory

## Objective

Open selected production Event-Store writers at the Gate-0 durability posture before the canonical `SpineLedger` performs its first generic migration write.

## Authority decision

The schema, transaction, read and write authority remains `daedalus.spine.ledger.SpineLedger`. The public API is `daedalus.spine.open_gate0_spine_writer`.

The factory uses a private, unexported subclass solely for the connection-opening hook that `SpineLedger.__init__` already invokes immediately before `_migrate`. Its override calls `super()._apply_pragmas()` and then changes only the connection-local synchronous mode to `FULL`. It defines no schema, transaction, intent, event, read or write implementation.

This is a narrow strangler seam, not a second Event Store.

## Opening contract

The factory:

1. clamps the writer timeout to at least the canonical minimum;
2. opens the canonical ledger with WAL, foreign keys and `synchronous=FULL` before migration;
3. reads the live connection posture back from SQLite;
4. closes and refuses the writer when the final readback is weaker than required;
5. returns a `SpineLedger`-compatible object using the unchanged canonical schema and transaction paths.

Bare legacy `SpineLedger` construction remains `synchronous=NORMAL` and is not silently upgraded. This preserves compatibility while making Gate-0 admission explicit and reviewable.

## Selected migration

A path-created `AttemptLedger` now obtains its owned Event Store through this factory. Injected `SpineLedger` instances still pass through exact-connection admission. The Attempt lifecycle index remains installed through the same admitted canonical transaction.

## Adversarial batch

Builder tests and a separate counter-review cover:

- synchronous mode observed at entry to the inherited generic migration;
- absence of any extra Gate-0 tables or transaction implementation;
- legacy-default separation;
- timeout clamping and malformed timeout refusal;
- final-readback refusal with connection cleanup;
- public factory/private profile visibility;
- migration of the path-created Attempt writer;
- compatibility with canonical intent and terminal-event transactions.

The mutation runner attacks a NORMAL downgrade, bypass of the opening profile, removal of final readback refusal, removal of the timeout floor and a failure-path connection leak.

## Honest residual boundary

Only the path-created Attempt lifecycle writer has been migrated. All other production `SpineLedger` construction sites remain to be inventoried and moved through the factory or explicitly classified as read-only/legacy. The private opening seam also requires independent architecture review before any release claim.

GitHub Actions issue #67 still blocks exact-head execution, supported-platform evidence, mutation execution, full-suite verification and isolated-wheel checks. Host power-loss testing remains an external fault-harness requirement.

No effect is executed, no OwnerApproval is minted, no checkout is mutated and no merge or promotion is requested.

Iron Plan: **ALIGNED BY SCOPE; WRITER MIGRATION INCOMPLETE**  
Iron Gate: **0**  
Promotion: **not requested**
