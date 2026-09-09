# §14 kill-criteria assessment — the reading rule, frozen before the board is filled

`[PRE-REGISTERED 2026-09-09 on origin/main ea5b1f08, before any criterion was scored]`
Classification: `EXPERIMENT` (assessment of existing evidence; measures nothing new).
**Decides nothing. Kills no track. Proposes no amendment.**

## Why this exists

Several days of measurement have produced a consistent run of negative
results — twelve retrieval arms below a pooled BM25 baseline, an ingestion
contract that admits neither of two mainstream repositories, a production type
extractor covering 3.40 % and 1.60 % of two real corpora's annotation sites,
and a resolver whose marginal contribution over an annotation-only control is
≤ 2.37 pp on five real corpora.

Plan §14 exists precisely for this situation, and §1 says a kill result is
archived and acted on, not silently dropped. But §14's criteria are written
about **specific objects**, and most of my measurements were made on a
*substitute* instrument. The temptation this document exists to remove is
scoring a criterion `FIRED` because the evidence is suggestive rather than
because it is about the thing the criterion names.

## The rule

Each of §14's criteria gets exactly one of four verdicts.

**`FIRED`** — a measurement exists, it was made on **the object the criterion
names**, it satisfies the comparison discipline that criterion demands
(budget-equal, replicated, baseline present, as applicable), and the condition
holds.

**`NOT_FIRED`** — as above, but the condition does not hold.

**`NOT_EVALUABLE`** — no measurement exists on the object the criterion names.
This includes the case where a measurement exists on a *different* object, no
matter how strongly it suggests an answer. The row must name the blocking
reason and what would have to exist to make it evaluable.

**`UNANSWERABLE_AS_WRITTEN`** — the criterion cannot be evaluated by any
instrument this repository could build, because the object it names does not
have the property the criterion assumes. Distinct from `NOT_EVALUABLE`: that is
a gap in evidence, this is a defect in the criterion. Requires an argument, not
just an absence.

## The substitution ban, stated explicitly

> **A criterion is never `FIRED` on evidence from a substitute instrument.**

Concretely, and decided now rather than case by case:

- `forest_v2` retrieval results are about **suffix-partitioned lexical
  retrieval over three planes**. They are *not* about the four-plane Project
  Twin. Any §14 criterion naming "the full representation", "cross-plane
  fusion", or "a plane" refers to the Twin. Those rows cannot be `FIRED` by
  `forest_v2` evidence.
- `s02_types` corpus results are about **one plane's construction machinery
  against an annotation-only control**. They are not a plane-ablation of the
  four-plane representation.
- Fixture-scale results (`tests/fixtures/ignition/voltage`,
  `examples/fourfold_wiki_app`, six files each) do not establish a
  repository-scale property.

Where such evidence is strong and points somewhere, it is recorded in an
**Adjacent evidence** column, which is explicitly *not* a verdict.

## Each row must carry

verdict; the object the criterion names; the object actually measured; the
evidence document; and, for `NOT_EVALUABLE`, the specific missing instrument.

## What this assessment may and may not conclude

**May:** report how many criteria are currently evaluable at all, and name what
blocks the rest. That is a statement about the *programme's ability to falsify
its own central prior*, which is worth knowing independently of any verdict.

**May not:** kill a track, propose an amendment, or declare the four-plane prior
refuted. §14 requires "replicated, budget-equal experiments"; a review of
existing single-run evidence is not that, and this document does not pretend
otherwise. If the board comes out mostly `NOT_EVALUABLE`, the honest conclusion
is that the prior is currently **untested**, which is not the same as surviving
a test.

## Committed before scoring

This file is committed before any criterion is scored, so the ordering is
checkable in git history. The four verdicts and the substitution ban are fixed
here and will not be widened after seeing how the board comes out.
