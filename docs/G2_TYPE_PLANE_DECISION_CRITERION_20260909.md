# Type plane: the criterion, fixed before the numbers

`[PRE-REGISTERED 2026-09-09 on origin/main 22628bdf, before the comparison was run]`
Classification: `ALIGNED` (implementation decision, not a plan amendment).

## Why this is mine to decide

`G2_TYPE_PLANE_FOUR_DEFINITIONS_20260909` measured four incompatible Type-plane
definitions in this repository, disagreeing from 0 % to ≈58 % of the same
corpus. I twice reported it to the owner as a pending decision. The owner has
now delegated it explicitly: *"entscheide du, nimm die most general advanced
option."*

**This is not a plan amendment.** Plan §5 already says what the Type plane
contains — "declared/inferred types, constraints, contracts, interfaces". The
four implementations disagree about how to *operationalise* that sentence, which
is an implementation question, and `AGENTS.md` §3 and plan Invariant 1 both
require exactly one canonical answer. Nothing in §5 changes.

## The criterion, fixed now

A Type-plane rule is judged on two numbers, and it must do well on both:

**Coverage** — of a repository's *declared type information* (annotation sites:
parameter annotations, return annotations, annotated assignments), what
fraction lies inside the plane the rule assigns?

**Discrimination** — what fraction of the corpus does the rule place *in* the
Type plane? A plane that contains everything partitions nothing, and a §14.4
ablation of it would be an ablation of the whole corpus.

> **The canonical rule is the one with the highest coverage that is still a
> proper subset.** Coverage of 100 % at discrimination of 100 % is not a Type
> plane; it is a relabelling of the corpus.

Two disqualifiers, decided now rather than after seeing the table:

- **Coverage 0 % disqualifies.** A rule with no members cannot be ablated, and
  §14.4 is `NOT_EVALUABLE` under it by construction.
- **Discrimination 100 % disqualifies**, for the reason above.

## What "most general" means here, and what it does not

The owner's standing instruction is to take the most general advanced option.
For this decision I read that as: prefer the rule that admits the *most* type
information, and prefer multi-plane membership over forcing one plane per file
if the evidence supports it — a `.py` file genuinely is both code and type, and
a rule that must choose one is less general than one that need not.

It does **not** mean "pick the rule with the biggest number". A rule that calls
everything Type is maximally inclusive and minimally useful; the criterion above
exists to stop me choosing it because it looks general.

## Subjects

`black` @ `c3cc5a95`, `fastapi` @ `53d2453d`, and `daedalus` @ current main —
three repositories of different size and typing posture, the same three the
four-definitions census used.

## What this decision may and may not do

**May:** name one rule canonical, wire it, and record the others as superseded
with their measurements retained.

**May not:** change plan §5, touch the amendment chain, or invalidate any
measurement already published. Every existing result keeps the scope it was
recorded with — `G2_SYMARM_01_RESULT` measured definition 4 and says so, and
that stays true whichever rule becomes canonical.

Committed before the comparison runs, so the ordering is checkable in git
history. The two disqualifiers and the "highest coverage that is still a proper
subset" rule are fixed here and will not be moved after seeing the numbers.
