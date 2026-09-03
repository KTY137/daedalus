# Why the architecture baseline is broken, what was repaired, and the one thing that cannot be repaired by a lane

**MEASURED 2026-08-25**, working tree at `765b6c36`, `docs/architecture-state.json`
as committed. Every number below names the command that produced it.

This closes the diagnosis half of Rank 3 in
`docs/GATE0_INTEGRATION_GAPS_20260825.md` ("re-baseline the architecture
snapshot before any lane ranks work from it"). None of the three defects is
closed by this page. One file is restored, which removes a warning without
changing a number. One is a re-baseline that stays a reviewed decision. One is
a design tension a lane must not resolve alone — and the measurement that
matters most turned out to be none of the three.

> **Revised 2026-08-25 after review.** The first version of this page called
> Defect 1 "repaired" and gave a causal story for Defect 3 that the committed
> baseline refutes. Both are corrected below, and what refuted them is named.

## Defect 1 — the scope declaration was lost in a merge. Restored; NOT a repair of the baseline.

`map --check` refused to compare its counts at all:

```text
IGNORE CONFIG CHANGED (1)
  ! DAEDALUS_IGNORE unset, no .daedalusignore
      the baseline was taken under DAEDALUS_IGNORE unset,
      .daedalusignore de1f022b7b6667a6
```

`.daedalusignore` was **not deleted by any commit** — `git log --all
--diff-filter=D` finds nothing. It was dropped by a merge:

| | `.daedalusignore` |
|---|---|
| `9831ddae^1` (376a1b8c) | absent |
| `9831ddae^2` (74ee0d5b) | **present** |
| `9831ddae` (the unification merge) | **absent** |

The same merge hand-resolved `docs/architecture-state.json` and took
**parent-2's `ignore.file` digest** into it. So the merge kept the *record* of
the scope declaration and discarded the *declaration*. That is the whole reason
the baseline was irreproducible: the snapshot said "taken under
`de1f022b7b6667a6`", and the file hashing to `de1f022b7b6667a6` had been removed
by the commit that wrote that line.

Restored from `9831ddae^2`, 486 bytes, hashing to `de1f022b7b6667a6` exactly —
not a reconstruction, the same file. `map --check` no longer reports
`IGNORE CONFIG CHANGED`.

**And that is all it does.** `daedalus/mapping/drift.py:180-185` is explicit:

> `DAEDALUS_IGNORE` and `.daedalusignore` narrow the structural index. Since
> the gate now reads the tree through `reach`, which walks the filesystem
> itself, **they cannot narrow what the gate sees** — but the configuration is
> recorded in the snapshot and compared on every run anyway, so that a green
> result taken under a narrowed configuration can never be indistinguishable
> from a green result taken under a clean one.

The declaration is a provenance fingerprint. Restoring it restores *parity with
what the baseline recorded* — the block was refusing to compare because the
configuration genuinely differed, and now it does not. It changes **no count**,
and it does not make the snapshot reproducible. Reading the vanished warning as
"the baseline is comparable now" would be wrong; Defect 3 says why.

Three things about the restored file a reader should not assume:

- **It is untracked.** Until committed, this repair exists on one box only —
  the original failure repeated. Committing it is the point.
- **Its `center:` line does nothing.** `load_ignore_rules` feeds every
  non-comment line to `_parse_line`, which turns `center: daedalus, tools,
  apps/web/src` into an ignore rule matching no path in any repository;
  `project_scope` takes center only from an argument or `DAEDALUS_CENTER`
  [MEASURED 2026-08-25: `project_scope(Path('.')).center` is `()`]. The file's
  header claims "everything outside the center is SHELL", and nothing
  implements that sentence. Either `load_ignore_rules` learns the directive, or
  the line goes and the center moves into `projects/agent_env.json`.
- **Three of its rules are unanchored.** `runs/`, `vault/` and `references/`
  carry no internal slash, so per gitignore semantics they match a directory of
  that name at *any* depth. Today the only nested hit is inert; a future
  `daedalus/runs/` package would silently become shell. `/runs/`, `/vault/`,
  `/references/` is what the file appears to mean.

## Defect 2 — the snapshot is self-inconsistent. NOT repaired; a re-baseline is a reviewed decision.

```text
INVALID SNAPSHOT (2)
  ! counts.modules   snapshot says 520, its own 'modules' list has 521
  ! digest           the mechanical lists do not match the digest written with them
```

Same cause: the unification merge hand-resolved a **generated, digest-covered**
file, adding one module name to the census without updating `counts.modules` and
without recomputing the digest. `docs/GATE0_INTEGRATION_GAPS_20260825.md` §0
traces the exact diff.

A `--refresh` would now produce a snapshot whose recorded configuration matches
the one before it. It would not produce a *reproducible* one — see Defect 3. It
is not a lane's call either way: the refresh banks 78 islands in one stroke, and
the gate says why that must move through a reviewed diff rather than a
convenience command.

## Defect 3 — the census counts run artifacts, and that is deliberate

This is the one worth reading, because it looks like a bug, and it is a
defended property.

`reach.analyse` walks the filesystem and **does not consult the scope
declaration**. Measured today: 1638 modules in the census, of which

| directory | modules |
|---|---:|
| `runs/` | **1109** |
| `daedalus/` | 294 |
| `experiments/` | 103 |
| `scripts/` | 88 |
| `tools/` | 19 |
| `docs/`, `vault/`, `examples/` | 25 |

Two thirds of the architecture census is run artifacts. Wiring the existing
scope engine (`daedalus/structcore/ignore.effective_rules`) into the walk drops
it to 1113 and prunes exactly `daedalus/runs/`, `docs/recovery/`, `references/`,
`runs/`, `tests/_looptmp/runs/`, `vault/` — all six of which the declaration
names as "not this project's code".

**That change was implemented, measured, and reverted.** It fails
`tests/test_mapping_drift.py::test_the_gate_does_not_read_the_tree_through_the_ignore_configuration`,
whose docstring states the invariant plainly:

> Belt and braces. The gate reads the tree through reach, which walks the
> filesystem, so a narrowing cannot hide a module from it at all — the recorded
> configuration above is the second line of defence, not the only one.

The reasoning is sound and is the same doctrine as the `IGNORE CONFIG CHANGED`
block: if `.daedalusignore` could narrow the gate, then adding one line to it
would hide modules from the gate, and a green result from a narrowed run would
be indistinguishable from a green result from a full one. The gate is
deliberately un-narrowable.

`reach.py:112`'s `_IGNORE_DIRS` is usually described as the machine floor —
`.git`, `__pycache__`, `build`. That description is not quite honest, and the
comment three lines above the set says so: `build` is excluded because "a stale
wheel-build copy of the whole package lives under `build/` and would otherwise
**double every count**". So a counting judgement already lives in that set. The
line between floor and scope is thinner than it looks; what the invariant
actually forbids is narrowing driven by *configuration a lane can edit*, not
scope-awareness as such.

### The tension that follows, stated but not resolved

`ReachReport`'s docstring claims the report's purpose:

> two runs over an unchanged tree produce byte-identical `to_dict()` … it is
> what makes a diff of this report mean "the architecture moved" instead of
> "the scanner ran".

That holds for an unchanged tree. It does not hold across two checkouts of the
same revision, and that is the finding this page nearly missed:

> **1082 of the 1119 `.py` files under `runs/` are untracked** [MEASURED
> 2026-08-25]. Only 37 are committed.

So two thirds of the architecture census is one machine's lane debris. Two
people at the same commit get different island counts. The determinism the
docstring promises is real *per machine* and false *per revision* — the
baseline is not aging, it is machine-local by construction, and re-baselining
today would commit one box's leftovers as the architecture.

Both properties are defended and they pull against each other:

- the gate must not be narrowable by a config file (defended by a test);
- the gate's diff should mean the architecture moved (defended by a docstring).

Resolving this is not a lane's decision. The shapes available, none applied:

1. **Leave it.** Accept that the baseline ages with run volume, and re-baseline
   often. Cheapest; keeps both properties nominally, honours neither in practice.
2. **Classify instead of filter — and this already exists.** Keep walking
   everything, so the invariant survives, but have the report mark each module
   project-or-artifact so the counts can be read either way and a narrowing
   still hides nothing. This is not a new idea: `docs/PROJECT_SCOPE.md:49-54`
   already defines a **shell** zone — "still indexed and still resolvable as an
   import target … but withheld from every metric" — and `structcore.index`
   already implements it. The mapping layer simply never adopted it. A shell
   module stays in `modules` and stays in `islands`, so it also passes the
   invariant test as written. The danger is in the classifier: if it reads
   `.daedalusignore`, the number a human reviews becomes narrowable by one
   line while the number nobody reads stays honest, and the invariant survives
   in letter while dying in practice. Whatever classifies must not be a
   one-line config edit.
3. **Move run artifacts out of the walked tree.** Changes where receipts live —
   a storage decision with evidence-retention consequences.
4. **Derive the census from tracked files.** Reproducible on any clone at a
   revision; not narrowable by an unreviewed config edit, because hiding a
   module would mean not committing it, and an uncommitted module is not
   architecture. It deletes the problem instead of classifying it. The cost is
   that genuinely untracked-but-real code stops being reported, which on this
   tree is the 1082 run artifacts and little else.

**Recommendation: option 4, with option 2 as the follow-on** if a project-vs-
artifact split is still wanted after the census is reproducible. Either is a
Work Packet, not a patch: both change a gate's reported shape and need an
acceptance matrix. [The four-option framing, the untracked measurement and the
shell-zone precedent came from an adversarial review of this page's first
version.]

## Addendum, same day: the declaration DOES narrow the gate — through one path

While this page was being written, a parallel lane ran `map --refresh`. The
result refutes the paragraph above that says the declaration "changes no
count", and it is the most important measurement here.

The refreshed snapshot in the working tree [MEASURED 2026-08-25, HEAD
`765b6c36`]: `digest_ok` **true**, 509 modules, `ignore.file`
`de1f022b7b6667a6` — the file restored this morning. Its module list contains
only `daedalus` 294, `experiments` 103, `scripts` 88, `tools` 19, `examples` 5.
**No `runs/`, no `vault/`, no `docs/recovery/`, no `references/`** — exactly the
directories the declaration names. A live `reach.analyse(root)` at the same
moment returns 2252 modules including all 1119 `runs/` files.

So the same tree yields 509 or 2252 depending on how the census is entered:

- `drift.scan(root)` with `index=None` → `reach` walks the filesystem itself,
  unscoped. This is the path `tests/test_mapping_drift.py::test_the_gate_does_
  not_read_the_tree_through_the_ignore_configuration` exercises, and on this
  path the invariant holds.
- `map --check` / `map --refresh` → `render.analyse_once` builds a structcore
  index when none is supplied (`render.py:615-624`, `cached_index(refresh=True)`),
  and `structcore.index` **does** apply `project_scope` (`index.py:583`). That
  index is handed to `reach.analyse(root, index=index)`, and the census that
  reaches the snapshot is scoped.

`drift.py:180-185` says the ignore configuration "cannot narrow what the gate
sees". That is true of the path the test takes and false of the path the CLI
takes. **The invariant is defended on a path the command line does not use.**

Consequences, in order of severity:

1. Adding one line to `.daedalusignore` can remove modules from what the
   committed snapshot records — the precise outcome the invariant exists to
   forbid — while the test that guards it stays green.
2. This page's Defect-1 section, and `docs/STATUS.md`, both said the
   restoration "changes no count". Both were reasoning from that docstring.
   Corrected here rather than silently edited there.
3. The 509-module snapshot now in the working tree is *scoped*, and the
   `runs/`-debris problem below does not apply to it. That makes it a better
   baseline than this page assumed — and it was produced by a lane, not by a
   reviewed decision.

[The chain `map -> analyse_once -> cached_index -> project_scope` is read from
the source and corroborated by the snapshot's contents; the direct A/B
measurement (`reach.analyse` with and without a scoped index) timed out at 600s
under concurrent load and is NOT claimed as executed.]

## What was done, exactly

| | |
|---|---|
| `.daedalusignore` | restored from `9831ddae^2`; digest matches the baseline's record. **Still untracked** — commit it or the repair is local to one box. Its `center:` line is inert and three rules are unanchored (see Defect 1) |
| `daedalus/mapping/reach.py` | scope wiring implemented, measured, **reverted**; byte-identical to HEAD (`bda7dfa0a698b2a1`) |
| `docs/architecture-state.json` | untouched. Still invalid. Re-baseline is a reviewed decision |

## How to see all of it

```powershell
python -m daedalus.interfaces.cli.entry map --check
git show 9831ddae^2:.daedalusignore | python -c "import sys,hashlib;print(hashlib.sha256(sys.stdin.buffer.read().decode('utf-8').replace(chr(13)+chr(10),chr(10)).encode()).hexdigest()[:16])"
python -m pytest tests/test_mapping_drift.py -q
```
