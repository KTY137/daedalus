# G2-SYMGOLD-01 — result: `FEASIBLE`. Symbol-level gold exists at volume, on one of two subjects

`[MEASURED 2026-09-09 on origin/main 9a720b3c]`
Pre-registration: `G2_SYMGOLD_01_PREREGISTRATION_20260909.md`, committed at
`2501e635` **before** any census data existed.
Classification: `EXPERIMENT` (read-only). **Built nothing. Closes no gate.**

## Verdict against the frozen table

**`FEASIBLE`.**

| subject | commits with a changed symbol | mean symbols/commit | **cross-plane cases** | …carrying a type-bearing symbol |
| --- | ---: | ---: | ---: | ---: |
| `black` @ `c3cc5a95` | 661 | 11.3 | **440** | **435** |
| `fastapi` @ `53d2453d` | 174 | 37.8 | 54 | 51 |

1 500 first-parent commits walked per subject.

The frozen rule required **≥ 200** cross-plane cases carrying at least one
type-bearing symbol **on at least one subject**. `black` returns **435**.
`fastapi` returns 51, which lands in the pre-registered `MARGINAL` band
(50–199).

This is not the `UNANSWERABLE` straddle, which was defined as subjects splitting
across `FEASIBLE` and `INFEASIBLE`. `FEASIBLE` + `MARGINAL` is exactly the case
the "at least one subject" clause was written for, so the verdict follows the
rule as written rather than needing it stretched.

## What the numbers say beyond the verdict

**435 usable cases is the same order as the instrument it would extend.** The
existing file-level cross-plane task sets ran at 561 (`fastapi`) and 730
(`black`) cases. A symbol-level set at 435 is a step down in power, not a
different regime — and the pre-registration accepted that step in advance.

**The two subjects fail differently, and the reason is visible.** `fastapi`
walks 1 500 commits but only 174 of them change a Python symbol at all, because
its history is dominated by documentation — the same 981 `.md` files that
`G2_INGEST_01` found. When it does change code it changes a lot of it: 37.8
symbols per commit against `black`'s 11.3. So `fastapi` is not short of symbols;
it is short of *commits that are about symbols*, which is a property of the
project's workflow rather than of the method.

**Type-bearing coverage is near-total where it exists**: 435 of 440 on `black`,
51 of 54 on `fastapi` — 98.9 % and 94.4 %. Whatever else is hard about a Type
plane, *finding a changed symbol that carries an annotation* is not the
bottleneck. That is a genuine contrast with the file-level instrument, where
Type had no representative at all.

## What this unblocks, stated narrowly

`s09_eval/taskset_xplane.py:58` names two prerequisites and records that neither
was attempted:

> "gold whose unit is a *symbol* — a (path, qualified name, revision) triple —
> which needs a symbol-resolving extractor over the pre-image tree and a
> retriever contract whose candidates are symbols rather than files."

This probe settles the **gold** half: it exists, at 435 cases, on `black`. The
extractor and the retriever contract remain unbuilt and unmeasured.

## What this does NOT claim

- **Not** that §14 becomes evaluable. A symbol-level task set would make Type
  *addressable*, which is a precondition for criterion 14.4 and nothing more.
  The other fifteen criteria are untouched.
- **Not** that the resulting instrument would be the Project Twin. These
  cross-plane counts are a property of **commit history**, not of a compiled
  Twin. Under the substitution ban frozen at `3fbdb6a1`, a task set built on
  them could not by itself fire a criterion naming the four-plane
  representation.
- **Not** a claim about retrieval quality. Nothing here retrieves anything. A
  buildable task set is not a task set on which any arm wins.
- The changed-symbol definition is deliberately coarse: module-level
  `def`/`class` plus methods one level in, compared by source segment. It will
  count a whitespace-only reformat as a change and will miss a symbol moved
  between files. Both are acceptable for a volume census and would need
  tightening before the set is used for measurement.

## Reproduction

Per subject at the pinned anchor: `git rev-list --first-parent -n 1500`, then
for each commit AST-parse the pre- and post-image of every changed `.py` file,
diff qualified names by source segment, and count the commit as cross-plane when
it also touches a `knowledge` or `data` file under the plan's plane set.
