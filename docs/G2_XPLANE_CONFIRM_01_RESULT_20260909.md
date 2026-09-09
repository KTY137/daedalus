# G2-XPLANE-CONFIRM-01 result: two KEEPs, and the one comparison that still fails

`[MEASURED 2026-09-09]`
Protocol: `docs/work-packets/G2-XPLANE-CONFIRM-01_PREREGISTRATION.md`, committed
`af2851a2` **before** the subject repository was cloned.
Subject: `fastapi` @ `53d2453d1a77f3384a1648d717f8ddafb5e9e460` (2025-12-29), MIT.
Classification: `EXPERIMENT`. Decides nothing, promotes nothing, opens no gate.

## The headline

This is the **first time any plan §14 kill criterion has returned KEEP**. Two
did. It is also the first time criterion 14.1's binding comparison has been
measured at usable power, and it **still fails**.

```
coverage   3 of 16 plan criteria decidable   (was 2 of 16)
verdicts   KEEP 2   KILL 0   INCONCLUSIVE 1   UNDECIDABLE 1   NOT_EVALUABLE 12
```

| criterion | verdict | comparison | diff | CI95 | n |
| --- | --- | --- | ---: | --- | ---: |
| **14.1** `full_beats_code_only_and_bm25` | **INCONCLUSIVE** | vs `code_only` | +0.1565 | [+0.1183, +0.1948] | 561 |
| | | **vs `bm25`** | **-0.0237** | **[-0.0517, +0.0040]** | 561 |
| **14.3** `four_indices_equal_fusion` | **KEEP** | vs `separate_indices` | +0.1468 | [+0.1097, +0.1850] | 561 |
| **14.7** `gain_vanishes_after_leakage_scrub` | **KEEP** | raw | +0.1565 | [+0.1185, +0.1956] | 561 |
| | | **scrubbed** | **+0.0679** | **[+0.0354, +0.1017]** | 561 |

## Against the pre-registered hypotheses

| | prediction | result | |
| --- | --- | --- | --- |
| **H1** primary | fusion beats `code_only` on the cross-plane stratum | +0.1690, CI95 [+0.1296, +0.2084] | **HOLDS** |
| **H2** placebo | fusion is *worse* on the single-plane control, CI excludes zero | -0.0646, CI95 [-0.1885, +0.0603] | **FAILS to replicate** |
| **H3** binding | fusion does **not** beat `bm25` on cross-plane | -0.0211, CI95 [-0.0501, +0.0076] | **HOLDS** |

### The registered reading does not cleanly fit, and I am not going to pretend it does

The pre-registration fixed a 2x2 table. For (H1 holds, H2 fails) it says:
*"fusion helps everywhere; the 'cross-plane' story is wrong even though the
number is good."*

**That reading does not describe what happened.** It assumed H2 failing meant
the control effect turning *positive*. It did not: the control point is
**-0.0646**, negative, the same direction as Daedalus's -0.1871. What failed is
significance, not direction — and the control stratum is capped at
`single_plane_control_target: 30` by the frozen rule, so it is underpowered in
**both** runs by construction, at n=30 out of 561 cases here.

So the honest statement is: **H2's registered test fails, and the reason is a
design limit I should have caught when writing the pre-registration.** A
placebo capped at 30 cases cannot detect an effect of -0.065. The registered
binary framing was too coarse for the outcome space, and that is my error, not
a property of the result.

What *is* measurable is the concentration difference, consistent across both
repositories:

| | cross-plane minus control |
| --- | ---: |
| daedalus (n=58/30) | +0.3017 |
| fastapi (n=531/30) | +0.2337 |

## What replicated, and what did not

**Replicated.** Fusion beats `code_only` and beats `separate_indices`, both
decisively, on an independently selected repository under a frozen protocol.
On Daedalus these were +0.1147 with a CI that included zero; here they are
+0.1690 and +0.1588 with CIs that exclude it. 14.3 is a **KEEP**: four separate
indices are *not* equal to cross-plane fusion.

**Also replicated, and it is the important one.** H3. Fusion does not beat plain
BM25 — point estimate negative on both repositories (-0.0178 on Daedalus,
-0.0211 here), and at n=561 the CI is [-0.0517, +0.0040]: tight, and sitting on
zero from below. Criterion 14.1 requires beating `code_only` **and** `bm25`.
The first is now established. The second is not, and the estimate points the
wrong way.

**Did not replicate.** The single-plane cost, as a significant effect. See
above — the honest cause is the n=30 cap, not an absence of the effect.

**New, and not from Daedalus at all.** 14.7 is a **KEEP**: the advantage
survives leakage scrubbing. It shrinks by 57% (+0.1565 raw → +0.0679 scrubbed)
but stays SUPERIOR with a CI excluding zero. Plan §14 lists "the gain
disappears after temporal and knowledge-leakage scrubbing" as a kill condition;
it did not disappear. That the gain more than halves is worth stating plainly
alongside the KEEP.

## The instrument-transfer check the pre-registration demanded

Declared threat: *"a large drop in absolute MRR is a reason to distrust the
comparison and must be reported."* It did not fire.

| arm | fastapi MRR | daedalus xplane88 |
| --- | ---: | ---: |
| `fusion_rrf` | 0.4072 | 0.4820 |
| `bm25` | 0.4309 | — |
| `code_only_bm25` | 0.2507 | — |
| `random_uniform` | 0.0203 | — |

Both resolvers were built against Daedalus and transferred without collapse.
`path_lexical` scores 0.5121 raw and **0.0000** scrubbed, which is the known
path-token leakage arm behaving exactly as documented — it is not one of the
registered comparisons.

## What this does NOT establish

- **Not a KILL of anything.** KILL count is 0. 14.1 is INCONCLUSIVE, not
  refuted: `[-0.0517, +0.0040]` neither excludes zero nor fits inside the ±0.02
  equivalence band. Absence of a difference is not evidence of equivalence, and
  s10 says so in its own footer.
- **Not Gate 2.** Two repositories are two data points. Gate 2 requires a
  license-audited corpus, deterministic Twin rebuilding, cross-repository
  alignment and motif provenance. None of that is here.
- **Not a claim that fusion is useful.** It beats the structured ablations it
  was designed against and loses to the simplest baseline in the room. A
  practitioner reading only 14.3's KEEP would draw the wrong conclusion.
- **Not budget-equal against a strong baseline.** `recency_prior` (0.3690) and
  `path_lexical` are excluded from the s10 role vocabulary for reasons the
  adapter records; they are not part of these verdicts.

## Reproduction

```
python -m experiments.forest_v2.s09_eval.taskset_xplane \
    --repo <fastapi> --anchor 53d2453d1a77f3384a1648d717f8ddafb5e9e460 --out <ts>.json
python -m experiments.forest_v2.s09_eval.run_xplane_harness \
    --repo <fastapi> --taskset <ts>.json \
    --retriever experiments.forest_v2.s11_fusion.fusion_retrievers:FusionRetriever \
    --retriever experiments.forest_v2.s11_fusion.fusion_retrievers:CodeOnlyRetriever \
    --retriever experiments.forest_v2.s11_fusion.fusion_retrievers:SeparateIndicesRetriever \
    --out <raw>.json
python -m experiments.forest_v2.s09_eval.to_s10 --raw <raw>.json \
    --run-id s09-fastapi561-fusion@53d2453d-20260909 \
    --gold-planes-from taskset_xplane --taskset <ts>.json --repo <fastapi> --out <kill>.json
python -m experiments.forest_v2.s10_kill.cli <kill>.json
python -m experiments.forest_v2.s09_eval.probe_stratified_fusion_effect --input <kill>.json
```

Task set digest `sha256:84f6f76158544fe6b943910892fb4702f2f2ea58fcd5408ceb17eeed7befa501`.
Stratified probe run twice, byte-identical. Evidence under
`docs/evidence/G2-XPLANE-CONFIRM-01/`.

## The correction this forces on the morning's write-up

`docs/GATE2_CROSS_PLANE_SUPPLY_CEILING_20260909.md` concluded that 14.1 and
14.3 were undecidable on this repository by roughly two orders of magnitude,
then corrected itself to "short by ten cross-plane cases". Both framings were
about *Daedalus*. Measured on a second repository:

- 14.3 is **decided**, KEEP, at n=561.
- 14.1 is still not decided, but no longer for want of cases — at n=561 the
  binding CI is ±0.028 wide. It is undecided because **the effect is
  approximately zero**, which is a different and more useful state than
  "underpowered".

The corpus obligation stands, but its purpose changes: not to reach significance
on 14.1 — that comparison is now tightly bounded near zero — but to test whether
14.3's KEEP and 14.7's KEEP survive on repositories that are not
documentation-heavy Python web frameworks.
