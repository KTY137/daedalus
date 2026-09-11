---
name: project-daedalus-lane-hazards
description: Daedalus runs several concurrent agent lanes over one checkout plus .claude/worktrees; reviewing means read-only, no git state changes, and never touching apps/web/dist
metadata:
  type: project
---

Daedalus work happens in parallel lanes: the primary checkout plus per-packet worktrees
under `.claude/worktrees/`. Review tasks arrive as "commit X on branch Y in worktree Z,
read-only". Treat that literally: no `git add`, no branch switching, no builds that emit
into a tracked artifact directory. As of 2026-09-10 another lane holds **uncommitted build
output in `apps/web/dist/**`**, so `npm run build` / `vite build` in any lane is a
destructive act against someone else's working tree.

**Why:** lanes cannot see each other, and a stray write there is indistinguishable from
that lane's own work when it goes to commit.

**How to apply:** for `apps/web` type checking use `npx tsc` (tsconfig already sets
`noEmit`), never `npm run build`. Playwright specs need a built bundle *and* a live API,
so they are normally UNVERIFIED for a reviewer — say so rather than skipping the point.
The two npm scripts that do run cheaply are `test:app` and `test:motion`. See
[[feedback-review-output-contract]].

**A worktree has no `node_modules`, so frontend evidence looks unrunnable — it is not.**
Junction the primary checkout's copy in, run, then drop the junction (2026-09-11, PR #370):
`cmd //c mklink //J <worktree>/apps/web/node_modules <primary>/apps/web/node_modules`,
run from a subshell so the parent cwd stays in the primary checkout, then
`cmd //c rmdir <worktree>/apps/web/node_modules` — `rm -rf` on a junction can delete
*through* it. `node_modules/` is gitignored, so the worktree stays clean; `run-spec.mjs`
does mkdtemp under the primary `node_modules/.cache` and cleans up after itself.

**Why:** without this, every frontend claim in a worktree review is UNVERIFIED, and the
one thing a reviewer is there to do is not guess.

**How to apply:** `npm run test:app` is the whole frontend suite (620+ checks). There is
**no vitest in this repo** — specs are plain modules exporting `runXSpec()` that
`apps/web/src/app/run-spec.mjs` bundles with esbuild and calls by name, so a new spec file
that is not registered there silently never runs.

**Verifying a "pre-existing failure" claim is a trap here.** Running the suspect test in
the primary checkout does *not* test committed `main`: other lanes leave uncommitted test
fixes in the working tree, so the test can pass there and fail in the packet's worktree
for reasons that have nothing to do with the packet. Confirmed 2026-09-11 on G1-SETTINGS-01,
where a one-line `tmp_path.resolve()` fix sat uncommitted in the primary copy of
`tests/test_desktop_runtime.py`. Compare `git show <rev>:<path> | sha256sum` against the
worktree copy before believing either result, or diff the working tree for that file.
