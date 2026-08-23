# Branch consolidation 2026-08-23 — owner kit

Iron Plan: ALIGNED · Iron Gate: 0 · consolidation/deletion only; no new subsystem.

## What already happened (no owner action needed)

[MEASURED 2026-08-23, consolidation session]

- `origin/main` was 1,525 commits behind the local trunk (last push 2026-07-13).
  It is now fast-forwarded: `4da74308..8a7de245` and later.
- `experiments/forest_v2` slices **s02, s07, s09** landed on `main` from their
  `grind/f2-*` lanes (commits `d082684a`, `d572cc3a`, `a550d330`, note
  `6f3aae70`). Isolated experiment tree only; 256/259 tests green, the three
  failures are snapshot-pinned repo measurements and are recorded in the
  slice README's consolidation note.
- Every other branch was checked in-memory against `main`
  (`git merge-tree`): 24 fully contained, the rest either superseded by later
  work on `main` (e.g. the 2026-08-04 `promotion-*-linear` chain, which
  would have re-added 15 promotion modules beside `kernel/promotion.py` — a
  second promotion path, release-blocking per AGENTS.md) or already
  tag-frozen by the 2026-08-22 orphan pass.
- Preservation: 148 `archive/*` tags on origin — `archive/orphan/<branch>` for
  every remote line, `archive/lane/<branch>` for local lanes, and
  `archive/lane/<branch>-wip` for 27 lanes whose worktrees held uncommitted
  work (committed as `wip(salvage)` on the lane; list in
  `salvaged_lanes.txt`). Nothing was discarded.
- Local: 31 lane worktrees under `agent_env.worktrees/` and the jobs `integ`
  worktree removed; 50 local branches deleted (all tag-covered or in `main`).

## What the owner runs (blocked for the agent: mass remote deletion)

All 125 branches in `remote_branches_to_delete.txt` are either ancestors of
`origin/main` or contained in an `archive/*` tag that is already on origin.
Re-verify, then delete:

```bash
cd /c/Users/nukei/Desktop/agent_env_g0
git fetch --prune origin
# verify: every listed branch is covered before anything is deleted
while read b; do
  git merge-base --is-ancestor "origin/$b" origin/main \
    || [ -n "$(git tag -l 'archive/*' --contains "origin/$b" | head -1)" ] \
    || { echo "NOT COVERED: $b"; exit 1; }
done < docs/recovery/cleanup_2026-08-23/remote_branches_to_delete.txt && echo "all covered"
# delete on GitHub (one push)
git push origin $(sed 's#^#:refs/heads/#' docs/recovery/cleanup_2026-08-23/remote_branches_to_delete.txt)
git fetch --prune origin && git branch -r
```

Expected remainder on origin: `main` and `checkpoint/2026-07-20-session`
(the archived pre-ruling line; its worktree is still the docs home of one
session, tag `archive/checkpoint-2026-07-20-session` is at `e37294c3`, the
branch tip `6225d3e4` is one vet.py commit later and is ported on `main`).

Rollback of any deletion: `git push origin archive/orphan/<name>:refs/heads/<name>`.

## Left alone on purpose

- `C:/Users/nukei/AppData/Local/daedalus/worktrees/…/daedalus-attempt-kairos-…`
  — kernel attempt workspace, owned by the runtime.
- Two scratchpad worktrees of other sessions (`…/d3328700…/scratchpad/lab`
  on `experiment/deepseek-lab`, 672 dirty files; `…/d766ceca…/atalanta-s02-trunk`).
- `C:/Users/nukei/dfix` on `fix/windows-portability-20260817` (in `main`; a
  directory in the user's home, not the lane folder).
