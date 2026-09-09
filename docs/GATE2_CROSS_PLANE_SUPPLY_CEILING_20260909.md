# Gate 2 cannot be decided on this repository: the cross-plane supply ceiling

`[MEASURED 2026-09-09 on integration/gates-1-to-4-20260909 @ 4b5914ba]`
Classification: `EXPERIMENT` (read-only analysis of retained `forest_v2` evidence)
Active gate: 1. This document decides nothing and promotes nothing.

## The claim

> Criteria 14.1 and 14.3 — the only two of the plan's sixteen that the
> cross-plane run can reach at all — need between **5,500 and 11,600 cases** to
> return anything but INCONCLUSIVE. The entire reachable history of this
> repository supplies **58** cross-plane cases, and all 58 are already in use.
>
> The four-plane prior is therefore not "unproven pending more work here". It
> is **structurally undecidable on Daedalus alone**, by roughly two orders of
> magnitude.

## What was measured, and how to re-measure it

Both halves are reproducible from the committed tree:

```
python -m experiments.forest_v2.s10_kill.cli \
    experiments/forest_v2/s09_eval/results/s10_adapter_runs/kill_input_xplane88_fusion_2026-08-24.json
python -m experiments.forest_v2.s10_kill.power_projection
python -m experiments.forest_v2.s09_eval.taskset_xplane --out <scratch>.json
```

The third command re-derives the task set from git history and produced a
**byte-identical digest** to the retained `taskset_xplane.json` of 2026-08-24
(`digest equal: True`, 1457 commits considered, 766 admissible, 88 accepted —
every field equal). The census below is therefore re-measured, not quoted.

### The intervals (reproduced, not cited)

| criterion | comparison | point | CI95 | n | w/l/t |
| --- | --- | ---: | --- | ---: | --- |
| 14.1 | `fusion_rrf` vs `code_only_bm25` | +0.0118 | [-0.0807, +0.1069] | 88 | 29/38/21 |
| 14.1 | `fusion_rrf` vs `bm25` | +0.0101 | [-0.0699, +0.0930] | 88 | 27/33/28 |
| 14.3 | `fusion_rrf` vs `separate_indices_bm25` | +0.0111 | [-0.0811, +0.1060] | 88 | 29/38/21 |

Note the win/loss columns, which the mean hides: `fusion_rrf` **loses more
individual cases than it wins** in all three comparisons. Its positive mean is
a small number of large wins, not broad superiority.

### Decisive n

s10 decides `SUPERIOR` when the CI excludes zero and `EQUIVALENT` when the CI
lies inside ±0.02. Projecting the bootstrap half-width as `1/sqrt(n)`:

| criterion | n for SUPERIOR | n for EQUIVALENT |
| --- | ---: | ---: |
| 14.1 vs `code_only` | 5,539 (63×) | 11,579 (132×) |
| 14.1 vs `bm25` | 5,759 (65×) | 5,916 (67×) |
| 14.3 vs `separate_indices` | 6,231 (71×) | 9,741 (111×) |

**The assumption is stated because it is the whole projection:** half-width
shrinks as `1/sqrt(n)` only while the per-case difference distribution is
unchanged. Drawing more cases from *this* repository at the same anchor is the
regime where that holds best, so these are the **optimistic** bound. Cases
drawn from other repositories will almost certainly raise the variance, and the
required n rises with it.

### Supply

| quantity | count |
| --- | ---: |
| commits considered in reachable history | 1,457 |
| admissible | 766 |
| **cross-plane admissible** | **58** |
| cross-plane accepted | 58 |
| **cross-plane unused** | **0** |

The 678 admissible-but-unsampled commits are all **single-plane**: 592 are
single-file (sampling them would confound plane-span with gold-set size, so the
control stratum is drawn only from multi-file single-plane commits), and 86 are
beyond the control quota, which is capped so the placebo cannot outweigh the
stratum it contrasts with. Neither pool contains a single additional
cross-plane case.

The taskset builder already says this in its own census note, and it was right:

> Cross-plane supply is the binding constraint, not a quota: every admissible
> cross-plane commit in the whole reachable history is accepted, and
> `cross_plane_unused` is 0 because there is nothing left to take. **Read a
> demand for more cross-plane cases as a demand for a different repository.**

## What this changes

Plan §11 Gate 2 says: *"Ingest a small license-audited, temporally pinned
repository corpus"* and *"Do not scale the corpus before the full graph beats
simpler representations."* Read together and applied to this measurement, those
two sentences are in tension: the graph cannot be shown to beat anything at
n=88, and n=88 is this repository's ceiling.

The tension resolves once the ceiling is measured rather than assumed. The
corpus obligation is not premature scaling and it is not optional
enrichment — **it is the only available path to a decidable measurement**, and
the plan already authorizes it at Gate 2. The caution in the second sentence is
about scaling to a *large* corpus on the strength of an unproven prior; it
cannot sensibly forbid the small corpus that the same paragraph requires and
that the first measurement is powerless without.

What must NOT be concluded from this document:

- It is **not** evidence for the four-plane prior. The prior remains exactly as
  unproven as before; this changes the reason from "we measured and could not
  tell" to "this instrument cannot tell, at any effort, on this subject."
- It is **not** evidence against it either. An INCONCLUSIVE at n=88 with the
  loss column ahead of the win column is not a KILL, and §14 requires an
  amendment for a KILL, not an inference.
- It does **not** license scaling to a large corpus. The decisive-n numbers
  say what a *decisive* run would cost; they do not say the prior deserves that
  spend before cheaper falsifications are tried.

## CORRECTION (same day): the pooled number was the wrong instrument

Everything above is arithmetically right and **materially misleading**, because
it projects from a POOLED mean over two strata whose effects have opposite
signs and similar magnitude. Running the stratified analysis the task set was
designed for changes the conclusion by two orders of magnitude.

`taskset_xplane.json::census.not_sampled` states the design intent:

> The control is a placebo, not a second measurement: it exists to check
> whether a cross-plane method's gain concentrates where cross-plane gold is.

**That check had never been run.** s10 evaluates one pooled number over all 88
cases and `case_groups` in the kill input is empty, so the strata are invisible
to every criterion. The strata are recoverable: the kill input carries
`gold_planes` only for cases whose gold sits in exactly one plane (30), and the
other 58 are the cross-plane stratum — the same 58/30 split the census reports.

`experiments/forest_v2/s09_eval/probe_stratified_fusion_effect.py`,
`[MEASURED 2026-09-09, run twice, byte-identical, retained under
docs/evidence/gate2-stratified-20260909/]`:

| comparison | stratum | n | point | CI95 | w/l/t |
| --- | --- | ---: | ---: | --- | --- |
| 14.1 vs `code_only` | pooled | 88 | +0.0118 | [-0.0807, +0.1069] | 29/38/21 |
| | **cross-plane** | 58 | **+0.1147** | [-0.0073, +0.2405] | 27/20/11 |
| | **control** | 30 | **-0.1871** | **[-0.2863, -0.0917]** | 2/18/10 |
| 14.3 vs `separate_indices` | cross-plane | 58 | +0.1147 | [-0.0073, +0.2405] | 27/20/11 |
| | control | 30 | -0.1891 | **[-0.2875, -0.0961]** | 2/18/10 |
| 14.1 vs `bm25` | cross-plane | 58 | **-0.0178** | [-0.1241, +0.0951] | 14/25/19 |
| | control | 30 | +0.0640 | [-0.0503, +0.1755] | 13/8/9 |

The pooled +0.0118 is the average of **+0.1147 and -0.1871**. It is not a small
effect; it is two large effects cancelling.

### Decisive n, recomputed per stratum

| comparison | stratum | decisive n | vs available |
| --- | --- | ---: | --- |
| 14.1 vs `code_only` | pooled | 5,539 | 63x |
| | **cross-plane** | **68** | **1.2x — 58 available, short by 10** |
| | control | 8 | **already decisive** |
| 14.3 vs `separate_indices` | cross-plane | 68 | short by 10 |
| 14.1 vs `bm25` | cross-plane | 2,198 | 38x |

### What this actually establishes, stated carefully

1. **The supply ceiling above is not the binding constraint it appeared to be.**
   For the comparison the mechanism is about, this repository is short by
   **ten** cross-plane cases, not by thousands. One additional repository would
   cover it. The "two orders of magnitude" framing was an artifact of pooling.
2. **The control result is already decisive, and it is a cost.** Fusion is
   significantly WORSE than code-only and than separate indices on single-plane
   queries (-0.187, CI excludes zero, losing 18 of 30 cases). Whatever RRF buys
   when there is something to fuse, it pays for when there is not. No criterion
   currently asks this question, and it is the clearest measured fact in the run.
3. **14.1 would probably still not be met.** It requires beating `code_only`
   **and** `bm25`. On cross-plane cases fusion is *behind* plain BM25 (-0.0178).
   The concentration signature holds against the structured baselines and not
   against the simplest one — which is the comparison plan §14 cares most about.

### What this does NOT establish

- Not a KEEP. The cross-plane CI [-0.0073, +0.2405] **includes zero**. It is
  close, and close is not decided.
- Not a licence to read the stratum I highlighted as the result. I chose which
  comparison to foreground **after** seeing the numbers. The stratification
  itself was pre-registered in the task set's design, which is what makes this
  a legitimate re-analysis rather than fishing — but the honest status is
  **hypothesis-generating**, not confirmatory. A confirmatory run needs its own
  pre-registration naming the cross-plane stratum as primary before it is cut.
- The n=68 projection carries the same 1/sqrt(n) assumption, and it is weaker
  here than above: the ten additional cases would come from a DIFFERENT
  repository, which is exactly the regime where the per-case variance is
  expected to rise. Ten is a floor, not an estimate.

### The concrete consequence for Gate 2

The corpus obligation stands, but its required SIZE collapses from "roughly 63
Daedalus-sized repositories" to "one, chosen for cross-plane density". That is
squarely the "small license-audited, temporally pinned repository corpus" plan
§11 already authorizes, and it is now a measured requirement rather than an
aspiration.

The first thing that corpus should measure is **not** 14.1. It is the control
result: if fusion reliably loses on single-plane queries across repositories,
that is a finding about the method that no amount of cross-plane evidence
offsets, and it is available at n=30.

## The cheaper thing to try first -- measured, and it is cheaper than it looks but does less than hoped

14.4 (`plane_has_no_marginal_contribution`) is `NOT_EVALUABLE` because the type
plane carries **0** gold labels, in both this task set and the Gate-3 corpus
that `G1-EVAL-CORPUS-01` landed. A plane with no labels cannot be ablated.

The first version of this section guessed that closing that gap "would make one
more criterion decidable without a second repository". **That was too strong,
and the measurement below corrects it.**

### The Type plane is empty because of the RULE, not the repository

`taskset.py::PLANE_BY_SUFFIX` assigns planes by file suffix and says the
consequence in its own comment: *"the Type plane has no file-level
representative at all, so a corpus can look 'three-plane' here while touching
two."* That is true of the rule. It is not true of the tree, which tracks
**90 `*.schema.json` files** -- JSON Schema, i.e. declared contracts, which is
precisely plan §5's Type plane ("declared/inferred types, constraints,
contracts, interfaces") -- and sends every one of them to `data` along with the
configs and fixtures.

`experiments/forest_v2/s09_eval/probe_type_plane_supply.py` applies exactly one
refinement (`*.schema.json` is Type, nothing else changes) over the same anchor
and 1200-commit window. `[MEASURED 2026-09-09, run twice, byte-identical]`:

| quantity | value |
| --- | ---: |
| commits carrying Type gold | 51 |
| ... that are single-plane today and become cross-plane | **0** |
| commits spanning all FOUR planes (0 today) | 7 |
| Type gold paths in total | 52 |

| plane combination | frozen | refined |
| --- | ---: | ---: |
| `data` | 271 | 230 |
| `type` | 0 | 41 |
| `code+data+knowledge` | 28 | 21 |
| `code+data+knowledge+type` | 0 | 7 |

### What that actually buys, and what it does not

It buys: the Type plane stops being empty, four-plane commits exist at all
(7 of them), and 14.4 moves from NOT_EVALUABLE to **evaluable**.

It does not buy: any additional cross-plane supply. Every one of the 51 is a
commit that was ALREADY multi-plane or already single-plane `data`; the
refinement relabels within them and creates no new cross-plane case. The
binding constraint of the previous section is untouched.

So 14.4 becomes **evaluable but underpowered by the same argument** -- 52 gold
paths across 51 commits is roughly one path each, and 7 four-plane commits is
not an ablation anyone should publish. "Decidable without a second repository"
was wrong; "runnable without a second repository" is right.

### What has NOT been done, deliberately

The frozen rule is **unchanged**. Refining `plane_of` would change
`taskset_xplane.json`'s digest, which is load-bearing and pinned, and it would
re-cut every existing measurement. That is a decision with its own baseline,
its own retained before/after evidence, and its own packet -- not a side effect
of a probe. Adding a stub to satisfy a census would be plane laundering, and
`G3-BASE-01` already refused to do it; silently re-cutting a frozen task set to
improve a census is the same sin wearing better clothes.

## Provenance

- Anchor commit for both task sets: `d849c2a94d66ffb1bf892de924995645395bf2a6`
- s10 register verified 1:1 against the plan §14, 16 bullets, plan sha256
  `04e8cbf94411`
- Decision rule: CI95 percentile bootstrap, 10,000 resamples, seed 20260818,
  equivalence margin ±0.02, min_cases 10
- Coverage: 2 of 16 criteria decidable from this run (12.5%); 13 NOT_EVALUABLE
  for want of a control arm or a different measurement entirely, 1 UNDECIDABLE
  on this data at any sample size (14.2)
