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

## Slice s08 (2026-08-18): graph baselines — `s08_graph_baselines/`

Sub-spec, frozen before the run.  This slice does not test the Project Twin;
it builds the two **baselines** the Twin will have to beat, so that a later
gain has something to be a gain *against*.  Master plan §10 (Gate 3) names
them; §13 turns both into kill criteria.

- **Hypothesis (falsifiable, two parts):**
  (a) *code-only graph retrieval* — ranking a module by the import/call
  neighbourhood of a lexical seed set retrieves documents that lexical
  matching alone misses, and the effect survives a degree-preserving rewiring
  of the graph;
  (b) *four separate single-plane indices without fusion* — four independent
  BM25 indices with no cross-plane scoring reach materially less than one
  index over the same documents, and the loss is attributable to plane
  routing rather than to ranking.
  Both are stated so a null result is a result.  A null (a) means the code
  graph is not a retrieval signal at this granularity; a null (b) means
  "four independent indices perform equivalently" — plan §13, verbatim.
- **Contract of the outputs.**  `s08_api.py` fixes the shared call, the one
  slice s07 and slice s08 must both answer:
  `retriever.query(text: str, k: int) -> list[Hit]`, with
  `Hit(doc_id, score, plane, locator, why)` and
  `doc_id == f"{plane}:{locator}"`.  Documents are `Document(doc_id, plane,
  locator, text, symbols, tokens)`, plane ∈ {code, type, data, knowledge}.
  Scores are comparable **only within one retriever** — four independent BM25
  scales are not commensurable and this slice refuses to pretend otherwise.
  `s08_selftest.py` prints exactly one JSON object and writes nothing.
- **Scope:** read-only, pure stdlib, no repository imports, no writes, no
  network, no subprocess, no model calls.  The corpus indexes `daedalus`,
  `tools`, `runs` (code), `docs`/`runs`/root Markdown (knowledge), and
  schema-shaped files under `daedalus`/`docs`/root (data);
  `runs/**/*.json` (3329 receipt files) is excluded as evidence, not data.
  `experiments/` is not indexed, so the slice never measures itself.
- **Budget:** ≤ 4 h implementation, one process, no spend.  Measured run cost:
  corpus build 20.9 s, index build 4.3 s, 600 queries × 5 retrievers ≈ 12 s.
- **Expiry: 2026-09-15.**  Re-measure before reuse; the tree moves weekly.

### RAW measurement (2026-08-18, this worktree @ `46fd456c`) [MEASURED]

Corpus: 1037 documents — code 318, type 289, data 65, knowledge 365;
1,066,495 tokens; 0 unparseable code files, 0 oversize skips.
Graph: 318 modules, 992 undirected edges, mean degree 6.239, 14 isolated
modules.  Queries: 600 = 3 families × 200, seed 20260818, deterministic.

Query-token overlap with the own gold document (the honesty column):
`symbol` 1.0, `docstring` 1.0, `knowledge_ref` 0.6252.  The first two families
are lexically easy by construction; only `knowledge_ref` is cross-plane.

All 600 queries, cutoff 10, RAW hits out of 600:

| retriever | R@1 | R@5 | R@10 | MRR | hits @1/@5/@10 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `bm25_code_only` (control) | 0.5483 | 0.7650 | 0.8183 | 0.6432 | 329/459/491 |
| `graph_code_only` (a) α=0.5, 2 hops | 0.3717 | 0.7400 | **0.8283** | 0.5256 | 223/444/497 |
| `graph_code_only` rewired (control) | 0.4767 | 0.7517 | 0.8183 | 0.5926 | 286/451/491 |
| `four_plane_no_fusion` (b) | 0.5483 | 0.6733 | 0.7200 | 0.5816 | 329/404/432 |
| `bm25_single_index_all_planes` | 0.3883 | 0.6617 | 0.7300 | 0.5035 | 233/397/438 |

Gross rescue/loss at k=10 (net deltas hide which system you have):

| pair | both | only A | only B | neither |
| --- | ---: | ---: | ---: | ---: |
| A=`bm25_code_only`, B=`graph` | 482 | 9 | 15 | 94 |
| A=`graph rewired`, B=`graph` | 484 | 7 | 13 | 96 |
| A=`no_fusion`, B=`single index` | 415 | 17 | 23 | 145 |
| A=`no_fusion`, B=`bm25_code_only` | 432 | **0** | 59 | 109 |

### What the numbers say, including against the hypothesis

1. **(a) is mostly refuted as stated, with a small surviving remainder.**  The
   graph buys +6 documents at k=10 (491 → 497, +1.0 pp) and *costs* 106 at
   k=1 (329 → 223, −17.7 pp); MRR falls 0.6432 → 0.5256.  Propagated mass
   flows into high-degree modules and pushes the correct answer down.  The
   remainder is real though: against the degree-preserving rewired control the
   real graph rescues 13 and loses 7 (net +6 of 600), and the rewired graph
   lands on exactly the lexical control's 491.  So structure contributes
   about **one percentage point at k=10**, and nothing at k=1.  A one-point
   effect is not a foundation; it is a measurement.
2. **α = 0 is the best-ranking setting, and it is the control.**  Post-hoc
   sweep over the same 600 queries: α=0.0 → MRR 0.6432 (identical to
   `bm25_code_only`, which is also the consistency check that the two paths
   agree), α=0.25 → 0.6254, α=0.5 → 0.5256, α=0.75 → 0.4333.  Recall@10 peaks
   at α=0.25 (499/600, 0.8317).  Monotone in the wrong direction for the
   hypothesis; reported, not buried.
3. **(b) is confirmed, and more sharply than expected.**  `no_fusion` is
   *strictly dominated* by `bm25_code_only`: 0 queries found that code-only
   missed, 59 lost.  Its R@1 is identical (0.5483) because the round-robin's
   first slot is always the code index's top hit — the loss is purely the
   three slots per cycle spent on planes that cannot hold the answer.
4. **The routing cost is the whole story, and the fusion question is NOT
   answered here.**  Per-plane hits@10 of the four indices (out of 200 per
   family) are code 190 / 117 / 184 for docstring / knowledge_ref / symbol,
   and type = data = knowledge = **0** on all three families, because every
   gold label in this query set is a code document by construction.  The
   plane oracle therefore equals the code index exactly.  This slice measures
   the *cost of not routing*; it cannot measure the *value of fusing*, and no
   fusion retriever exists yet to compare against.  §13's "four independent
   indices perform equivalently to cross-plane fusion" is instrumented here,
   not evaluated.
5. **One number is a query-set artefact, measured rather than argued away.**
   For the `knowledge_ref` family the query is lifted from a Markdown file
   that the all-planes index also contains; that source file lands in the top
   ten for **181 of 200** queries at mean rank 2.26.  The single-index
   retriever's weak knowledge_ref R@1 (0.1200 vs code-only 0.3100) is
   therefore partly a property of the query set, not of the retriever.

### Honest caveats

- The type plane is a **proxy**: the tree carries no `.pyi`, so type documents
  are annotations/bases extracted from the same source files the code plane
  indexes.  A plane derived from another plane cannot demonstrate independent
  marginal contribution (plan §13) — that ablation needs real type artifacts.
- All gold labels are code documents; two of three query families draw their
  text from the gold file itself (overlap 1.0).  These families measure
  string matching more than retrieval and are kept only as a sanity floor.
- Graph weights (import 1.0, call 0.5/site capped at 10), α=0.5, 2 hops and
  25 seeds were frozen before the run.  The sweep is labelled post-hoc and no
  headline number was selected from it.
- The rewiring control preserves each module's edge *count* exactly; summed
  edge weight per node can shift, because weights travel with the swapped
  edge.
- One query of 600 yields no tokens after stopword removal and returns empty
  for every retriever; it is counted as a miss for all of them equally.
- Single machine, single run, no repeated trials, no confidence intervals.
  Differences of a few documents out of 600 are not separated from noise here.

### How to run

```
python experiments/forest_v2/s08_graph_baselines/s08_selftest.py
python -m pytest experiments/forest_v2/s08_graph_baselines/ -q
```

32 tests, all green at `46fd456c` [MEASURED].  They assert mechanics on a
synthetic four-plane tree, never this repository's measured numbers; two
structural tests check that the slice imports no repository package and calls
nothing that writes.

## Boundary note

This directory currently contains no effectful entrypoint (the probe's
`main` only prints, which the effect scanner correctly treats as read-only).
Anyone adding an effectful entrypoint under `experiments/` must either
register it in the canonical effect registry or extend `HARNESS_PACKAGES` —
an unscanned effectful directory is the exact blind spot the boundary work
just closed.
