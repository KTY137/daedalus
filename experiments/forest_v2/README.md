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

## Slice s02 (2026-08-18): the type plane — `s02_types/`

Sibling slice to the call-resolution probes above, same frozen frame, own
sub-directory. Where those measure the **code** plane's resolution gap, this
one builds the **type** plane of master plan section 5 and measures how much
of it is actually recoverable from declarations.

### RETRACTION (2026-08-18) — the headline comparison was a straw man

**Withdrawn:** *"92.77% signature resolution against a 37.16% builtins-only
control = +55.6 pp, so the plane does not need type inference."* That
comparison is withdrawn in full. It is not restated in weaker words below; it
is gone, and what replaces it is a much smaller number.

**The error.** The builtins-only control cannot read a single import
statement — there is no code path by which it could (`type_plane.py`, the
`builtins_only_bucket` rule). Scoring low against it is guaranteed for any
corpus that names a non-builtin type, so the 55.6 pp measured "this repository
uses types that are not `int`", which nobody doubted. 823 of that control's
1562 hits (52.69%) are functions with no parameters at all, resolving on a
return annotation alone. Two further faults compounded it:

1. **The natural control was never run.** The honest question is "is the
   signature syntactically annotated at all?". Against *that* control the
   entire import-binding and symbol-table machinery changes the verdict on
   **5 of 4203 functions — 0.119 pp** (conditional resolution rate
   3899/3904 = 99.87%).
2. **The stated falsifier could not fire.** `sig_resolved` was coupled to
   `sig_annotated` by construction: a missing annotation set both to false, so
   `sig_resolved ⊆ sig_annotated` always. A low rate could only ever have meant
   "this corpus is not annotated", never "types here are not resolvable". The
   slice was measuring how well `daedalus/` is annotated and reporting it as
   how resolvable types are — while citing the kill criterion *"a plane has no
   marginal contribution in ablation"* next to the one ablation that cannot
   answer it.

**What is claimed now.** The marginal contribution of the machinery over an
annotation-only control is **0.119 pp on this repository**, it is *subtractive*
(the resolver is a strict subset of its control, so this is also its ceiling),
and on five of six corpora it is between 0.000 and 1.249 pp. The construction
claim that survives is much narrower and is stated in "What the slice now
claims" below.

### Frozen specification (slice s02)

- **Hypothesis, original text — the inference clause is UNTESTED:** *"the type
  plane of this repository can be recovered from declarations alone —
  annotations, signatures, dataclass and TypedDict fields, class bases, type
  aliases — at a rate high enough that Gate 2 does not need type *inference*
  to make the plane useful, and the residue that cannot be recovered is small,
  enumerable, and mostly a real defect rather than a limit of the extractor."*
  The second half stands: the residue on `daedalus/` is 7 names and 6 of them
  are real source defects, enumerated below. The inference clause does not:
  nothing in this slice compares a declaration-only plane against an inferring
  one, so it was never in a position to conclude that inference is
  unnecessary. See "What the slice now claims".
- **Falsifier — original text, WITHDRAWN:** *"if the resolved-signature rate
  had come out low, or if the unresolved residue were dominated by extractor
  limitations rather than real source problems, the type plane would need
  inference (a far larger Gate-2 cost) before it could carry any weight, and
  this slice would say so."* This was not a falsifier. `sig_resolved` was
  coupled to `sig_annotated` by construction, so a low rate could only ever
  have reported low annotation coverage. The spec is corrected here rather
  than quietly reworded, and the original wording is kept above so the
  correction is auditable.
- **Falsifier — replacement, decoupled and demonstrated to fire:** two rates
  now carry the resolvability question, and neither is bounded by annotation
  coverage:
  - `type_name_resolution_pct` — resolved / all type-name occurrences;
  - `sig_present_annotations_resolve_pct` — of the functions carrying at least
    one annotation, the share whose *present* annotations all attribute.

  Either can go to 0 on a fully annotated corpus and to 100 on a barely
  annotated one, and both directions are exercised by checks
  (`test_falsifier_fires_full_annotation_coverage_zero_resolvability`,
  `test_decoupled_rate_is_high_when_coverage_is_low`). A mutant that pads the
  resolved counter is killed by `falsifier_can_fire` in the mutation probe, so
  the metric cannot be inflated back into uselessness without something going
  red. **Verdict: the falsifier can now fire.** On `daedalus/` it does not
  (99.95% / 99.86%); on the fixture corpus it does (86.67% / 81.25%).
- **Kill-criterion linkage (section 14, "a plane has no marginal
  contribution"):** the first version of this slice cited that criterion while
  running the one ablation that could not answer it. Corrected: the ablation
  below is *construction*-side only, and it now uses the control the criterion
  actually implies (annotation-only). It shows what the extraction machinery
  buys in coverage over a corpus that is already annotated; it does **not**
  show that the type plane improves any downstream task. That is Gate 3/4 work
  and this slice claims none of it. On the construction side the answer is now
  measured and small — see the corpus table.
- **Contract of outputs** — schema `forest-v2-type-plane/1`, one JSON object
  on stdout, deterministic, revision-stamped:
  - type nodes `type:<bucket>:<canonical name>`, plane `type`;
  - symbol nodes `sym:<module>.<qualname>` and `...#<param>`, plane `code`.
    These are *anchors* only: the slice does not re-derive the code plane,
    it names the endpoints its edges need.
  - cross-plane edges (code -> type): `param_type`, `return_type`,
    `field_type`, `var_type`, `subtype_of`;
  - intra-plane edges (type -> type): `type_arg`, `alias_of`;
  - edges are unique per `(src, dst, kind)` and carry `count` plus a
    `first_seen` source locator.
  - Every edge here is *declaration evidence*, not a latent proposal. The
    section 6 verifier problem does not arise; what does arise is whether the
    annotation's name can be attributed at all, which is what the buckets
    measure.
- **Scope:** read-only AST analysis of the kernel package — **widened in
  continuation 3** to a fixture corpus inside this directory and to
  externally-authored corpora already present on the machine (the
  interpreter's own standard library and installed distributions), read in
  place and never written. No imports of the analysed code, no writes, no
  network, no subprocess. `daedalus/` is read and never edited, and nothing in
  `daedalus/` imports this directory. The widening is recorded here rather
  than assumed: the original scope could not answer the marginal-contribution
  question, because the original corpus had no headroom in which to fail.
- **Budget:** one module plus its checks, grown to four modules and two check
  files across three continuations; no model calls, no spend. The whole suite
  re-runs in under 30 s; the widest corpus sweep is ~19 s.
- **Expiry:** 2026-09-15. Re-measure before reuse after that date — the tree
  moves, and every number below is revision-bound.

### Measured baseline (2026-08-18) — `[MEASURED]`, raw

`python experiments/forest_v2/s02_types/type_plane.py` over `daedalus/` at
tree state `d849c2a9` (this slice adds only files under `experiments/`, so
the measured package is byte-identical to that base):

| quantity | raw | rate |
| --- | ---: | ---: |
| files parsed | 285 (0 unparseable) | |
| functions / methods / nested | 2588 / 1519 / 96 | |
| signatures syntactically annotated (**the control**) | **3904 / 4203** | **92.89%** |
| functions with a resolved signature | 3899 / 4203 | 92.77% |
| resolved, excluding zero-parameter functions | 2796 / 3089 | 90.51% |
| parameters annotated (implicit `self`/`cls` excluded) | 6784 / 7148 | 94.91% |
| returns annotated | 4112 / 4203 | 97.83% |
| dataclass fields resolved | 3294 / 3295 | 99.97% |
| classes / dataclasses / class bases | 765 / 435 / 319 | |
| type aliases (conservative rule) | 10 | |

Controls, same tree, same counting rule:

| resolver | resolved signatures | rate | status |
| --- | ---: | ---: | --- |
| **annotation-only (the control)** | **3904** | **92.89%** | is the signature syntactically complete; no name looked up |
| full (bindings + repo symbol tables) | 3899 | 92.77% | control AND every referenced name attributable |
| **marginal contribution** | **5 functions** | **0.119 pp** | subtractive, and its own ceiling |
| builtins-only | 1562 | 37.16% | **RETRACTED — not a control.** Cannot read an import by construction; 823 of its hits (52.69%) are zero-parameter functions. Kept in the code as executable negative evidence |
| resolved without needing any repo type | 2811 | 66.88% | |
| resolved, requires a repo type | 1088 | 25.89% | |

Decoupled rates, same tree — these are the ones a resolvability claim may rest
on, because neither is bounded by annotation coverage:

| quantity | raw | rate |
| --- | ---: | ---: |
| type-name occurrences resolved | 26,797 / 26,810 | **99.95%** |
| functions whose *present* annotations all resolve | 4167 / 4173 | **99.86%** |
| functions with no annotation at all | 30 | |

The 4167/4173 is one function larger in the denominator than
`sig_annotated_but_unresolvable` would suggest (6 failures, not 5): one
function carries a dangling annotation *and* an incomplete signature, so the
coupled metric had already discarded it for the wrong reason. That single row
is the decoupling working.

Graph size: 641 type nodes (`repo` 549, `stdlib` 46, `builtin` 19,
`typing` 18, `special` 1, `third_party` 1, `unresolved` 7), 16,485 symbol
anchors, 16,216 unique edges / 26,811 weighted
(`param_type` 6784, `return_type` 4112, `field_type` 3318, `var_type` 1041,
`type_arg` 632, `subtype_of` 319, `alias_of` 10).

Construction cost: 7.0 / 8.0 / 7.2 s wall for three full runs, single
process, cold-ish cache, Python 3.10.11 on Windows. Cheap enough that the
section 14 cost-frontier criterion is not threatened at this repository size;
nothing is claimed about larger trees.

### The unresolved residue, enumerated with locators

The whole residue is 7 distinct names across 4,203 functions and 3,295
fields. Small enough to list, so it is listed rather than summarised:

| name | sites | verdict |
| --- | --- | --- |
| `Mapping` | `daedalus/core.py:488`, `:768`, `daedalus/kairos/gated_writes.py:154` | **true positive** — used as `Mapping[str, Any]`, never imported in either module |
| `Any` | `daedalus/kairos/gated_writes.py:102`, `:125`, `:158` | **true positive** — not bound in the module |
| `GatedCandidate` | `daedalus/kairos/gated_writes.py:146` | **true positive**, and the sharpest one — the name has **no definition anywhere in the tree**, only this annotation and two docstring mentions |
| `ContainmentAttestation` | `daedalus/spine/attempt.py:627` | **true positive** — string forward ref; the class exists in `daedalus/spine/containment.py` but only the *module* is imported here, and the module-qualified form is used everywhere else in the file |
| `LeasedEffectAuthorization`, `EffectExecutionRequest` | `daedalus/offload.py:724`, `:725` | **true positive** — same pattern; both classes exist in `daedalus/kernel/effects.py`, neither name is bound here |
| `original` | `daedalus/budget.py:1135` | **false positive** — `class GuardedPopen(original)` where `original` is a closure variable; the extractor has no local-scope tracking |

Six of seven were confirmed by hand against the sources (grep for the import
and for the definition); one is a known limitation of this extractor and is
recorded as such rather than quietly dropped.

Under `from __future__ import annotations` none of these raise at import
time, which is why they survived. They break `typing.get_type_hints()` and
any runtime schema derivation over those objects. Repairing them is
production work and out of scope here — three of the five files are protected
artifacts. This slice reports; it does not touch them.

### Continuation 2 (2026-08-18): a corpus the resolver can fail on

`daedalus/` cannot grade this resolver. It is 92.89% annotated, uses almost no
re-export chains, has no wildcard imports, and — measured — **every** one of
its 2680 corpus-internal type-name occurrences verifies. A corpus on which
the machinery cannot fail is not evidence that the machinery works.

`s02_types/corpus_alias/` is 18 files and 19 functions, deliberately **73.68%**
annotated, exercising cross-file resolution, aliased imports, module aliases,
relative imports at two levels, `TYPE_CHECKING` guards, two-hop re-exports,
package-`__init__` re-exports, wildcard imports, class-scope aliases, closure
shadowing, and try/except fallback imports. Every annotation name has one
hand-computed answer in `s02_types/ground_truth.json`, derived from the
sources and written before the resolver was pointed at the corpus — the
failing rows were predicted, not discovered.

`python experiments/forest_v2/s02_types/resolver_accuracy.py` → `[MEASURED]`

| quantity | raw | rate |
| --- | ---: | ---: |
| annotation sites graded | 30 | |
| **verified precision** (of the claims called `repo`) | **14 / 16** | **87.50%** |
| **verified recall** (of names defined inside the corpus) | **14 / 24** | **58.33%** |
| over-claims (verified bucket, wrong definition) | 2 | |
| misses (hedged or absent where a definition exists) | 8 | |
| correct abstentions (no definition anywhere) | 1 / 1 | |
| trivial builtin sites, excluded from both rates | 5 | |

Where it fails, by case:

| case | verdict | why |
| --- | --- | --- |
| aliased import, module alias, relative import, `TYPE_CHECKING`, same-module | hit | one hop, one symbol table |
| two-hop re-export (×2), aliased re-export (×2), package-`__init__` re-export | **miss** | `top_level_symbols` never collects import bindings, so a re-exporting module has no symbol to verify against; the answer degrades to `repo_unverified` |
| wildcard import (×2) | **miss** | `import_bindings` skips `*`; decidable by expanding the exporting symbol table, which this resolver does not do |
| class-scope alias | **miss** | only module-level scope is tracked |
| closure shadowing | **over-claim** | a class defined inside a function shadows the imported name; the resolver returns the import, confidently and wrongly |
| try/except fallback import | **over-claim** | `ast.walk` order makes the *never-taken* `except` branch win the binding |

**Coverage overstates correctness on the very same 30 sites**: the extraction
rate calls 86.67% of them resolved; the grader recovers 58.33% and gets 2 of
its 16 confident answers wrong. That gap is invisible to any metric the
original slice reported.

### Continuation 3 (2026-08-18): the same metrics on five other corpora

The 0.119 pp was a property of `daedalus/`. Six corpora, annotation posture
declared before measurement, every declared corpus reported present or absent,
none dropped afterwards. `[MEASURED]` on Python 3.10.11, Windows, this box;
each row carries a content pin in the JSON.

`python experiments/forest_v2/s02_types/probe_external_corpora.py --table`

| corpus | funcs | annot% (control) | resolved% | **marginal pp** | name res% | verified share of internal names |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `daedalus/` (kernel) | 4203 | 92.89 | 92.77 | **0.119** | 99.95 | **100.00%** |
| stdlib, all 30 package dirs | 10173 | 0.28 | 0.28 | **0.000** | 98.78 | 84.27% |
| `fastapi` + `anyio` (py.typed) | 1212 | 95.63 | 95.63 | **0.000** | 99.69 | 78.60% |
| `attr` + `attrs` (re-export pair) | 187 | 5.35 | 5.35 | **0.000** | 100.00 | 83.33% |
| `bs4` + `click` (untyped) | 1361 | 39.53 | 38.28 | **1.249** | 99.08 | 100.00% |
| `corpus_alias/` (adversarial fixture) | 19 | 73.68 | 57.89 | **15.790** | 86.67 | 76.19% |

Three things follow, and only these three:

1. **The retraction generalises.** Over an annotation-only control the whole
   binding + symbol-table machinery is worth 0.000–1.249 pp on every corpus
   that was not built to break it. On a corpus that *was*, it is worth 15.79 pp
   — which is the honest statement of what the machinery is for.
2. **Attribution is easy; verification is what fails.** 98.8–100% of written
   type names attribute to *something* everywhere. The share of
   corpus-internal names actually *verified* against a symbol table is
   100% on `daedalus/`, and 78.6–84.3% on the three external corpora. The
   kernel package sits at the ceiling, which is exactly why it could show
   nothing.
3. **Annotation coverage and resolvability are now visibly independent.** The
   stdlib is annotated at 0.28% and resolves 98.78% of the names it does
   write; `fastapi`/`anyio` are annotated at 95.63% and resolve 99.69%. Under
   the old coupled metric these two corpora would have been reported as 0.28%
   and 95.63% "resolved", and the difference read as a resolver result.

### Mutation probe — do the checks notice when the resolver lies?

`python experiments/forest_v2/s02_types/mutation_probe.py --fast` →
6 mutants, **6 killed, 0 survivors**, baseline clean. `[MEASURED]`

| mutant | killed by |
| --- | --- |
| `bindings_ignore_asname` | accuracy_headline, corpus_coverage_rates, failure_classes |
| `symbols_drop_classes` | accuracy_headline, corpus_coverage_rates, failure_classes, no_silent_overclaim |
| `relative_base_off_by_one` | accuracy_headline, failure_classes |
| `resolve_claims_everything` | all five fixture guards |
| `emit_counts_everything_resolved` | corpus_coverage_rates, **falsifier_can_fire** |
| `builtins_control_accepts_everything` | retracted_control_stays_weak |

The guards are the same functions the check suite asserts on, so there is one
definition of "the reported numbers still hold" rather than two that can drift
apart. The fifth row matters most: it is the mutant that would quietly turn the
new falsifier back into an always-true metric, and something goes red.

### What the slice now claims

Everything below is construction-side and corpus-bound. Nothing here says the
type plane helps retrieval, generation, or evaluation.

- **Claimed:** on `daedalus/`, 92.89% of signatures are syntactically complete;
  of the type names actually written across six corpora, 98.8–100% attribute
  to some bucket; the unresolved residue on `daedalus/` is 7 names, 6 of them
  real source defects.
- **Claimed:** the marginal contribution of import-binding + symbol-table
  resolution over an annotation-only control is 0.119 pp on `daedalus/` and
  ≤ 1.249 pp on four external corpora.
- **Claimed:** where the machinery does earn its keep is *verification*, and
  it currently gets 87.50% precision / 58.33% recall on a corpus built to
  contain the cases that occur in real trees.
- **Not claimed, and previously implied:** that the plane does not need type
  inference. This slice never tested that. It tested whether names in
  annotations can be attributed, which is a different and much easier
  question. A resolver that cannot follow a re-export or a wildcard import is
  not evidence about inference either way.
- **Not claimed:** anything about downstream task performance (Gate 3/4), or
  about trees larger than these.

### Honest caveats

- **Only `repo` is verified.** `stdlib`, `third_party` and `repo_unverified`
  are name attributions through import bindings, not existence proofs — the
  same caveat continuation 1 carries. `repo_unverified` happened to be empty
  on this tree; that is a property of this tree, not a guarantee.
- **The headline is a coverage rate, not a correctness rate.** "Resolved"
  means every name in the signature was attributable. It says nothing about
  whether the annotation is *true* of the runtime value. The type plane is
  explicitly not a correctness oracle (section 5). Continuation 2 now measures
  the other half of this — whether the attribution names the *right*
  definition — and the answer is 87.50% precision, not 100%.
- **`repo_unverified` is where the real work is, and it is 0 here.** On
  `daedalus/` no corpus-internal name lands in that bucket, so the slice's
  original numbers could not distinguish a resolver that verifies from one
  that guesses. On external corpora 15.7–21.4% of internal names land there.
- **The fixture corpus is adversarial by construction.** Its 15.79 pp marginal
  contribution and its 58.33% recall are what happens when the cases are
  *selected* to be hard. They are an existence proof that the resolver can
  fail and a map of how, not an estimate of a failure rate in the wild. The
  external corpora carry the un-selected figures.
- **Zero-parameter functions inflate the headline.** 1114 of 4203 functions
  take no arguments, and 1103 of them resolve trivially on their return
  annotation alone. The `excl_zero_param` row (90.51%) is the number to quote
  when that matters.
- **The residue is a lower bound.** Names bound by a wildcard import, by a
  closure, or at class scope are invisible to a module-level symbol table, so
  the extractor can both miss real dangling names and invent false ones (it
  did, once).
- **Aliases are detected conservatively** — `TypeVar`/`NewType`/`ParamSpec`
  calls and typing subscripts only. Plain `X = SomeClass` rebinding is not
  counted, so 10 is a floor.
- **`type_arg` edges aggregate.** `dict -> str` accumulates across every
  `dict[str, ...]` in the tree; the edge is a repository-level fact with an
  occurrence count, not a per-occurrence instantiation. Gate 2 needs
  parameterized type identity if it wants the latter.
- **No downstream claim.** Nothing here shows the type plane helps retrieval,
  generation, or evaluation. Section 14's marginal-contribution criterion is
  answered only on the construction side.

### Reproduce

```text
python experiments/forest_v2/s02_types/type_plane.py               # summary JSON
python experiments/forest_v2/s02_types/type_plane.py --graph       # + nodes/edges
python experiments/forest_v2/s02_types/resolver_accuracy.py        # precision/recall
python experiments/forest_v2/s02_types/resolver_accuracy.py --sites
python experiments/forest_v2/s02_types/probe_external_corpora.py --table
python experiments/forest_v2/s02_types/mutation_probe.py --fast
python -m pytest experiments/forest_v2/s02_types/
```

53 checks, all green (25 original + 7 for the corrected controls and the
decoupled rates, 13 for accuracy and the mutation probe, 8 for the corpus
comparison). Each grades the extractor against a source tree whose answer was
computed by hand. The two in-repository corpora are pinned by content digest;
external corpora are asserted only on properties that do not depend on the
versions a given machine has installed, and their exact figures are reported
above with the interpreter version next to them.

## Boundary note

This directory currently contains no effectful entrypoint (every `main` only
prints, which the effect scanner correctly treats as read-only).
Anyone adding an effectful entrypoint under `experiments/` must either
register it in the canonical effect registry or extend `HARNESS_PACKAGES` —
an unscanned effectful directory is the exact blind spot the boundary work
just closed.

`s02_types/corpus_alias/` is fixture *data*: a package tree that exists to be
parsed, never imported and never executed. It deliberately contains a wildcard
import, a dangling annotation name and a never-taken fallback import. Nothing
in the repository imports it, and nothing should.
