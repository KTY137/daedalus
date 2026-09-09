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

## The cheaper thing to try first

14.4 (`plane_has_no_marginal_contribution`) is `NOT_EVALUABLE` for a reason that
has nothing to do with sample size: the type plane carries **0** gold labels, in
both this task set and the Gate-3 corpus that `G1-EVAL-CORPUS-01` landed. A
plane with no labels cannot be ablated. Closing that is a corpus-construction
problem measured in labels, not in thousands of commits, and it would make one
more criterion decidable without a second repository.

Whether it should be closed by finding real type-plane evidence, or whether the
honest answer is that this repository has no type-plane signal to find, is not
settled here. Adding a stub to satisfy a census would be plane laundering, and
`G3-BASE-01` already refused to do it.

## Provenance

- Anchor commit for both task sets: `d849c2a94d66ffb1bf892de924995645395bf2a6`
- s10 register verified 1:1 against the plan §14, 16 bullets, plan sha256
  `04e8cbf94411`
- Decision rule: CI95 percentile bootstrap, 10,000 resamples, seed 20260818,
  equivalence margin ±0.02, min_cases 10
- Coverage: 2 of 16 criteria decidable from this run (12.5%); 13 NOT_EVALUABLE
  for want of a control arm or a different measurement entirely, 1 UNDECIDABLE
  on this data at any sample size (14.2)
