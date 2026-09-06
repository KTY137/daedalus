# G1-WIKI-01 — Wiki instruments stop reading frozen copies of the tree

Packet ID: G1-WIKI-01
Artifact role: primary
Active gate: 1
Classification: ALIGNED
Owner: repository owner
Base revision: 585b7ea4e141332928ad6c9578b9c9997e55f247
Dependencies: `daedalus/wiki` (plan, verify, metrics, qml_index, `__main__`),
registry rows `cli.wiki_plan` and `cli.wiki_verify` (unchanged); owner
instruction 2026-09-05 21:30 ("arbeite weiter bis daedalus komplett ist")
after the docs/wiki regeneration of the same day
Plan revision 12, SHA-256
`126594137ebf1854458e625b64831c431c64b4a9f3dd8ca2b03c7867e0e8d8fb`.
Status: built and builder-verified 2026-09-05; measurements below; no
registry row, digest pin, fence or policy touched.

## Primary acceptance claim

`daedalus.wiki.plan`, `daedalus.wiki.verify`, `daedalus.wiki.metrics` and
`daedalus.wiki.qml_index` no longer walk a frozen application bundle
(PyInstaller one-dir, marker `_internal/base_library.zip`) as if it were this
project's source, and each says so: `plan` returns the 63 real topics instead
of 153, `verify` counts real modules only, `metrics` names the bundles in
`could_not_measure`. The exclusion is structural (a marker, like `pyvenv.cfg`
and `.git`), is applied by one shared walker that prunes at directory level,
and every regression test carries a positive control that removes the marker
and shows the copy leaking back in. `metrics` and `__main__` gain their first
tests.

## Scope

In scope:

- `daedalus/wiki/treewalk.py` (new): the three structural rules and the
  pruned `os.walk` (`walk`, `walk_files`, `foreign_roots`, `foreign_kind`).
- `daedalus/wiki/plan.py`: `survey` walks through `treewalk`; the private
  `_venv_roots`, `_nested_checkout_roots`, `_usable` are deleted (their
  measurements moved into `treewalk`'s docstring).
- `daedalus/wiki/verify.py`: `exclusions` lists nested checkouts AND frozen
  bundles via `treewalk.foreign_roots`; `index_symbols`, `tree_vocabulary`,
  `_config_keys` and `tree_files` walk through `treewalk`; dead `_in_excluded`
  deleted; `_config_keys` does one walk instead of four `rglob`s. Its
  `SKIP_DIRS` gains the artefact names `plan` and `metrics` already skip
  (`runs`, `artifacts*`, `scratchpad`, `build`, `dist`, `htmlcov`, `.tox`,
  `spikes`); `docs` deliberately stays in. Reason, MEASURED 2026-09-05 after
  the bundle rule: 3084 of 4661 `source_modules` were six wheel-build and
  smoke-install copies of `daedalus` under the gitignored `build/`.
- `daedalus/wiki/metrics.py`: `_walk` prunes by `treewalk.foreign_kind` and
  reports what it left out by kind (nested checkout, venv, frozen bundle).
- `daedalus/wiki/qml_index.py`: the existing pruned walk also applies
  `treewalk.foreign_kind`.
- `daedalus/wiki/__init__.py`: docstring names all generate/measure modules
  (finding D3 of `runs/wiki_findings_20260905.md`).
- Tests: `tests/test_wiki_plan.py` (+1), `tests/test_wiki_verify.py` (+2, one
  parametrized over four artefact names),
  `tests/test_wiki_metrics.py` (new, 4), `tests/test_wiki_cli.py` (new, 6).
- Docs: `docs/wiki/architecture/wiki.md` (module row, tests table, numbers).

Forbidden and untouched: `daedalus/spine/effect_boundary.py` and every digest
pin; the size caps of the three instruments and `plan`/`metrics` `SKIP_DIRS`
(only `verify`'s list changed, for the measured reason above); the effectful
generation step (fan-out, web search, page writing), which still does not
exist inside this package; anything outside `daedalus/wiki`, its tests and
its wiki page.

## Contracts and behavior

Added:

- `treewalk.foreign_kind(dir) -> "nested_checkout" | "venv" | "frozen_bundle" | None`,
  tested in that order; `root` itself is never tested.
- `treewalk.walk(root, skip_dirs, excluded)` / `walk_files(..., suffixes)`:
  deterministic (sorted names), prunes before descending, does not follow
  symlinks (`os.walk` default), resolves `root` and `excluded` on both sides so
  a relative root cannot make an exclusion fail open.
- `treewalk.foreign_roots(root, skip_dirs)`: outermost foreign directory per
  kind, over the same pruned tree.

Changed:

- `verify.exclusions` now also returns frozen bundle roots; `tree_files` (the
  `missing_file_reference` source) is pruned structurally too, so a filename
  that exists only inside a nested checkout or bundle is now reported as
  missing rather than acquitted (non-blocking finding kind; the wiki verdict
  is unaffected).
- `metrics.wiki_health(...)["could_not_measure"]` gains one line per foreign
  kind present ("N frozen application bundle(s) not walked -- ...").

Deleted: `plan._venv_roots`, `plan._nested_checkout_roots`, `plan._usable`,
`verify._in_excluded`, `metrics._nested_checkout` (all private, no external
caller: `grep -rn` over `daedalus/ tests/ tools/ scripts/` 2026-09-05).

Unchanged: the two registry rows, their effects (`FILESYSTEM_WRITE` only),
`begin_effect` above argument handling in both `main`s, output files
`runs/wiki_plan.json` and `runs/wiki_verify.json`, all finding kinds and the
verdict rule.

## Acceptance matrix

| # | Check | Command | Result (MEASURED 2026-09-05) |
| --- | --- | --- | --- |
| 1 | Bundle is not a topic; marker removed -> topic again | `pytest tests/test_wiki_plan.py -k frozen` | red before, green after |
| 2 | Bundle supplies no evidence, demands no page; marker removed -> `uncovered_module` | `pytest tests/test_wiki_verify.py -k frozen` | red before, green after |
| 2b | An artefact tree (`build`, `dist`, `artifacts`, `htmlcov`) supplies no evidence and demands no page; the same module under `src/` is counted | `pytest tests/test_wiki_verify.py -k artefact` | 4 passed; NOT observed red first (test and skip list landed together), non-vacuity rests on the positive control |
| 3 | Bundle left out of the graph and named; marker removed -> walked | `pytest tests/test_wiki_metrics.py` | red before (bundle case), green after |
| 4 | CLI exit codes 2/3, argv contract to delegates, default `k` | `pytest tests/test_wiki_cli.py` | 6 passed (new) |
| 5 | No existing wiki behavior regressed | `pytest tests/test_wiki*.py tests/test_index_wiki_layer.py tests/test_markdown_wikilinks.py tests/test_registry_new_doors.py` | 163 passed in 41.2 s before the artefact rule; 118 passed in 39.7 s for the six wiki/registry suites after it |
| 6 | Real tree, planner | `python -m daedalus.wiki.plan . 10 docs/wiki` | 63 topics / 300825 lines in 3.4 s (before: 153 topics / 760014 lines, > 300 s, walk not pruned) |
| 7 | Real tree, verifier, bundle rule only | `python -m daedalus.wiki.verify . docs/wiki` | PASS, `source_modules` 4661, coverage 29.4% (1370/4661), 21:38:18-21:42:05 = 3 min 47 s (before: 6133, 22.3%, 9 min at 20:46; 24 min at 20:15). `health`: 2 frozen bundles and 11 nested checkouts named in `could_not_measure`, 14 s. |
| 7b | Real tree, verifier, both rules | same | PASS, `source_modules` 1577 (= tests 777 + daedalus 474 + experiments 174 + scripts 89 + tools 28 + docs 22 + .claude 8 + examples 5), coverage 86.9% (1370/1577), `uncovered_module` 207, 21:46:15-21:48:19 = 2 min 4 s. `missing_file_reference` 8 -> 13: filenames that existed only inside artefact trees are now reported (non-blocking, verdict unchanged). |
| 8 | Registry untouched | `git diff --stat daedalus/spine/effect_boundary.py` | empty |

Refusal / fault cases covered by tests: root that is not a directory (exit 2
for all three subcommands; `metrics` reports "nothing was walked" instead of
an empty tree); `health` without a callable `wiki_health` (exit 3, never 0).

## Migration and rollback

No data migration: `runs/wiki_plan.json` and `runs/wiki_verify.json` keep
their schema; counts change because copies are no longer counted. Rollback is
`git checkout -- daedalus/wiki tests/test_wiki_plan.py tests/test_wiki_verify.py`
plus deleting the four new files; nothing else depends on `treewalk`.

## Evidence, expected failures and review

- Builder run: 163 passed (see matrix row 5); the three new bundle tests were
  observed red before the implementation (TDD, 3 failed / 64 passed at 21:34).
- Planner before/after: `runs/wiki_plan.json` (after) vs
  `runs/wiki_plan_10_filtered.json` (the manual filter used for the docs/wiki
  regeneration, which G1-WIKI-01 makes unnecessary).
- Verifier after the bundle rule alone: PASS, 4661 modules, 3 min 47 s. The
  denominator was then measured by top-level directory: `build` 3084, `tests`
  777, `daedalus` 474, `experiments` 174, `scripts` 89, `tools` 28, `docs` 22,
  `.claude` 8, `examples` 5. `build/` is gitignored and holds six copies of
  the package (wheel builds, smoke installs), which is why the artefact names
  were added to `verify.SKIP_DIRS` in the same packet. Verifier after both
  rules: see the addendum line below. `tests/` (777) stays counted: `verify`
  never excluded test modules, and the module pages link their tests; whether
  a test module should count as "uncovered" is a review question, not a
  silent change. Final: 1577 modules, 86.9% coverage, 2 min 4 s (matrix row 7b).
  After the same-day coverage additions to docs/wiki (fixtures, loose
  interface modules, s03/s04, two single-file probes): 74 pages, 88.7%
  (1399/1577), `uncovered_module` 178 (tests 53 of the first 80 listed, docs
  22, examples 5), PASS, 2 min 14 s at 21:51. Every `.py` under `daedalus/`,
  `experiments/`, `tools/` and `scripts/` is now linked from a page.
- Expected, retained negatives: the `missing_file_reference` for
  `asyncio.Lock` (`lock` is in `FILE_SUFFIXES`) is unchanged and out of scope;
  `SKIP_DIRS` divergence between `metrics` and `verify` remains an open
  question on the wiki page.
- Review questions: (a) should `verify.exclusions` also list venvs found by
  `pyvenv.cfg` (today they are pruned by the walk but not listed, because the
  list is documentation of what may not vouch, and a venv never could);
  (b) is `_internal/base_library.zip` the right marker for PyInstaller
  one-file bundles too (no, and none exists in this tree; a one-file bundle
  has no directory to exclude).
- Residual risk: a frozen bundle produced by a tool other than PyInstaller
  (Nuitka, briefcase) carries no such marker and would be walked again; adding
  its marker is one line in `treewalk`, with the same positive-control test.
