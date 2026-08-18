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

## Slice s09 (2026-08-18): the eval harness and its first RAW table

Directory: `experiments/forest_v2/s09_eval/`. Run the suite with
`python -m pytest experiments/forest_v2/s09_eval` (54 tests), the harness
with `python -m experiments.forest_v2.s09_eval.harness`.

### Frozen specification

- **Hypothesis (falsifiable):** a retrieval method built on Forest v2
  structure (s07/s08 and any later fusion) will beat *both* a lexical
  baseline and a query-blind churn prior on "which existing files does this
  request change", at equal candidate budget. Until that is measured, the
  four-plane track has no retrieval evidence, only a design argument.
- **Contract of my outputs** — what other slices may depend on:
  - `taskset.json` — 20 frozen cases, digest
    `sha256:c3ef36f1…` over the canonical case list. Query = commit message,
    gold = files that commit changed *and* that existed in its parent tree,
    universe = that parent tree. `taskset.load()` recomputes the digest and
    refuses a drifted set.
  - `contract.py` — implement `name` + `rank(QueryView, Sequence[Candidate])
    -> Sequence[str]`. `QueryView` carries `case_id`, `text`, `variant`,
    `revision` and **no gold**; `Candidate.text()` truncates at the shared
    byte budget. Attach with
    `--retriever your_module:YourRetriever`; nothing here imports s07/s08.
  - `results/raw.json` — schema `forest_v2.s09.results/1`: aggregates, MRR
    bootstrap intervals, paired comparisons, per-case rows, cost.
- **Budget:** identical universe object, 65 536 bytes per file, cutoffs
  1/5/10/20, tokenization charged once per case. Pure stdlib plus read-only
  git plumbing. No model calls, no spend. Full run: 79 s wall.
- **Expiry:** 2026-09-15. After that, re-freeze against a current anchor
  before reusing any number below; the history keeps moving.

### RAW results [MEASURED]

20 cases, 35 gold paths, universe 3896–4731 files, anchor `d849c2a9`,
Python 3.10.11 on `Windows-10-10.0.26200-SP0`, 79.4 s wall for the whole
run. Counts are hits/gold pooled over cases.

| retriever | variant | R@1 | R@5 | R@10 | R@20 | macro R@20 | MRR | hit cases |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| recency_prior | raw | 2/35 | 7/35 | 16/35 | 19/35 | 0.762 | **0.224** | 16/20 |
| bm25_content_only | raw | 1/35 | 6/35 | 7/35 | 11/35 | 0.412 | 0.157 | 9/20 |
| bm25 | raw | 1/35 | 6/35 | 7/35 | 8/35 | 0.287 | 0.141 | 7/20 |
| path_lexical | raw | 1/35 | 4/35 | 7/35 | 13/35 | 0.435 | 0.124 | 12/20 |
| random_uniform | raw | 0/35 | 0/35 | 0/35 | 1/35 | 0.025 | 0.004 | 1/20 |
| recency_prior | scrubbed | 2/35 | 7/35 | 16/35 | 19/35 | 0.762 | **0.224** | 16/20 |
| bm25_content_only | scrubbed | 1/35 | 6/35 | 6/35 | 7/35 | 0.237 | 0.126 | 6/20 |
| bm25 | scrubbed | 1/35 | 6/35 | 6/35 | 7/35 | 0.237 | 0.117 | 6/20 |
| random_uniform | scrubbed | 0/35 | 0/35 | 0/35 | 1/35 | 0.025 | 0.004 | 1/20 |
| path_lexical | scrubbed | 0/35 | 0/35 | 0/35 | 0/35 | 0.000 | **0.000** | 0/20 |

MRR with 95% bootstrap CI (2000 resamples, seed 20260818), and the paired
delta against the query-blind prior:

| retriever | MRR raw (95% CI) | delta vs recency_prior | excludes 0 |
| --- | --- | --- | --- |
| recency_prior | 0.224 [0.121, 0.361] | — | — |
| bm25_content_only | 0.157 [0.056, 0.286] | −0.067 [−0.211, 0.048] | no |
| bm25 | 0.141 [0.043, 0.268] | −0.083 [−0.226, 0.034] | no |
| path_lexical | 0.124 [0.049, 0.232] | −0.099 [−0.256, 0.062] | no |
| random_uniform | 0.004 [0.000, 0.011] | −0.220 [−0.358, −0.117] | yes |

### What these numbers do and do not say

1. **The bar for s07/s08 is a prior that never reads the query.**
   `recency_prior` ranks files purely by how recently they changed before
   the case revision and leads every column. A Forest-v2 retriever that
   does not clearly beat 0.224 MRR / 0.762 macro R@20 has not earned its
   construction cost, because churn is free.
2. **No query-aware baseline is distinguishable from that prior at n=20.**
   On the raw queries every paired interval except `random_uniform`'s
   straddles zero. The honest reading is "none of these beats churn", not
   "churn wins" — the sample is too small to separate them, and saying
   otherwise would be the overclaim this harness exists to prevent. Under
   scrubbing, `bm25` (−0.107 [−0.240, −0.001]) and `path_lexical` do
   separate from the prior, but as *losses*, which is not a result anyone
   should be pleased about.
3. **The filename echo is real and it is total for path matching.**
   `path_lexical` falls 0.124 → 0.000 when gold-path tokens are scrubbed
   from the query. Every point it scored was the commit message naming its
   own file. Any future method that reads paths must report both variants
   or its number is uninterpretable.
4. **BM25 mostly survives scrubbing** (0.141 → 0.117; content-only 0.157 →
   0.126), so its signal is largely real content matching rather than echo.
5. **Negative result, retained:** adding path tokens to the BM25 document
   *hurt* it in both variants (0.157 → 0.141 raw). Path tokens inflate
   document frequency for common directory names. Do not assume "more
   fields" helps.

### Limitations, stated once and not walked back

- **Hindsight queries.** The commit message is written after the change.
  Even scrubbed, it is a description of finished work, not a request from
  someone who has not seen the diff. This corpus cannot measure that.
- **n = 20, one repository.** Intervals are wide; nothing here transfers to
  another repository without another corpus. Bootstrap resamples quantify
  sampling noise across these cases, nothing more.
- **Churn is unusually strong here.** This history hammers a small set of
  gate-0 files, which flatters `recency_prior`. That makes it a demanding
  local bar and a weak general claim.
- **Single-file bias.** ~95% of this history is one-file commits; the set is
  stratified to 8 multi-file and 12 single-file cases, which is supply-capped,
  not chosen.
- **`revision` is a norm, not a sandbox.** A retriever with repository
  access could read commits after the case. The harness cannot stop it, and
  the plan is explicit that a prompt is not a boundary.

## Boundary note

This directory currently contains no effectful entrypoint (the probe's
`main` only prints, which the effect scanner correctly treats as read-only).
Anyone adding an effectful entrypoint under `experiments/` must either
register it in the canonical effect registry or extend `HARNESS_PACKAGES` —
an unscanned effectful directory is the exact blind spot the boundary work
just closed.
