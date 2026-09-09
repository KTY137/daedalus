# G2-SYMGOLD-01 — pre-registration: is symbol-level gold buildable at usable volume?

`[PRE-REGISTERED 2026-09-09 on origin/main 9a720b3c, before any census was run]`
Classification: `EXPERIMENT` (read-only feasibility probe). **Builds nothing.**
**Decides nothing. Closes no gate.**

## Why

`G14_KILL_CRITERIA_BOARD_20260909` measured that **0 of 16** §14 criteria are
evaluable for the four-plane Project Twin, and named the circle:

> §14 cannot be evaluated until the Twin can ingest a repository; the Twin
> cannot ingest one until manifest authorship is solved; and the retrieval
> instrument that runs at scale answers a different question.

The third leg is the reachable one, and the existing code already specifies the
fix and states it was not attempted — `s09_eval/taskset_xplane.py:58`:

> "Making the Type plane addressable needs gold whose unit is a *symbol* — a
> (path, qualified name, revision) triple — which needs a symbol-resolving
> extractor over the pre-image tree and a retriever contract whose candidates
> are symbols rather than files. Both are out of scope here and neither is
> attempted."

This probe asks only the first question that gates that work: **does a real
repository yield symbol-level gold at usable volume?** If it does not, the
instrument cannot be built and the circle is closed on all three legs — which is
itself the finding.

## The instrument

For each subject repository at its pinned anchor, walk commits and derive
symbol-level gold **without building any retriever**:

1. For each commit, take the changed `.py` files.
2. AST-parse the pre-image and post-image of each.
3. A **changed symbol** is a qualified name (module-level `def`/`class`, and
   methods one level in) whose source segment differs between the two images,
   or which exists in exactly one image.
4. A case is **cross-plane** when the commit changes at least one code symbol
   **and** at least one file in another plane, using the plan's plane set
   (`code`, `type`, `data`, `knowledge`) rather than the experiment's
   suffix map — `type` membership is carried by a symbol that has an
   annotation, which is the whole point of the exercise.

Subjects, pinned: `black` @ `c3cc5a95d4f72e6ccc27ebae23344fce8cc70786`,
`fastapi` @ `53d2453d1a77f3384a1648d717f8ddafb5e9e460`. Commit budget: the most
recent 1 500 commits per subject, first-parent, so the walk is bounded and
reproducible.

## Reading table — frozen before the census

Four branches. My binary tables have failed three times this session on spaces
that contained a third outcome, so the middle and the null are named explicitly.

**`FEASIBLE`** — at least one subject yields **≥ 200** cross-plane cases that
also carry **≥ 1 type-bearing symbol**. Enough for the paired bootstrap the s10
evaluator already uses (10 000 resamples, CI95); the existing file-level task
sets ran at 561 and 730 cases, so 200 is a deliberate step down in power that is
still worth running.

**`MARGINAL`** — the best subject yields **50–199** such cases. The instrument is
buildable but underpowered; it may be built only as a single-subject probe with
the reduced power stated in its headline, and it may not be used to fire or
clear any §14 criterion.

**`INFEASIBLE`** — the best subject yields **< 50**. Symbol-level gold cannot be
derived at usable volume from commit history, the third leg of the circle is
closed, and no packet is opened.

**`UNANSWERABLE`** — the census cannot be executed (parse, timeout, or
environment fault), or the two subjects straddle `FEASIBLE` and `INFEASIBLE` in
a way no single verdict covers. A straddle is reported as a straddle, not
rounded to the friendlier half.

## What this probe may not do

- It may **not** build the extractor or the retriever. Volume first; the review
  of `G2-INGEST-02` established what building before measuring costs.
- It may **not** claim that a feasible task set would make §14 evaluable. It
  would make Type *addressable*, which is a precondition for criterion 14.4 and
  nothing more. The other fifteen criteria are untouched by this.
- Cross-plane counts here are a property of **commit history**, not of the
  Project Twin. A symbol-level task set built on them is still not the Twin, and
  under the ban frozen at `3fbdb6a1` it could not by itself fire a criterion
  naming the four-plane representation.

## Committed before measurement

This file is committed before the census runs, so the ordering is checkable in
git history. The 200 / 50 thresholds and the commit budget are fixed here and
will not be moved after seeing the counts.
