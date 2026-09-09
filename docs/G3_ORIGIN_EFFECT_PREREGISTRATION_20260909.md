# Pre-registration — how much of a cross-plane difference at Gate 3's primary tier is just corpus origin?

Status: FROZEN before measurement, 2026-09-09
Classification: EXPERIMENT (Gate-3 prework; active delivery gate is 1)
Packet: G3-ORIGIN-EFFECT-01
Instrument: `daedalus.eval.gate3` arms + `runner.run_comparison` (first end-to-end drive)

This document is written and committed **before** the run. Nothing below is
adjusted afterwards. The result goes in a separate file that cites this one.

## 1. The structural fact, established by counting and NOT under test here

Measured 2026-09-09 on `packet/g3-mint-corpus` (`_probe_origin.py`, read-only),
over the 14 primary-tier tasks of `daedalus.eval.harness.all_tasks()`:

| origin | code | type | data | knowledge | n |
| --- | ---: | ---: | ---: | ---: | ---: |
| fixture (six-file `garden/` + `wiki/` + `schemas/` tree) | 4 | 0 | 2 | 2 | 8 |
| real (this repository) | 6 | 0 | 0 | 0 | 6 |

Two things follow immediately, by counting alone:

1. **Complete separation.** Every non-code primary task is fixture-derived;
   every repository-derived primary task is code. For the data and knowledge
   planes, origin is not merely correlated with plane — it is *constant*.
2. **No adjustment exists.** Under complete separation there is no residual
   variation with which to separate a plane effect from an origin effect. This
   is stronger than the confound recorded in
   `G3_CORPUS_IS_TWO_POPULATIONS_20260909.md`, which described the two
   populations but did not establish that the separation is total.

`docs/G3_CORPUS_IS_TWO_POPULATIONS_20260909.md` should be read as superseded on
this point.

**Therefore: no outcome of the run specified below can license a cross-plane
claim at the primary tier.** Complete separation is a fact about the corpus,
not a hypothesis this run tests. This run does exactly one thing: it bounds
*how large* the origin effect is, on the one plane where origin is identifiable.

## 2. Why the code plane is the only place this is measurable

The code plane is the only plane holding tasks of *both* origins (4 fixture,
6 real). So it is the only place where origin can vary while plane is held
constant. Everywhere else, asking the question is impossible.

## 3. Statistic

For each arm `A`:

    delta_A = mean(score | code, real) - mean(score | code, fixture)
              n=6                        n=4

`score` is the sealed evaluator's score for the arm's retrieval on that task
(`SealedEvaluator.score`), as returned by `run_trial`. The arms never see
`must_include` (plan §4 invariant 3).

Uncertainty: percentile bootstrap, **stratified within each origin group**
(resample the 6 and the 4 independently), **10,000 resamples**, **seed
20260818** — the s10 convention already adopted in this session's
pre-registrations, so this run is not free to pick a friendlier resample count.

Equivalence margin: **±0.02**, the adopted s10 margin.

## 4. Arms

The four arms that are deterministic (`stochastic = False`) and require no
network, no API key, and no paid call:

- `bm25`
- `code_only_graph`
- `embeddings`
- `separate_indices`

Deterministic ⇒ one seed each; seed variance is not a term in this design.
The six stochastic arms are excluded because their seed variance at n=6/n=4
would swamp the quantity of interest; excluding them is a scope decision, not
a result, and they are not run and then dropped.

## 5. Reading table — frozen, per arm

Exhaustive and mutually exclusive. Evaluated in this order; the first match wins.

| # | Condition | Reads |
| --- | --- | --- |
| 1 | every trial in **both** groups returns the identical score (zero variance overall), or all scores are at floor 0.0, or all at ceiling 1.0 | **DEGENERATE** — the arm distinguishes nothing here; the comparison is vacuous for this arm and says nothing about origin |
| 2 | CI95 for `delta_A` lies entirely outside `[-0.02, +0.02]` | **ORIGIN_EFFECT_LARGE** |
| 3 | CI95 for `delta_A` lies entirely inside `[-0.02, +0.02]` | **ORIGIN_EFFECT_NEGLIGIBLE** |
| 4 | otherwise (CI overlaps the margin boundary) | **UNINFORMATIVE** — at n=6 vs n=4 this is the *expected* reading, and it is a real outcome, not a failed run |

## 6. Reading table — frozen, aggregate

| # | Condition | Verdict |
| --- | --- | --- |
| 1 | every arm reads DEGENERATE | **INSTRUMENT_VACUOUS** — the finding is about the arms, not about origin; nothing is learned about the corpus and the run must not be reported as if it were |
| 2 | at least one non-degenerate arm reads ORIGIN_EFFECT_LARGE | **CROSS_PLANE_UNSUPPORTED_STRONG** — with plane held constant, origin alone moves the score past the equivalence margin on at least one instrument. Since origin is perfectly nested inside plane for non-code, a cross-plane difference at this tier is not attributable to plane |
| 3 | every non-degenerate arm reads ORIGIN_EFFECT_NEGLIGIBLE | **ORIGIN_BOUNDED_SMALL** — the origin effect is bounded below the margin on every instrument tested. Complete separation still forbids the cross-plane claim (§1); this outcome downgrades severity, it does not grant permission |
| 4 | otherwise (some UNINFORMATIVE, no LARGE) | **UNBOUNDED** — the available data cannot bound the origin effect in either direction. The cross-plane claim is unsupported for want of evidence, which is distinct from refuted |

## 7. Stated prior, recorded so it cannot be retro-fitted

I expect **CROSS_PLANE_UNSUPPORTED_STRONG, with fixture scoring above real
(`delta_A` negative)**.

Mechanism: every one of these arms retrieves over the *task's own repo root*
(`bm25`'s docstring pins this explicitly to `harness._repo_chunks` walked from
the task root). The fixture root holds six files; this repository holds
thousands. At a fixed retrieval budget, precision on a six-document corpus
should be far higher than on a several-thousand-document one. If that is what
the numbers show, the "code vs non-code" contrast at the primary tier is
substantially a "hard corpus vs easy corpus" contrast.

If the run instead reads ORIGIN_BOUNDED_SMALL, my first suspicion is the
instrument, not the corpus — specifically scores pinned at floor — and reading
table §5 row 1 exists to catch exactly that before it is reported as a
substantive null.

## 8. What this run is not

- Not a Gate-3 baseline result. Gate 3's baseline obligation requires the full
  arm set, frozen public tasks, and a sealed evaluator; this is a two-group
  contrast inside one plane.
- Not evidence about plane-conditioned retrieval. Six independent negatives on
  that question already exist and are unaffected either way.
- Not a promotion of anything out of quarantine.

Iron Plan: EXPERIMENT
Iron Gate: 1
