# G2-SYMARM-01 — result: `TYPE_NULL`. Declared type information contributes nothing, on the first corpus where the Type plane has members

`[MEASURED 2026-09-09 on origin/main 7be1fb56]`
Pre-registration: `G2_SYMARM_01_PREREGISTRATION_20260909.md`, committed at
`8f6179ab` **before** any retrieval was run.
Classification: `EXPERIMENT`. **Kills no track. Fires no criterion for the
Project Twin.**

## Verdict against the frozen table

**`TYPE_NULL`** — and it replicates on the secondary metric and the secondary
query variant.

Subject `black` @ `c3cc5a95`, **403 cases**, identical universe both arms,
BM25, CI95 percentile bootstrap, 10 000 resamples, seed 20260818, equivalence
margin ±0.02.

| variant | metric | `full` | `type_ablated` | Δ | CI95 | excludes 0? | inside ±0.02? |
| --- | --- | ---: | ---: | ---: | --- | --- | --- |
| **scrubbed** (primary) | **recall@10** | 0.15533 | 0.15326 | **+0.0021** | [−0.0039, +0.0095] | no | **yes** |
| scrubbed | MRR@20 | 0.14487 | 0.14372 | +0.0012 | [−0.0042, +0.0062] | no | **yes** |
| raw | recall@10 | 0.30746 | 0.30518 | +0.0023 | [−0.0032, +0.0081] | no | **yes** |
| raw | MRR@20 | 0.26985 | 0.27312 | −0.0033 | [−0.0102, +0.0030] | no | **yes** |

All four intervals lie **entirely inside** the ±0.02 equivalence margin and
none excludes zero. Under the frozen table that is `TYPE_NULL`, not
`INCONCLUSIVE` — the distinction the pre-registration existed to protect.

**The confound test passes.** Mean indexed tokens: 64.20 (`full`) vs 61.56
(`type_ablated`), a spread of **4.105 %**, under the pre-registered 5 %
threshold. The ablation is measuring type content, not document length. The
margin was not comfortable, which is why the test was declared in advance
rather than after seeing it.

## The number that says it most plainly

On the primary comparison, **396 of 403 cases produced an identical top-10**.
Three cases improved, four worsened.

Stripping *every* parameter annotation, *every* return annotation and *every*
annotated assignment from an entire repository changes which symbols BM25
retrieves in **seven cases out of four hundred and three**.

## Why this measurement was not possible before today

Every plane-conditioned result in this programme was previously measured on a
corpus where the Type plane had **no members at all** — a file-level gold label
cannot name a type, as `G2_TWIN_PLANE_ORACLE_NOT_FEASIBLE` established. So
criterion 14.4 was `NOT_EVALUABLE` by construction, not by absence of effort.

`G2-SYMTASK-01` built a corpus whose unit is a symbol, in which **402 of 403
cases** carry a gold symbol that declares a type. This is the first ablation of
a plane that actually has members in the corpus being ablated.

## What this licenses — the binding scope limit

Quoted from the pre-registration, unchanged:

> On a symbol-level retrieval corpus where the Type plane genuinely has
> members, declared type information has no measurable marginal contribution.

**It does not license** "criterion 14.4 has fired". Under the substitution ban
frozen at `3fbdb6a1`, this corpus is not the four-plane Project Twin: its gold
comes from commit history, not from a compiled Twin. The §14 board's verdict of
**0 of 16 evaluable for the Twin** is unchanged by this document.

What has changed is the *character* of the gap. Before today the honest
statement was "Type cannot be tested here". It is now "Type was tested on the
closest available instrument and contributed nothing measurable". Those are
different claims and only the second is evidence.

## What would still explain a null

Recorded in the pre-registration and not resolved:

- **Annotation redundancy.** `def f(path: Path)` carries `path` in the
  identifier already, so BM25 may be finding the type information through the
  name whether or not the annotation is indexed. One subject cannot separate
  these, and this result does not.
- **`black` is one repository**, and a heavily annotated one (94 % by the
  `s02_types` census family). A sparsely annotated corpus might behave
  differently — though it would have *less* type content, not more.
- **BM25 is a lexical retriever.** A method that consumed types *as types*
  rather than as tokens is untested here. The claim is about declared type
  information under lexical retrieval, which is what was measured.

## Consistency with the rest of the programme

This is the fifth independent negative on plane-conditioned retrieval:

| measurement | result |
| --- | --- |
| 12 plane-using arms vs pooled BM25 (`CONFIRM-01`…`04`) | all negative, 7 of 8 CIs excluding zero |
| resolver machinery vs annotation-only control (`s02`, 5 real corpora) | ≤ 2.37 pp, 0.00 pp on two |
| Twin ingestion of a real repository (`INGEST-01`) | `INFEASIBLE_CONTRACT` |
| production type extraction coverage (`INGEST-02`) | 3.40 % / 1.60 % |
| **Type-plane ablation, symbol corpus (here)** | **`TYPE_NULL`** |

Five measurements, five instruments, one direction. None of them individually
fires a §14 criterion for the Twin, and the pattern is not evidence either —
but it is the reason the next packet should be chosen for what it could
*falsify*, not for what it could add.

## Reproduction

```
python s09_eval/run_symbol_ablation.py <repo> c3cc5a95d4f72e6ccc27ebae23344fce8cc70786 \
    --limit 1500 --variant scrubbed
```

Resamples and seed are passed explicitly in the runner rather than defaulted:
`s09`'s `DEFAULT_RESAMPLES` is 2 000 while the s10 evaluator — whose decision
rule the pre-registration adopted — uses 10 000. The first run of this packet
took the module default and was re-run before being read, because a result
computed under a different protocol from the frozen one is not the frozen
protocol's result.
