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
`python -m pytest experiments/forest_v2/s09_eval` (116 tests), the harness
with `python -m experiments.forest_v2.s09_eval.harness`.

> **Correction pass, 2026-08-18.** An independent adversarial reconstruction
> rebuilt the ten-row table below from git history without reusing any helper
> in this package; every per-case reciprocal rank matched, and three probe
> retrievers confirmed the instrument separates in both directions. **The
> measurements stand unchanged.** Five *claims about* those measurements did
> not, and two modules had no test file at all. Everything struck through
> below is retracted in place under a heading naming the error, never
> silently overwritten. The numbers in the table are the same numbers.

### Frozen specification

- **Hypothesis (falsifiable):** a retrieval method built on Forest v2
  structure (s07/s08 and any later fusion) will beat *both* a lexical
  baseline and a query-blind churn prior on "which existing files does this
  request change", at equal candidate budget. Until that is measured, the
  four-plane track has no retrieval evidence, only a design argument.
  **Read the plane-composition limitation below before grading anything
  against this hypothesis on this corpus.**
- **Contract of my outputs** — what other slices may depend on:
  - `taskset.json` — schema `forest_v2.s09.taskset/2`, 20 frozen cases,
    digest `sha256:c3ef36f1…` over the canonical case list. Query = commit
    message, gold = files that commit changed *and* that existed in its
    parent tree, universe = that parent tree. `taskset.load()` recomputes the
    digest and refuses a drifted set. **`/2` is additive over `/1`: the case
    list and therefore the digest are byte-identical.** What is new is the
    record around the cases — `selection_census`, `acceptance`,
    `dropped_breakdown`, `plane_composition` — all of which were previously
    computed during selection and thrown away.
  - `contract.py` — implement `name` + `rank(QueryView, Sequence[Candidate])
    -> Sequence[str]`. `QueryView` carries `case_id`, `text`, `variant`,
    `revision`, `repo` and **no gold**; `Candidate.text()` truncates at the
    shared byte budget. Attach with `--retriever your_module:YourRetriever`;
    nothing here imports s07/s08. **`repo` is new and load-bearing: read the
    repository from that field, never from a hardcoded path**, or you will be
    graded outside the isolation described below.
  - `results/raw.json` — schema `forest_v2.s09.results/1`: aggregates, MRR
    bootstrap intervals, paired comparisons, per-case rows, cost. **The key
    for `paired_comparisons` is `(subject, reference, variant)`** — declared
    in the payload as `paired_comparisons_key`. See the retraction below if
    you wrote a consumer against the earlier shape.
- **Budget:** identical universe object, 65 536 bytes per file, cutoffs
  1/5/10/20, tokenization charged once per case. Pure stdlib plus read-only
  git plumbing. No model calls, no spend.
- **Expiry:** 2026-09-15. After that, re-freeze against a current anchor
  before reusing any number below; the history keeps moving.

### RAW results [MEASURED]

20 cases, 35 gold paths, universe 3896–4731 files, anchor `d849c2a9`,
Python 3.10.11 on `Windows-10-10.0.26200-SP0`. Counts are hits/gold pooled
over cases. Every row below is now pinned to `results/raw.json` by
`test_published_numbers.py`.

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
| path_lexical | scrubbed | 0/35 | 0/35 | 0/35 | 0/35 | 0.000 | 0.000 | 0/20 |

MRR with 95% bootstrap CI (2000 resamples, seed 20260818), and the paired
delta against the query-blind prior:

| retriever | MRR raw (95% CI) | delta vs recency_prior | excludes 0 |
| --- | --- | --- | --- |
| recency_prior | 0.224 [0.121, 0.361] | — | — |
| bm25_content_only | 0.157 [0.056, 0.286] | −0.067 [−0.211, 0.048] | no |
| bm25 | 0.141 [0.043, 0.268] | −0.083 [−0.226, 0.034] | no |
| path_lexical | 0.124 [0.049, 0.232] | −0.099 [−0.256, 0.062] | no |
| random_uniform | 0.004 [0.000, 0.011] | −0.220 [−0.358, −0.117] | yes |

**Timings are not reported and no longer appear in this document.** The
earlier "79.4 s wall" figure is withdrawn: a re-run of identical work
measured `bm25` at 6.525 s against a stored 26.806 s, a 4.1× swing that is
machine load, not the harness. `raw.json` still records `rank_seconds` and
`wall_seconds_total` for shape, now carrying a `timing_disclaimer` field
next to them. Do not cite them and do not rank retrievers by them.

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
3. ~~**The filename echo is real and it is total for path matching.**
   `path_lexical` falls 0.124 → 0.000 when gold-path tokens are scrubbed
   from the query. Every point it scored was the commit message naming its
   own file.~~ **RETRACTED — see "Correction F1" below. That 0.000 is
   arithmetic, not a measurement.**
4. **BM25 mostly survives scrubbing** (0.141 → 0.117; content-only 0.157 →
   0.126), so its signal is largely real content matching rather than echo.
   This claim is unaffected by F1: BM25 scores document tokens, which the
   scrub does not structurally empty.
5. **Negative result, retained:** adding path tokens to the BM25 document
   *hurt* it in both variants (0.157 → 0.141 raw). Path tokens inflate
   document frequency for common directory names. Do not assume "more
   fields" helps.

### Correction F1 — a tautology was published as a finding

The retracted claim inferred a property of this repository from a number
that cannot vary. `scrub()` bans exactly `path_tokens(gold)`. `PathLexical`
scores exactly `|word_tokens(query) ∩ path_tokens(candidate)|` and drops
zero-scoring candidates. After the scrub that intersection is empty **by
definition**, so gold is unscorable for any path-token retriever on any
corpus in any repository. Measured: scrubbed queries are token-disjoint from
their gold on **20/20** cases and **0/35** gold paths are scorable. The
package's own `test_scrubbed_queries_share_no_token_with_their_gold` proves
the identity, and the README then reported its consequence as evidence.

The inference was wrong in a second way. The scrub bans *directory* tokens
too, so it erases every path signal, not merely the filename echo.

**The requested repair was built and run, and it returns a null.** The
audit's suggestion — scrub only the basename, leave directory tokens — is
implemented as `taskset.scrub_basename` and exposed as
`--variant scrubbed_basename`. On this corpus it produces **byte-identical
queries to the full scrub on all 20 cases**, because of a property worth
recording on its own:

| quantity | value |
| --- | ---: |
| gold paths that have at least one directory token | 35/35 |
| gold paths whose commit message names any directory token | **0/35** |
| gold paths scorable by path overlap, raw query | 26/35 |
| gold paths scorable by path overlap, basename scrub | **0/35** |
| gold paths scorable by path overlap, full scrub | 0/35 |

So the honest replacement statement is narrower than the retracted one and
is a real measurement: **whatever path signal these commit messages carry is
entirely the filename; not one of them names a directory of the file it
touches.** The weaker scrub removes exactly the same tokens as the stronger
one, this corpus cannot separate echo from path signal, and `path_lexical`'s
0.000 stays arithmetic in *both* scrubbed variants. Pinned by
`test_the_basename_scrub_is_indistinguishable_from_the_full_scrub_here` and
`test_no_commit_message_names_a_directory_of_its_gold_file`.

### Correction F2 — "supply-capped, not chosen" was false

The limitation list said the 8/12 split was "supply-capped, not chosen", and
the selection comment in `taskset.py` said the shortfall was "filled from the
single-file stratum". Both were wrong, and the second describes an event that
never happened.

| quantity | value |
| --- | ---: |
| admissible commits in the 1200-commit window | 728 |
| admissible **multi-file** commits | **18** |
| `SELECTION["multi_file_target"]` | **8** |
| multi-file cases used | 8 |
| admissible multi-file commits left unused | **10** |

Supply exceeded the quota by more than 2×. The split is a **choice**. No
shortfall occurred, so nothing was filled from anywhere. The quota is left at
8 rather than raised, because raising it re-freezes the corpus and discards a
table that has been independently reconstructed; the correction is to the
description, and `selection_census` in `taskset.json` now carries supply
against quota so the claim cannot drift back into prose. Pinned by
`test_the_multi_file_quota_is_a_choice_not_a_ceiling`.

### Correction F3 — 15 rejections were counted nowhere, and they are not random

Filling 20 slots required considering 35 commits. `consider()` returned
`False` for 15 of them and incremented no counter, so a 57.1% acceptance rate
appeared in no field of `taskset.json` and in no sentence here.

| quantity | value |
| --- | ---: |
| commits considered | 35 |
| commits accepted | 20 |
| commits rejected | **15** |
| acceptance rate | **57.1%** |
| rejection reason (all 15) | every changed file was created by that commit |

The denominator matters less than the bias. A commit is rejected exactly when
nothing it touched existed in the pre-image tree — that is, when it **creates**
files. Both rejected multi-file commits were five-file commits of the shape
`.github/workflows/*.yml` + `docs/work-packets/*.md` + `tests/fixtures/*.py` +
tests: three planes in one commit, which is **precisely the cross-plane shape
the four-plane prior exists to exploit**, removed from the corpus without a
trace.

Stated plainly, as a property of the corpus: **this task set is biased toward
edits to existing code and against the introduction of new cross-plane
structure.** Recorded in `taskset.json` under `acceptance`
(`commits_considered`, `acceptance_rate`, `rejection_reasons`,
`rejected_commits`, `composition_bias`) and pinned by
`test_the_rejection_denominator_is_recorded` and
`test_the_rejected_population_is_file_creating_commits`.

### Correction F4 — this corpus cannot exercise the hypothesis it grades

Declared here **before** s07 or s08 are graded against it, because it decides
how their results may be read.

| quantity | value |
| --- | ---: |
| gold paths that are `.py` | **32/35 (91.4%)** |
| gold paths by plane | code 32, data 2, knowledge 1 |
| cases spanning more than one plane | **3/20** |
| cases touching the Knowledge plane | **1/20** |
| cases matching the Gate-1 Python+Markdown+CSV scenario | **0** |
| file-level representatives of the Type plane | **0** |

This is the mirror image of s08's defect and it points the safe way. A
four-plane method can register a **loss** on this corpus. It has almost no
mass on which a cross-plane **win** could appear. **A null result here is
close to preordained and must not be read as a kill criterion firing**
(plan §13); it is evidence that this corpus cannot see the effect, not
evidence that the effect is absent. Grading a cross-plane hypothesis for
real needs a corpus built to contain cross-plane commits — including the
file-creating ones F3 removes. Recorded under `plane_composition` (with the
warning text inside the artifact) and pinned by
`test_the_corpus_cannot_exercise_the_hypothesis_it_grades`.

### Correction F5 — the published contract was ambiguous and misled a consumer

`PairedDelta` carried no `variant` and `as_dict()` emitted none, while the
runner concatenates every variant into one flat `paired_comparisons` array:
8 entries, **4 distinct `(subject, reference)` keys**, nothing separating raw
from scrubbed. Position was no fallback either, because each variant block is
independently re-sorted by `-delta.point`. A consumer keying on the only
meaningful pair silently read the scrubbed number — which happened to the
verifier's own script before they caught it.

`variant` is now a field on `PairedDelta`, emitted by `as_dict()`, matching
what `Aggregate.as_dict()` always did. The payload declares
`paired_comparisons_key: ["subject", "reference", "variant"]`, and
`harness.comparison_payload` **refuses to serialise** an array with a missing
variant or a colliding key rather than publishing something misreadable. The
regenerated `raw.json` has 8 entries under 8 distinct keys; every other number
in it is byte-identical to the version the audit reconstructed.

### Correction — `gold_created_dropped` is mislabelled (a label, not a scandal)

`dropped` collects every changed path outside the *eligible* universe, so
files that existed in the parent tree but fail the suffix/size rule are
recorded as if the commit had created them. Of the 5 dropped paths, **3 were
created by their commit and 2 existed in the parent tree**
(`.daedalus-bootstrap/g0-final.patch`,
`docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl`).

**The total 35 gold paths is unaffected and the denominator was never
shaved** — an ineligible file is outside the searchable universe too, so it
really is unretrievable. The field name is kept because renaming it would
change the case schema and therefore the digest that anchors every published
number; `dropped_breakdown` in `taskset.json` carries the honest split and
says so in the artifact. Pinned by
`test_dropped_paths_are_split_into_created_and_ineligible`.

### The oracle hole is closed for foreign retrievers (A3)

`QueryView.revision` documented "read nothing committed after the case" and
called itself "a norm, not a sandbox". Executed: a retriever walking git
forward to its own child commit scored **MRR 1.000, 20/20 hits, fully
separated, detected by nothing**. An s07 or s08 retriever could trip this by
accident — indexing the current HEAD tree instead of the pre-image is enough.

Grading now runs against a **pre-image-only bare clone, one per case**, and
that is the **default whenever `--retriever` is used**
(`--no-isolate-preimage` opts out and prints a warning). The clone is built by
pushing a single commit into a fresh bare repository, so `git push` computes
the object closure: ancestors come along, descendants cannot. The commit
holding the answer is not merely unreferenced — it is **absent from the object
store**. One clone per case, because reachability is a property of a
repository and not of a ref: a single clone holding every case's pre-image
would still expose an older case's answer commit as an ancestor of a newer
case's pre-image.

Verified by an executed attack rather than by inspection:
`test_a_forward_walking_retriever_is_blinded_by_isolation` runs the same
forward-walking oracle twice, asserts it names the gold file **first** against
the live repository, and asserts it cannot against the clone. Disabling the
isolation turns that test red.

Residue, stated rather than papered over: a retriever that ignores
`QueryView.repo` and hardcodes a path to the live working tree escapes this.
Baseline-only runs leave isolation off, so the table above is unchanged and
reproducible exactly as published.

### Limitations, stated once and not walked back

- **Plane composition (new, and the most consequential).** 91.4% of gold is
  Python, 3/20 cases span more than one plane, 1/20 touches Knowledge, the
  Type plane has no representative, and the Gate-1 scenario has none. See
  Correction F4: a null result from a cross-plane method on this corpus is
  uninformative, not a kill.
- **Composition bias from silent rejection (new).** 15 of 35 considered
  commits were rejected, all of them file-creating, including two five-file
  three-plane commits. See Correction F3.
- **Hindsight queries.** The commit message is written after the change.
  Even scrubbed, it is a description of finished work, not a request from
  someone who has not seen the diff. This corpus cannot measure that.
- **n = 20, one repository.** Intervals are wide; nothing here transfers to
  another repository without another corpus. Bootstrap resamples quantify
  sampling noise across these cases, nothing more.
- **Churn is unusually strong here.** This history hammers a small set of
  gate-0 files, which flatters `recency_prior`. That makes it a demanding
  local bar and a weak general claim.
- **The 8/12 stratum split is a choice, not a supply ceiling.** Corrected;
  see F2. Ten admissible multi-file commits were left unused.
- **`revision` is enforced only under isolation.** Foreign retrievers are
  graded against a pre-image clone by default (see A3), but a retriever that
  ignores `QueryView.repo` still reaches the live repository, and the plan is
  explicit that a prompt is not a boundary.
- **Timings are not a property of this harness.** See above; the wall-clock
  figure is withdrawn.

### What the suite does and does not establish

116 tests, up from 54. The gaps the mutation pass found, and what closed them:

- **`gitio.py` and `tokens.py` had no test file.** `gitio.read_blobs` supplies
  *all* document content; made to return `b""` for every blob, the published
  BM25 table would collapse to near zero and **54/54 tests still passed**.
  Nothing constructed a `BlobStore`, called `read_blobs`, or exercised
  `build_universe`. `test_gitio.py` now drives that path end to end against a
  real three-commit fixture repository, and that mutation turns three named
  tests red.
- **No test reproduced any published number.** All 54 asserted rules against
  synthetic fixtures; nothing read `results/raw.json`. The suite would have
  stayed green if every number here were wrong. They are right —
  independently reconstructed — but the suite was not what established that.
  `test_published_numbers.py` now pins all ten table rows, the interval
  separations, and every census field to the artifacts.
- **The read-only claim covered 4 of 5 call sites.** `gitio`'s docstring said
  "no command in this module can mutate a repository" while `read_blobs`
  shelled `cat-file --batch` around the gate and `RecencyPrior._recency`
  shelled `git log` straight out of `retrievers.py`. Both now route through
  `_run`, the gate takes `stdin` so it can, and the docstring states the
  precise claim: no function here can mutate the repository it reads from,
  and exactly one function (`make_preimage_clone`) writes at all — into a
  caller-supplied destination that must not already exist.
- **Tokenizer rules were untested.** Lowercasing, the camelCase split and the
  length-1 filter could each be deleted with the suite green. Now each has a
  named test.

Every guard added in this pass was mutation-tested: disabled, confirmed to
turn a **named** test red, restored, and the suite reconfirmed at 116.
One honest exception: dropping `variant=variant` at the harness's *call site*
leaves the suite green and is instead caught by the runner refusing to
serialise (exit 1, `ValueError: paired comparison carries no variant`). The
guard itself (`comparison_payload`) is covered by named tests; the caller
mistake is caught fail-closed at runtime, not by pytest.

### Known hazard, recorded and not chased

`BlobStore.ensure` clears the whole cache mid-batch on cap overflow, which
would blank blobs already fetched in that same batch and hand retrievers empty
documents without any error. Not reached in this run: 4945 blobs / 40.6 MiB
against a 256 MiB cap. It is a latent correctness bug, not a live one, and it
is written down here so a larger corpus does not rediscover it as a mystery.

## Slice s09, continuation 2 (2026-08-18): a corpus that can be asked the question

Artifact: `s09_eval/taskset_xplane.json`, schema
`forest_v2.s09.taskset_xplane/1`, cases digest
`sha256:0148e7f0e3744c40420cc90e31ee0f306930f7ac9e341289d8e5ac247e6c6386`,
anchor `d849c2a94d66ffb1bf892de924995645395bf2a6`.
Build: `python -m experiments.forest_v2.s09_eval.taskset_xplane`.
Rebuilt twice at the same anchor, byte-identical both times [MEASURED].

**This is additive. The first corpus is untouched** and stays the corpus every
number published above was measured on. Proof is below, and a test enforces it.

### Frozen specification

- **Hypothesis this instrument is built to test (not tested here):** verified
  cross-plane structure improves retrieval of the files a change must touch,
  and the improvement concentrates on changes that actually span planes.
- **What this continuation delivers:** the corpus, and nothing else. No
  retriever is run, imported, or scored against it in this slice. Gold is
  derived from git history and frozen first; that ordering is the property
  that let the first corpus survive independent reconstruction when nine
  sibling slices did not.
- **Scope:** read-only git plumbing over one pinned anchor, one new module,
  one JSON artifact, one test file. No model calls, no network, no spend.
- **Expiry:** 2026-10-31, same as the rest of this pre-study. The anchor is
  pinned, so the corpus does not rot when the tree moves; but if nothing has
  consumed it by then, re-argue it rather than inherit it.
- **Kill-criterion linkage:** this corpus is what makes plan section 13's
  "graph-conditioned prioritization does not beat random or evaluator-only
  choice" *checkable* here. It does not make a result from it *conclusive* —
  see "What this does not buy" below.

### Why a second corpus rather than a wider first one

The first corpus cannot decide anything about cross-plane structure, measured
rather than asserted: 32 of its 35 gold slots are `.py`, 3 of 20 cases span
more than one plane, exactly 1 touches Knowledge, 0 touch Type, and the Gate-1
flagship shape has no representative. A cross-plane retrieval arm scored
against it returned a paired MRR delta of exactly +0.000000 with a bootstrap
CI of [0, 0] — degenerate, because the graph signal reached 5 of 35 gold slots
and the text baseline had already placed the gold at rank 1–3 on every one.

Re-freezing the first corpus to fix that would invalidate every number
published against it at once, so it is left alone.

### What the old selection rule could not see

| old rule | what it cost |
| --- | --- |
| `history_limit: 1200` | 61 commits in this history carry usable cross-plane gold; only 13 fall inside a 1,200-commit window. **48 were excluded by window position alone.** The new limit covers all 1,457 reachable single-parent commits. |
| `require_python_change: true` | deletes the entire `{data, knowledge}` stratum — 10 commits where a document and a schema move together with no Python at all. That is the purest cross-plane shape in the history. Dropped. |
| `max_changed: 6` | leaves 39 cross-plane commits and collapses `{code,data,knowledge}` from 15 to **3** [MEASURED]. |

### Composition of the new corpus [MEASURED]

88 cases: 58 cross-plane, 30 single-plane control.

| quantity | first corpus | this corpus |
| --- | ---: | ---: |
| cases | 20 | **88** |
| gold slots | 35 | **475** |
| cases spanning >1 plane | 3 | **58** |
| cases spanning 3 planes | — | **13** |
| cases touching Knowledge | 1 | **45** |
| cases touching Type | 0 | **0** |
| Gate-1 `.py`+`.md`+`.csv` shape | 0 | **0** |

Gold slots by plane: code 313, knowledge 78, data 71 (plus 13 `.html`/`.css`
slots, which are gold but are **not** counted as plane span — see below).
By suffix: `.py` 285, `.md` 78, `.json` 60, `.tsx` 17, `.html` 10, `.js` 6,
`.yml` 6, `.ts` 5, `.toml` 5, `.css` 3.

Cases by plane combination:

| combination | cases | stratum |
| --- | ---: | --- |
| `code+knowledge` | 22 | cross-plane |
| `code+data` | 14 | cross-plane |
| `code+data+knowledge` | 13 | cross-plane |
| `data+knowledge` | 9 | cross-plane |
| `code` | 28 | control |
| `data` | 1 | control |
| `knowledge` | 1 | control |

The target was ≥60 cases, ≥20 spanning ≥2 planes, ≥15 touching Knowledge. All
three are met, and the ≥60 came from power rather than taste: at the observed
per-case reciprocal-rank spread (sd 0.244), n=20 cannot resolve an effect below
about 0.15 MRR against a base of 0.1168.

### The control stratum is a placebo, not a second measurement

30 single-plane cases exist so a cross-plane method's gain can be checked for
*specificity*. A method whose gain appears equally on single-plane cases is not
gaining from planes. The control is drawn only from single-plane commits with
≥2 gold paths, because cross-plane cases are multi-file by construction and a
single-file control would confound plane-span with gold-set size. Median gold
size: 5 in the cross-plane stratum, 3 in the control [MEASURED] — not equal,
and stated rather than smoothed.

### The denominator, in four buckets that close

1,457 commits considered = 691 rejected by rule + 766 admissible.
766 admissible = 88 accepted + 678 admissible-but-not-sampled.

| rejected by | count | why the rule exists |
| --- | ---: | --- |
| `no_retrievable_gold_in_pre_image` | 687 | every changed path was created by the commit or fails the suffix/size rule, so nothing it touched is retrievable from the pre-image tree |
| `gold_exceeds_largest_cutoff` | 3 | Recall@20 is bounded by 20/G < 1 above k, for every retriever including a perfect one |
| `rename_dominated_diff` | 1 | see below |
| `parent_tree_unreadable` | **0** | **not counted as a rule** — see below |

| admissible but not sampled | count | why |
| --- | ---: | --- |
| `single_plane_below_control_min_gold` | 592 | single-file; would confound plane-span with gold-set size |
| `single_plane_beyond_control_quota` | 86 | the control is capped so it cannot outweigh the stratum it contrasts with |

Rejection and non-selection are different facts and are kept in different
buckets. The first corpus recorded "35 considered, 20 accepted, 15 rejected"
and had no counter at all for the commits it never looked at.

**The largest bucket is biased and the bias is not fixable here.** The 687 are
dominated by file-*creating* commits, which is exactly the shape that
introduces new cross-plane structure. A pre-image retrieval task cannot score
a file that does not yet exist. This is recorded so nobody reads the corpus as
a uniform sample of the repository's history.

### A rule that cannot reject is not a rule

`parent_tree_unreadable` fires **0** times in this history. It is kept as an
I/O failure branch — it separates "git could not read the parent tree" from
"the parent tree holds no gold" — and it is deliberately kept **out** of
`SELECTION_RULES`, because a never-firing branch presented as a safeguard is
how a corpus acquires rigour it does not have. A test asserts both halves.

`min_message_chars >= 24`, inherited from the first corpus, was tried and
**removed**: it rejects 0 of the 770 gold-bearing commits. Its measured zero is
recorded in the artifact so the next person does not re-add it as prudence.

### The two bulk contaminants, excluded by rule

**The rename-dominated diff.** Commit `946db82a` is 249 R100 renames under
`runs/audit_swarm/` out of 309 diff entries. The rule is not "drop this sha" —
no commit sha appears in the selection code. It is `rename_fraction >= 0.5`,
and the reason is that this commit's gold set *is not stable*: under git's
default rename detection it reports 309 changed paths and yields 3 gold; under
`diff.renames=false` it reports **558**, and the 249 extra are the pre-rename
paths, which do exist in the parent tree and are eligible, so the same commit
would contribute ~249 gold slots [MEASURED]. A corpus whose Recall@k
denominator moves when a client-side git config flag moves is not frozen. The
rule makes the corpus invariant to that knob. It rejects exactly 1 commit, and
that commit was cross-plane — the rule costs something real.

**The mechanical mass edit.** `max_gold_paths <= 20` is set to the largest
reported cutoff, on the argument above about Recall@k being unattainable past
k. What it removed, measured: 3 commits, of which 2 were cross-plane and both
of those tri-plane — a 56-path central-wiring port and a 28-path rebrand that
also carries 34 renames. Neither is cross-plane evidence: those files moved
together because one substitution was applied to all of them, not because a
change in one plane implied a change in another. **That the cap happens to
remove exactly the mechanical commits is an observation, not the cap's
justification.** The justification is the metric bound; the tidiness is luck,
and if the two ever diverge the metric bound wins.

The cap costs 2 of 15 tri-plane commits. That cost is recorded in the artifact
under `cap_cost`, not left in prose.

### Supply attrition, as a chain that closes [MEASURED]

61 cross-plane commits exist before any rule → `rename_dominated_diff` takes 1
→ 60 → `gold_exceeds_largest_cutoff` takes 2 → **58 admissible, 58 accepted, 0
unused**. Cross-plane supply is the *ceiling*, not a quota: every admissible
cross-plane commit in the whole reachable history is in the corpus. A demand
for more cross-plane cases is a demand for a different repository.

Three separate numbers about "how many cross-plane commits there are" invite
the reader to assume they describe the same population. They do not, so the
artifact writes them as a chain that has to add up, and a test checks it does.

`presentation` (`.html`/`.css`) is **not** one of the four planes and is not
counted as span. Counting it would inflate this history's cross-plane supply
from 61 commits to 70. Such paths are still gold and still retrievable; they
just cannot make a case cross-plane on their own.

### The Type plane still cannot be represented

**0 gold slots, and this is not an oversight to be fixed by a wider suffix
map.** The Type plane has no file-level node, so a gold label whose unit is a
file path can never name it. Counting a `.py` file because it carries
annotations would not fix this: the retrievable unit would still be the file,
and a retriever that returned it would be scored for finding code. This corpus
represents **three** planes.

What symbol-level gold would take, stated but **not built under this brief**:
gold whose unit is a `(path, qualified name, revision)` triple; a
symbol-resolving extractor over each pre-image tree (the call-resolution probes
above are the closest existing machinery, and they attribute 30.3% of call
sites, which is nowhere near enough to ground a gold label); and a retriever
contract whose candidate universe is symbols rather than files — which changes
`Candidate`, the universe budget, and every metric denominator. That is a
different slice, and it should not be started on the strength of this
paragraph.

### The semantically tight shape is scarce

The one genuinely cross-plane shape in this history is the work-packet seam: a
`.md` document, its `.json` contract, the `.py` implementation and the `.yml`
workflow moving together. Two files changing together because someone ran a
formatter satisfies "multi-plane" and is not cross-plane evidence.

Detected mechanically as a shared basename stem appearing in two or more
planes inside one gold set. **It occurs in 5 of the 88 cases** [MEASURED],
including both known instances `4d67a562` and `824b1ec9`. Five is far too few
to build a corpus from, so the shape is *labelled per case* (`seam_stems`)
rather than used as a filter. Any analysis that wants only semantically tight
cross-plane evidence should restrict to those cases and report the reduced n
honestly. The scarcity is itself a finding about what this repository can
support.

### What this buys, and what it does not

It buys **askability**. There is now mass on which a cross-plane win could
appear, and a control stratum on which it should not.

It does **not** buy an interpretable answer, and the write-up should not
pretend otherwise. The cross-plane edges this repository can currently produce
are laundered: all 2,528 carry one hardcoded evidence constant, and a
deliberately falsified edge was measured to receive the same
`assurance='verified'` label as a true one. Until that verifier is fixed — work
that lives outside this directory and is not this slice's — a win measured on
this corpus is a win for a *label*, not for a plane.

**This artifact is an instrument awaiting a subject.**

### Guards, and the mutation run that graded them

`s09_eval/test_taskset_xplane.py`, 29 tests. Every one asserts a behaviour of
the artifact or of the builder; none asserts the presence of a word in a source
file, because a text-scanning guard has twice been satisfied here by an
unrelated occurrence.

14 mutations were applied one at a time, each with a named test to watch:

| guard disabled | named test | verdict |
| --- | --- | --- |
| cap unbound from the largest cutoff | `test_no_case_carries_more_gold_than_the_largest_cutoff` | RED |
| never-firing branch promoted to a rule | `test_every_selection_rule_rejects_at_least_one_commit` | RED |
| digest check removed from `load()` | `test_load_refuses_a_tampered_case` | RED |
| `presentation` admitted as a plane | `test_presentation_paths_cannot_make_a_case_cross_plane` | RED |
| Type plane faked by relabelling `.py` | `test_the_type_plane_has_no_gold_slot_anywhere` | RED |
| seam detector stops requiring two planes | `test_seam_detection_needs_one_artifact_in_two_planes` | RED |
| builder pulls in a retriever | `test_building_the_corpus_imports_no_retriever_and_no_scorer` | RED |
| census denominator understated | `test_census_buckets_add_up` | RED |
| supply chain no longer closes | `test_supply_chain_closes` | RED |
| rename-dominated commit smuggled back in | `test_the_rename_dominated_commit_is_absent_and_accounted_for` | RED |
| one case's gold silently widened | `test_gold_is_reconstructible_from_raw_git_without_this_package` | RED |
| the first corpus rebuilt under this slice | `test_the_first_corpus_is_byte_reachable_and_unchanged` | RED |
| control stratum allowed to be single-file | `test_the_control_stratum_is_matched_on_gold_set_size` | RED |
| cap-cost arithmetic falsified | `test_the_cap_reports_what_it_cost` | RED |

**14 of 14 caught — but only on the second run.** The first pass had one
survivor, and it is worth recording rather than quietly fixing: a builder
rewritten to relabel every `.py` as `type` left
`test_the_type_plane_has_no_gold_slot_anywhere` **green**, because that test
read only the frozen record, which had been built before the mutation. The
guard was strengthened to run the live labeller over the corpus's own paths.
The lesson generalises: a guard that reads a frozen artifact proves the
artifact is clean and proves nothing about the code that would dirty the next
one.

### Proof the first corpus is unchanged [MEASURED]

- `git diff` against HEAD for `s09_eval/taskset.json` and `s09_eval/taskset.py`:
  empty.
- EOL-normalised sha256 of `taskset.json`, HEAD vs worktree:
  `c83841ae…` both.
- Loaded through its own loader, which recomputes the digest from the cases:
  file digest and recomputed digest both
  `sha256:c3ef36f19ebaaf953ef8c26615295dfe7e845a89ec68b50ffb5c933df96d8c33`,
  schema `forest_v2.s09.taskset/2`, 20 cases, ids `c00`…`c19`.
- `test_the_first_corpus_is_byte_reachable_and_unchanged` pins the digest and
  goes red if the corpus is rebuilt.

The only change to a pre-existing file in this continuation is one added
function in `s09_eval/gitio.py`, `read_rename_stats`, which reads diff
statuses through the module's existing read-only verb gate rather than around
it. The rename rule needs to see rename *statuses*, and `read_history` uses
`--name-only`, which hides them.

## Boundary note

**Corrected 2026-08-18.** This note previously read "this directory currently
contains no effectful entrypoint". That stopped being true in the same commit
that stated it. **Updated again in continuation 2: the count is now three, not
two.** Adding an entrypoint without updating this table is precisely how the
note went stale the first time.

| entrypoint | effect |
| --- | --- |
| `s09_eval/harness.py:main` | `mkdir` + `write_text` of `results/raw.json`, on the default path, suppressed only by `--no-write` |
| `s09_eval/taskset.py:main` | `write_text` of `taskset.json` |
| `s09_eval/taskset_xplane.py:main` | `write_text` of `taskset_xplane.json` |

Both are unscanned. `daedalus/spine/effect_boundary.py` pins
`HARNESS_PACKAGES = ("scripts", "tests")`, so nothing under `experiments/` is
seen by the effect scanner at all.

**Escalation, not a fix.** Extending `HARNESS_PACKAGES` or registering these
entrypoints in the canonical effect registry is a kernel change to a protected
policy artifact and belongs to the owner, not to an experiment slice. This
slice does not touch `daedalus/`. The exact gap:

- file: `daedalus/spine/effect_boundary.py`
- constant: `HARNESS_PACKAGES = ("scripts", "tests")`
- unscanned effectful entrypoints:
  `experiments/forest_v2/s09_eval/harness.py:main`,
  `experiments/forest_v2/s09_eval/taskset.py:main`,
  `experiments/forest_v2/s09_eval/taskset_xplane.py:main`
- both write only inside `experiments/forest_v2/s09_eval/`; neither performs
  network egress, spend, or model calls.

An unscanned effectful directory is the exact blind spot the boundary work
just closed, and it is now open again under `experiments/`. Anyone adding a
further effectful entrypoint here inherits the same gap.
