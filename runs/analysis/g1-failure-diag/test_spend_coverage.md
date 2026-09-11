# Diagnosis: tests/test_spend_coverage.py (2 failing node IDs)

Repo: C:/Users/Administrator/daedalus, branch `main` @ `74008fab`.
Interpreter used throughout: `.venv/Scripts/python.exe` (never bare `python`).

## Common root cause (read this first)

Both failures share ONE mechanism. `runnable_spend_entrypoints()` and
`test_the_guard_is_installed_by_exactly_one_function_in_the_tree` both do
`Path(ROOT).rglob("*.py")` over the WHOLE repo root, skipping only
`_SKIP_PARTS = {"__pycache__", "node_modules", ".git", ".venv", "venv",
"build", "daedalus.egg-info", ".pytest_cache", "dist", "structcore-rs"}`
(`tests/test_spend_coverage.py:155-156`). This box runs ~85 concurrent
agents against this shared checkout, and its orchestration tooling creates
FULL NESTED CHECKOUTS of the repo directly under `ROOT`, at
`.claude/worktrees/agent-<id>/` (excluded via `.git/info/exclude:11`) and
`.daedalus_worktrees/<name>/` (excluded via `.gitignore:68`, added in commit
`1077d63c`). MEASURED live on disk at diagnosis time:

```
$ ls .claude/worktrees/
agent-a70c09217a46d8f0b  agent-a73944f451e5de589  agent-ad4bf55b04697eefc
agent-af7eff9d17e233223  agent-aff19b618da1d4584
$ ls .daedalus_worktrees/
g1-ide-11
```

Neither `.claude`, `worktrees`, nor `.daedalus_worktrees` is in
`_SKIP_PARTS`, so the `rglob` walk descends into every one of these five
sibling worktrees and finds byte-identical duplicates of
`daedalus/claude_bridge.py`, `daedalus/cli.py`, `daedalus/budget.py`,
`daedalus/loop.py`, `runs/ab/run_arm.py`, `runs/council/*.py`,
`tools/operability_drill.py`, and the five mocked test modules — each
re-relativized to a path like
`.claude/worktrees/agent-a70c09217a46d8f0b/daedalus/claude_bridge.py`. Those
paths are obviously not in `KNOWN_UNGUARDED_ENTRYPOINTS` (which only lists
`daedalus/claude_bridge.py`) and obviously not in the pinned installer set
(which only lists the eight canonical relative paths), so both assertions
go red — not because the canonical tree changed, but because the scanner
now also counts everyone else's private, gitignored, ephemeral working
copies as if they were new files in "the tree".

Direct probe (isolated `python -c` call against `runnable_spend_entrypoints`
and the installer-scan body from the test file, run standalone, filtering
surprises/installers by whether their path contains
`.claude/worktrees` or `.daedalus_worktrees`):

```
TOTAL found: 126
TOTAL unguarded: 43
TOTAL surprises: 42
worktree-origin surprises: 42
NON-worktree surprises (the real question): 0
installers total: 56
non-worktree installers: ['daedalus/budget.py', 'daedalus/cli.py', 'daedalus/loop.py',
  'runs/ab/run_arm.py', 'runs/council/room.py', 'runs/council/room_server.py',
  'runs/council/summarize.py', 'tools/operability_drill.py']
non-worktree installers == expected? True
diff (non_worktree_installers - expected): []
diff (expected - non_worktree_installers): []
```

Every one of the 42 surprises and the 48 extra installer hits is worktree-
prefixed. Once those are filtered out, the canonical-tree answer is exactly
what both assertions expect: zero new unguarded entry points, and installers
== the pinned 8-element set with no additions and no omissions. The
instrument's target claim (nothing changed in the canonical tree) is TRUE;
the instrument itself cannot currently say so because its file walk has no
concept of "not my worktree".

---

## test_no_new_unguarded_spend_entrypoint_has_appeared

**Verdict:** Deterministic across 3 back-to-back standalone runs on this
box RIGHT NOW (same 5 worktree IDs, same failure), but load/environment
-dependent in the sense that matters: the assertion's outcome is a function
of which sibling worktrees happen to exist under `ROOT` at scan time, which
changes as the ~85 concurrent agents on this shared box create and tear
down worktrees. It is not a property of the source tree at commit
`74008fab`.

**Evidence:**

```
$ TAG=spendcov_92671
$ for i in 1 2 3; do .venv/Scripts/python.exe -m pytest tests/test_spend_coverage.py -q \
    > /tmp/${TAG}_run${i}.txt 2>&1; echo "RUN$i RC=$?"; done
RUN1 RC=1
RUN2 RC=1
RUN3 RC=1
$ for i in 1 2 3; do grep -E "passed|failed" /tmp/${TAG}_run${i}.txt | tail -1; done
2 failed, 27 passed in 10.87s
2 failed, 27 passed in 12.97s
2 failed, 27 passed in 10.71s
```

(NOTE: a first attempt at this used non-unique filenames `/tmp/run1.txt` etc.
and produced a completely unrelated failure from `tests/test_ikarus_llm_voice.py`
— a different agent on this shared box overwrote the file between my write and
read. Re-ran with a PID-tagged unique filename per the "background mutators
invalidate foreground runs" prior; all further evidence below uses the
tagged files.)

Full assertion body from run 1 (`tests/test_spend_coverage.py:340`):

```
E   AssertionError: new directly-runnable spend entry point(s) with NO spend ceiling:
    ['.claude/worktrees/agent-a70c09217a46d8f0b/daedalus/claude_bridge.py',
     '.claude/worktrees/agent-a70c09217a46d8f0b/tests/test_codex_provider.py',
     '.claude/worktrees/agent-a70c09217a46d8f0b/tests/test_health_surface.py',
     '.claude/worktrees/agent-a70c09217a46d8f0b/tests/test_ikarus_context.py',
     '.claude/worktrees/agent-a70c09217a46d8f0b/tests/test_ikarus_stream.py',
     '.claude/worktrees/agent-a70c09217a46d8f0b/tests/test_tools_vet.py',
     '.claude/worktrees/agent-a70c09217a46d8f0b/tests/test_wires.py',
     ... (same 7-file group repeated for agent-a73944f451e5de589,
          agent-ad4bf55b04697eefc, agent-af7eff9d17e233223,
          agent-aff19b618da1d4584, and .daedalus_worktrees/g1-ide-11)]
```

Set sizes, enumerated: **42 surprises total = 7 files × 6 nested worktree
copies** (5 under `.claude/worktrees/`, 1 under `.daedalus_worktrees/`).
The 7-file group per worktree is exactly `daedalus/claude_bridge.py` (the
one file already carrying a documented, reasoned `KNOWN_UNGUARDED_ENTRYPOINTS`
entry in the canonical tree) plus the 6 test modules the file's own comment
at line ~317 says were "each INSPECTED 2026-07-29 and found to patch every
vendor call" — i.e. every single surprise is a duplicate of a file that is
ALREADY known-safe or already excluded in the canonical tree, just re-found
at a worktree-prefixed path the exclusion/allowlist logic never matches.
Direct filtered probe (above) confirms **0 non-worktree surprises**.

**First failing commit:** not bisected. The polluting directories
(`.claude/worktrees/*`, `.daedalus_worktrees/*`) are both git-ignored
(`.git/info/exclude:11`, `.gitignore:68`) and are never committed; `git log`
over `tests/test_spend_coverage.py` shows `_SKIP_PARTS` has never contained a
worktree-related entry since the file was created (`git log -p --follow`,
grep for `_SKIP_PARTS`/`worktree` across the whole file history: no hits
besides the definition itself). This failure is not caused by any diff to
source; it is caused by the live population of sibling worktrees on this
shared box at the moment the scan ran. That population is not visible to
`git log` at all — it is runtime state, created by this session's own
concurrent-agent orchestration infrastructure. There is no commit to blame.

**Root cause classification: (c) blinded instrument** — with the specific
shape being over-inclusion rather than the more familiar "matches nothing".
The detector's notion of "the tree" leaks into other agents' private,
gitignored, ephemeral working copies, so it cannot currently distinguish "a
new unguarded entry point was added to Daedalus" from "another agent's
worktree contains a duplicate of a file we already know about." The
instrument is not lying about coverage dropping — canonical coverage is
unchanged and complete (verified above) — but it is currently incapable of
reporting that truthfully whenever ≥1 sibling worktree exists, which on this
box is most of the time. This is the false-positive twin of the exact same
disease as `d7ba2a43`'s "boundary rule could not see 75 of the 76 flat
modules": a tree-walk detector with an incomplete notion of what counts as
"the tree", just failing in the over-counting direction instead of under
-counting.

**Fix sketch:** add `.claude` (or specifically `worktrees`) and
`.daedalus_worktrees` to `_SKIP_PARTS` in `tests/test_spend_coverage.py`
(both occurrences, lines ~155 and reused at ~442), OR change the walk to
skip any directory containing a `.git` file/dir of its own (the general
signature of a nested worktree/checkout), which would also future-proof
against other worktree root names. The sibling file
`tests/test_egress_coverage.py` has the byte-identical `_SKIP_PARTS`
definition (`tests/test_egress_coverage.py:114`) and the same unguarded
`rglob(ROOT)` pattern — it is exposed to the identical failure mode and
should be checked/fixed in the same change.

**Owner:** whoever owns `tests/test_spend_coverage.py` (this is the "audit
that created this test", per the module docstring — a Gate-0/Gate-1 spend
-ceiling coverage instrument). Not a `daedalus/` product change; it is a
test-scope fix.

---

## test_the_guard_is_installed_by_exactly_one_function_in_the_tree

**Verdict:** Deterministic across the same 3 standalone runs (identical
mechanism, same run log as above — both tests fail together every time,
`2 failed, 27 passed` all three runs). Same environment-dependence caveat as
above: outcome tracks live worktree population, not source content.

**Evidence:** Full assertion body from run 1
(`tests/test_spend_coverage.py:452`):

```
E   AssertionError: the set of processes that install the spend ceiling changed:
    ['.claude/worktrees/agent-a70c09217a46d8f0b/daedalus/budget.py',
     '.claude/worktrees/agent-a70c09217a46d8f0b/daedalus/cli.py',
     '.claude/worktrees/agent-a70c09217a46d8f0b/daedalus/loop.py',
     '.claude/worktrees/agent-a70c09217a46d8f0b/runs/ab/run_arm.py',
     '.claude/worktrees/agent-a70c09217a46d8f0b/runs/council/room.py',
     '.claude/worktrees/agent-a70c09217a46d8f0b/runs/council/room_server.py',
     '.claude/worktrees/agent-a70c09217a46d8f0b/runs/council/summarize.py',
     '.claude/worktrees/agent-a70c09217a46d8f0b/tools/operability_drill.py',
     ... (same 8-file group repeated for the other 4 `.claude/worktrees/agent-*`
          dirs and for `.daedalus_worktrees/g1-ide-11`)
     'daedalus/budget.py', 'daedalus/cli.py', 'daedalus/loop.py',
     'runs/ab/run_arm.py', 'runs/council/room.py', 'runs/council/room_server.py',
     'runs/council/summarize.py', 'tools/operability_drill.py']
```

Set sizes, enumerated: `installers` measured = 56 total = **8 canonical +
8 files × 6 worktree copies (48)**. Expected pinned set = exactly the same
8 canonical paths (`daedalus/cli.py`, `tools/operability_drill.py`,
`runs/ab/run_arm.py`, `runs/council/room.py`, `runs/council/room_server.py`,
`runs/council/summarize.py`, `daedalus/loop.py`, `daedalus/budget.py`).
Direct filtered probe (above): `non_worktree_installers == expected` is
`True`; `diff (non_worktree_installers - expected)` and
`diff (expected - non_worktree_installers)` are both `[]`. The 48 extra
installer hits are the identical 8 canonical files, each re-discovered
inside a nested worktree copy and counted as if it were a distinct,
newly-appeared install site.

**First failing commit:** not bisected, same reason as above — the failure
is driven by non-git-tracked, git-ignored runtime directories
(`.claude/worktrees/*`, `.daedalus_worktrees/*`) whose population is a
function of concurrent-agent orchestration state on this shared box at scan
time, not of any commit. `git log -p --follow -- tests/test_spend_coverage.py`
shows the pinned installer set and `_SKIP_PARTS` have been edited only to
ADD legitimately-new canonical installer sites (`bf86f2e7` "the ceiling
detector learns the central wiring it has been blind to since 2026-08-18",
which is the commit that added `daedalus/budget.py` to the pin) — never to
add or remove a worktree exclusion.

**Root cause classification: (c) blinded instrument.** Same mechanism and
same nuance as the sibling test above: the architectural fact this test
pins ("the guard is installed by exactly one function/set of files in the
tree") is still TRUE of the canonical tree (verified: exact match, zero
diff either direction once worktree paths are filtered). The instrument
cannot currently express that truth because it counts other agents' nested
checkouts as part of "the tree". Not (a): no new install site was actually
added in the canonical tree. Not (b): the pinned set is not stale — it is
exactly correct against the canonical tree as measured.

**Fix sketch:** identical to the sibling test above — add the worktree
root names to `_SKIP_PARTS` (shared by both functions at
`tests/test_spend_coverage.py:155-156`), or skip any subtree containing its
own `.git`. One fix in `_SKIP_PARTS` resolves both failing node IDs, since
they share the same walk and the same missing exclusion.

**Owner:** same as above — `tests/test_spend_coverage.py` owner.

---

## Cluster

Both failing node IDs are ONE defect, not two: a single missing exclusion
(`_SKIP_PARTS` doesn't know about nested agent/worktree checkouts) that
happens to be read by two separate assertions (`runnable_spend_entrypoints`
directly, and the parallel hand-rolled walk inside
`test_the_guard_is_installed_by_exactly_one_function_in_the_tree`). Fixing
`_SKIP_PARTS` (or switching to a "skip anything with its own `.git`"
predicate) in one place fixes both. `tests/test_egress_coverage.py` shares
the identical `_SKIP_PARTS` list and walk pattern and is exposed to the same
latent bug — not confirmed failing in this diagnosis (out of assigned
scope), but worth the same fix in the same commit.

## Security severity

**Not a security defect.** This is release-blocking-shaped (a hard-red CI
assertion) but the underlying architectural claim the test exists to
protect — "the process-spend ceiling covers exactly the known, reasoned set
of entry points, and no new unguarded one has appeared" — is TRUE and
UNCHANGED in the canonical tree, verified directly by re-running the same
scan logic filtered to exclude nested worktree paths (0 surprises, exact
installer-set match). No new unguarded spend entrypoint exists. The residual
risk is entirely in the test's own scope-boundary (environmental
false-positive), not in product code. Recommend treating this as a
test-infrastructure bug to fix for the shared multi-agent box, not as
evidence of a spend-ceiling gap.
