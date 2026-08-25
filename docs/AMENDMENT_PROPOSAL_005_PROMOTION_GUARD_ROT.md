# Amendment proposal 005 — the promotion guard lost its subject

Status: **MOOT — never approved, subject retired.** Proposed 2026-08-17 by
Athena (coordinator) against `tools/iron_plan_guard.py`, deleted in the
2026-08-22 guard retirement before the amendment protocol was invoked.
Affected invariants claimed: 5 (sealed promotion), 10 (no silent constitution
change).

## What it found

The guard's two sealed-promotion static checks both inspected
`daedalus/kairos/gated_writes.py` for an `AUTO_PROMOTE_LEVELS = ("never",)`
literal and a `run_write_wave` function that must not call
`promote_candidates`. After that module was refactored into a
retained-source strangler (implementation `exec()`'d from a git-blob-pinned
`.src` file), neither symbol was visible to static AST analysis: the first
check failed permanently (true positive on staleness, not on an unsealed
promotion — verified `AUTO_PROMOTE_LEVELS` still held `("never",)` at
runtime inside the retained blob), and the second passed vacuously because
`run_write_wave` no longer existed as a parseable function to inspect.
Meanwhile real promotion authority had moved to
`daedalus/kernel/promotion.py` (`authorize_promotion`,
`authorize_persisted_promotion`), which no guard check inspected at all.

Proposed fix: re-point both checks at `daedalus/kernel/promotion.py`, asserting
the two authorization entrypoints exist and that
`authorize_persisted_promotion` still requires a `consumed_approval`
parameter — asserting presence before asserting behavior, so a rename could
not turn the check vacuous again. Rejected alternatives: deleting the checks
(removes the only mechanical statement that promotion requires owner
approval); redeclaring the constant in the outer module (creates two sources
of truth for one policy value, worse than a red guard); having the guard
`exec()` the module to inspect it (a policy guard must not execute the code
it polices).

## Why it is moot rather than accepted or rejected

`tools/iron_plan_guard.py` no longer exists, so there is nothing to
re-point. The underlying observation — promotion authorization now lives in
`daedalus/kernel/promotion.py` and `daedalus/kernel/approvals.py` — still
matches the current tree [MEASURED 2026-08-25: both modules present]; any
present-day mechanical check on sealed promotion should target those, not
`gated_writes.py`, but that is a fresh design decision, not a reactivation of
this proposal.
