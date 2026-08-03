# G0-ES-14 — Canonical Event Store Durability Profile

## Purpose

Gate 0 requires intent-before-effect ordering, restart/replay safety and a green
fault matrix. The canonical `SpineLedger` already owns the single Event Store,
uses WAL, commits intents before returning and preserves append-only terminal
events. Its legacy default connection profile is nevertheless
`synchronous=NORMAL`, which is insufficient for a Gate-0 power-loss durability
claim.

This packet adds a **connection-local Gate-0 durability profile** for the exact
existing `SpineLedger`. It does not add a table, database, event type, state
machine or alternate ledger implementation.

## Profile

`enforce_gate0_durability(ledger)`:

1. requires an existing writable `SpineLedger` instance;
2. refuses a non-WAL Event Store instead of silently changing persistent file
   state;
3. applies `PRAGMA synchronous=FULL` to the exact active writer connection;
4. applies at least the canonical 30-second busy timeout;
5. reapplies foreign-key enforcement;
6. reads all settings back from SQLite;
7. returns a deterministic machine-readable status only when the complete
   readback satisfies the profile.

The function returns the same authority; it does not open a second database or
return a new ledger. `inspect_gate0_durability` is read-only and reports
`satisfied=false` for the legacy `NORMAL` profile rather than upgrading the
claim.

## Honest connection semantics

SQLite `synchronous` is connection-local. Closing a hardened writer and opening
a new bare `SpineLedger` therefore returns to the legacy `NORMAL` profile. Tests
make this explicit: every production writer connection must apply and verify the
profile. The packet does not pretend that one successful call globally upgrades
all future writers.

This is a strangler seam. A later packet must route every Gate-0 production
Event-Store writer through one canonical factory/profile application and make
the canonical Gate report enumerate any writer that does not do so.

## Fault and adversarial coverage

The packet defines executable tests for:

- legacy `NORMAL` posture reporting `satisfied=false`;
- hardening the exact existing connection without adding tables or stores;
- idempotent profile application and stable machine readback;
- explicit profile application on every newly opened writer connection;
- read-only inspection without mutation and refusal as a writer;
- non-WAL refusal without silent persistent journal migration;
- refusal when SQLite readback remains weaker than requested;
- abrupt `os._exit` after a FULL-profile committed intent, followed by restart,
  unresolved-intent recovery and `integrity_check`.

The bounded mutation runner attacks FULL→NORMAL downgrade, read-only writer
acceptance, silent WAL rewriting, busy-timeout removal, foreign-key disablement,
weakened satisfaction logic and skipped post-apply readback.

## Limits and blockers

This packet is intentionally **partial**:

- it does not change the broad legacy `SpineLedger` default because that would
  require a separately executable compatibility and performance review;
- no canonical writer factory yet enforces the profile for every production
  Event-Store connection;
- PR #115 does not yet consume this profile;
- a killed process is tested, but a host power cut or storage-cache-loss harness
  is still open; FULL readback is configuration evidence, not a physical power
  interruption experiment;
- GitHub Actions issue #67 prevents exact-head execution, mutation, packaging and
  platform evidence;
- independent review remains open.

The machine-readable companion
`G0-ES-14_EVENT_STORE_DURABILITY.json` records the fault matrix and blockers. No
Gate-0 durability boundary is claimed while its `status` remains `partial`.

Iron Plan: **ALIGNED BY SCOPE; MIGRATION AND EXECUTION OPEN**  
Iron Gate: **0**  
Promotion: **not requested**
