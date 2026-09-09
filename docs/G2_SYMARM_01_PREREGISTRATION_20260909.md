# G2-SYMARM-01 — pre-registration: does the Type plane contribute anything on a corpus where it has members?

`[PRE-REGISTERED 2026-09-09 on origin/main 7be1fb56, before any retrieval was run]`
Classification: `EXPERIMENT`. **Decides nothing. Kills no track. Fires no
criterion for the Project Twin.**

## Why this is possible now and was not before

Every plane-conditioned measurement in this programme so far has been made on a
corpus where the Type plane **had no members at all** — a file-level gold label
cannot name a type. `G2-SYMTASK-01` built a corpus whose unit is a symbol, and
measured that **402 of its 403 cases** carry at least one gold symbol declaring
a type. So for the first time, criterion 14.4 —

> a plane has no marginal contribution in ablation

— is addressable rather than `NOT_EVALUABLE` by construction.

## The ablation

Identical universe, identical budget, identical queries, one difference.

| arm | indexed text per symbol |
| --- | --- |
| `full` | the symbol's source, unchanged |
| `type_ablated` | the same source with **every annotation removed** — parameter annotations, return annotations, and annotated-assignment annotations stripped from the AST and unparsed back |

Both arms rank the same candidate set, so the comparison is not confounded by
universe size. What is removed is the Type plane's *content*, not its
membership.

**Why content and not membership.** In this corpus a symbol is a member of both
`code` and `type` — which is exactly what the production registry says
(`LanguageSpec("python", (".py", ".pyi"), "text", ("code", "type"))`). Dropping
type-bearing symbols from the universe would drop code members with them and
confound the result. Stripping annotations removes the plane's contribution
while holding membership fixed. This is a real limitation of the ablation and
is stated here rather than discovered later: it tests whether *declared type
information* helps retrieval, not whether a separately materialised type node
would.

Retriever: BM25 over the indexed text, the same implementation both arms use.
Subject: `black` @ `c3cc5a95d4f72e6ccc27ebae23344fce8cc70786`, 403 cases.
Primary metric: recall@10. Secondary: MRR@20. Both query variants
(`raw`, `scrubbed`) are reported; the **scrubbed** variant is primary, because
a raw commit message can name the symbol and hand over the answer.

## Decision rule — the existing one, not a new one

The s10 evaluator's rule is reused verbatim rather than re-invented: CI95
percentile bootstrap, 10 000 resamples, seed 20260818, equivalence margin
±0.02, paired by case.

## Reading table — frozen before any run

**`TYPE_CONTRIBUTES`** — `full` beats `type_ablated` and the CI95 of the paired
difference **excludes zero**. The Type plane has a marginal contribution;
criterion 14.4 does **not** fire on this corpus.

**`TYPE_NULL`** — the CI95 lies **entirely inside** ±0.02. The two arms are
statistically equivalent, so the Type plane's declared content contributes
nothing measurable, and criterion 14.4 **fires for this instrument** (see the
scope limit below, which is not optional).

**`TYPE_HARMS`** — `type_ablated` beats `full`, CI excluding zero. Annotations
would be actively misleading the retriever. Reported as its own outcome and not
folded into either neighbour, because it means something different from both.

**`INCONCLUSIVE`** — the CI includes zero **and** extends beyond the ±0.02
margin: underpowered at 403 cases. Reported as underpowered, never rounded to
`TYPE_NULL`. The two are not the same claim and conflating them is the specific
error this branch exists to prevent.

## Scope limit, binding on every outcome

Under the substitution ban frozen at `3fbdb6a1`, this corpus is **not** the
four-plane Project Twin: its gold comes from commit history, not from a
compiled Twin. So even a clean `TYPE_NULL` **cannot** be reported as
"criterion 14.4 has fired" for the Twin. The most it licenses is:

> On a symbol-level retrieval corpus where the Type plane genuinely has
> members, declared type information has no measurable marginal contribution.

That is a stronger statement than anything measured so far — every previous
plane result came from a corpus where Type had no members — and it is still
narrower than §14's criterion. Both halves of that sentence are load-bearing.

## What would make this wrong

- If annotation-stripping changes token counts enough to shift BM25 length
  normalisation on its own, the ablation measures document length rather than
  type content. **Mitigation, declared now:** report mean indexed-token count
  per arm alongside the result; if the arms differ by more than 5 % in mean
  tokens, the result is reported as confounded regardless of which branch the
  CI lands in.
- If `black`'s annotations are largely redundant with identifier names
  (`def f(path: Path)`), a null result may reflect that redundancy rather than
  the plane's worth. This cannot be controlled within one subject and is
  recorded as a limitation, not resolved.

## Committed before measurement

This file is committed before any retrieval runs. The four branches, the
decision rule, the primary metric and variant, and the 5 % token-count
confound test are fixed here and will not be moved after seeing the numbers.
