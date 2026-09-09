# §14 kill criteria: nothing is evaluable for the four-plane Twin, and the instrument that says otherwise measures a different four planes

`[MEASURED 2026-09-09 on origin/main ea5b1f08]`
Reading rule frozen at `3fbdb6a1`, **before** any criterion was scored.
Classification: `EXPERIMENT`. **Decides nothing. Kills no track. Proposes no
amendment.**

## The machine board, reproduced rather than quoted

Re-running `experiments.forest_v2.s10_kill.cli` on the retained inputs:

| run | decidable | KEEP | KILL | INCONCLUSIVE | UNDECIDABLE | NOT_EVALUABLE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `s09-fastapi561-fusion@53d2453d` | 3 / 16 | 2 | 0 | 1 | 1 | 12 |
| `s09-black730-fusion@c3cc5a95` | 3 / 16 | 2 | **1** | 0 | 1 | 12 |
| all 7 registered `s08_*` runs | **0 / 16** | 0 | 0 | 0 | 2 | 14 |

On `black` the evaluator emits `[KILL] 14.1 full_beats_code_only_and_bm25` and,
at track level, `[KILL] four_plane_project_twin (3/9 decidable)`.

The tool is honest about its own standing and says so unprompted:

> ADVISORY — this report gates nothing, promotes nothing and blocks nothing. A
> KILL is a proposal to open an amendment (plan §15), not an action.

## The finding: those verdicts are about a different four planes

§14's criteria name the four-plane Project Twin. The two plane sets are not the
same set, and they differ by **half their non-shared membership**:

| | plane set |
| --- | --- |
| plan §5 / `daedalus/twin/contracts.py:33` | `code`, **`type`**, `data`, `knowledge` |
| experiment `s09_eval/taskset.py:74` `PLANE_BY_SUFFIX` | `code`, `data`, `knowledge`, **`presentation`** |

The experiment has a **`presentation`** plane the plan does not define, and has
**no `type` plane at all** — grep for `"type"` in `taskset.py` returns nothing.
They agree on three members and disagree on the fourth.

They also differ in kind, not only in membership. The plan's Twin is
revision-bound, compiled by `daedalus/twin/`, and carries *verified* cross-plane
bindings. `PLANE_BY_SUFFIX` assigns a plane from a filename suffix and indexes
files lexically. `.html` and `.css` become a semantic plane; a `.py` file's
declared types become nothing.

So under the rule frozen at `3fbdb6a1`, which banned substitution before the
board was filled:

> **`black`'s `[KILL] 14.1` is a verdict about suffix-partitioned lexical
> retrieval over `code/data/knowledge/presentation`. It is not a verdict about
> the four-plane Project Twin, and it cannot be reported as one.**

The same applies to both `KEEP`s. 14.3 (`four_indices_equal_fusion`) and 14.7
(`gain_vanishes_after_leakage_scrub`) are equally measured on the substitute, so
they do not vindicate the prior either. **The ban costs the programme its only
two positive rows as well as its only KILL** — which is the point of freezing it
in advance.

## The re-scoped board

| | criteria |
| --- | ---: |
| `FIRED` for the four-plane Twin | **0 of 16** |
| `NOT_FIRED` for the four-plane Twin | **0 of 16** |
| `NOT_EVALUABLE` | **16 of 16** |

Every row is `NOT_EVALUABLE`, and for one shared reason:

> **No instrument in this repository has ever run a §14 comparison on the
> four-plane Project Twin.** The instrument with scale (`forest_v2`, 1 457–6 489
> commits) measures a different plane set. The instrument with the plan's plane
> set (`daedalus/twin/`) has been compiled over exactly two hand-authored
> projects of about six files each, and `G2_INGEST_01_RESULT` measured that it
> admits neither of two mainstream repositories.

## What this licenses, and what it does not

**Licensed.** The four-plane prior is currently **untested**. Not surviving,
not refuted — untested. Plan §5 calls it "the strongest falsifiable prior"; the
measured position is that the programme has not yet been able to falsify it,
because it cannot build the object at the scale a comparison needs.

**Not licensed.** Killing the track. Proposing an amendment. Reporting
"criterion 14.1 has fired". §14 demands replicated, budget-equal experiments,
and re-reading single-run evidence is not that. This document changes no plan
text and touches no amendment chain.

**Also not licensed:** treating `NOT_EVALUABLE` as reassuring. Twelve retrieval
arms below a pooled BM25 baseline, an ingestion contract that admits no real
repository, and a type extractor covering 1.60–3.40 % of real annotation sites
are not evidence *for* the prior. They are adjacent evidence that the objects
§14 asks about are hard to build at all.

## Adjacent evidence — explicitly not verdicts

Recorded under the frozen rule's Adjacent column, which is not a verdict:

| observation | measured on | document |
| --- | --- | --- |
| 12 plane-using retrieval arms, all negative vs pooled BM25, 7 of 8 CIs excluding zero in the final round | suffix-partitioned lexical retrieval | `G2_XPLANE_CONFIRM_04_RESULT` |
| Twin admits neither `black` nor `fastapi`; fastapi has zero files in the data vocabulary | production Twin compiler | `G2_INGEST_01_RESULT` |
| production type extraction covers 3.40 % / 1.60 % of annotation sites | `daedalus/twin/_reference_inventory.py` | `G2_INGEST_02_RESULT` |
| resolver machinery adds ≤ 2.37 pp over an annotation-only control on 68 471 sites across five real corpora | `s02_types` | `S02_CORPORA_COMPLETED_AND_PIN_TRIPWIRE` |

Each measures something real. None measures the object §14 names.

## The most useful consequence

The cheapest way to make **any** §14 criterion evaluable is not another
retrieval arm. It is a `forest_v2` task set whose planes come from
`daedalus/twin/`'s plane set rather than from a suffix map — which
`G2_TWIN_PLANE_ORACLE_NOT_FEASIBLE` already measured as **not feasible**,
because the Twin does not discover planes and only two hand-written manifests
exist.

That circle is the actual state of the programme, and naming it is worth more
than another arm below the baseline:

> §14 cannot be evaluated until the Twin can ingest a repository; the Twin
> cannot ingest a repository until manifest authorship is solved; and the
> retrieval instrument that *can* run at scale answers a different question.

## Reproduction

```
python -m experiments.forest_v2.s10_kill.cli <kill_input>       # per run
python -m experiments.forest_v2.s10_kill.cli --measured <name>  # registered runs
```
Inputs: `docs/evidence/G2-XPLANE-CONFIRM-01/kill_input_fastapi.json.gz`,
`docs/evidence/G2-XPLANE-CONFIRM-02/kill_input_black.json.gz`, and the seven
names in `s10_kill/measured_inputs.py::MEASURED_RUNS`. Plane sets read from
`daedalus/twin/contracts.py:33` and `experiments/forest_v2/s09_eval/taskset.py:74`.
