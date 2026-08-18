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

**Section numbering:** the kill criteria are **section 14** in plan revisions 5
and 6. They were section 13 in earlier revisions; section 13 is now "Forbidden
default directions". The code no longer *cites* the live numbering, it reads
it: `plan_register.py` matches the section by title and takes the number from
the heading, so the next renumbering is a red check rather than a wrong
citation. Section 14 is byte-identical in revisions 5 and 6 [MEASURED].

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
  harness it grades. It reads exactly one repository file, the master plan,
  and only to derive and verify the criteria register.
- **Budget:** one package, ~2.6k lines of implementation plus ~0.7k of
  self-check, re-runnable in seconds. No model calls, no spend.
- **Expiry: 2026-09-15.** After that, re-measure before reuse. The criteria
  themselves no longer expire quietly: they are re-derived from the live plan
  on every check run, and a drifted register is a red check rather than a
  stale list nobody noticed. This bullet used to say "re-derive the criteria
  from the live plan before trusting a verdict" and left the doing to a
  future reader -- who was, predictably, nobody.

### RETRACTED (2026-08-18): the published coverage was 60%, the truth is 56.3%

**Withdrawn claim:** "Nine of the plan's *fifteen* kill criteria are decidable"
— i.e. 9/15 = 60% coverage, as printed by `report.py` and by this README.

**What the error was.** Section 14 of the living plan lists **sixteen**
bullets. The criteria register was copied by hand and had lost one:
*"corpus licensing/provenance or extraction cost prevents reproducible reuse"*
(14.15) appeared nowhere — neither as a predicate nor as a declared
out-of-scope entry. Because the remaining entries were then numbered by hand,
the orchestration criterion slid into the freed index, so the code cited it as
`14.15` when the plan numbers it `14.16`: anyone checking a `14.15` citation
against the plan read a **different criterion** than the report meant. Nine
decided criteria divided by a denominator that had silently shrunk gave 60%
instead of 56.3%, and the check that existed to prevent exactly this pinned
the wrong constant with a confident reason (`"the plan lists 15 kill
criteria"`).

The number was not rounded, mis-typed or stale — it was computed from a
register that no longer matched the document it claimed to mirror. So the
repair is not a corrected constant. `plan_register.py` now parses section 14
out of the living plan at check time and compares the code register to it one
to one — count, order, `plan_ref`, and verbatim wording — and coverage is
`n_decided / n_registered`, computed. A plan that gains, loses, renumbers or
rewords a bullet turns
`test_the_register_matches_the_living_plan_one_to_one` red.

**Corrected figure: 9 of 16 = 56.3%.**

Two side effects of doing it this way, both worth having: the section number
is read from the plan too (it has already moved once, 13 → 14), and the
comparison spans revisions — section 14 is byte-identical in plan revisions 5
and 6, checked, so this register is valid against both [MEASURED].

### What it decides, and what it refuses to

Nine of the plan's sixteen kill criteria are decidable from a retrieval result
set (**9/16 = 56.3%**). Seven are not, and are reported as `NOT_EVALUABLE`
**with the reason and counted in the denominator**, because shipping nine
checks under the name "the kill criteria" would be the dishonest version —
and dividing them by fifteen is the same dishonesty with a decimal point.

| decided from retrieval results | needs evidence this format does not carry |
| --- | --- |
| 14.1 full beats code-only / BM25 | 14.5 graph movement predicts behaviour |
| 14.2 rewired cross-plane control | 14.10 revision-atomic snapshot cost |
| 14.3 four indices vs fusion | 14.11 embedding precision after verification |
| 14.4 per-plane ablation | 14.13 motif composition vs direct generation |
| 14.6 graph-conditioned prioritization | 14.14 Genesis round-trip conformance |
| 14.7 gain survives leakage scrubbing | **14.15 corpus licensing / provenance** |
| 14.8 extra tokens explain the gain | 14.16 orchestration transfer |
| 14.9 quality/cost frontier | |
| 14.12 held-out transfer | |

14.15 is out of scope for a reason stronger than "not yet": it is not a
retrieval question at all. Deciding it needs per-document corpus ingestion
metadata — source repository, revision, license, temporal cutoff, extraction
version and extraction cost (plan sections 5 and 9.1) — so *no* result set of
this schema can ever decide it. That is recorded in the register with the
reason attached, which is the difference between a stated limit and the
silent omission that produced the 60%.

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

`python -m pytest experiments/forest_v2/s10_kill/ -q` -> **60 passed in 12.74s**
(2026-08-18, after the register repair; was 44 passed in 7.84s before it).

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

### Can this evaluator ever say KILL? [MEASURED]

The question the slice has to ask about itself. Synthetic scenarios prove the
machinery fires, which is not the same as a verdict being reachable from the
measurements this project actually has. Verdict: **it can, and one structural
bias toward KEEP was found and removed. On today's real numbers it withholds
— and the withholding is correct.**

**The bias that was there.** A criterion whose control arm a run never shipped
came back `NOT_EVALUABLE`, and `NOT_EVALUABLE` never blocked a KEEP. So a
prior could survive by being under-instrumented: ship `full`, `code_only` and
`bm25`, omit the rewiring control, the ablations, the scrubbed variant and the
token-matched arm, and every criterion that might have killed the prior is
simply absent — the fewer controls a run carried, the safer its prior looked.
The rollup now separates a *limit of the instrument* (a criterion this input
schema can never carry, e.g. 14.15) from a *hole in the run* (a criterion
implemented here that the run did not ask), and a prior with holes cannot
reach KEEP. `test_a_prior_cannot_reach_keep_while_its_controls_were_never_shipped`
pins it; `surviving_prior`, which ships every control, still reaches KEEP.

**On real data it withholds.** Slice s08's landed 600-query run, rebuilt from
its published 2x2 counts (`measured_inputs.py`; both marginals and the pairing
come back out exactly, no score invented):

```text
python -m experiments.forest_v2.s10_kill.cli --measured s08_graph_structure
```

| criterion | verdict | mean diff | CI95 | n | rescued/lost |
| --- | --- | ---: | --- | ---: | --- |
| 14.2 graph vs its degree-preserving rewiring | INCONCLUSIVE | +0.0100 | [-0.0050, +0.0250] | 600 | 13 / 7 |

The interval reaches 0.0250 against a ±0.02 margin, so it is neither a win nor
demonstrable equivalence — and the evaluator says so instead of reading "not
significant" as "equivalent". This is a real limit worth stating: **with a
binary per-query metric, 600 paired queries cannot resolve inside a ±0.02
band.**

How far off is it? Holding s08's observed discordance rate (13 rescued, 7
lost, 580 tied) and scaling the query set, CI95 percentile bootstrap, 20,000
resamples [MEASURED — a power projection over the real effect shape, not more
data]:

| queries | mean diff | CI95 | state |
| ---: | ---: | --- | --- |
| 600 (s08 as run) | +0.0100 | [-0.0050, +0.0250] | INCONCLUSIVE |
| 1200 | +0.0100 | [+0.0000, +0.0208] | INCONCLUSIVE |
| **1800** | +0.0100 | [+0.0017, +0.0183] | **EQUIVALENT → 14.2 fires KILL** |
| 2400 | +0.0100 | [+0.0029, +0.0171] | EQUIVALENT |

So the criterion is reachable, and the gap is a factor of three in query
count, not a structural impossibility: at s08's own effect size a 1800-query
run would kill 14.2. (A graded metric — MRR, nDCG — would get there sooner
than more binary queries, since the variance is mostly the 0/1 quantisation.)
Every verdict from the real run also carries `run declares 1 seed(s)`; s08 was
a single run with no repeated trials.

**14.3 is refused, not answered.** The s08 plane-routing run
(`--measured s08_plane_routing`) reports `0 of 16` criteria decidable. s08
measured the *cost of not routing* — a round-robin over four independent
indices, strictly dominated by the code-only index (0 rescued, 59 lost) — but
built no cross-plane **fusion** retriever, so 14.3 has no treatment arm:
`missing: fusion|full`. The tempting shortcut is to let the nearest available
arm stand in; that is how a criterion gets "decided" by a comparison nobody
ran, and it is pinned shut by
`test_a_run_without_a_fusion_arm_refuses_to_decide_the_fusion_criterion`.
Independently of the arms, s08's query set carries **100% code gold labels**,
so the type/data/knowledge indices score zero by arithmetic rather than by
measurement — the fusion question is not cleanly decidable on that query set
whatever arms are added.

So: no criterion fires on the evidence available today, and the reason is
insufficient resolution and missing controls, not a KEEP-shaped evaluator.

### Mutation probe (2026-08-18) [MEASURED]

Checks that cannot fail are decoration. Each mutation was applied, the suite
run, and the tree restored.

| mutation | result |
| --- | --- |
| remove criterion 14.9 from `REGISTER` | **6 failed, 53 passed** — `test_the_register_matches_the_living_plan_one_to_one` red: `count: the plan lists 16 kill criteria, the code registers 15`, plus `position 16: ... the code registers nothing -- a criterion is missing, not out of scope` |
| reword plan bullet 14.3 (on a copy) | red: `14.3: wording differs / plan: 'four independent indices are basically fine' / code: 'four independent indices perform equivalently to cross-plane fusion'` |
| add a 17th bullet to the plan (on a copy) | red: `count: the plan lists 17 kill criteria, the code registers 16` + 15 misfiled-citation reports |
| drop 14.15, slide later refs up (**the landed defect**) | red: `misfiled citation: the register cites 14.15 for a criterion the plan numbers 14.16; anyone looking up 14.15 in the plan reads a different criterion` |

The real plan file is never modified: plan-side mutations are applied to a
copy in a temporary directory, and the helper asserts the tamper anchor still
matched, so a probe that mutates nothing fails instead of passing quietly.

### Honest caveats

- **Every number in the scenario tables is synthetic.** This slice measures the
  *evaluator*, not the Project Twin. The `--measured` runs are real s08
  numbers, but they are a *rebuild* from published aggregate counts, not a
  live re-run, and s08's own graph is a code graph — nothing here is evidence
  about the four-plane Twin. The first end-to-end real input will come from
  the s09 harness.
- **The s08 rebuild reproduces published pairings, not unpublished ones.**
  Where s08 printed a 2x2 the reconstruction is exact; where it did not, the
  joint is filled deterministically and no criterion consumes that pairing.
  The two runs are deliberately kept apart for this reason rather than merged
  into one five-arm result set that would imply pairings nobody measured.
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
- **The `NOT_EVALUABLE` seven are not "fine".** They are unmeasured. A prior
  whose only decidable criteria pass is a prior that survived a partial exam —
  which is now enforced rather than merely written here: a run missing the
  controls for criteria this evaluator implements cannot roll up to KEEP.
- **A verified register is not a verified evaluator.** The check proves the
  code's criteria list matches the plan's wording, order and numbering. It
  says nothing about whether each predicate is a *faithful operationalisation*
  of its bullet — that judgement stays with a reader, and 14.1's mapping of
  "the full representation" onto whatever arm a run labels `full` is the
  loosest joint in the whole slice.

## Boundary note

This directory currently contains no effectful entrypoint (the probe's
`main` only prints, which the effect scanner correctly treats as read-only).
Anyone adding an effectful entrypoint under `experiments/` must either
register it in the canonical effect registry or extend `HARNESS_PACKAGES` —
an unscanned effectful directory is the exact blind spot the boundary work
just closed.
