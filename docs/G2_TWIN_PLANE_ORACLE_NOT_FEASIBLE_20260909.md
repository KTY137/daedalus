# The Twin-plane-oracle instrument is not feasible, and both instruments agree why

`[MEASURED 2026-09-09 on origin/main 094f3567]`
Classification: `EXPERIMENT` (read-only feasibility measurement; nothing built).
**Decides nothing.** This document exists to stop a packet being started.

## What was proposed, one iteration ago

`G1_IGNITION_STATUS_AND_A_PLANE_DEFINITION_CONFLICT_20260909.md` closed with:

> **The obvious next instrument, named but not built.** A retrieval task whose
> planes come from the **Twin compiler** rather than from a suffix map. […]
> That is a substantially larger packet than a suffix refinement, and it is the
> one that would actually test plan §5.

It is not feasible, and the reason is worth more than the packet would have
been.

## Three measurements that close it

**1. The Twin does not discover planes. It is handed them.**
`compile_reference_project` (`daedalus/twin/reference_compiler.py:55`) reads a
`fourfold.json` manifest from the project root and takes its file
classification verbatim.

**2. The manifest declares THREE file classes, not four.**
`MANIFEST_KEYS` (`daedalus/twin/_reference_common.py:12`) and the fixture agree:

```
manifest keys: claims, code_files, data_files, knowledge_files, repository_id, schema
type_files:    ABSENT
```

**3. Exactly two repositories in existence have one**, both hand-written and
roughly six files:

```
examples/fourfold_wiki_app/fourfold.json
tests/fixtures/ignition/voltage/fourfold.json
```

So the Twin cannot be pointed at `fastapi` or `black`. Producing a manifest for
a 6,500-commit repository by hand is not a work packet; it is a project, and it
would make the plane assignment a human artifact rather than a measurement.

## The convergence, which is the actual finding

The previous document said my `.schema.json → type` refinement "pointed the
wrong way". Measured properly, it is worse than that: **I invented a
file-level Type class that neither instrument has.**

| | how Type is represented |
| --- | --- |
| `forest_v2` task set | no `type` suffix in `PLANE_BY_SUFFIX` — no type files |
| Twin manifest | no `type_files` key — no type files |
| Twin *output* | `type:field:src/…/models.py#Event.bias_voltage` — **derived from inside a code file** |

And the fixture manifest classifies `schemas/event.schema.json` as a
**`data_file`**, which is the assignment `PLANE_BY_SUFFIX` already made and the
one I overrode.

> Both instruments independently agree that **Type is not a file-level
> property**. One expresses it by having no type suffix; the other by having no
> type manifest key and deriving type nodes from code files.

`taskset.py`'s comment — *"the Type plane has no file-level representative at
all"* — is not a limitation of the suffix map. It is a true statement about the
domain, and both implementations encode it.

## The consequence, stated at full strength

> **A file-retrieval task can never have a Type plane, in either instrument's
> model.** Criterion 14.4 (`plane_has_no_marginal_contribution`) is therefore
> not merely `NOT_EVALUABLE` on the runs performed so far — it is
> **unevaluable by any file-level retrieval task**, and no plane-rule change
> can alter that.

Testing §5's Type plane requires a task whose unit is a **symbol or annotation
site**, not a file: "which declared types must change when this contract
changes" rather than "which files changed". `s02_types` already measures at
that granularity (46,882 type-name sites, 7,052 functions) and has never been
wired to a retrieval evaluation.

## What this retires, and what it leaves standing

**Retired.** The Twin-plane-oracle instrument, before any effort was spent on
it. And `G2-TYPEPLANE-01`'s refinement is now withdrawn on a firmer basis than
last iteration's: not "the Twin disagrees", but "no instrument in this
repository, including the Twin, represents Type at file level".

**Standing.** `G2-TYPEPLANE-01`'s acceptance-step-2 proof (frozen artifacts
byte-identical after the refined build) and its creation-event measurement (41
of 52 schema changes are additions, unretrievable from the pre-image). Both
were correctly measured; only the plane assignment they served is withdrawn.

**Standing, with scope now precise.** The twelve retrieval measurements are
results about **suffix-partitioned lexical retrieval over three planes**. That
was true when `CONFIRM-04` was written; what has changed is that the missing
fourth plane is now known to be unreachable by the task class, not merely
absent from the corpus.

## Why this is recorded as a finding rather than silently dropped

Plan §1 requires retained negative evidence, and the strongest form of that
here is a *feasibility* negative: the next obvious step, named by my own
document one iteration earlier, cannot be built. Recording it costs one page
and saves the packet. Not recording it would leave the same idea to be
rediscovered and half-built later.
