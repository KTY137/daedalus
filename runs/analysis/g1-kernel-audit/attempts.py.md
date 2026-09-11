# daedalus/kernel/attempts.py  (34 lines)

Base 54f09753. Static read-only. Auditor: parent (W6 slice, subagent cap hit).

## What the file is for

A pure re-export facade. It imports 10 names from `.attempt_contracts`,
`AttemptLedger` from `.attempt_ledger`, and `IsolatedAttemptCoordinator` from
`.attempt_workspace`, and re-lists all 12 in `__all__`. No logic, no state, no
divergent definitions.

## Axis 1 — docstring truth

### CONFIRMED — the facade's stated justification is not met in production

`:1-5`:

> "Compatibility surface for the isolated Attempt lifecycle kernel.
> The implementation is split by responsibility while **this stable import path
> remains available to existing callers**."

"Existing callers" is a claim about the world, and it is checkable. Greps run
(copy directories excluded — `.claude/worktrees/`, `.daedalus_worktrees/`,
`build/`, `apps/web/src-tauri/{backend,target}/` all contain stale duplicates of
this tree and inflate a naive count ~8x):

```
grep -rn  "kernel\.attempts" --include=*.py daedalus/ tests/ scripts/ tools/
grep -rln "kernel\.attempts" --include=*.py daedalus/   ->  0
grep -rln "kernel\.attempts" --include=*.py tests/      -> 11
```

**11 importing files, 0 of them production.** The full set, enumerated because
the claim is universal:

1. `tests/kernel/test_attempt_durability_admission.py:10`
2. `tests/kernel/test_isolated_attempt_lifecycle.py:10`
3. `tests/kernel/test_isolated_attempt_lifecycle_adversarial.py:11`
4. `tests/kernel/test_isolated_attempt_lifecycle_review.py:11`
5. `tests/kernel/test_isolated_attempt_spine_wire_review.py:12`
6. `tests/kernel/test_isolated_attempt_time_and_preflight.py:10`
7. `tests/kernel/test_isolated_attempt_time_completion_order.py:29`
8. `tests/kernel/test_isolated_attempt_time_tampering.py:11`
9. `tests/kernel/test_isolated_attempt_workspace_identity_review.py:8`
10. `tests/kernel/test_isolated_attempt_workspace_root_authority.py:10`
11. `tests/test_spine_gate0_writer_factory.py:11`

So the "existing callers" the compatibility shim exists to serve are exclusively
the test suite — and every one of those tests could import the three real modules
directly. The facade is preserving a migration path that nothing is migrating
from.

This is a **mild** finding and I want to be precise about its weight: nothing is
broken, nothing is unsafe, and a 34-line re-export costs almost nothing. What it
does do is make the test suite import through a path production never exercises,
which is the seam-blindness shape — the tests are not exercising the import
surface production uses. Per the brief, zero production callers is a finding, not
a verdict; the finding here is specifically that the docstring's justification is
false as written, not that the file must go.

## Axis 2 — effect surface

None. Import statements only.

## Axis 3 — unreleased resources

None.

## Axis 4 — validator gaps (W4 class)

Not applicable. No validators, no path construction, no identifiers.

## Axis 5 — dead / duplicate

Covered under Axis 1 — the file *is* the Axis-5 finding.

Checked for the dangerous form of a facade and did **not** find it: `attempts.py`
defines nothing of its own and shadows nothing. Every name in `__all__`
(`:21-34`) resolves to the single canonical definition in
`attempt_contracts.py` / `attempt_ledger.py` / `attempt_workspace.py`. I compared
the 12 exported names against the 10 in `attempt_contracts.__all__:341-352` plus
`AttemptLedger` and `IsolatedAttemptCoordinator` — they match exactly, with no
extra and no omission. So there is no divergence risk, only redundancy.

## What I did not cover

Nothing — the file is 34 lines and fully covered.
