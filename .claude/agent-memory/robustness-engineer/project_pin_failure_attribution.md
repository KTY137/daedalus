---
name: pin-failure-attribution
description: How to prove a red pinned-number test (s02 corpus, byte pins, digest pins) predates the branch under review without creating a worktree or touching git state
metadata:
  type: project
---

This repo has several tests that pin a measured number over the whole
`daedalus/` tree (e.g.
`experiments/forest_v2/s02_types/test_external_corpora.py::test_kernel_row_is_the_retracted_headline_restated`
pins `annotation_only_pct` / `full_resolver_pct` / `marginal_functions`). They go
red on almost any commit, so "red on this branch" is not evidence the branch
caused it — and during a read-only review you cannot `git worktree add` to get a
baseline.

**Why:** on the 2026-09-10 `fix/health-latency` review the s02 kernel row was red
(`94.47 != 94.46`) and looked like collateral from the branch. Exporting the
parent revision showed 94.47 at `6fecb134` (branch parent) *and* at main
`5cb2b2d4` — the branch moved the corpus by exactly 1 function and 3 type-name
sites and moved none of the four pinned percentages. Blaming it would have sent
someone to re-pin for the wrong reason.

**How to apply:** materialise the revisions into `$TEMP` with plumbing only —
`git -C <primary> archive <rev> daedalus > x.tar` then `tar -xf` — and call the
measurement function directly (`type_plane.build_type_plane(root, ("daedalus",))`
for s02) on each export. Print the pinned fields for branch-parent, each commit,
and current main side by side. `git archive` reads objects and writes nothing to
the repo, so it is safe under a read-only mandate.

Same shape works for `.gitattributes` closure failures: check
`git cat-file -e <parent>:<path>` for the modules the test names — if they
already existed at the parent and `.gitattributes` is unchanged in the diff
(`git diff --stat <parent> <tip> -- .gitattributes`), the failure is inherited.

Related: [[crlf-text-pin-trap]].
