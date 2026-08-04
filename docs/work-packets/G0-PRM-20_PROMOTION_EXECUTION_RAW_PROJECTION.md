# G0-PRM-20 — Promotion Execution Raw Projection

## Objective

Harden the `G0-PRM-19` promotion-execution lifecycle against ambiguity and substitution in raw SQLite rows before any persisted start or terminal receipt is trusted. This packet is stacked directly on the Core Event-Spine packet and does not add a second writer, workflow database, owner-decision receipt, Git authority, automatic promotion path, or merge action.

## Read-only projection

`promotion_execution_reader.py` opens the same canonical `SpineLedger` database with `mode=ro` and `PRAGMA query_only=ON`. It retains raw SQLite text long enough to reject:

- duplicate JSON keys and non-finite constants;
- non-ASCII or noncanonical JSON bytes;
- substituted payload digests;
- start events that do not bind the exact payload digest;
- missing, repeated or reordered lifecycle events;
- intent-row and start-event timestamp disagreement;
- malformed terminal detail;
- foreign lifecycle rows using the reserved `promotion.execution:` effect-key prefix.

Resolved rows remain visible to reconciliation. A corrupt terminal event therefore cannot hide merely because ordinary `open_intents()` would omit it.

## Index contract

The Core packet requests one unique partial index over `intents(effect_key)` for rows whose kind is `promotion.execution`. `CREATE ... IF NOT EXISTS` alone is insufficient because a same-named weaker index could already exist. Every security read therefore verifies:

- exact normalized SQL and predicate;
- one unambiguous index identity;
- `unique=1` and `partial=1`;
- explicit user-created origin;
- exactly one indexed column named `effect_key`.

Nonunique, nonpartial, wrong-predicate and wrong-column substitutes fail closed before a lifecycle row can be used.

## Adversarial evidence prepared

The focused tests cover duplicate payload and terminal keys, noncanonical terminal bytes, coherently recomputed duplicate-key payload digests, payload-SHA substitution, broken start-detail binding, non-`INTENDED` first events, detached start timestamps, third events, generic `FAILED` transitions, foreign reserved effect keys and all same-name index substitutions.

Independent AST/source review checks that the Core ledger no longer uses permissive `resolve_by_effect` or `open_intents` hydration for promotion security rows, that the raw reader contains no write statements, and that index verification precedes row selection.

A dedicated bounded mutation campaign attacks duplicate-key refusal, canonical-byte equality, payload-digest verification, event count and ordering, start-event binding, terminal-detail shape, index verification, SQL-shape verification, uniqueness and read-only database mode.

## Deliberate remaining boundary

This packet still does not wire the live `promote_candidates` mutation seam. The next dependent packet must measure the primary-checkout fingerprint itself, register the execution entrypoints in the canonical effect inventory, persist a start immediately before the first live mutation and retain either an exact terminal receipt or a visible pending-reconciliation record.

Gate 0 remains open. No OwnerApproval is created, no branch is merged and no candidate is promoted.

## Verification status

All executable tests, mutation runners, full-suite checks and isolated-wheel checks are prepared on the branch. They become evidence only after execution on the exact branch head. Repository Actions issue #67 currently prevents jobs from reaching Step 1; a zero-step failure is an infrastructure observation, not verification.

Iron Plan: **ALIGNED BY SCOPE**  
Active gate: **Gate 0**  
Promotion: **not requested**
