# Gate 3's corpus is two populations, and the mint cannot fix it

`[MEASURED 2026-09-09 on origin/main 4f7ba431]`
Classification: `EXPERIMENT` (read-only measurement). **Decides nothing. Opens
no gate. Builds nothing.**

## What I was going to do, and why I stopped

`G3_CROSS_PLANE_UNBLOCKED_AND_A_HOLE_IN_MY_GUARD_20260909.md` measured that
Gate 3's R3 refusal stopped firing and named the remainder as a **power**
problem: four non-code tasks out of 31. The obvious next step was to mint more
of them.

Two measurements stopped that, and the second one reframes the first.

## 1. The mint is structurally code-only

`daedalus/eval/mint.py` enforces a SCOPE rule: a changed file is eligible as
target or label source **only if it appears in `cached_index(repo)["modules"]`**
— deliberately the same membership test `slice.py` uses, not a second opinion.

Measured on this repository:

| | |
| --- | ---: |
| modules indexed | **681** |
| `.py` | 536 |
| `.ts` / `.tsx` | 66 / 47 |
| `.css` / `.js` / `.mjs` / `.sh` | 23 / 5 / 3 / 1 |
| **`.md`, `.rst`, `.json`, `.yaml`, `.csv`** | **0** |

**Zero data or knowledge files are in scope.** The mint cannot produce a
non-code task, and not by oversight — the scope test mirrors the slicer's own
boundary, which is what makes minted labels independent in the first place.

Raw material is not the constraint. Walking 400 first-parent commits for
changed `.md` headings and new `.json` keys yields **74 knowledge label sets**
(mean 3.4 labels) and **56 data label sets** (mean 1.1) — roughly 130 candidate
non-code tasks against the 4 that exist. Every one is out of scope.

`mint.py`'s own docstring already says what a fix would take:

> A future contributor who wants richer minted labels needs a THIRD provenance
> value, not a quiet edit to this one.

## 2. The four non-code tasks are from a different corpus

This is the finding that matters, and it is not a power problem.

| plane | provenance | target |
| --- | --- | --- |
| data | `artifact_parsed` | `data/articles.csv` |
| data | `artifact_parsed` | `schemas/article.schema.json` |
| knowledge | `artifact_parsed` | `wiki/ADR/ADR-001-CSV-Storage.md::Consequences` |
| knowledge | `artifact_parsed` | `wiki/Security.md` |

None of those paths exists in the repository root. They live in
`daedalus/eval/fixtures/fourfold_wiki_app/` — **the six-file toy fixture**.

The 27 code tasks come from the daedalus repository. The 4 non-code tasks come
from a synthetic example app. So the cross-plane comparison R3 now permits would
put **code tasks from a real 681-module repository** against **documentation and
fixture tasks from a six-file toy**.

That is not an underpowered comparison. It is a **confounded** one: plane and
corpus vary together, so any difference between them is unattributable. It is
the same defect class as the s08 false verdict that R3 was written to prevent —
a setup whose arrangement, not whose method, determines the result.

## What this does to the previous finding

My earlier statement was:

> R3 stopped refusing, and §F2 is now the reason not to run it yet.

**Incomplete.** §F2's tokenizer bias is real and I measured it, but it sits on
top of a corpus-validity problem that no tokenizer fixes. Corrected:

> R3's *structural* refusal stopped firing because the census counts planes,
> not populations. The comparison it now permits is confounded by construction,
> because the only non-code tasks come from a different corpus than every code
> task.

R3 asks "are the gold labels in more than one plane". It does not ask "did they
come from the same place". On this corpus those two questions have different
answers, and only the first is guarded.

## What would actually resolve it

Named, not built, and not costed here:

1. **A third provenance value with its own scope boundary** — what "in scope"
   means for a document or a fixture, given the slicer does not walk them. This
   is a design decision about the boundary, not a coding task, which is why
   `mint.py` demands a new provenance rather than an edit.
2. **Non-code tasks from the real repository**, so plane and corpus stop
   co-varying. The raw material exists: 130 candidates from 400 commits.
3. **Or an explicit declaration** in the frozen spec that the cross-plane
   comparison is fixture-versus-repository, with that confound stated in every
   number it produces. Honest, but it makes the comparison much weaker than
   Gate 3 needs.

## What this does not claim

- The four fixture tasks are **not** wrong or badly made. `artifact_parsed` is
  an honest provenance and they measure what they say. The problem is using
  them opposite repository-derived code tasks.
- No baseline was run, and none should be until this is resolved or declared.
- I did **not** mint anything. Adding 130 tasks that the scope rule rejects
  would have produced a corpus the harness refuses, and adding them by
  loosening the scope rule would have removed the independence guarantee that
  makes minted labels worth having.
- Nothing here touches §F2 or §F3. Both remain as measured.

## Reproduction

```
python -c "from daedalus.structcore.index import cached_index; print(len(cached_index('.')['modules']))"
python -c "from daedalus.eval.harness import all_tasks; from daedalus.eval.gate3 import taskset; ..."
```
Extension census over `cached_index(repo)["modules"]`; plane and provenance per
task via `classify_task_plane` and `task["label_provenance"]`; target existence
by path test against the repository root.
