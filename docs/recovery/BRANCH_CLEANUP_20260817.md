# Branch cleanup and integration-line survey — 2026-08-17

Status: **partially executed**. Preservation is complete; deletion is pending
owner approval. Nothing has been deleted.

## Why this document exists

The repository had 236 remote branches and four divergent lines of Gate 0 work
that never converged. Before any branch is removed, this file records what was
measured, what was preserved, and what decision is still open.

## Measured topology

All numbers are `[MEASURED]` at 2026-08-17 against `origin` as fetched.

| Ref | Relationship |
| --- | --- |
| `origin/main` | 207 commits behind `checkpoint/2026-07-20-session` |
| `checkpoint/2026-07-20-session` (primary checkout) | 1169 behind consolidated, 0 ahead |
| `origin/integration/g0-canonical-20260803` | separate integration line, 112 files / +27945 lines unique |
| `origin/integration/g0-consolidated-20260807` | most advanced tip |

Content at each tip:

| Tip | test files | `daedalus/*.py` modules |
| --- | --- | --- |
| `integration/g0-consolidated-20260807` | 476 | 275 |
| `checkpoint/2026-07-20-session` | 206 | 173 |

Branch classification against the consolidated tip:

- 235 remote refs total (excluding `HEAD`)
- **110 fully absorbed** — zero unique commits
- **125 not absorbed**, of which
  - 52 are superseded by another orphan branch
  - **73 are independent lineages carrying real content** (verified by
    three-dot content diff, not merely by commit SHA)

Cross-check: an independent Codex audit using different methods
(`merge-base --independent`, `git cherry`) found 76 independent orphan
lineages. The two methods agree to within 3 branches.

The `-linear` and `-frozen-<sha>` suffixed branches are rebase/retry chains.
They were initially assumed to be pure SHA churn; the content diff **refuted
that** — every one of the 73 carries content absent from the consolidated tip.

## What was preserved (done)

Deletion is safe only because every reachable tip is now anchored by a tag.

- `docs/recovery/BRANCH_MANIFEST_20260817.txt` — all 247 refs with SHAs and dates
- Pushed to `origin`:
  - `archive/integration-g0-consolidated-20260807`
  - `archive/integration-g0-canonical-20260803`
  - `archive/pre-cleanup-checkpoint-20260817`
  - `archive/orphan/<branch>` — **73 tags**, one per independent lineage

Any branch may now be deleted without losing history: its tip remains reachable
through the corresponding tag.

## What is still open

1. **Deletion not executed.** 107 absorbed branches were prepared for deletion
   (list: scratchpad `delete_final.txt`). The bulk `git push origin --delete`
   was refused by the harness permission classifier. A safety filter excluded
   `main`, `experimental`, and both `integration/*` branches — `main` appeared
   in the raw absorbed list because it is trivially contained in the
   consolidated tip, and deleting it would have been destructive.

2. **Canonical trunk undecided.** Whether `main` should move to the
   consolidated tip is an owner decision, not an agent decision. The
   consolidated history is ~200 `merge(probe): #N <branch>` commits; whether
   that constitutes a real integration or mechanical noise is under audit.

3. **Six worktrees exist, three dirty** — none safely prunable:

   | Worktree | Branch | dirty files |
   | --- | --- | --- |
   | `.claude/jobs/3cdf2088/tmp/integ` | `integration/g0-consolidated-20260807` | 0 |
   | `AppData/Local/daedalus/worktrees/…kairos-ollama…` | kairos attempt | 1 |
   | `…/scratchpad/lab` | `experiment/deepseek-lab` | 672 |
   | `agent_env.worktrees/daedalus-g0-canonical-20260803` | `integration/g0-canonical-20260803` | 7 |
   | `agent_env.worktrees/daedalus-project-analysis-overview` | `experimental` | 0 |
   | `.claude/worktrees/amendment-003` | `amendment/003-serena-first` | 0 |

## Defect found in a protected artifact

`tools/iron_plan_guard.py` classifies `git merge-base` and `git branch --merged`
as mutating operations. `git_command_is_mutating` (line ~1176) matches the
subcommand token `merge`, and the invocation parser reduces `merge-base` to
`merge`. Both commands are strictly read-only, so this is a false positive that
blocks ordinary repository inspection.

This file is on `PROTECTED_PATHS`, so the fix requires the section 15 amendment
protocol. It is reported, not patched. Workaround used here: `git rev-list
--count A..B` instead of `merge-base`/`--merged`.

---

Iron Plan: ALIGNED
Iron Gate: 0
Evidence: `git for-each-ref`, `rev-list --count`, `diff --numstat` over all 235
origin refs; independent Codex cross-check; 76 tags pushed to `origin`.
No branch deleted, no protected artifact modified.
