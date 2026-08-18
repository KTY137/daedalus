# EXPERIMENT: Forest v2 pre-study — call-resolution gap baseline

Classification: `EXPERIMENT` (master plan §1, §11 Gate 2 prework).
Status: read-only pre-study. **No production promotion. No production import
may reference this directory.** The pre-study may read production code; it
may never be wired into it.

## Frozen specification

- **Hypothesis (falsifiable):** Gate-2 function/method resolution will
  materially increase the fraction of statically attributable call sites in
  the production packages, and that increase will make at least the three
  measured invisibility classes of the Gate-0 effect scanner (cross-module
  sinks, dispatch tables, subclass evasion) mechanically detectable.
- **Baseline (this pre-study):** measure, with the same stdlib-AST method the
  effect boundary uses, how many call sites a same-module fixed point can
  resolve today. The number must exist BEFORE any resolver is built, so the
  later experiment cannot grade its own homework.
- **Scope:** read-only AST analysis of `daedalus`, the tool directory and the
  run directory. No imports of repository code, no writes, no network, no
  subprocess. The probe prints one JSON object.
- **Budget:** ≤ 2 hours of implementation, one probe module, re-runnable in
  seconds. No model calls, no spend.
- **Expiry:** 2026-10-31. If Gate 2 has not consumed this baseline by then,
  re-measure before use (the tree will have moved) and retire this document.
- **Kill criterion linkage:** if a later resolver does not beat this baseline
  on attribution while keeping the quality/cost frontier (plan §14), the
  four-plane track's code-plane investment must be re-argued, not assumed.

## Measured baseline (2026-08-17, this worktree @ 05d5ba3)

`python experiments/forest_v2/probe_call_resolution.py` →

| quantity | value |
| --- | ---: |
| files parsed | 307 (0 unparseable) |
| module functions / methods | 2850 / 1551 |
| call sites | 42,725 |
| same-module resolvable | 6,616 (**15.5%**) |
| cross-module or dynamic | 36,101 |
| unresolvable call shape | 8 |
| resolution gap (upper bound) | **84.5%** |

Honest caveat: the 84.5% is an UPPER bound on what function/method resolution
could address — it counts stdlib calls, method calls on instances, and
attribute chains that no repo-internal resolver should claim. The later
experiment must therefore report its gain against this same counting rule,
not against a friendlier denominator.

Context that motivated the probe: the Gate-0 inventory measured three
concrete invisibility classes caused by the same-module limit —
`tools/guarded_call.py` (cross-module-only sink), `tools/system_check.py`
(dispatch table), `runs/council/room_server.py` (subclass evasion). All three
are now hand-registered rows; a resolver that finds them mechanically has a
ready-made acceptance test.

## Continuation 1 (2026-08-18): import-binding resolution probe

Sub-spec, frozen before the run: same frame (stdlib AST, read-only, no repo
imports, no writes/network/subprocess, one JSON, no spend), budget ≤ 2 h,
same counting rule and same expiry as the pre-study.  Question: how much of
the 84.5% gap does the CHEAPEST resolver (per-file import bindings, whole
tree incl. function-level imports) already attribute, and does it make the
three measured invisibility classes mechanically detectable?

`python experiments/forest_v2/probe_cross_module_resolution.py` @ this
worktree (base 4fb2251; baseline re-measured here: 44,115 sites, 15.5%):

| quantity | value |
| --- | ---: |
| attributed total (same-module + cross-module) | **30.3%** (from 15.5%) |
| cross-module, repo-verified | 2,413 (5.5%) |
| cross-module, external-attributed (unverified) | 4,098 |
| still unattributed | 69.7% |
| classes with externally-attributed base | 39 of 812 |
| registry decorators / registered functions | 4 / 38 |

Acceptance sites (the three invisibility classes):

1. **Subclass evasion — DETECTED.** `runs/council/room_server.py` resolves
   `RoomServer -> http.server.ThreadingHTTPServer` and
   `Handler -> http.server.BaseHTTPRequestHandler` purely mechanically.
2. **Dispatch table — DETECTED (structurally).** `tools/system_check.py`
   `@check -> CHECKS` found as a registry decorator with 18 registered
   top-level functions; the call site stays a subscript, but the registered
   population is known without executing anything.
3. **Cross-module sink — DETECTED, correcting the pre-study's expectation.**
   The inventory pinned `tools/guarded_call.py` as statically invisible; that
   holds only for the same-module fixed point.  Its sink imports are
   function-level (`from daedalus.env import load_env`,
   `from daedalus.providers.deepseek import DeepSeekProvider`, lines 62/68)
   and a whole-tree import walk attributes both.  Retained as a measured
   correction: the invisibility class is narrower than documented — it is
   "invisible to same-module fixed point", not "statically invisible".
   Revisiting the `not_rediscovered` pin is Gate-2 production work, not this
   experiment's.

Honest caveats: external attributions are unverified name claims (good
enough for sink matching, not existence proofs); the registry count only
sees top-level `FunctionDef`s; the baseline's generous last-segment
same-module rule is kept unchanged for comparability, so the cross-module
buckets only ever split the baseline's cross_module_or_dynamic mass.

## Slice s07 (2026-08-18): the BM25 baseline — `s07_bm25/`

### Frozen specification

- **Hypothesis (falsifiable):** a plain lexical BM25 over the repository's
  files is a *hard* baseline for project-scale file retrieval — good enough
  that a four-plane / graph-conditioned retriever has to earn its cost, and
  cheap enough (pure stdlib, no model, no index server) that no comparison can
  excuse skipping it.
- **Why it exists at all:** the master plan requires BM25 twice — as a Gate-3
  baseline (§10) and inside a kill criterion (§13: "the full representation
  does not beat code-only or **BM25** retrieval"). A kill criterion with no
  implementation cannot fire. This slice is the implementation, frozen before
  any graph retriever exists, so the later comparison cannot grade its own
  homework.
- **Scope:** read-only, stdlib only, no repository imports, no writes, no
  network, no subprocess. Nothing under `daedalus/` may import it.
- **Budget:** ≤ 2 h implementation, three modules, no model calls, no spend.
  Full-corpus rebuild is seconds, not minutes.
- **Expiry: 2026-09-15.** The measured numbers below are bound to this tree.
  Past that date, re-run `measure_bm25.py` before quoting any of them; a
  baseline quoted from a moved tree is not a baseline.
- **Kill-criterion linkage:** if a graph-conditioned retriever does not beat
  the primary arm below at equal context budget, §13's first kill criterion
  fires and the code-plane retrieval investment must be re-argued.

### Output contract (for the s09 eval harness)

In-process — the directory is deliberately not a package, so nothing in the
production tree can import it by accident:

```python
import sys
sys.path.insert(0, str(root / "experiments/forest_v2/s07_bm25"))
from bm25_index import BM25Index, IndexConfig, CODE_DOC_EXTENSIONS

index = BM25Index.build(root, IndexConfig())      # build once
hits  = index.search("budget ceiling ledger", k=10)
ranked_paths = [hit.path for hit in hits]         # repo-relative POSIX, best first
```

- `SearchHit(rank: int, path: str, score: float, matched_terms: tuple[str, ...])`,
  `rank` 1-based and dense; ties break on `path` ascending, so a fixed tree
  gives a byte-identical ranking on every run.
- `index.rank_of(query, path)` → 1-based rank or `None` — the one call a
  gold-file evaluation needs.
- `index.with_scoring(k1=…, b=…)` → a view sharing the same postings, so a
  scoring ablation cannot accidentally index a different corpus.
- `IndexConfig.exclude_paths` is the contamination firewall: a harness **must**
  exclude the files carrying its own query strings (see below).

Process boundary, language-agnostic, same ranking:

```
python experiments/forest_v2/s07_bm25/bm25_index.py --root . --k 10 "query"
```

→ one JSON object, `"schema": "forest-v2-s07-bm25/1"`, with `results[].hits[]`
as above plus the RAW build counters. `measure_bm25.py` emits
`"schema": "forest-v2-s07-bm25-measure/1"`.

### Measured baseline (2026-08-18, this worktree @ 8bfaa7a, Windows, CPython 3.10.11)

12 frozen queries, one gold file each, ranks searched to 100. `hit@N` counts
queries whose gold file landed in the top N. **All RAW, single run, no
repetition** — treat build seconds as ±30 % (the same corpus rebuilt between
13.8 s and 19.8 s across arms).

| arm | files | build s | h@1 | h@3 | h@5 | h@10 | MRR@10 | ms/query |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **full corpus, path_weight=3 (primary)** | 5062 | 19.8 | **4** | 10 | 10 | **12** | **0.5613** | 35.5 |
| full corpus, path_weight=1 | 5062 | 18.6 | 3 | 10 | 10 | 12 | 0.5188 | 25.2 |
| full corpus, path_weight=0 (content only) | 5062 | 17.8 | 3 | 9 | 10 | 12 | 0.5076 | 30.9 |
| **code+prose only (no `.json`/`.jsonl`)** | 1557 | 5.9 | **8** | 12 | 12 | 12 | **0.8056** | 7.7 |
| contaminated control (carriers left in) | 5064 | 13.8 | 3 | 8 | 10 | 12 | 0.5046 | 36.1 |
| full corpus, b=0 (no length norm) | 5062 | — | 3 | 6 | 7 | 9 | 0.4021 | 31.4 |
| full corpus, k1=0 (presence only) | 5062 | — | 2 | 6 | 8 | 10 | 0.3669 | 25.3 |

Primary-arm corpus: 5062 files / 41.9 MB / 5,536,028 tokens / 62,660 distinct
terms / mean 1093.6 tokens per document, from 5276 files walked.

What the arms actually say:

1. **BM25 is a real baseline, not a straw man.** Every gold file is in the
   top 10 on the primary arm, and 10 of 12 are in the top 3. A graph retriever
   that "finds the right file" has not beaten anything; it has to beat rank 1
   at equal cost.
2. **Term frequency and length normalisation both earn their keep.** Removing
   length normalisation (b=0) costs 0.159 MRR and drops three golds out of the
   top 10; ignoring term frequency entirely (k1=0, pure idf) costs 0.194.
3. **Path tokens help, mildly.** 3× path weight buys +0.054 MRR over
   content-only — real, but far smaller than the corpus effect.
4. **The machine-written artifact tree is the dominant retrieval hazard.**
   Dropping `.json`/`.jsonl` removes 3505 files (24 MB) and takes h@1 from 4 to
   8 and MRR from 0.561 to 0.806, while making the build 3.3× and queries 4.6×
   faster. Receipt dumps under `runs/` beat their own subject matter: a scan
   receipt *about* `worktree.py` outranks `worktree.py`, and plan-critique
   receipts outrank the master plan itself. **This is a finding s09 must
   inherit**: a Data-plane corpus needs a stated inclusion rule, and any
   cross-plane comparison that silently varies it is measuring the corpus, not
   the retriever.

### Retained negative results

- **The confusable-neighbour miss (pinned in the self-test).** For "same module
  call site resolution baseline probe", `probe_cross_module_resolution.py` (the
  *continuation*) outranks `probe_call_resolution.py` (the subject). Bag of
  words cannot separate "the document about X" from "the document that cites
  X". Not reworded, not excluded — this is exactly the failure class a
  structure-aware retriever must beat, so it is asserted as a known miss and
  will fail loudly if it ever silently changes.
- **The evaluation contaminated itself on the first run.** `measure_bm25.py`
  lives in the corpus it measures and quotes all 12 queries verbatim; it took
  rank 1 for four of them. Fixed by `exclude_paths`, and kept measurable as the
  contaminated control arm. Note the direction: the leak *lowered* MRR by 0.057
  (a carrier is a distractor, not a gold), so "our number went up after we
  fixed leakage" is not, by itself, evidence that leakage was absent.
- **Legitimate relevance is still counted as a miss.** `tests/test_effect_boundary.py`
  outranking `tools/effect_boundary_check.py` is arguably correct behaviour;
  the single-gold rule counts it against BM25 anyway. Absolute numbers here are
  therefore pessimistic and comparable only *within* this table.

### Honest limits

12 queries with author-written gold labels, one machine, one run, no variance
estimate, no repetition, no second annotator. Enough to catch "retrieval is
broken" and to anchor an ablation; **not** enough for a published comparison.
Gate 3 needs a frozen task set produced by someone other than the retriever's
author.

### Reproduce

```
python -m pytest experiments/forest_v2/s07_bm25/test_bm25_index.py -q   # 27 passed, 2.8 s
python experiments/forest_v2/s07_bm25/measure_bm25.py --root .          # the table above
```

## Boundary note

This directory currently contains no effectful entrypoint (the probe's
`main` only prints, which the effect scanner correctly treats as read-only).
Anyone adding an effectful entrypoint under `experiments/` must either
register it in the canonical effect registry or extend `HARNESS_PACKAGES` —
an unscanned effectful directory is the exact blind spot the boundary work
just closed.
