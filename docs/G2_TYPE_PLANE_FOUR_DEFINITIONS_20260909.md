# The Type plane has four incompatible definitions in this repository, and they disagree by a factor of thirty

`[MEASURED 2026-09-09 on origin/main 5800c875 + tensor lane]`
Classification: `EXPERIMENT` (read-only census of existing code).
**Decides nothing. Changes no definition. Proposes no amendment.**

## What prompted this

`G14_KILL_CRITERIA_BOARD_20260909` said three instruments disagree about the
Type plane and left it there. Integrating the tensor lane surfaced a **fourth**,
and unlike the earlier three it can be *counted* — so the disagreement is now
measurable rather than asserted.

## The four definitions

| # | where | rule | Type share |
| --- | --- | --- | ---: |
| 1 | `s09_eval/taskset.py:74` `PLANE_BY_SUFFIX` | no `type` key exists; `.html`/`.css` get a **`presentation`** plane the plan does not define | **0 %** |
| 2 | `twin/extractors/registry.py` `semantic_planes` | multi-plane: `.py → ("code", "type")`, `.json → ("data", "knowledge")` | **every `.py`** (≈58 % of daedalus) |
| 3 | `tensor_embeddings/encoding.py:361` `infer_plane` | one plane per path; `type` for `.pyi/.proto/.graphql` or a filename containing `schema`/`types`/`typing` | **≈2 %** |
| 4 | `twin/_reference_inventory.py:60` `_python` | a type node only from a module-level `@dataclass` | **3.40 % / 1.60 %** of annotation sites |

Definitions 1 and 2 are the two the §14 board named. 3 and 4 are file-level and
symbol-level respectively, and both are measurable.

## Definition 3, measured on three independent repositories

```
black     total=  447   code=350 (78.30%)  type=11 (2.46%)  data=43 (9.62%)  knowledge=43 (9.62%)
fastapi   total= 2529   code=1476 (58.36%) type=48 (1.90%)  data=52 (2.06%)  knowledge=953 (37.68%)
daedalus  total= 6052   code=3540 (58.49%) type=121 (2.00%) data=1231 (20.34%) knowledge=1160 (19.17%)
```

**2.46 %, 1.90 %, 2.00 %.** Three repositories of different size, language
posture and purpose, and the Type plane lands within half a percentage point of
2 % in all three. That is a property of the *rule* — a filename heuristic finds
about the same tiny slice everywhere — not of the corpora.

## The disagreement, stated as a number

For the same repository, "what fraction of the corpus is the Type plane?" has
answers spanning **0 % to ≈58 %**, a factor of roughly thirty between the two
non-zero file-level rules, depending only on which module you ask:

| rule | daedalus |
| --- | ---: |
| `PLANE_BY_SUFFIX` | 0 % |
| `infer_plane` | 2.00 % |
| `semantic_planes` | ≈58 % |

These are not refinements of one another. They are different objects wearing the
same word.

## Why this matters more than a naming quibble

Plan §14.4 is *"a plane has no marginal contribution in ablation."* Every one of
these rules would ablate a different thing:

- under `PLANE_BY_SUFFIX` the ablation is **undefined** — there is nothing to remove;
- under `infer_plane` it removes **2 %** of documents;
- under `semantic_planes` it removes **every Python file**, which also removes
  the code plane and is not an ablation of Type at all;
- under `_python` it removes **dataclass declarations**, which
  `G2_SYMARM_01_RESULT` measured at `TYPE_NULL`.

A §14.4 verdict is therefore **not portable between instruments**, and any
future document reporting "the Type plane contributes nothing" has to say which
of the four it ablated. `G2_SYMARM_01_RESULT` says so explicitly; this document
exists so the next one has to as well.

## The tensor campaign this was checking, and why it is not launched

The tensor-embeddings experiment has the arm set §14 asks for — a
`structured_contraction` primary, a budget-identical `flattened_cosine`
reference, and `plane_label_permutation` / `role_label_permutation` /
`uniform_kernel` as negative controls. It has only ever been run on **one
diagnostic case**, which its own `PERFORMANCE_NOTE.md` labels as not
scientifically evaluable.

**Cost is not the blocker.** Measured here, one case with the full arm census:

| universe | wall time |
| ---: | ---: |
| 50 | 0.61 s |
| 200 | 2.39 s |
| 800 | 9.69 s |

Linear at ≈12 ms per candidate. The `830 s` in `PERFORMANCE_NOTE.md` covers five
seeds, fifteen comparisons, Git object loading and validation in one process —
extrapolating it to "≈93 hours for 403 cases", as this session did one iteration
ago, was **wrong by more than an order of magnitude**. A 403-case campaign at
realistic universe sizes is hours, not days.

**The blocker is what would be tested.** A plane-structured campaign under
`infer_plane` would ablate a plane holding 2 % of documents. A null result there
would say almost nothing about §5's Type plane, and a positive one would rest on
11 files in `black`. Running it before deciding *which* Type plane is under test
would spend hours to produce a number nobody could interpret.

## What this does not claim

- **No definition is declared correct here.** Four exist; picking one is an
  owner decision about what §5's Type plane *means*, not a measurement.
- The ≈2 % figure is about `infer_plane`'s heuristic, not about how much type
  information a repository contains. `s02_types` measured `black` at 94 %+
  annotation coverage; type information is everywhere, and this rule finds it in
  filenames.
- Nothing here overturns `G2_SYMARM_01_RESULT`. That measured definition 4 and
  said so.
- The tensor arms are not judged. They are unrun at scale, which is a different
  state from measured-and-negative.

## Reproduction

```
python -c "from experiments.forest_v2.tensor_embeddings.encoding import infer_plane; ..."
```
over `git ls-tree -r --name-only` at each pinned anchor. Cost curve: synthetic
universes of 50/200/800 candidates through
`tensor_embeddings.benchmark.run_benchmark` with the full default arm census and
a caller-asserted recency ranking.
