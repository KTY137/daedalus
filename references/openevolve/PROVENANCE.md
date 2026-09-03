# OpenEvolve — slim algorithmic reference

**Upstream:** https://github.com/codelion/openevolve
**Commit dissected:** `411fb59c886c18704caaffb611e17cf9e7d824d2`
**Upstream commit date:** 2026-07-18T21:15:47+08:00
**Fetched / dissected:** 2026-07-29
**License:** Apache-2.0 — verified two ways at the pinned SHA: the `LICENSE`
file (copied here verbatim, unmodified) and `pyproject.toml`
(`license = { text = "Apache-2.0" }`).

Apache-2.0 §4 requires that redistribution retain the license and carry notice
of modification. The vendored files here are **byte-identical to upstream**;
the only change is the filename extension, recorded below with its reason.
Files derived from this reference elsewhere in the tree carry their own
attribution header.

## What this is, and what it is not

This is a **dissection plate**, not a runtime. Nothing here is imported,
executed, or on `sys.path`. A full vendored copy of a foreign evolutionary
runtime would be a corpse we keep having to feed; what we want is the handful
of files where the actual algorithm lives, kept at hand so a claim about
"what OpenEvolve does" can be checked against source instead of memory.

**Nothing in this directory may be imported.** The graft that took ideas from
it re-implements them against our own spine; it does not call this code.

## Why the files end in `.py.txt` (do not "fix" this)

The extension is load-bearing and was chosen after a measurement, not a taste.

Four repo scanners walk the tree looking for `*.py`, and **none of them
excludes `references/`**:

| Scanner | Scope | Would vendored `.py` be picked up? |
|---|---|---|
| `daedalus/spine/docrefs.py` `_suffix_index` (line 340) | `root.rglob("*.py")`, whole repo, `_EXCLUDED_DIRS` only | **Yes** |
| `daedalus/mapping/reach.py` `_iter_py` (line 328) | whole repo root, `_IGNORE_DIRS` only | **Yes** — would report them as islands |
| `daedalus/mapping/switches.py` `_iter_sources` (line 221) | whole repo root, `_SKIP_DIRS` only | **Yes** — would invent env-var switches from their provider code |
| `daedalus/mapping/inventory.py` `_packages_on_disk` (line 316) | limited to `pyproject.toml [tool.setuptools] packages` | No — self-limiting |

The `docrefs` one is the dangerous one, because it fails **silently and
globally**. `_suffix_index` resolves a documentation reference like
`config.py` only when exactly **one** module in the tree ends with that
suffix; two makes it ambiguous, and an ambiguous suffix stops resolving.
`references/openevolve/config.py` and `cli.py` would each collide with
`daedalus/config.py` and `daedalus/interfaces/cli/entry.py`.

MEASURED on 2026-07-29, by monkeypatching `_suffix_index` in-process (no files
written to the tree, so no concurrent agent's gate run was disturbed):

```
BASELINE                    files=52  resolving=554  broken=4  skipped=122
WITH VENDORED .py           files=52  resolving=553  broken=4  skipped=123
check_denominator(554, 553) -> evidence_destroyed
```

`resolving` is the **gate denominator**. A drop makes
`daedalus.spine.docrefs.check_denominator` return `evidence_destroyed`, which
is a hard refusal — so the next agent to fix an unrelated broken docref would
have its correct fix rejected, and the cause would be a vendored file three
directories away that it never touched. Vendored prose making claims about
vendored code must never become docref candidates or shift the denominator.

Renaming to `.py.txt` closes all four scanners at once, structurally, without
editing four exclusion lists owned by three different agents — and without
relying on every future scanner remembering to exclude `references/`.

`PROVENANCE.md` itself is safe unrenamed: `docrefs.DOC_GLOBS` is
`("docs/**/*.md", "README.md")`, and `mapping/drift.py` `_doc_paths` reads
top-level `*.md` plus `docs/**`. This file is in neither scope. Verified after
landing: the corpus is still 52 files / 554 resolving.

To read a file here as Python, copy it to a scratchpad — do not rename it in
place.

## What was taken, and why

Only the files where the algorithm actually lives. Deliberately **excluded**:
`controller.py` (their orchestration loop — we have our own spine),
`config.py` (their knobs; the constants worth having are transcribed below
instead), `process_parallel.py`, `api.py`, `cli.py`, the `llm/` clients,
`openevolve-run.py`, `configs/`, `examples/`, `tests/`.

| File here | Upstream path | Lines | Why kept |
|---|---|---|---|
| `database.py.txt` | `openevolve/database.py` | 2616 | The whole population model: MAP-Elites feature grid, the elite archive, island topology + migration, and every parent/inspiration sampling strategy |
| `prompt_sampler.py.txt` | `openevolve/prompt/sampler.py` | 740 | How parent + inspirations + artifacts become one prompt |
| `prompt_templates.py.txt` | `openevolve/prompt/templates.py` | 238 | The prompt strings the sampler assembles; `sampler.py` is unreadable without them |
| `evaluator.py.txt` | `openevolve/evaluator.py` | 727 | The cascade (`_cascade_evaluate`) and their evaluator contract |
| `code_utils.py.txt` | `openevolve/utils/code_utils.py` | 299 | SEARCH/REPLACE diff parsing vs full-rewrite parsing — the mutation-format question we have measured locally |

## Empirical constants worth stealing (MEASURED from the pinned SHA)

These encode their tuning runs and are free evidence. All line numbers are
`openevolve/config.py` at `411fb59`. We have **not** validated any of them on
our workload — they are a starting prior, not a result.

| Constant | Value | Line |
|---|---|---|
| `population_size` | 1000 | 321 |
| `archive_size` | 100 | 322 |
| `num_islands` | 5 | 323 |
| `elite_selection_ratio` | 0.1 | 326 |
| `exploration_ratio` | 0.2 | 327 |
| `exploitation_ratio` | 0.7 | 328 |
| (implied random ratio) | 0.1 | — |
| `feature_dimensions` | `["complexity", "diversity"]` | 337 |
| `feature_bins` | 10 per dimension | 347 |
| `diversity_reference_size` | 20 | 349 |
| `migration_interval` | every 50 generations | 351 |
| `migration_rate` | 0.1 of population | 352 |
| `num_top_programs` (into prompt) | 3 | 268 |
| `num_diverse_programs` (into prompt) | 2 | 269 |
| `cascade_evaluation` | True | 385 |
| `cascade_thresholds` | `[0.5, 0.75, 0.9]` | 386 |
| `checkpoint_interval` | 100 iterations | 421 |
| `diff_based_evolution` | True | 436 |
| `max_code_length` | 10000 | 437 |

The three sampling ratios (0.2 / 0.7 / 0.1) are the single most transferable
number here: their loop spends **70% of its budget exploiting the archive**,
only 20% exploring the current island, 10% uniformly random
(`database.py:1280-1298`).

Note their `cascade_thresholds` are thresholds on **score**, gating access to
progressively harder test stages. They are *not* a cost cascade. Ours would be
a cascade on **price** (free bench → cents → real money). Same shape, different
axis; the constants do not transfer.

## The one thing not to copy

`evaluator.py.txt:_cascade_evaluate` loads the evaluation module with
`importlib.util.spec_from_file_location` + `spec.loader.exec_module(module)`,
after `sys.path.insert(0, eval_dir)` — it executes evaluator code **in the
orchestrator process**, unisolated, with no worktree boundary. Our
`daedalus/eval/correctness.py` freezes the selection before candidate code
runs and measures in a disposable guarded worktree. Do not regress toward
their model.
