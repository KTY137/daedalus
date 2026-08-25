# G0-CI-02 — Historical Forest Baseline Binding

## Packet identity

- Plan classification: **ALIGNED**
- Active delivery gate: **Gate 0**
- Exact parent revision:
  `c7a1a7c5f20c4b82b4f051784ada94f1f382f439`
- Parent packet: `G0-CI-01`
- Candidate branch: `codex/g0-forest-baseline-binding-20260825`
- Packet owner: **Codex implementation lane**; merge, promotion, release, and
  Gate decisions remain repository-owner decisions.
- Primary claim: repository-backed Forest-v2 baseline assertions replay against
  the exact historical source trees that produced their measurements rather
  than silently treating the moving checkout as that corpus; external stdlib
  rows remain descriptive evidence bound to their exact content, not universal
  semantic thresholds.
- Merge, promotion, release, Gate transition, and plan amendment: not requested.

## Reproduced problem

The consolidated current tree made three retained Forest-v2 checks red:

1. the s02 kernel row expected 4,203 functions but measured 4,592 in the moving
   current `daedalus/` tree;
2. the s07 known-hit query expected the intentionally owner-retired
   `tools/iron_plan_guard.py`, which cannot exist in the current tools tree;
3. the s07 retained known miss moved outside its top-five ceiling as unrelated
   files accumulated in the moving Forest corpus.

All three failures reproduce at the G0-CI-01 parent. They are not caused by the
new workflow definition. Replacing the old values with current values, changing
the frozen query, selecting a new gold file, raising the rank ceiling, skipping
missing history, or restoring the retired guard would destroy rather than
repair the baseline.

Fresh Windows-runner validation then exposed a fourth false contract: the s02
stdlib test called `type_name_resolution_pct > 90` version-independent. The
Windows Store and python.org CPython 3.10.11 distributions ship different
stdlib trees and measure 98.78% and 88.96% respectively. The universal claim is
retracted; the 88.96% failure and both exact content pins are retained.

## Source authority and exact bindings

Git source objects are the authoritative artifacts:

| use | exact revision | exact selected tree |
| --- | --- | --- |
| s02 published kernel row | `deabb5182e94eeb939611aa835f72ca8234e84c8` | `daedalus` = `aacb26ef791f0b0c96a0a840e24c6ba63c32bab8` |
| s07 leak-closed real-tree self-tests | `dd1a4a2103a9952963e267c0bf5f4f3582d1e2ab` | `tools` = `740685aa810a54b35ece54717b6ed5f42379eb04`; `experiments/forest_v2` = `ff4df8704d9da6de6e18395a2192412a5f125300` |

The current BM25 and type-plane implementations remain the code under test.
Only the repository-backed corpus bytes are revision-bound. The old result
tables and original scientific record are not rewritten.

## Exact in-scope paths

- `experiments/forest_v2/_historical_tree_fixture.py`
- `experiments/forest_v2/test_historical_tree_fixture.py`
- `experiments/forest_v2/s02_types/test_external_corpora.py`
- `experiments/forest_v2/s07_bm25/test_bm25_index.py`
- `experiments/forest_v2/s09_eval/gitio.py`
- `experiments/forest_v2/s09_eval/test_gitio.py`
- appended resolution note in `experiments/forest_v2/README.md`
- this work packet

## Forbidden paths and authority

- master plan and amendment chain
- Daedalus kernel, policy, evaluator, ledger, admission, trust, release,
  promotion, and runtime implementation
- BM25 queries, gold paths, contamination exclusions, or top-five miss ceiling
- s02 published numbers and result JSON
- `type_plane.py`, `bm25_index.py`, and `measure_bm25.py`
- mutation of the current source checkout, index, refs, branch, Git objects, or
  worktree metadata

No candidate, evaluator, policy, promotion, merge, or release authority changes.

## Historical fixture contract

The fixture reuses the existing `s09_eval.gitio` read-only gate. Source-content
Git access is limited to `rev-list`, `rev-parse`, `ls-tree`, and
`cat-file --batch`.
Repository/worktree boundary metadata is read only to refuse unsafe output
destinations. The Git gate blocks all Git transport, requests no-lazy behavior
where supported, disables prompts, replacements, and optional locks, and strips
every inherited `GIT_*` environment variable before adding back only the
explicit safety settings.
The re-added settings include an empty Git protocol whitelist, so repository
config cannot opt a promisor remote or custom helper back into transport.

It requires:

- a full lowercase 40-hex commit that resolves to itself;
- one or more canonical safe repository prefixes;
- a caller-owned destination that does not yet exist, whose parent exists, is
  below the OS temporary root, and overlaps none of the current, common, admin,
  main, or linked-worktree boundaries exposed by the source metadata;
- a `.git`-named common directory; common paths with any other basename fail
  closed. Git records no backlink to the original worktree when a separate
  admin directory itself is named `.git`, so that layout cannot be globally
  distinguished from a conventional main worktree by repository metadata;
- no `.git` file, directory, or symlink on any destination ancestor up to the
  trusted temporary root, closing unregistered gitfile aliases as well;
- Windows-portable names with no drive/ADS syntax, reserved device component,
  DOS short-alias syntax, trailing dot/space, control character, or
  case/Unicode-normalisation collision, and no component beyond 255 UTF-8
  bytes or UTF-16 code units;
- regular 100644/100755 blobs only;
- complete selected prefixes with no unexpected paths;
- exact size and recomputed Git blob SHA-1 for every payload before any output
  directory is created;
- a `rev-list --missing=print` proof that every selected blob is already local
  before `cat-file`; promised trees are likewise unable to cross the global
  transport boundary.

Verified bytes are written only under a Pytest temporary directory. The
materializer performs no checkout, reset, worktree operation, archive command,
lazy source-object fetch, source repository write, or skip-on-missing-history
behavior. An adversarial contract test constructs disposable linked worktrees:
a non-`.git` separate common path is refused globally; for a separate admin
directory named `.git`, a destination below the otherwise undiscoverable
original worktree is refused by the independent marker scan while a safe
sibling outside every worktree is allowed.

## Scientific disposition

- s02's two exact historical comparisons use a module-scoped materialized
  `daedalus/` corpus from its publication revision.
- s02's moving-corpus arithmetic and external-corpus property checks still run
  against the current environment.
- s07's three real-tree known hits and one retained miss use the exact
  leak-closed dd1 `tools/` and `experiments/forest_v2/` corpus and exclusions.
- the stdlib row is a descriptive, content-pinned schema/arithmetic contract;
  the disproven universal `> 90%` threshold is removed and explicitly retracted.
- the retired guard exists only as read-only historical test data in a Pytest
  temp directory; no active code or workflow calls it.
- the initial pre-firewall s07 run recorded rank 3. The leak-closed dd1 run and
  current BM25 implementation both yield rank 2 on dd1's exact corpus, which
  remains a miss and satisfies the unchanged `rank > 1` and `rank <= 5` contract.

## Acceptance and refusal matrix

- incorrect, abbreviated, unavailable, or mismatched revision: red;
- unsafe, missing, non-canonical, or empty prefix: red;
- non-portable Windows path or portable-filesystem collision: red;
- non-regular leaf entry (symlink, submodule, or other non-blob leaf): red;
- existing, missing-parent, non-temp, repository, Git-admin, or linked-worktree
  destination: red without modification;
- non-`.git` Git common-directory path: red before output;
- separate admin directory named `.git`: a target below the original worktree
  is red via its `.git` marker; a safe sibling outside all worktrees is allowed;
- destination below any `.git` marker, including an unregistered gitfile alias:
  red before output;
- missing, truncated, or digest-mutated blob: red before destination creation;
- promised but locally unavailable Git object: red without network fallback;
- `blob:none` and `tree:0` partial-clone mutants: red with byte-for-byte stable
  source/Git metadata, no lock/temp file, and no destination;
- unavailable historical subtree: red, never skipped;
- s02 exact published row reproduces all seven pinned values;
- all three s07 known hits rank first;
- retained s07 negative result stays strictly below first and within top five;
- current queries, golds, ceilings, published numbers, and result JSON remain
  byte-unchanged.

## Budgets and honest non-claims

- s02 materializes 291 historical files; s07 materializes 28.
- all historical-fixture source reads are local Git object reads; existing s02
  external/current-corpus checks remain read-only filesystem analysis. All
  writes are temporary test data.
- focused validation is 83 tests and measured 22.24 seconds on Windows,
  Python 3.10;
- the helper plus complete s02, s07, and s09 slices are 331 tests and measured
  29.94 seconds on the same runner.
- this packet does not claim a new experimental result, live-current-tree
  retrieval quality, full-suite acceptance, or GitHub System-CI acceptance.
- GitHub execution remains separately blocked by the account billing condition
  documented in G0-CI-01.

## Verification

    $env:PYTHONDONTWRITEBYTECODE = "1"
    $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
    $env:PYTHONHASHSEED = "123456"
    python -m pytest -q -p no:cacheprovider experiments/forest_v2/test_historical_tree_fixture.py experiments/forest_v2/s02_types/test_external_corpora.py experiments/forest_v2/s07_bm25/test_bm25_index.py
    python -m pytest -q -p no:cacheprovider experiments/forest_v2/test_historical_tree_fixture.py experiments/forest_v2/s02_types experiments/forest_v2/s07_bm25 experiments/forest_v2/s09_eval
    python -m py_compile experiments/forest_v2/_historical_tree_fixture.py experiments/forest_v2/test_historical_tree_fixture.py experiments/forest_v2/s02_types/test_external_corpora.py experiments/forest_v2/s07_bm25/test_bm25_index.py experiments/forest_v2/s09_eval/gitio.py experiments/forest_v2/s09_eval/test_gitio.py
    python -m pytest -q -ra -p pytest_asyncio.plugin -p _hypothesis_pytestplugin

The complete suite must run from a frozen tree without ignored build output in
the checkout. Collection, a partial run, or a run spanning edits is not a pass.

A broad `compileall experiments/forest_v2` probe is deliberately not accepted
as this packet's syntax check: it reaches
`s03_data/corpus/src/unparseable_fixture.py`, whose invalid syntax is
intentional parser fixture data. That observed SyntaxError is retained; only
the changed executable Python files are compiled directly.

## Rollback

Before owner merge, deleting this isolated branch removes the candidate without
touching `main`. After merge, revert this packet commit. The historical source
objects and original measurements remain unchanged in either case.

No automatic merge, promotion, owner approval, release, or Gate transition is
authorized.
