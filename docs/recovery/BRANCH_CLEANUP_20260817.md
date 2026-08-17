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

2. **Canonical trunk undecided — but the evidence now argues against the
   consolidated tip.** See "Trunk evidence" below.

3. **Six worktrees exist, three dirty** — none safely prunable:

   | Worktree | Branch | dirty files |
   | --- | --- | --- |
   | `.claude/jobs/3cdf2088/tmp/integ` | `integration/g0-consolidated-20260807` | 0 |
   | `AppData/Local/daedalus/worktrees/…kairos-ollama…` | kairos attempt | 1 |
   | `…/scratchpad/lab` | `experiment/deepseek-lab` | 672 |
   | `agent_env.worktrees/daedalus-g0-canonical-20260803` | `integration/g0-canonical-20260803` | 7 |
   | `agent_env.worktrees/daedalus-project-analysis-overview` | `experimental` | 0 |
   | `.claude/worktrees/amendment-003` | `amendment/003-serena-first` | 0 |

## Trunk evidence `[MEASURED]` 2026-08-17

The consolidated tip is larger and better-tested, and it **fails the
repository's own constitutional guard**. Both are true; the second decides it.

| | checkpoint line | consolidated tip |
| --- | --- | --- |
| ref | `e206de6` (was `8647091`) | `60b2bfe` |
| `tools/iron_plan_guard.py verify` | **Iron Plan OK** | **IRON PLAN ERROR** |
| test files / modules | 206 / 173 | 476 / 275 |
| collected | 4455, 0 errors | 6501, 0 errors (after 2 fixes) |
| full suite | *(running)* | **268 failed, 6183 passed, 51 skipped** (29:54) |

The guard error is:

```
IRON PLAN ERROR: daedalus/kairos/gated_writes.py exposes automatic promotion
```

### This is a guard false positive, not a behavioural violation

An initial reading treated this as a live invariant-5 breach. That was wrong
and is corrected here.

`iron_plan_guard.py:711` enforces invariant 5 by parsing the AST of
`gated_writes.py` and requiring a literal `AUTO_PROMOTE_LEVELS = ("never",)`.
The strangler refactor moved that constant out of the watched module and into
the retained source that gets `exec()`'d. Measured:

| line | static, watched module | static, retained source | **runtime** |
| --- | --- | --- | --- |
| consolidated `60b2bfe` | *(not found)* | `('never',)` | **`('never',)`** |
| checkpoint `e206de6` | `('never',)` | *(absent)* | **`('never',)`** |

Promotion is sealed on both lines. No candidate can auto-promote.

### Practical consequence: the consolidated tip is uncommittable `[MEASURED]`

The false positive is not cosmetic. The same check runs as a pre-commit hook,
so it rejects **every** commit on that line. Verified by attempting to commit
two small, unrelated, non-protected fixes in a clean worktree at `60b2bfe`:

```
$ git commit -a -F <msg>
IRON PLAN ERROR: daedalus/kairos/gated_writes.py exposes automatic promotion
$ git log --oneline -1
60b2bfe merge(probe): #56 g0/claude-provider-broker   <- unchanged, commit refused
```

No work can land on the consolidated tip until the guard is repaired or an
amendment token is used. Any session migrating to that tip — including
`work/g0-trunk-20260817` — will hit this wall immediately. This makes repairing
the guard the first task on that line, ahead of the ~240 test failures.

### The real defect is guard blindness

What actually regressed is *enforcement*, not behaviour. On the consolidated
line the static check that protects invariant 5 no longer inspects anything
meaningful: the value it guards now lives in a file it does not read. Someone
could later set `AUTO_PROMOTE_LEVELS` to something unsafe in the retained
source and the guard would stay silent.

This lands squarely on the AGENTS.md release-blocking list — "a hook or
instruction advertised as a complete security guarantee". The guard still
*claims* to enforce sealed promotion while having stopped doing so.

Fix direction (requires an amendment; `iron_plan_guard.py` is protected):
teach the check to resolve the constant through the retained source, or better,
assert the **runtime** value rather than a source literal, so the check cannot
be evaded by relocating the assignment.

The concurrent session working in this checkout reached the same conclusion
independently — commits `a7d4d0c` *"the sealed-promotion guard lost the module
it was watching"* and `e206de6` *"sealed promotion is implemented twice, with
opposite trust roots"*.

### Recommendation

Do **not** fast-forward `main` to the consolidated tip yet — but the reason is
test debt and guard blindness, **not** a constitutional breach. Order of work:

1. Restore invariant-5 *enforcement* (amendment): make the check see the
   relocated constant, ideally by asserting the runtime value.
2. Triage the 268 failures with a complete capture. The first run was piped
   through `tail`, so only 44 were recorded and 224 remain uncharacterised;
   a `--junitxml` re-run is in flight.
3. Apply amendment 004 so the Windows leg can execute the promotion tests.
4. Then reconsider the trunk move on evidence.

The checkpoint line remains the safer trunk today — it is smaller, but its
guard coverage is intact and its collection is clean.

### Caveat on these numbers

The 268-failure run executed in a detached scratch worktree. That was tested as
a confound and **refuted**: the same 7 guard/spend failures reproduce in the
pre-existing job worktree (9 vs 10 total on the same three files), so they are
properties of the tip, not of the scratch checkout.

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
