# daedalus/kernel/attempt_execution.py  (2724 lines)  — OWNED by the "chip-refusal" packet

Base 54f09753. Static read-only. Per the shared brief, this file is being
actively modified right now, so I flag rather than build full cases.

## What the file is for (context only)

The other, older Attempt lifecycle: git-worktree-based candidate execution
(`storage -> intent -> worktree -> runner -> patch -> gates -> resolve ->
cleanup`, per its own module docstring at :13) with a single hardened `_git`
choke point for every git invocation.

## OWNED-FLAG

- **"ONE way to attempt a task" (module docstring, `:1-11`, "exactly one
  seam") is not true of the package as a whole.** `grep -n
  "AttemptLedger\|IsolatedAttemptCoordinator" daedalus/kernel/attempt_execution.py`
  returns zero hits — confirmed independently. A second, structurally
  different Attempt lifecycle lives in the same `daedalus/kernel/` package:
  `attempt_contracts.py` / `attempt_ledger.py` / `attempt_workspace.py` /
  `source_trees.py`, registered under its own three Effect Registry rows
  (`daedalus/spine/effect_boundary.py:350,372,394`). The two lifecycles do
  not share code and use structurally different mechanisms to get candidate
  content onto disk: this file drives `git worktree` + its own `_git`
  choke point (`:505-599`) against a checkout, while the other lifecycle
  content-addresses a `SourceTreeManifest` in `source_trees.py` and
  `os.replace`s it into a workspace — no git involved at all. Both commit
  through the same `SpineLedger`, so this is not a second event store (the
  docstring's stronger, more important claim survives), but "ONE way to
  attempt a task" / "exactly one seam" is false as a description of the
  package's actual attempt surface — there are two, unrelated at the code
  level, doing the same job by different mechanisms.
- **`_git` (`:505`) and `_git_env` (`:470`) are this module's own,
  self-contained choke point — not centralized with anything else, and not
  duplicated within it.** `grep -n "_git\b" daedalus/kernel/source_trees.py
  daedalus/kernel/attempt_workspace.py daedalus/kernel/attempt_ledger.py
  daedalus/kernel/attempt_spine_reader.py` (my four files) returns zero
  hits — the other lifecycle never shells out to git at all, so there is no
  cross-module git-invocation duplication to find. Within this file itself,
  `grep -n "subprocess.run" daedalus/kernel/attempt_execution.py` shows
  exactly one call (`:591`, inside `_git`), matching the file's own claim at
  `:587-588` ("ONE subprocess call in this module, and a test asserts there
  is exactly one"). Git invocation is centralized *within this file*, just
  not across the package (see previous point) and not shared with
  `daedalus/kernel/sandbox.py`'s Docker-CLI subprocess call, which is an
  entirely separate choke point for a different external process.

## What I did not cover

Per the brief, no full case was built for this file — no Axis 2-5 tables, no
line-by-line docstring sweep beyond the two flagged leads. This file is
2724 lines and under active modification; a full audit would be stale on
arrival.
