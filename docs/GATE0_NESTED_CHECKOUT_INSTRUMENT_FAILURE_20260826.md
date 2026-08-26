# A checkout inside the checkout turned three instruments off

**Measured:** 2026-08-26, live tree, HEAD `e83d8d8a`.
**Classification:** `ALIGNED` -- instrument repair. No production effect path,
policy, evaluator, ledger or promotion path changed.
**Iron Gate:** 0.

## The one-sentence version

A git worktree checked out at `.claude/worktrees/wiki-generation-gate` on
2026-08-25 22:49 -- excluded through `.git/info/exclude`, therefore invisible to
`git status` -- put a second copy of every module into three repository-wide
scanners, and each of them responded by measuring *less* and reporting it as a
clean result.

## Why a nested checkout is not "a slightly bigger sample"

Both affected scanners are keyed on *identity by name*. A second copy of the
tree does not add noise at the margin; it makes every name in the repository
collide with itself exactly once, which is the precise input that turns each
scanner's own safety rule into a global off-switch.

| Instrument | Rule it applies | What one nested checkout does to it |
| --- | --- | --- |
| `scripts/declare_write_surfaces.py` (`NameIndex`) | a module-private helper is admitted only if its name appears nowhere outside its own file | every private helper in the tree now appears outside its own file, so **no door can admit any private callee** |
| `daedalus/spine/docrefs.py` (`_suffix_index`) | an ambiguous path suffix is the absent-module case | every module has a twin, so **almost every suffix is ambiguous** and documented modules report as undocumented |

Neither failure is loud. `NameIndex`'s class docstring argues its over-count is
safe because it "can only ever exclude a helper, never admit one" -- true, and
the unstated half is that the safe direction is also the direction in which the
instrument returns nothing and looks like a clean tree. This is the failure mode
this repository has now hit often enough to name: **an instrument must be able
to say "could not measure" distinguishably from "measured, nothing found."**

## Measurements

### 1. Write-surface lease dominance `[MEASURED]`

`python.offload` is the only registry row in the tree that dominates any write
surface at all. With the nested checkout in the index versus without, same
commit, same code:

```text
with     private_callees=()                          dominated positions=94    bench write attributed: no
without  private_callees=('<the door's bench helper>')  dominated positions=573   bench write attributed: yes
```

The 1173 files under `.claude/worktrees/` were the entire difference.
`tests/gates/test_write_surface_lease_dominance.py::test_the_offload_door_lease_dominates_its_bench_write`
fails in the live tree and passes in a fresh checkout of the same commit, which
is exactly the shape that gets a failure written off as flaky.

### 2. Documentation-reference resolution `[MEASURED]`

```text
before   suffixes=13111   ambiguous=3622   of which ambiguous ONLY due to the nested checkout: 3242
after    suffixes= 9590   ambiguous= 380
```

Nine out of ten ambiguities were the copy. `_EXCLUDED_DIRS` did hold
`.worktrees` -- and the directory in the tree was `.claude/worktrees`, so the
name-based list missed it. A list of names is always one name behind.

A second, pre-existing test also fails under the un-pruned walk:
`tests/test_docrefs_false_positives.py::test_the_actual_stale_vendor_constant_remains_actionable`.
It was already failing in the live tree before this repair.

### 3. The repair defeated itself once, and that is the sharpest finding

`NameIndex` is built from RAW TEXT: the class docstring states that a name in a
comment or a string literal counts as a mention. The first draft of the fix
documented itself by naming the exact private helper it had just restored --
in a file the index scans. The name promptly landed in every other file's
`outside` set and the attribution broke again. **The repair and its own defeat
in one commit.**

That is now pinned:
`tests/gates/test_write_surface_lease_dominance.py::test_the_generator_never_names_a_door_private_helper`
reads the generator's text, derives every CENTRAL door module's private
top-level helpers, and fails on any overlap. On first run it found three that
predate this work -- two helpers of the offload door named in comments, and one
collision between the generator's own `_head_revision` and the same name in
`daedalus/loop.py`. All three are fixed here: prose describes helpers instead of
spelling them, and the generator's helper is renamed. The instrument gives way,
not the door.

## The rule adopted

Structural, not nominal: **a directory holding a `.git` entry is another
repository** -- a file for a worktree, a directory for a clone -- and is pruned
while walking. `root` itself is never tested, because the walk enters it before
any test applies. Applied in `NameIndex.build` and in
`docrefs._repository_python_files`; both carry the measurement in their
docstrings.

## What this does NOT claim

- It does not claim the two nested checkouts should be deleted. Both fixes make
  the tree correct with them present, which is the property worth having: a
  scanner that is only right when the working directory is tidy is not a
  scanner.
- It does not revise `docs/GATE0_INTEGRATION_GAPS_20260825.md`. That survey ran
  earlier on 2026-08-25, before the checkout at 22:49, so its Rank-2 numbers
  were taken under a clean index. Re-measured at `e83d8d8a` after the repair:
  `surfaces=447 declared=35 unclassified=412`, 22 doors, and **still exactly
  one** lease-dominated door. The headline finding is unchanged; what the
  checkout broke was every run after it.
- It did not, at first, audit the other root-walking scanners. Two of the
  three have since been measured and fixed in the same sweep:
  `daedalus/wiki/plan.py` drew **480 of 983 surveyed files from the copy**
  (78 topics -> 40, 983 files -> 503 after the prune), and
  `daedalus/wiki/verify.py` counted the copy's modules as material the wiki
  must cover, halving `module_coverage` -- it now excludes nested checkouts
  through `exclusions()`, beside the wiki and `runs/` trees it already named.
  `daedalus/health.py` still walks from a root with a name-based skip list and
  is **not** measured. That one is named as remaining work, not waved through.

## Reproduce

```text
python -m pytest tests/gates/test_write_surface_lease_dominance.py -q
python -m pytest tests/test_docrefs_false_positives.py -q
python scripts/declare_write_surfaces.py --dry-run
```

The dominance and docrefs probes both die if the prune is removed; both were
mutation-checked that way before being reported.

Iron Plan: ALIGNED
Iron Gate: 0
Evidence: the three measurements above, each re-runnable from this tree.
