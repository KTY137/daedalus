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
  **The frozen text above is left exactly as it was written.  How (b) was
  first measured against it was wrong on two counts — see "What was withdrawn"
  below.  The result now standing for (b) is a null against the comparator
  this text names.**
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
- **Budget:** ≤ 4 h implementation, one process, no spend.  Measured run cost
  after the correction: corpus build 22.9 s, index build 8.5 s, whole self-test
  149.6 s wall [MEASURED] — the added arms and the second query set roughly
  triple the earlier ≈ 40 s.
- **Expiry: 2026-09-15.**  Re-measure before reuse; the tree moves weekly.

### RAW measurement (2026-08-18, this worktree @ `49e40793`) [MEASURED]

> **This section replaces the first reported run.**  An adversarial review found
> two defects in it, both biased *towards* the four-plane hypothesis.  The
> retraction is spelled out under "What was withdrawn" below; the numbers here
> are the corrected ones.

Corpus: 1037 documents — code 318, type 289, data 65, knowledge 365;
1,066,495 tokens; 0 unparseable code files, 0 oversize skips.
Graph: 318 modules, 992 undirected edges, mean degree 6.239, 14 isolated
modules.  Frozen queries: 600 = 3 families × 200, seed 20260818, deterministic,
**unchanged**.  Added non-code-gold families: 138 (seed 20260819).

Query-token overlap with the own gold document (the honesty column):
`symbol` 1.0, `docstring` 1.0, `knowledge_ref` 0.6252, `doc_ref` 0.5847,
`data_ref` 0.1618.  The first two families are lexically easy by construction.

All 600 frozen queries, RAW hits out of 600:

| retriever | R@1 | R@5 | R@10 | MRR | hits @1/@5/@10 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `bm25_code_only` (control) | 0.5483 | 0.7650 | 0.8183 | 0.6432 | 329/459/491 |
| `graph_code_only` (a) α=0.5, 2 hops | 0.3717 | 0.7400 | **0.8283** | 0.5256 | 223/444/497 |
| `graph_code_only` rewired (control) | 0.4767 | 0.7517 | 0.8183 | 0.5926 | 286/451/491 |
| `four_plane_no_fusion` (b, round-robin) | 0.5483 | 0.6733 | 0.7200 | 0.5816 | 329/404/432 |
| `union_no_fusion` (b, per-plane top-k) | 0.5483 | 0.7650 | 0.8183 | 0.6432 | 329/459/**491** |
| `union_no_fusion` truncated to 10 | 0.5483 | 0.7650 | 0.8183 | 0.6432 | 329/459/491 |
| `union_no_fusion` code-LAST order | 0.0000 | 0.0000 | 0.0067 | 0.0346 | 0/0/4 |
| `bm25_single_index_all_planes` | 0.3883 | 0.6617 | 0.7300 | 0.5035 | 233/397/438 |

The 138 added queries whose gold label is **not** a code document, and the
extended 738:

| retriever | non-code @1/@5/@10 (n=138) | extended @1/@5/@10 (n=738) |
| --- | ---: | ---: |
| `bm25_code_only` | 0/0/**0** | 329/459/491 |
| `graph_code_only` | 0/0/**0** | 223/444/497 |
| `four_plane_no_fusion` | 0/12/32 | 329/416/464 |
| `union_no_fusion` | 0/0/1 | 329/459/492 |
| `union_no_fusion` code-LAST | 3/7/10 | 3/7/14 |
| `bm25_single_index_all_planes` | 10/39/**49** | 243/436/487 |

Gross rescue/loss **at every cutoff** (net deltas hide which system you have;
one cutoff hides which direction you have).  net = only B − only A:

| pair | k | both | only A | only B | neither | net |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A=`bm25_code_only`, B=`graph` | 1 | 182 | 147 | 41 | 230 | **−106** |
| A=`bm25_code_only`, B=`graph` | 5 | 423 | 36 | 21 | 120 | **−15** |
| A=`bm25_code_only`, B=`graph` | 10 | 482 | 9 | 15 | 94 | +6 |
| A=`graph rewired`, B=`graph` | 1 | 184 | 102 | 39 | 275 | **−63** |
| A=`graph rewired`, B=`graph` | 5 | 420 | 31 | 24 | 125 | **−7** |
| A=`graph rewired`, B=`graph` | 10 | 484 | 7 | 13 | 96 | +6 |
| A=`no_fusion`, B=`single index` | 1 | 229 | 100 | 4 | 267 | **−96** |
| A=`no_fusion`, B=`single index` | 5 | 374 | 30 | 23 | 173 | **−7** |
| A=`no_fusion`, B=`single index` | 10 | 415 | 17 | 23 | 145 | +6 |
| A=`no_fusion`, B=`bm25_code_only` | 1 | 329 | 0 | 0 | 271 | 0 |
| A=`no_fusion`, B=`bm25_code_only` | 5 | 404 | 0 | 55 | 141 | +55 |
| A=`no_fusion`, B=`bm25_code_only` | 10 | 432 | 0 | 59 | 109 | +59 |
| A=`union_no_fusion`, B=`bm25_code_only` | 1 | 329 | **0** | **0** | 271 | **0** |
| A=`union_no_fusion`, B=`bm25_code_only` | 5 | 459 | **0** | **0** | 141 | **0** |
| A=`union_no_fusion`, B=`bm25_code_only` | 10 | 491 | **0** | **0** | 109 | **0** |
| A=`union_no_fusion`, B=`single index` | 1 | 229 | 100 | 4 | 267 | −96 |
| A=`union_no_fusion`, B=`single index` | 5 | 396 | 63 | 1 | 140 | −62 |
| A=`union_no_fusion`, B=`single index` | 10 | 438 | **53** | **0** | 109 | −53 |

The graph pairs are not the only ones that flip: `no_fusion` vs the named
single joint index is **−96 / −7 / +6** across k=1/5/10, so the +6 that the
frozen-600 verdict rests on is the one cutoff of three where the joint index is
ahead.  The `union_no_fusion` tie with `bm25_code_only` is the opposite case and
is now shown to be a tie at **every** cutoff, 0 discordant queries throughout,
not only at k=10.

### What the numbers say, including against the hypothesis

1. **(a) is refuted as stated, and the "surviving remainder" was a
   single-cutoff artefact.**  The graph buys +6 documents at k=10
   (491 → 497, +1.0 pp) and *costs* 106 at k=1 (329 → 223, −17.7 pp); MRR falls
   0.6432 → 0.5256.  Propagated mass flows into high-degree modules and pushes
   the correct answer down.  Against the degree-preserving rewired control —
   the comparison plan §14.2 actually names — the sign **flips with the
   cutoff**: net **−63 at k=1**, **−7 at k=5**, **+6 at k=10**.  The earlier
   reading ("structure contributes about one percentage point") quoted the last
   of those three and called it the remainder.  It is the only cutoff at which
   the real graph beats its own randomised control, and the k=1 effect against
   that control is **ten times larger in the opposite direction**.  Read across
   all cutoffs, randomised edges do *not* perform worse than real ones; below
   k=10 they perform better.
2. **α = 0 is the best-ranking setting, and it is the control.**  Post-hoc
   sweep over the same 600 queries: α=0.0 → MRR 0.6432 (identical to
   `bm25_code_only`, which is also the consistency check that the two paths
   agree), α=0.25 → 0.6254, α=0.5 → 0.5256, α=0.75 → 0.4333.  Recall@10 peaks
   at α=0.25 (499/600, 0.8317).  Monotone in the wrong direction for the
   hypothesis; reported, not buried.
3. **(b) is NOT confirmed.  The earlier confirmation is withdrawn — see below.**
   The un-starved no-fusion arm ties the code-only control exactly: 491 = 491,
   rank-identical on **600 of 600** queries, 0 rescued and 0 lost.  Against the
   comparator the frozen sub-spec actually names it goes the other way: the
   no-fusion arm rescues 53 and loses 0.  On the 138 non-code-gold queries the
   direction reverses again and the single joint index wins (49 against 32 and
   1).  Three query sets, three different signs — the honest summary is that
   (b) is *comparator- and query-set-dependent*, which is not a confirmation
   of anything.
4. **The routing cost is the whole story, and the fusion question is still NOT
   answered.**  Per-plane hits@10 of the four indices (out of 200 per family)
   are code 190 / 117 / 184 for docstring / knowledge_ref / symbol, and
   type = data = knowledge = **0** on all three frozen families, because every
   gold label there is a code document by construction.  The plane oracle
   therefore equals the code index exactly.  This slice measures the *cost of
   not routing*; it cannot measure the *value of fusing*, because no fusion
   retriever exists in it.
5. **A fixed plane order is a hidden prior worth almost everything here.**  The
   union arm's tie with the code-only control is not a property of no-fusion
   retrieval; it is a property of putting the code block first.  Reverse the
   order and the same arm scores 4/600 instead of 491/600.  Concatenation order
   is not a cross-plane score comparison, but it decides rank just as firmly,
   and on a query set with only code gold labels the code-first order is
   exactly the flattering one.  Stated because it would otherwise read as a
   result rather than as a choice.

### What was withdrawn (2026-08-18)

An adversarial review found two defects in the first reported run; correcting
them surfaced a third, of the same class, in the graph half of the slice.  All
three bias towards the four-plane hypothesis, so all three are retracted here
rather than reworded.

**Withdrawn claim 1 — "`no_fusion` is *strictly dominated* by
`bm25_code_only`: 0 queries found that code-only missed, 59 lost."**  That was
an artefact of slot allocation, not a property of no-fusion retrieval.  The
arm split ONE budget of k slots round-robin across four planes, so the only
plane that can hold a code gold label received slots 1, 5 and 9 — its top-3.
The measurement that refutes the claim:

| measurement | hits of 600 |
| --- | ---: |
| `four_plane_no_fusion` @10 (the arm as reported) | 432 |
| `bm25_code_only` @**3** (what the arm effectively had) | 430 |
| `union_no_fusion` @10 (per-plane top-k, no shared budget) | **491** |
| `bm25_code_only` @10 (the control it was said to lose to) | **491** |

`union_no_fusion` gives each plane its own top-k and concatenates; it compares
no score across planes anywhere.  It ties the control exactly, rank for rank,
on all 600 queries.  The clipped row in the table above shows the tie is not
bought with a bigger budget: truncated to the same 10 returned documents it is
still 491.  "Strictly dominated" was measuring the handicap, not the design.

**Withdrawn claim 2 — the comparator was substituted.**  The frozen sub-spec
names *"one index over the same documents"*, i.e.
`bm25_single_index_all_planes`.  The confirmation was reported against
`bm25_code_only`, a different and much stronger comparator over a subset of the
documents.  Re-reported against the named one (materiality declared in this
correction, not at freeze time: |Δ hits@10| ≥ 5% of the query set with the same
sign at k=1, 5 and 10):

| query set | arm | Δ hits @1/@5/@10 vs named comparator | verdict |
| --- | --- | ---: | --- |
| frozen 600 | `four_plane_no_fusion` | +96 / +7 / −6 | NULL |
| frozen 600 | `union_no_fusion` | +96 / +62 / +53 | REFUTED (opposite direction) |
| extended 738 | `four_plane_no_fusion` | +86 / −20 / −23 | NULL |
| extended 738 | `union_no_fusion` | +86 / +23 / +5 | NULL |
| non-code gold 138 | `four_plane_no_fusion` | −10 / −27 / −17 | CONFIRMED |
| non-code gold 138 | `union_no_fusion` | −10 / −39 / −48 | CONFIRMED |

Against the named comparator, hypothesis (b) is a **null** on the query set it
was frozen against, and the sub-claim that survives is confirmed only on the
138 queries whose answer the code plane cannot hold.

**Withdrawn claim 3 — "structure contributes about one percentage point at
k=10, and nothing at k=1."**  Found while correcting the first two, in the
graph half of the slice, and it is the same defect one level down: the first
two runs emitted crosstabs at **k=10 only**, which for the graph pairs is the
single cutoff where the graph wins.  Against the degree-preserving rewired
control that plan §14.2 names:

| cutoff | both | only rewired | only graph | neither | net for graph |
| ---: | ---: | ---: | ---: | ---: | ---: |
| k=1 | 184 | 102 | 39 | 275 | **−63** (−0.1050) |
| k=5 | 420 | 31 | 24 | 125 | **−7** (−0.0117) |
| k=10 | 484 | 7 | 13 | 96 | +6 (+0.0100) |

The k=1 effect is an order of magnitude larger than the k=10 effect and points
the other way.  "A one-point effect is not a foundation; it is a measurement"
was true as far as it went, but it quoted the one cutoff that favours the
hypothesis and omitted the two that refute it.  §14.2 ("degree-preserving
randomized cross-plane edges perform equivalently") is not answered by the
+6 row alone; read across cutoffs, the randomised control is *better* than the
real graph below k=10.  The self-test can no longer emit a single-cutoff
crosstab, and a check enforces it.

### Kill criterion §13 "four independent indices perform equivalently to cross-plane fusion"

**Verdict: NOT DECIDABLE AS STATED.**  Entered as the result, replacing the
earlier "instrumented here, not evaluated" framing, which implied the
instrumentation was sound.

Two independent reasons:

1. **No second arm exists.**  This slice contains no cross-plane fusion
   retriever, so the criterion's comparison cannot be run at all.  What is
   measurable is the weaker question "four independent indices vs *one joint
   index*", and a joint index is not fusion.
2. **The query set cannot decide it.**  All 600 frozen gold labels are code
   documents.  On such a set any cross-plane method can only spend slots on
   planes that are guaranteed not to hold the answer, and a code-only index
   cannot be beaten by anything.  The criterion is structurally unfalsifiable
   here, in the direction that favours the hypothesis.

What the added non-code gold labels *do* show, for the weaker joint-index
question (n=138, hits@10): `bm25_code_only` 0, `union_no_fusion` 1,
`four_plane_no_fusion` 32, `bm25_single_index_all_planes` **49**.  When the
answer can live outside the code plane, one joint index beats every no-fusion
arm — evidence *against* "four independent indices perform equivalently", for
the joint-index comparison only.  The plan's actual criterion stays open until
a fusion arm exists.

Closing it needs two things this slice does not have: a real cross-plane fusion
retriever, and gold labels in all four planes.

### The added non-code gold labels

The frozen 600 are untouched.  138 queries were added whose gold document is
not a code document, because without them the question above cannot be asked:

- `doc_ref` (**124**, gold in the knowledge plane) — a prose line in one
  Markdown file naming another Markdown file; the named path's tokens are
  stripped from the query, so the prose has to carry it.  Overlap with gold
  0.5847.
- `data_ref` (**14**, gold in the data plane) — the same derivation for
  schema-shaped files.  Overlap 0.1618.  **n = 14 is small**; treat its numbers
  as an existence proof, not as a rate.

Each gold document is capped at 4 mentions so a much-referenced file cannot
supply a family alone, and sampling uses its own generator (seed 20260819), so
the frozen families' stream is bit-for-bit unchanged.  Extended set: 738, gold
mix code 600 / knowledge 124 / data 14.

**Named gap — the type plane still has zero gold labels.**  No mechanical
derivation exists in this tree: the type plane is a proxy built from the same
source files as the code plane, and nothing references it as an artifact.  So
of the four planes, three can now be a retrieval target and one cannot.  Order
of magnitude: 289 type documents (27.9% of the corpus) carry 0 gold labels, and
their marginal contribution (plan §13, "a plane has no marginal contribution in
ablation") remains untested.  Closing it needs real type artifacts, not a
better query rule.

Also unchanged and still true: **one number is a query-set artefact, measured
rather than argued away.**  For the `knowledge_ref` family the query is lifted
from a Markdown file that the all-planes index also contains; that source file
lands in the top ten for **181 of 200** queries at mean rank 2.26.  The
single-index retriever's weak knowledge_ref R@1 (0.1200 vs code-only 0.3100) is
therefore partly a property of the query set, not of the retriever.

### Decidability audit: can this query set produce BOTH verdicts?

Asked after the s10 kill-criterion evaluator consumed the correction above and
observed that on the frozen 600 every gold label is a code document, so §13's
"four independent indices" criterion is structurally unfalsifiable there in the
direction that favours the hypothesis.  The commit that added 138 non-code gold
labels looked like the answer.  Measured, it is the answer to one of the two
criteria and not to the other.  Corpus pinned by digest
`b0d146a34356356782a6b4817b3398dd202ebdbc9682b8f54c3d8cd64b7175a2`; the
self-test now prints that digest beside every number it reports.

**Gold-label plane distribution** (all [MEASURED], `decidability_audit`):

| query set | n | code | knowledge | data | type |
| --- | ---: | ---: | ---: | ---: | ---: |
| frozen 600 | 600 | 600 | 0 | 0 | 0 |
| added non-code | 138 | 0 | 124 | 14 | 0 |
| extended | 738 | 600 | 124 | 14 | **0** |

Corpus for scale: code 318, type 289, data 65, knowledge 365 documents.  Three
of four planes can now hold an answer; the type plane holds 289 documents and
**zero** gold labels, and no mechanical rule in this tree yields one.

**Which planes each arm can return at all** — the number that decides what a
comparison is able to refute, measured over the extended 738 at k=10:

| arm | code | type | data | knowledge | can return non-code |
| --- | ---: | ---: | ---: | ---: | --- |
| `bm25_code_only` | 7345 | 0 | 0 | 0 | **no** |
| `graph_code_only` | 7370 | 0 | 0 | 0 | **no** |
| `graph_rewired` | 7370 | 0 | 0 | 0 | **no** |
| `four_plane_no_fusion` | 2447 | 1654 | 1468 | 1801 | yes |
| `union_no_fusion` | 7345 | 4648 | 5809 | 7359 | yes |
| `bm25_single_index_all_planes` | 3202 | 148 | 103 | 3917 | yes |

#### §13 "degree-preserving randomized cross-plane edges perform equivalently"

**Second arm exists** (`graph_rewired`).  **Verdict: still NOT resolvable in
either direction by this query set**, for two independent reasons, and the
non-code labels make it worse rather than better.

1. *The added labels carry zero information for it.*  Both arms index the code
   plane only, so on all 138 non-code-gold queries both score 0 and every one of
   them is concordant.  Discordant (informative) queries:

   | query set | n | k=1 | k=5 | k=10 |
   | --- | ---: | ---: | ---: | ---: |
   | frozen 600 | 600 | 141 | 55 | 20 |
   | added non-code | 138 | **0** | **0** | **0** |
   | extended | 738 | 141 | 55 | 20 |

   The discordant counts on 738 are *identical* to those on 600 while n grows
   23%.  An equivalence test run on the extended set therefore reports a
   smaller difference (6/738 = +0.0081 instead of 6/600 = +0.0100) and a
   tighter interval **from no new evidence at all**.  s10 projected that at the
   observed discordance rate n=1800 would flip 14.2 from INCONCLUSIVE to
   EQUIVALENT, i.e. fire KILL.  Padding with queries neither arm can answer is
   a way to walk to that n without measuring anything — the fastest route to a
   KILL verdict here is to add queries that contain no information.
2. *The object the criterion names does not exist in this slice.*  The graph
   has **992 edges and 0 of them cross a plane**: every edge joins two code
   modules (endpoint plane counts: code 1984, nothing else).  The rewiring
   control randomises an intra-code-plane import/call graph.  Whatever the
   graph-vs-rewired comparison measures, it is not "cross-plane edges perform
   equivalently".

**A KILL verdict for 14.2 from this query set would be an artefact** — evidence
about the arms' index scope and the graph's plane coverage, not about the
four-plane prior.  Stated plainly because the measurement says so, not because
it is the comfortable answer: the earlier −63/−7/+6 reading against the rewired
control still stands as a refutation of *this graph's* claimed structural gain,
but it cannot be promoted into a verdict on the plan's §13 clause.

#### §13 "four independent indices perform equivalently to cross-plane fusion"

**Second arm does not exist.**  No cross-plane fusion retriever is implemented
here, so the criterion has one arm on *any* query set.  That is a missing-arm
problem, and gold labels cannot fix it.  **Verdict: not resolvable in either
direction**, unchanged by the 138.

What the 138 *do* fix is the weaker joint-index proxy — and there the query set
now cuts both ways, which it did not before.  Hits@10 and discordant counts for
`union_no_fusion` vs `bm25_single_index_all_planes`:

| query set | union | joint index | net @10 | discordant k=1/5/10 |
| --- | ---: | ---: | ---: | ---: |
| frozen 600 | 491 | 438 | **union +53** | 104 / 64 / 53 |
| added non-code 138 | 1 | 49 | **joint +48** | 10 / 39 / 48 |
| extended 738 | 492 | 487 | union +5 | 114 / 103 / 101 |

Both directions are reachable, both are populated, and the two halves disagree.
That is a real finding about the cost of not routing.  It is **not** the plan's
criterion and must not be reported as one: a joint index is not fusion, and the
suite now refuses any arm named "fusion" while no fusion retriever exists.

#### What would make them resolvable

- **14.2**: cross-plane edges to rewire — the graph currently has none — and
  arms whose index can return the plane the gold label lives in.
- **14.3**: a real cross-plane fusion retriever as the second arm.
- **both**: gold labels in the type plane, which no mechanical rule in this tree
  yields.

Mutation evidence for the five checks added with this audit (each re-introduced
defect, each turning the suite red from 51 green): census blind to cross-plane
edges → 1 failed; `reachable_planes` always claiming non-code → 1 failed;
`informative_queries` counting agreement instead of discordance → 1 failed;
`corpus_digest` returning a constant → 1 failed; an arm renamed to
`cross_plane_fusion` → 1 failed.

### Honest caveats

- The type plane is a **proxy**: the tree carries no `.pyi`, so type documents
  are annotations/bases extracted from the same source files the code plane
  indexes.  A plane derived from another plane cannot demonstrate independent
  marginal contribution (plan §13) — that ablation needs real type artifacts.
- All gold labels of the **frozen 600** are code documents; two of its three
  families draw their text from the gold file itself (overlap 1.0).  Those
  families measure string matching more than retrieval and are kept only as a
  sanity floor.  The 138 added queries fix the plane mix, not the leakage.
- **The no-fusion baseline has two arms and neither is "the" one.**  The
  round-robin arm is budget-equal by construction but starves whichever plane
  holds the answer; the union arm is un-starved but returns up to 4k documents
  and imposes a fixed plane order.  They disagree by design — 432 vs 491 on the
  frozen set, 32 vs 1 on non-code gold — so any single-number "no-fusion
  result" is a choice of arm, and must be reported as one.
- The materiality rule (5% of the query set, consistent sign across cutoffs)
  was declared **in this correction, after seeing the first run**, not at
  freeze time.  It is a stated decision procedure, not a pre-registered one.
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

```text
python experiments/forest_v2/s08_graph_baselines/s08_selftest.py
python -m pytest experiments/forest_v2/s08_graph_baselines/ -q
```

42 checks, all green at `49e40793` [MEASURED].  They assert mechanics on a
synthetic four-plane tree, never this repository's measured numbers; two
structural checks verify that the slice imports no repository package and calls
nothing that writes.

Six of them exist to keep the two withdrawn defects from coming back, and each
was verified by re-introducing the defect and watching it fail [MEASURED]:

| defect re-introduced | checks that went red |
| --- | ---: |
| union arm shares one budget again (the starvation) | 3 of 42 |
| union arm sorts the concatenation by score (cross-plane comparison) | 4 of 42 |
| per-gold-document mention cap removed | 1 of 42 |
| non-code families yield nothing again | 2 of 42 |

Restoring each returned the suite to 42 green.

## Boundary note

This directory currently contains no effectful entrypoint (the probe's
`main` only prints, which the effect scanner correctly treats as read-only).
Anyone adding an effectful entrypoint under `experiments/` must either
register it in the canonical effect registry or extend `HARNESS_PACKAGES` —
an unscanned effectful directory is the exact blind spot the boundary work
just closed.
