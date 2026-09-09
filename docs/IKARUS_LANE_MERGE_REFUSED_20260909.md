# The ikarus lane must not be merged: it forks 1 218 commits behind main

`[MEASURED 2026-09-09]` Classification: `EXPERIMENT` (read-only integration
assessment). **Decides nothing. Merges nothing.**

Answers the standing instruction to integrate the codex lanes repeatedly, and
the owner's conditional *"integrate the ikarus lane if its worth"*, with a
measurement instead of a guess.

## Subject

`origin/g1/ikarus-runtime-invocation-binding-07d3` @ `ddb6dec0`, actively moving
today: sealed `TaskAttempt` Claude runner, live Claude dispatch from the attempt
owner, authority binding.

## The lane's own work is sound

| | |
| --- | --- |
| lane's own new tests | **91 passed** (`test_ikarus_claude_task_attempt_runner`, `…_authority`, `…_attempt_handoff`, `…_composition`, `…_supervisor_attempt_identity`, `test_runtime_registry_claude_shim`, `test_ikarus_effect_bridge`) |
| footprint | 38 files, +6 643 / −693 |
| areas | `daedalus/ikarus_supervisor.py`, `daedalus/kernel`, `daedalus/runtimes`, `daedalus/providers`, 14 × `apps/web`, ~10 test files |

This is real Gate-1 orchestration work and it passes on its own tree.

## Why it still cannot be merged

| measurement | value |
| --- | --- |
| lane ahead of main | 96 commits |
| **lane behind main** | **1 218 commits** |
| merge-base | `1c3c6028`, dated 2026-09-08 |
| main commits dated since 2026-09-08 | **102** |
| non-merge commits from merge-base to main tip | **1 115** |

Those last three rows are mutually inconsistent on their face, and the
inconsistency is the finding: a merge-base dated *yesterday* sits **1 218
commits back** in main's topology. That is the signature of the 2026-09-03
history rewrite recorded in `docs/recovery/purge-20260903/`. Commit dates were
carried forward; ancestry was not.

The consequence is directly observable in the tree rather than inferred:

```
tests/contracts/  entered main 2026-09-03 (21d15528)
tests/contracts/  ABSENT from the lane's tree at ddb6dec0
```

Running `tests/contracts/ tests/providers/` on the lane gives **"no tests ran"**;
the same command on current main gives **327 passed, 52 skipped, 28 subtests**.
The lane has never been executed against the kernel it would be merged into.

A naive merge would therefore re-introduce 1 115 non-merge commits of purged
history while touching `daedalus/kernel` — the exact trap the recovery notes
warn about. `git merge` of this branch was refused twice by the safety
classifier; the mechanical reason above is why that refusal was correct, and it
stands independently of the classifier.

## Decision

**Refused as a merge. Retained as a port.** The one change whose value is
independent of the lane's base — provider dispatch honesty — was ported on its
own merits and is open as **#332**. Nothing else in the lane is portable
without its 1 218-commit base.

**Not mine to do:** rebasing another agent's lane. The correct repair is
`git rebase --onto origin/main <old-base>` performed by the lane's author, per
`docs/recovery/purge-20260903/`. Doing it here would rewrite codex's branch
under it while it is actively committing — today's commits are hours old.

## What this does not claim

- The lane's work is **not** judged low-quality. Its 91 tests pass; the refusal
  is about base divergence, not content.
- The 1 218 figure is a topological count, not a claim that 1 218 distinct
  changes conflict. Most would merge cleanly; the kernel overlap is what makes
  "most" insufficient.
- No statement about whether the lane's live-dispatch design is right. That
  review has not been done and is not blocked by this.
