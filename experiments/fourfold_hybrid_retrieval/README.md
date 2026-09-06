# Fourfold hybrid retrieval experiment — retained evidence tombstone

Status: **retired from the live tree after integration review**.

The implementation formerly stored in this directory was the contained Gate-1
experiment `G1-EXP-FOURFOLD-HYBRID-RETRIEVAL-01`. It tested the hypothesis that
Fourfold should provide typed logical query semantics while BM25 and ordinary
relation-specific indices remain physical access paths.

The experiment was merged by PR #311 on 2026-09-04. A later integration review
found that keeping its independent `RelationStep` / `PathExpression` /
`ContractionPlan`, adjacency-index executor, and retrieval implementation in the
current tree would preserve a second implementation truth beside the canonical
Fourfold/Tensor relation kernel. G1-GARDEN-HYBRID-02 therefore removes the
executable experiment files and its dedicated CI/test surface from the live
tree. This deletion is containment, not evidence loss.

## Exact retained evidence

- pull request: `#311`
- experiment head: `f02b5e140308000676febf919bc92fd461d92716`
- merge commit: `521f95702e82265486f8a7a342092c0bc9276e82`
- original Work Packet retained in the live tree:
  `docs/work-packets/G1-EXP-FOURFOLD-HYBRID-RETRIEVAL-01.json`
- hosted experiment run recorded by the PR: `33748541975`

Original blobs remain addressable from the experiment head:

| path | Git blob |
| --- | --- |
| `README.md` | `3529e98ae54241b16b51500b600d2bbb3a1cc686` |
| `__init__.py` | `2bf6f03fa2b1fc5e9c8f750fc85246e6e3711e09` |
| `planner.py` | `3bf58f112011bc05e652ff4962d91b0b37dc4bca` |
| `relations.py` | `cc08a2f9624e5904155c7b7ac9ea67cdc8b2e36a` |
| `retrieval.py` | `c0ec989166c29a466ffca809c2d4b9fee1e013ac` |
| focused test | `88dcbdc69a0586cc955e2ca02747d5442019d5d3` |
| dedicated workflow | `e487cc6fe03c3b882315bb417aeed0ef5bd15edf` |

The merged PR, commits and blobs are the reproducible implementation evidence;
the live tree does not need to continue shipping or testing a superseded second
planner/retriever stack.

## Retained finding

The useful architectural result survives the implementation deletion:

```text
Fourfold / Forest = semantic authority
logical typed relations = query meaning
BM25 / exact lookup / relation indices = physical access paths
retrieval output = proposal only
```

No benchmark superiority was established by the experiment. Future retrieval
work must use the selected canonical relation semantics or justify an isolated,
frozen experiment; it must not silently re-create this retired parallel stack.
