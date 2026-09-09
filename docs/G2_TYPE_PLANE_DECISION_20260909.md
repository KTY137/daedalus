# Decision: `semantic_planes` is the canonical Type-plane rule

`[MEASURED 2026-09-09 on origin/main 22628bdf]`
Criterion frozen at `bde8f69e`, **before** the comparison was run.
Classification: `ALIGNED` — an implementation decision under plan §5, **not** an
amendment. §5's text is unchanged.
Delegated by the owner: *"entscheide du, nimm die most general advanced option."*

## The comparison

Coverage = share of a repository's **declared type information** (annotation
sites) that lies inside the plane the rule assigns. Discrimination = share of
the **corpus** the rule places in the Type plane.

| rule | black cov / disc | fastapi cov / disc | daedalus cov / disc |
| --- | ---: | ---: | ---: |
| `PLANE_BY_SUFFIX` | **0.00 %** / 0.00 % | **0.00 %** / 0.00 % | **0.00 %** / 0.00 % |
| **`semantic_planes`** | **100.00 %** / 70.69 % | **100.00 %** / 48.99 % | **100.00 %** / 31.16 % |
| `infer_plane` | 1.45 % / 2.46 % | 1.21 % / 1.90 % | 0.45 % / 2.00 % |
| `_python` `@dataclass` | 20.44 % / 2.91 % | 4.10 % / 0.51 % | 11.47 % / 1.14 % |

## Applying the frozen criterion

**`PLANE_BY_SUFFIX` — disqualified** by the pre-registered coverage-0 rule. It
has no Type plane at all, so §14.4 is `NOT_EVALUABLE` under it by construction.
That was already known; it is now quantified.

**`infer_plane` — rejected.** It captures **0.45–1.45 %** of declared type
information. Its filename heuristic finds `.pyi`/`.proto` and names containing
`schema`/`types`/`typing`, which is a *naming convention*, not a type system.
It puts 2 % of files in the plane and catches 1 % of the types.

**`_python` `@dataclass` — rejected.** 4–20 % coverage. It sees only
dataclass-decorated classes, so on `fastapi` — a library built on Pydantic and
annotations — it captures 4.10 % of the type information that is actually there.
This is the rule production uses today, and `G2_SYMARM_01_RESULT` measured
`TYPE_NULL` against it; that result keeps exactly the scope it was recorded with.

**`semantic_planes` — canonical.** 100 % coverage on all three subjects, and a
**proper subset** at 31–71 % discrimination, so it clears the second
disqualifier. Every annotation lives in a code file, and this is the only rule
that says so.

It is also the most general in the sense the owner asked for: it is the one rule
using **multi-plane membership**, so a `.py` file is *both* code and type rather
than being forced into one. `LanguageSpec("python", (".py", ".pyi"), "text",
("code", "type"))` — the field is named `semantic_planes`, plural, deliberately.

## The objection I raised against it, and why it does not hold

`G2_TYPE_PLANE_FOUR_DEFINITIONS` argued that under `semantic_planes` a §14.4
ablation "removes every Python file, which also removes the code plane and is
not an ablation of Type at all."

That objection assumed ablating a plane means **removing its member files**.
Under multi-plane membership it does not, and the correct method already exists
and has already been run: `G2-SYMARM-01` ablated the Type plane by **stripping
annotations** — removing the plane's *content* while holding membership fixed.
Identical universe, identical budget, one difference. That is a coherent Type
ablation under this rule, it is implemented, and it produced a clean verdict.

So the rule that wins on coverage is also the rule whose ablation method is
already built. My earlier objection was against a method, not against the rule.

## What is canonical, and what is now experiment-local

**Canonical:** `daedalus/twin/extractors/registry.py` — `LANGUAGE_SPECS` and its
`semantic_planes` field. Any question of the form "which plane does this
artifact belong to?" is answered there.

**Experiment-local, retained, not rewritten:**
`experiments/forest_v2/s09_eval/taskset.py::PLANE_BY_SUFFIX` and
`experiments/forest_v2/tensor_embeddings/encoding.py::infer_plane`. Both keep
their measurements and both now carry a comment naming the canonical rule and
saying that results obtained under them are scoped to them. **No published
measurement is invalidated** — the criterion forbade that, and rewriting an
experiment's plane rule after its results are published would do exactly what
this programme keeps refusing to do elsewhere.

**Production, unchanged for now:** `daedalus/twin/_reference_inventory.py` still
extracts type nodes from `@dataclass` only. Making it consume the registry is
the auto-ingestion work `G2-INGEST-01/02` scoped and did not land; this decision
names the target without pretending the wiring is done.

## What this decision changes and does not change

**Changes:** there is now one answer to "what is the Type plane", it is
enforced by a test, and a fifth definition or a silent edit to the plane
assignments fails that test.

**Does not change:** plan §5, the amendment chain, or any measurement.
`G2_SYMARM_01_RESULT`'s `TYPE_NULL` was measured against definition 4 and says
so; `G2_TENSOR_CENSUS_01_RESULT`'s `LABELS_NULL` was measured against definition
3 and says so. Both stay true and both stay scoped.

**Does not change the §14 board.** 0 of 16 criteria remain evaluable for the
four-plane Project Twin. Naming a canonical rule makes plane results
*comparable*; it does not make the Twin ingestible.

## Reproduction

For each pinned subject, `git ls-tree -r --name-only`, then per path compute the
plane set under each of the four rules and, for `.py` files, count annotation
sites (parameter annotations, return annotations, `AnnAssign`). Coverage is
annotation sites in Type-plane files over total; discrimination is Type-plane
files over total files.
