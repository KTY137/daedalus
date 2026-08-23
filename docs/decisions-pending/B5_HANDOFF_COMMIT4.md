# B5 handoff: what commit 4 needs, and the wall we measured

Branch `lane/b5-evidence-authentication`, five commits on `26a8b5eb`:
`44d47f1e` (literal pins) · `a3f20aa7` (per-surface derivation, aggregate flag
deleted) · `6be14dff` (row contract + report path runs its own verifiers) ·
`9ccc4cfc` (spec) · `1499e8bd` (producers).
73 tests green, 13/13 mutants killed, every anchor resolving once,
`surfaces_total` 410 -> 410.

## 1. A kernel defect, found and fixed here

`issuer_keyring` opened the lease-signing key without `O_BINARY`, so Windows
wrote `0x0A` as `0x0D 0x0A`. **MEASURED: ~12% of fresh control roots (1 of 7
over 8 roots) signed with bytes that were not the bytes on disk** -- those
leases are unverifiable once the process exits. 0 of 40 after the fix.
Any lease receipt produced on `main` before this lands should be re-verified
after a restart; a silent "absent" is the failure mode, not an error.

## 2. Zero surfaces authenticate, and the reason is structural

On an isolated snapshot with a real `grant() -> begin_effect() ->
finish_effect()`, `python.offload` authenticates with **0 refusals** and
declares **0 surfaces**: its writes sit in `_offload_impl`, which the
un-leased `live=False` path also calls. The 29 declared surfaces belong to 18
other doors, and `acquire_wave_offload_lease` **refuses every registry row
except `python.offload`**.

So the Gate-0 wall is not "receipts are missing". It is: *exactly one door in
the system can hold a lease at all.* No amount of producer work moves a
counter until that changes. Loop run at this commit
(`runs/loop/loop-20260823-183230-3b29b1.json`, 132.5 s, spend 0.0), verbatim:

    EffectLeaseStateError: the retained lease has no durable start for this
    execution; a granted-only lease is not a terminal receipt

## 3. Commit 4 (the `attempt.py` door)

Hooks are in place; the door is not.

    record_primary_checkout_disjointness(
        decision, *, primary_checkout, target_root, source_revision,
        evidence_root, control_root_path, recorded_at=None)

Pass the `containment.worktree` `GuardDecision` already built at
`attempt.py:2470` -- it records, it never re-decides.

    record_effect_lease_subject_parts(
        *, authorization, ledger_path, evidence_root, control_root_path,
        positions, issuer_target, issuer_module_path)

after `grant()`, then `emit_effect_lease_terminal_record` after
`finish_effect`. Also drop `daedalus/spine/attempt.py` from
`LIVE_LANE_EXCLUSIONS` -- both its doors are skipped today.

**The change commit 4 actually needs** is not the wiring above: it is
`acquire_wave_offload_lease` accepting the `attempt.py` row. Without that the
signature `410 -> 408` is unreachable, and reporting anything else as progress
would be a number without a measurement behind it.
