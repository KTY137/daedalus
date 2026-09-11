# G2-XPLANE-CONFIRM-04 result: H12 fires — no use of the planes beats a plain pooled index

`[MEASURED 2026-09-09]`
Protocol: `docs/work-packets/G2-XPLANE-CONFIRM-04_PREREGISTRATION.md` (`95371b56`).
Arm committed **before** any measurement (`69028ef0`).
Subjects: `fastapi` (n=561) and `black` (n=730), frozen task sets re-used
unmodified. Probes run twice, byte-identical.
Classification: `EXPERIMENT`. **Decides nothing. Enacts nothing.**

## The table this packet exists to produce

Every arm that uses plane information, against plain pooled `bm25`, cross-plane
stratum, paired mean difference in reciprocal rank:

| arm | how it uses plane | `fastapi` | `black` |
| --- | --- | ---: | ---: |
| `separate_indices_bm25` | partition + concatenate | **-0.1799** \* | **-0.1544** \* |
| `plane_calibrated` | partition + standardise | **-0.0911** \* | **-0.0817** \* |
| `fusion_rrf` | partition + reciprocal-rank fuse | -0.0211 | **-0.0810** \* |
| `pooled_plane_length` | **no partition**; plane only for length | **-0.0442** \* | **-0.0229** \* |

\* CI95 excludes zero.

**Eight measurements. Four arms. Two repositories. Every value negative, seven
of eight significantly so.**

## Against the pre-registered hypotheses

**H10 fails.** `pooled_plane_length` does not beat `bm25`; it is significantly
*inferior* on both subjects (-0.0442 and -0.0229, both CIs excluding zero).

**H11 fails on the letter, holds in substance, and the gap is mine to own.**
H11 said it beats *both* partitioned arms on *both* subjects. Measured:

| vs | `fastapi` | `black` |
| --- | ---: | ---: |
| `plane_calibrated` | +0.0469 \* | +0.0588 \* |
| `fusion_rrf` | -0.0231 (CI includes 0) | +0.0581 \* |

It beats `plane_calibrated` decisively on both and `fusion_rrf` on `black`; on
`fastapi` it is statistically **indistinguishable** from `fusion_rrf`, not worse.
So it never *loses* to a partitioned arm — it merely fails to beat one of them
on one subject.

My binary table has now failed to fit the outcome **twice** (`CONFIRM-02`'s H2
was the first). Both times the cause is the same: I wrote "holds/fails" where
the honest outcome space includes "indistinguishable". That is a defect in how
I write pre-registrations, recorded here rather than resolved by picking the
branch that flatters the result.

**H12 fires**, and its condition was H10 alone:

> If **H10 fails**, then across four arms and two repositories no use of plane
> information has beaten a plain pooled index, and the honest reading of 14.1's
> KILL widens from "partitioned per-plane retrieval fails" to
> **"plane-conditioned retrieval, as instrumented here, provides no measurable
> retrieval benefit"**.

Both gates passed first: MRR floor (0.3844 and 0.6309 against 0.20) and the
re-derivation guard (not equal to `bm25` to three decimals on either subject),
so this is a real arm producing a real ranking, not a relabelled baseline.

## What the progression shows, and where it breaks

On `black` the deficit shrinks monotonically as partitioning is removed:

```
partition + concatenate   -0.1544
partition + fuse          -0.0810
partition + calibrate     -0.0817
no partition              -0.0229
```

That is a clean confirmation of `CONFIRM-03`'s surviving claim: **the partition
is the expensive part.** Removing it recovers roughly three-quarters of the
deficit.

**On `fastapi` it does not hold.** `fusion_rrf` (-0.0211) sits *ahead* of the
un-partitioned arm (-0.0442), though the two are within each other's intervals.
So "removing the partition helps" is supported on one subject and not the
other, and this document does not claim it as general.

What *is* consistent across both: nothing reaches zero. Plane information, used
four different ways, never pays for itself against simply indexing everything
once.

## What this establishes, stated at its real strength

> Across four instantiations and two repositories, plane-conditioned retrieval
> as instrumented in `forest_v2` provides **no measurable benefit** over a
> single pooled BM25 index, and usually costs.

That is materially stronger than `CONFIRM-02`'s claim and stronger than
`CONFIRM-03`'s. It is the substantive basis for a §15 amendment proposal
against the retrieval instantiation of the four-plane prior.

## What it still does NOT establish

- **It is not an enacted KILL.** Plan §14 requires *replicated, budget-equal*
  experiments; two repositories is not replication in the plan's sense, and a
  KILL is a proposal to open an amendment under §15, never an action. The
  proposal is now well-evidenced; making it is the owner's.
- **It does not refute the four-plane Project Twin.** 14.3 and 14.7 remain
  KEEPs on both subjects: fusion genuinely beats four separate indices, and the
  advantage survives leakage scrubbing. The planes demonstrably carry *some*
  structure — they simply do not beat pooled lexical retrieval **at this task**.
- **The task is retrieval of changed files from a commit message.** Plan §5
  claims the Twin supports "understanding a software project across code,
  types, data and knowledge" and §6 puts the latent atlas behind a *verifier*.
  Nothing here tests cross-plane *verification*, motif composition, or any
  generative use. A negative retrieval result does not transfer to those, and
  saying otherwise would overclaim in the direction I have been arguing.
- **The type plane is still absent** (`probe_type_plane_supply.py`: 0 gold
  labels under the frozen rule), so every arm here fuses three planes, not four.
  A four-plane instrument has never been run.
- **Two subjects are not a corpus.** Gate 2's Twin-rebuilding, cross-repository
  alignment and motif-provenance obligations remain entirely untouched.

## Reproduction

```
python -m experiments.forest_v2.s09_eval.run_xplane_harness \
    --repo <subject> --taskset <frozen>.json \
    --retriever ...:FusionRetriever --retriever ...:CodeOnlyRetriever \
    --retriever ...:SeparateIndicesRetriever --retriever ...:PlaneCalibratedRetriever \
    --retriever ...:PooledPlaneLengthRetriever --out <raw>.json
python -m experiments.forest_v2.s09_eval.probe_arm_comparison \
    --raw <raw>.json --taskset <frozen>.json \
    --pair fusion_rrf:bm25 --pair plane_calibrated:bm25 \
    --pair separate_indices_bm25:bm25 --pair pooled_plane_length:bm25
```

Evidence with sha256s under `docs/evidence/G2-XPLANE-CONFIRM-04/`.
