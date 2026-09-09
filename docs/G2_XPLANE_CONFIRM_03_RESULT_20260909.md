# G2-XPLANE-CONFIRM-03 result: the redesign fails, and it refutes my own diagnosis

`[MEASURED 2026-09-09]`
Protocol: `docs/work-packets/G2-XPLANE-CONFIRM-03_PREREGISTRATION.md` (`f0d852e9`).
Arm committed **before** any measurement (`fdfeb987`); the ordering is checkable
in history.
Subjects: `fastapi` @ `53d2453d` (n=561) and `black` @ `c3cc5a95` (n=730), both
frozen task sets re-used unmodified with their recorded digests.
Classification: `EXPERIMENT`. Decides nothing, enacts nothing.

## The result

`plane_calibrated` — per-plane scoring combined by within-plane
standardisation instead of reciprocal-rank fusion — **fails both hypotheses on
both subjects.**

Cross-plane stratum, paired mean difference in reciprocal rank, CI95 bootstrap
(10,000 resamples, seed 20260818). Both probes run twice, byte-identical.

| comparison | `fastapi` (n=531) | `black` (n=700) |
| --- | ---: | ---: |
| vs `bm25` | **-0.0911** *(excl. 0)* | **-0.0817** *(excl. 0)* |
| vs `fusion_rrf` | **-0.0700** *(excl. 0)* | **-0.0006** |
| vs `separate_indices_bm25` | +0.0888 *(excl. 0)* | +0.0728 *(excl. 0)* |

**H7 fails.** It does not beat `bm25`; it is significantly *inferior* on both.

**H8 fails.** It does not beat `fusion_rrf`: significantly worse on `fastapi`,
statistically indistinguishable on `black`.

The pre-registered MRR gate passed on both (`plane_calibrated` raw MRR 0.3446
and 0.5768 against a 0.20 floor), and the re-derivation guard passed — it is
not silently reproducing `bm25` (0.3446 vs 0.4309; 0.5768 vs 0.6538).

## H9 fires: the CONFIRM-02 diagnosis is withdrawn

The pre-registration fixed this reading before the arm existed:

> **H9.** If **H8 fails** — calibration is no better than round-robin — then
> the diagnosis in `CONFIRM-02` is **wrong**, the "uniform deficit implies the
> combination step" reasoning does not survive, and the honest conclusion
> becomes that per-plane partitioned scoring is itself the problem regardless
> of how it is combined.

That is the outcome. **`CONFIRM-02`'s closing recommendation is withdrawn**:

> ~~"the deficit is uniform, which points at the partitioning, so a plane-aware
> ranking over a single pooled index is the next arm to build. Until it exists,
> the demonstrated claim is 'this fusion does not beat BM25', not 'the planes
> do not help'."~~

The first clause was right about *where* to look and wrong about *what to
build*. The arm it motivated is worse, not better.

## The mechanism, predicted in writing before the run

`fdfeb987`'s commit message, written when the arm was committed and before any
measurement:

> z-standardisation centres each plane at 0 and scales by that plane's own
> spread, so a plane whose matches are uniformly mediocre but tightly clustered
> still awards its best document a large z. That is a way for this calibration
> to inherit RRF's core defect, and if H8 fails it is where I would look first.

That is what happened. Standardising *within* a plane destroys cross-plane
magnitude at least as thoroughly as rank does: a tight cluster of mediocre
matches manufactures a high z-score for its best member. On `fastapi`, where
plane sizes and spreads differ most, this is measurably **worse** than
round-robin; on `black` it merely ties it.

I noticed this while writing the tests and did **not** fix it, because the
specification was frozen and adjusting it after seeing a toy case misbehave is
exactly the post-hoc fitting the pre-registration forbids. That restraint is
what makes this result usable rather than a story about a tuned arm.

## The finding that survives, and it is stronger than the one it replaces

| subject | `fusion_rrf` vs `bm25` | `plane_calibrated` vs `bm25` |
| --- | ---: | ---: |
| `fastapi` | -0.0211 | -0.0911 |
| `black` | **-0.0810** | **-0.0817** |

On `black` — the larger, code-heavy subject — **two structurally different
combination strategies lose to a single pooled BM25 index by almost exactly the
same margin** (-0.0810 and -0.0817). Rank-only interleaving and
distribution-based calibration have nothing in common except the partition, and
they converge on the same deficit.

Both arms also beat `separate_indices_bm25` on both subjects, so the
combination step is doing *something* — it is simply not recovering what the
partition threw away.

> The evidence now points at **partitioning the index by plane at all**, not at
> how the partitions are recombined. That is a sharper claim than
> `CONFIRM-02`'s and it is the one 14.1's KILL should be read against.

## What is NOT established

- **Still not an enacted KILL.** Plan §14 requires *replicated, budget-equal*
  experiments and a KILL remains a proposal to open an amendment under §15,
  never an action. What has strengthened is the *case* for that proposal.
- **Not a refutation of the four-plane prior.** 14.3 and 14.7 remain KEEPs on
  both subjects. Every arm measured so far partitions the index; a pooled index
  that carries plane as a *feature* is a different hypothesis and **nothing
  measured here tests it**. "The planes do not help retrieval" is still not the
  demonstrated claim.
- **Not a general result about calibration.** One calibration — within-plane
  z-standardisation — was tested. A magnitude-preserving calibration (global
  scaling, or not centring) is untried, and this measurement gives a concrete
  reason to expect it to behave differently.
- **Two subjects are not a corpus.** Gate 2's obligations are untouched.

## Reproduction

```
python -m experiments.forest_v2.s09_eval.run_xplane_harness \
    --repo <subject> --taskset <frozen taskset>.json \
    --retriever experiments.forest_v2.s11_fusion.fusion_retrievers:FusionRetriever \
    --retriever experiments.forest_v2.s11_fusion.fusion_retrievers:CodeOnlyRetriever \
    --retriever experiments.forest_v2.s11_fusion.fusion_retrievers:SeparateIndicesRetriever \
    --retriever experiments.forest_v2.s11_fusion.fusion_retrievers:PlaneCalibratedRetriever \
    --out <raw>.json
python -m experiments.forest_v2.s09_eval.probe_arm_comparison \
    --raw <raw>.json --taskset <frozen taskset>.json \
    --pair plane_calibrated:bm25 --pair plane_calibrated:fusion_rrf \
    --pair plane_calibrated:separate_indices_bm25 --pair fusion_rrf:bm25
```

`plane_calibrated` is deliberately given **no s10 role**, so it is compared by
`probe_arm_comparison` rather than through `to_s10`. Inventing a role for a
candidate arm would let it be judged under a label it has not earned, and would
put an untested arm into the plan's named-baseline vocabulary.

Evidence under `docs/evidence/G2-XPLANE-CONFIRM-03/`, both probes run twice and
byte-identical.
