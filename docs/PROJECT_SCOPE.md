# Project scope — `center` and `.daedalusignore`

## The problem, measured

`structcore` had one exclusion mechanism: `_IGNORE_DIRS`, a hardcoded blocklist of things that are never
source *anywhere* (`.git`, `node_modules`, `__pycache__`, `target`). It cannot express the case that actually
bites — material that is **real, checked-in, source-shaped, and still not this project's code**: vendored
trees, copied dependencies, spec examples, generated skeletons, scratch dirs, downloaded firmware.

On `project_tct`, the app is `TCT_app/`. The repo also contains `reference/`, `sources/`, `artifacts_claude/`,
`artifacts_codex/`, `design_assets/`, `lab_assets/`, `scratchpad/`, and `docs/`. Of 6,798 files scanned,
**6,413 were not the project**.

The consequences were not subtle:

| | whole repo | `center = TCT_app` |
| --- | --- | --- |
| wall (project_tct) | 171.0s | **22.3s** (7.68×) |
| files treated as core | 6,798 | 385 |
| exact clone clusters | 2,794 | 196 |
| `import_edges` | 8,558 | **8,558 (unchanged)** |

**93% of the duplication report — 11,001 of 11,859 clusters — contained no `TCT_app` file at all.**

And the flagship output was simply wrong. Top hotspots *before* scoping:

```text
reference/Printrun/printrun/gcoder_line.c
reference/Printrun/v3/Lib/site-packages/wx/core.pyi
sources/Marlin-2.1.2.8/Marlin/src/lcd/e3v2/jyersui/dwin.cpp
reference/Printrun/v3/Lib/site-packages/Cython/Compiler/ExprNodes.py
```

*After:*

```text
TCT_app/controller/scan_controller.py
TCT_app/tests/test_qml_kit_surface.py
TCT_app/gui/style.py
TCT_app/composition_root.py
```

"What should I distill or refactor?" was answering with Cython's compiler internals and wxPython stubs.

## The model: center, shell, outside

Three concentric zones. The middle one is the point.

* **core** — inside a declared `center` root. Full metrics, all clone passes, hotspot ranking, and free
  slice expansion.
* **shell** — in the repo, outside the center (or matched by an ignore rule). Still indexed and **still
  resolvable as an import target**, so edges pointing into it stay true — but withheld from every metric,
  and treated as a **boundary** by the slicer: you may name it, you do not expand through it.
* **outside** — not in the repo. An external dependency; a name only.

An empty center means the whole repo is core — the historical behaviour, and what every unconfigured repo
keeps getting.

### Why `center` beats a blocklist

`.daedalusignore` answers "what is *not* my code?" by enumeration, which is open-ended: on `project_tct` it
takes eight entries, and every newly vendored directory is a rule someone forgot to add. `center` answers the
same question by declaration — *this* is the project — in one line that stays correct as the repo grows.

## Configuration

**Per project** (`projects/<name>.json`) — the primary route:

```json
{
  "repo_root": "C:\\Users\\nukei\\Desktop\\project_tct",
  "center": ["TCT_app"],
  "ignore": ["@tests"]
}
```

`center` declares the tree; `ignore` carves exceptions *within* it. Both live in the project
config so a project can be scoped without adding files to a repo it may not own.

### The `@tests` preset

Tests are real, first-class code — but they are not **distillation targets**, and they dominate
the rankings they pollute. Measured on `TCT_app`:

| | tests in | tests out |
| --- | --- | --- |
| core files | 385 | **187** |
| wall | 29.9s | **18.5s** |
| exact clone clusters | 196 | 118 |
| clusters touching tests | **392** | 6 |
| test files in top-15 hotspots | **4** | 0 |

Tests were **half of the application** by file count, and **386 clusters were test-on-test
duplication** — test boilerplate is massively self-similar and completely unactionable as a
refactor target. Removing it surfaced real code that had been crowded out of the ranking
(`devices/oscilloscope.py`, `gui/analysis_viewmodel.py`).

`@tests` expands to:

```gitignore
tests/  test/  test_*.py  *_test.py  *_test.go  conftest.py
__tests__/  *.test.ts  *.test.tsx  *.test.js  *.spec.ts  *.spec.js
```

Deliberately narrow: it must not swallow `testing_utils.py`, `latest.py` or `contest.py`, all
of which are covered by a regression test. An unknown `@name` is passed through as a literal
pattern rather than dropped — a silent no-op would look exactly like a preset that did nothing.

**CLI:**

```powershell
python -m daedalus.structcore C:\...\project_tct --center TCT_app
```

**Environment** (one-off scoping, no file edits):

```powershell
$env:DAEDALUS_CENTER = "TCT_app"      # os.pathsep-separated
$env:DAEDALUS_IGNORE = "scratch/"     # extends .daedalusignore
```

Precedence for center: explicit argument (project config / CLI) over `DAEDALUS_CENTER`. Center matches on
**path segments**, so `app` covers `app/x.py` but never `apparel/x.py`.

### `.daedalusignore`

Still useful, and it **composes with** center: center says which tree is yours, ignore carves exceptions
*within* it (generated files, a vendored subfolder inside your app).

```gitignore
# comments and blank lines are skipped
reference/            # a directory and everything under it
*.generated.py        # glob on the filename
docs/vendor/          # contains a slash -> anchored at the repo root
!reference/keepme.py  # negation: re-include something excluded above
```

Rules apply **in order, last match wins** — that is what makes `!` work, so line order is load-bearing.
Anchoring follows gitignore: a pattern containing a slash is repo-root relative; one without matches a
segment at any depth. A trailing `/` marks a directory rule, which matches the directory and all descendants
but deliberately **does not** match a *file* of that name (`build/` will not swallow a script called `build`).

#### One deliberate divergence from gitignore

Matching is built on `fnmatch`, whose `*` **crosses path separators**. Real gitignore stops `*` at a `/` and
reserves `**` for spanning, so `docs/*` here also matches `docs/a/b/c.py` where git would match only
`docs/c.py`. This is a subset chosen to avoid a full gitignore engine (or a `pathspec` dependency) for a
feature whose realistic input is a handful of directory names. If that stops being enough, the honest fix is
to take the dependency rather than keep growing this.

## Why "withheld from metrics, kept for imports"

Shell files are still collected and still parsed. That keeps the dependency graph honest — `import_edges` was
**identical** (8,558) before and after scoping — while everything metric-bearing is withheld:

| Shell files are… | |
| --- | --- |
| in `import_edges` / `dependencies` / `fan_in` | ✅ kept |
| in `modules` (per-file metrics) | ❌ withheld |
| in `hotspots` / `module_heat` | ❌ withheld |
| in all four clone passes | ❌ withheld |
| in `languages` LOC/file summary and `n_files` | ❌ withheld |
| in the symbol resolver used by `slice.py` | ❌ withheld |

**This split is nearly free**, because scan time is not where it looks: the per-file parse is ~1.9s of a
~102s warm scan while the clone passes are ~96% of it. Keeping the parse buys an honest dependency graph for
~2% of the budget; dropping shell files from clone clustering skips the part that is actually expensive.

### It also stops slice fan-out

The slicer tests `modules` membership before expanding an edge, and shell files are not in `modules`, so they
can never become `dep_rels` — the slicer cannot expand through the boundary.

This used to be *accidental*: neighborhood expansion was built from a python-only dotted-module lookup keyed
off `modules`, so the boundary held as a side effect of how that lookup was populated. Once expansion moved
onto `idx["import_edges"]` (which is deliberately shell-**inclusive**, so an edge pointing into vendored code
still resolves to a real file instead of reading as "external"), the side effect was gone and the test became
an explicit one. Edges that stop at the boundary are counted and reported as `shell_boundary_stops` on the
slice result — a slice that stopped at the shell and a slice with no neighbors at all otherwise look
identical. Covered by `test_slice_does_not_fan_out_into_shell` and its non-Python twin.

## Exclusion is never silent

A duplication report that quietly shrank is indistinguishable from a codebase that got cleaner — the same
trap as `report.truncated` and the `max_files` ceiling. So the index carries an `ignored` block
(`count`, `n_files_scanned`, `center`, `ignore_patterns`, `source`, bounded `sample`, `truncated`), it is
surfaced by `structure_summary` for `/api/structure` and the UI, and the CLI prints:

```text
scope:   6413 of 6798 files are SHELL, withheld from metrics [center=TCT_app]
         (shell stays resolvable as an import target; it is not expanded through)
```

## Cache correctness

`cached_index` folds a fingerprint of the effective scope (center + ignore rules) into its cache key. Without
that, changing either would hand back the index built under the *old* scope — presenting as "the feature does
nothing", and only until the next restart, which is the worst kind of bug to chase. Unscoped repos keep their
bare path key, so nothing changes for them.

## ⚠️ Rust parity gap (open)

`structcore-rs/src/index.rs` carries its own `const IGNORE`, documented as *"Mirrors `index.py::_IGNORE_DIRS`
exactly"* — a hand-maintained duplicate. **It does not know about `center` or `.daedalusignore`**, so the two
engines will now report different duplication for the same repo. Before the Rust engine is used for anything
user-facing, scope must become a shared contract both read, rather than a third hardcoded list.

## Tests

`tests/test_structcore_ignore.py` — 25 tests: pattern semantics (directories, anchoring, globs, negation,
comments), center as path-segment prefix, multiple center roots, center∘ignore composition, the
metrics/imports split, hotspot and clone exclusion, slice boundary, cache-key invalidation for both center
and ignore edits, and determinism of the shell set.
