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

## Slice s10 (2026-08-18): the kill-criteria evaluator

`experiments/forest_v2/s10_kill/` turns the master plan's kill criteria into
code, so that stopping a research track becomes a computed proposal with a
stated uncertainty instead of a judgement call made under sunk cost.

**Section numbering:** the kill criteria are **section 14** in plan revision 5.
They were section 13 in earlier revisions; section 13 is now "Forbidden
default directions". The code cites the live numbering.

### Frozen specification

- **Hypothesis (falsifiable):** the mechanically checkable part of section 14
  can be decided from a retrieval result set alone, and an evaluator that
  applies it will withhold judgement exactly where the plan's own honesty
  rules demand it (too few cases, unequal budgets, equivalence that was never
  actually tested). Refuted if a constructed kill fails to fire, a constructed
  pass fires anything, or a guard has to be bypassed to get a usable verdict.
- **Contract of the outputs:** the evaluator reads `forest_v2.s10.kill-input/1`
  JSON (`schema.py`) and emits, per criterion, one of `KEEP` / `KILL` /
  `INCONCLUSIVE` / `NOT_EVALUABLE` with its comparison intervals, plus a
  per-prior rollup. Text and `--json` renderings carry the same content.
  **Advisory: it gates nothing, promotes nothing, blocks nothing, writes
  nothing.** A `KILL` is a proposal to open an amendment (plan section 15).
  Its exit code says whether the evaluation ran, never what it found.
- **Scope:** pure stdlib, read-only, no repository imports, no network, no
  subprocess, no writes. Consumes serialised results, so it never imports the
  harness it grades.
- **Budget:** one package, ~1.9k lines of implementation plus ~0.5k of
  self-check, re-runnable in seconds. No model calls, no spend.
- **Expiry: 2026-09-15.** After that, re-derive the criteria from the live
  plan revision before trusting a verdict -- the plan's own section numbering
  has already moved once, and a stale kill list is worse than none.

### What it decides, and what it refuses to

Nine of the plan's fifteen kill criteria are decidable from a retrieval result
set. Six are not, and are reported as `NOT_EVALUABLE` **with the reason and
counted in a coverage line**, because shipping nine checks under the name "the
kill criteria" would be the dishonest version.

| decided from retrieval results | needs evidence this format does not carry |
| --- | --- |
| 14.1 full beats code-only / BM25 | 14.5 graph movement predicts behaviour |
| 14.2 rewired cross-plane control | 14.10 revision-atomic snapshot cost |
| 14.3 four indices vs fusion | 14.11 embedding precision after verification |
| 14.4 per-plane ablation | 14.13 motif composition vs direct generation |
| 14.6 graph-conditioned prioritization | 14.14 Genesis round-trip conformance |
| 14.7 gain survives leakage scrubbing | 14.15 orchestration transfer |
| 14.8 extra tokens explain the gain | |
| 14.9 quality/cost frontier | |
| 14.12 held-out transfer | |

Three design decisions carry the honesty of the whole slice:

1. **Absence of a difference is not evidence of equivalence.** Four criteria
   fire on *equivalence*. Implemented as "the difference was not significant",
   they would kill a prior faster the less you measured. So equivalence is a
   separate test against a declared practical margin (default +/-0.02): the
   whole interval must lie inside the band. A wide interval is `INCONCLUSIVE`,
   which is a real answer and never a soft pass.
2. **A win bought with a larger budget is not a win.** Unequal budgets
   downgrade the verdict they flatter and leave standing the verdict they
   argue against -- a loss on fewer tokens is starvation, not refutation.
3. **The metric is declared in the input, before the numbers are seen.** The
   evaluator reads that one metric and cannot shop for a friendlier cutoff.

### Self-test result (2026-08-18, synthetic ground truth) [MEASURED]

`python -m pytest experiments/forest_v2/s10_kill/ -q` -> **44 passed in 7.84s**.

Nine scenarios with constructed ground truth, all scores drawn at runtime from
a seeded PRNG (no fixture tables). Default config: CI95 percentile bootstrap,
10,000 resamples, margin +/-0.02, `min_cases` 10.

| scenario | cases | decidable | KEEP | KILL | INCONCLUSIVE | fired | sec |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| surviving_prior | 40 | 9 | 9 | 0 | 0 | - | 2.68 |
| no_gain | 40 | 2 | 1 | 1 | 0 | 14.1 | 0.50 |
| rewire_kill | 40 | 3 | 2 | 1 | 0 | 14.2 | 0.82 |
| leakage_kill | 40 | 3 | 2 | 1 | 0 | 14.7 | 1.06 |
| cost_kill | 40 | 2 | 0 | 2 | 0 | 14.1, 14.9 | 0.47 |
| held_out_kill | 60 | 3 | 2 | 1 | 0 | 14.12 | 0.89 |
| tiny_win | 80 | 2 | 1 | 1 | 0 | 14.1 | 0.91 |
| underpowered | 5 | 2 | 0 | 0 | 2 | - | 0.14 |
| budget_bought_win | 40 | 2 | 0 | 0 | 2 | - | 0.47 |

Every constructed kill fired its own criterion; the constructed pass fired
nothing. The headline comparison (14.1, full vs code-only) shows the guards
doing the work:

| scenario | verdict | mean diff | CI95 | n | state |
| --- | --- | ---: | --- | ---: | --- |
| surviving_prior | KEEP | +0.1503 | [+0.1430, +0.1581] | 40 | SUPERIOR |
| no_gain | KILL | +0.0012 | [-0.0028, +0.0052] | 40 | EQUIVALENT |
| tiny_win | KILL | +0.0035 | [+0.0020, +0.0051] | 80 | EQUIVALENT(but +) |
| underpowered | INCONCLUSIVE | +0.2065 | [-0.1500, +0.4489] | 5 | INCONCLUSIVE |
| budget_bought_win | INCONCLUSIVE | +0.1504 | [+0.1432, +0.1578] | 40 | SUPERIOR |

The last three rows are the point of the slice. `underpowered` holds a real
+0.21 effect and decides nothing, because five noisy cases cannot decide.
`budget_bought_win` shows a clean, significant win and is still withheld,
because the winner held 2.50x the tokens. `tiny_win` is a *statistically*
unambiguous win (CI entirely above zero) that is killed anyway for being
smaller than the practical margin -- with a warning saying exactly that.

Prior rollups are asymmetric on purpose: one fired criterion outranks any
number of passes, since the plan stops the track on any single one.
`rewire_kill` rolls up to `four_plane_project_twin = KILL (3/9 decidable)`
on 14.2 alone, while `surviving_prior` reaches `KEEP (7/9)` only because
every decidable criterion passed.

### Honest caveats

- **Every number above is synthetic.** This slice measures the *evaluator*,
  not the Project Twin. It has never seen a real Forest result; the first real
  input will come from the s09 harness, and nothing here should be read as
  evidence about the priors themselves.
- **The margin is a judgement, not a measurement.** +/-0.02 absolute on a 0..1
  metric decides the difference between `tiny_win` being a KILL and a KEEP. It
  should be pre-registered per campaign, not defaulted.
- **The input contract is s10's, not s09's.** s09 was still in flight when this
  was written, so the two were never wired end to end. The roles, budget and
  cost fields are shape-matched to s09's `contract.py` (arms, per-case scores,
  raw/scrubbed variants, cutoff metrics) but the adapter that emits this schema
  from an s09 run does not exist yet.
- **Bootstrap CIs on 40 paired cases are not a substitute for seeds.** The
  evaluator warns below 5 declared seeds; it cannot manufacture the repetitions
  the plan asks for.
- **The `NOT_EVALUABLE` six are not "fine".** They are unmeasured. A prior whose
  only decidable criteria pass is a prior that survived a partial exam.

## Boundary note

This directory currently contains no effectful entrypoint (the probe's
`main` only prints, which the effect scanner correctly treats as read-only).
Anyone adding an effectful entrypoint under `experiments/` must either
register it in the canonical effect registry or extend `HARNESS_PACKAGES` —
an unscanned effectful directory is the exact blind spot the boundary work
just closed.
