# G2-XPLANE-CONFIRM-02 result: a KILL fires on 14.1, and the two KEEPs survive

`[MEASURED 2026-09-09]`
Protocol: `docs/work-packets/G2-XPLANE-CONFIRM-02_PREREGISTRATION.md`, committed
`b40d36b6` **before** the subject was selected.
Subject: `black` @ `c3cc5a95d4f72e6ccc27ebae23344fce8cc70786` (2025-12-12), MIT.
Classification: `EXPERIMENT`. **Decides nothing. Enacts nothing.**

## The headline, stated precisely

s10 returned **the first KILL this programme has produced**, on criterion 14.1,
alongside the same two KEEPs `CONFIRM-01` found.

```
coverage   3 of 16 criteria decidable
verdicts   KEEP 2   KILL 1   INCONCLUSIVE 0   UNDECIDABLE 1   NOT_EVALUABLE 12
```

| criterion | verdict | comparison | diff | CI95 | w/l/t |
| --- | --- | --- | ---: | --- | --- |
| **14.1** | **KILL** | vs `code_only` | +0.0702 | [+0.0369, +0.1036] | 295/260/175 SUPERIOR |
| | | **vs `bm25`** | **-0.0806** | **[-0.1013, -0.0598]** | 116/303/311 **INFERIOR** |
| **14.3** | KEEP | vs `separate_indices` | +0.0681 | [+0.0351, +0.1014] | 293/260/177 |
| **14.7** | KEEP | scrubbed | +0.0862 | [+0.0534, +0.1194] | 313/247/170 |

14.1 reads *"the full representation does not beat code-only or BM25
retrieval."* On `black`, fusion is not merely failing to beat BM25 — it is
**significantly inferior** to it, losing 303 cases and winning 116.

## Against the pre-registered hypotheses

| | prediction | result | |
| --- | --- | --- | --- |
| **H4** primary | 14.3 replicates on a code-heavy subject | cross-plane +0.0734, CI [+0.0418, +0.1100] | **HOLDS** |
| **H5** | 14.7 replicates, scrubbed CI excludes zero | +0.0862, CI [+0.0534, +0.1194] | **HOLDS** |
| **H6** | H4's effect is below +0.08, i.e. less than half `fastapi`'s +0.1588 | **+0.0734** | **HOLDS** |

The registered reading for (H4 holds, H6 holds) was fixed before the subject
was chosen:

> the KEEP is real but **dose-dependent on documentation density**. 14.3
> survives; the interpretation narrows sharply and must say so.

That is the outcome, and this document says so.

| | `fastapi` | `black` |
| --- | ---: | ---: |
| knowledge:code files | 0.79 | **0.14** |
| 14.3 effect (cross-plane) | +0.1588 | **+0.0734** |

Halve the documentation, roughly halve the gain. The mechanism is real and its
size tracks how much prose there is to fuse.

## The finding the strata make visible, which neither pooled number shows

Look at `cross-plane minus control` per comparison:

| comparison | cross-plane | control | difference |
| --- | ---: | ---: | ---: |
| vs `code_only` | +0.0756 | -0.0565 | **+0.1321** |
| vs `separate_indices` | +0.0734 | -0.0565 | **+0.1299** |
| **vs `bm25`** | **-0.0810** | **-0.0710** | **-0.0101** |

Fusion's **advantage** over the structured ablations is concentrated in the
cross-plane stratum — the signature the mechanism predicts.

Fusion's **deficit** against plain BM25 is **uniform across both strata**
(difference ≈ 0). It is not a plane-crossing failure at all. Reciprocal-rank
fusion over partitioned per-plane indices simply loses information that a
single pooled index keeps, and it loses it everywhere, on single-plane and
cross-plane queries alike.

So the coherent statement is:

> Cross-plane fusion beats the structured ablations it was designed against,
> and loses to indexing everything in one place. The advantage is about
> crossing planes; the loss is about partitioning at all.

## Consistency across all three subjects

| subject | `fusion` vs `bm25`, cross-plane | verdict |
| --- | ---: | --- |
| daedalus (n=58) | -0.0178 | INCONCLUSIVE |
| fastapi (n=531) | -0.0211 | INCONCLUSIVE |
| **black (n=700)** | **-0.0810** | **INFERIOR** |

The point estimate is negative on every subject measured, and the one run with
both the largest n and the least prose resolves it. Nothing here has ever
measured fusion ahead of BM25.

## What this does NOT do, and the distinction matters

**It does not enact a KILL.** Plan §14 opens: *"Stop or redesign the
four-plane/latent track when **replicated**, budget-equal experiments show any
of the following."* One subject firing is not replication. s10 says the same
thing in its own footer: a KILL is *"a proposal to open an amendment (plan
§15), not an action."*

**It does not close, open or satisfy Gate 2**, and it produces no candidate and
no promotion.

**It does not refute the four-plane prior.** 14.3 and 14.7 are KEEPs on both
subjects. What is in question is narrower and sharper: whether *partitioned
per-plane indices combined by RRF* is the right way to use the planes. The
plan's own §5 says the Forest "exposes typed intra-plane and verified
cross-plane edges" — this measurement is about one retrieval implementation,
not about the representation.

**The honest recommendation** is therefore a redesign proposal rather than a
stop: fusion's deficit is uniform, which points at the partitioning, and a
plane-aware ranking over a **single pooled index** is the obvious next arm to
build. It does not exist yet, and until it does, "the four planes do not help
retrieval" is not the demonstrated claim — "this particular fusion of them does
not beat BM25" is.

## The pre-registered gate that had to pass first

Declared threshold: if `fusion_rrf` raw MRR fell below 0.20, the comparison
would be reported as untrustworthy and H4/H5/H6 recorded as **not answered**.

`fusion_rrf|raw` MRR = **0.5732**. The gate passed with room; the instrument
transferred to a code-heavy subject better than to `fastapi` (0.4072). Absolute
MRR is *higher* here for every arm, `random_uniform` included (0.0828 against
0.0203), which is what a smaller candidate universe does and is not evidence
about any method.

## Reproduction and evidence

Task set digest recorded in the evidence bundle; stratified probe run twice,
byte-identical; s10 report retained in full. All under
`docs/evidence/G2-XPLANE-CONFIRM-02/`, alongside the candidate log — which
includes **`pytest`'s rejection** and the criterion it missed, because the
pre-registration required recording failures and not only the winner.

One amendment to the protocol is recorded in the pre-registration itself:
criterion 5 originally said "`.md`-to-`.py` ratio", which `pytest` would have
passed on a technicality while being *more* documentation-heavy than `fastapi`
(it documents in `.rst`). It was amended to count knowledge-plane files as
`PLANE_BY_SUFFIX` does, **before any retrieval was run**, and the amendment
made the criterion stricter against the candidate then under test.

One prediction in that pre-registration was **wrong**, and cost nothing:
I declared that criteria 4 and 5 pull against each other, and that a code-heavy
repository might have too few cross-plane commits to run at all. `black` is
code-heavy by file count (0.14) and has a **33%** cross-plane commit density
against `fastapi`'s 8%. Commit density and file density are different things
and I conflated them.
