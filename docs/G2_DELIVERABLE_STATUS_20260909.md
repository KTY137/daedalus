# Gate 2's deliverables, measured: the four-plane Twin exists and is deterministic — at six files

`[MEASURED 2026-09-09 on origin/main 094f3567 + tensor wave 8]`
Classification: `EXPERIMENT` (read-only measurement of production code).
**Decides nothing. Closes no gate.**

## Why this document exists

I have spent the day on Gate 2's *kill-criteria* side and never measured its
**deliverables**. Plan §11 lists them:

> Add function/method resolution, data/schema extraction, knowledge crosslinks,
> revision atomicity, evidence locators, and four-plane ablations. Ingest a
> small license-audited, temporally pinned repository corpus and prove
> deterministic Twin rebuilding, cross-repository alignment, and motif
> provenance.

## What is measurably there

Compiling `tests/fixtures/ignition/voltage` through the **production**
`daedalus/twin/reference_compiler.py`:

### Deterministic Twin rebuilding — PROVEN

Three consecutive compiles of the same tree:

| digest | identical ×3 |
| --- | --- |
| `snapshot.digest` | **yes** |
| `snapshot.source_forest_sha256` | **yes** |
| `manifest_sha256` | **yes** |
| `source_bundle_sha256` | **yes** |

Plan §11's "prove deterministic Twin rebuilding" is satisfied by this
measurement — **at fixture scale**, which is the whole caveat.

### The four-plane snapshot — REAL, and it has a Type plane

```
code         5 nodes   status=complete
type         3 nodes   status=complete
data         6 nodes   status=complete
knowledge    1 node    status=complete
```

The Type plane is populated and its nodes are *derived from inside code files*:

```
type:field:src/ignition_app/models.py#Event.id
type:field:src/ignition_app/models.py#Event.voltage
```

### Knowledge crosslinks — REAL, and verified

10 cross-plane bindings, **every one `assurance=verified`**:

| source → target | count |
| --- | ---: |
| `type` → `data` | 4 |
| `knowledge` → `data` | 2 |
| `knowledge` → `code` | 2 |
| `knowledge` → `type` | 1 |
| `code` → `type` | 1 |

e.g. `knowledge:doc:wiki/Event.md` → `type:src/ignition_app/models.py#Event`,
relation `documents`, assurance `verified`.

## The two-instrument split, now fully measured

This resolves the confusion that ran through today's Gate-2 work:

| | planes | Type plane | scale |
| --- | --- | --- | --- |
| **`daedalus/twin/`** (production) | **4** | populated, derived from code files, verified bindings | **6 files**, hand-declared manifest |
| **`forest_v2` retrieval** (experiment) | 3 | structurally absent — planes are file suffixes | 1,457–6,489 commits, automatic |

**Both are real; neither is Gate 2's Forest v2.** The production compiler has
the semantics and none of the scale; the experiment has the scale and only
three planes. Every retrieval result I produced today is about the right-hand
column, and the four-plane claim lives in the left.

That is a sharper statement than "the type plane is empty", and it explains
why: the two instruments were never measuring the same object.

## What Gate 2 still lacks, item by item

| §11 deliverable | status |
| --- | --- |
| function/method resolution | prototype only, `experiments/forest_v2/s01_resolution` (EXPERIMENT, no production import permitted) |
| data/schema extraction | production, fixture scale |
| knowledge crosslinks | **production, verified, fixture scale** |
| revision atomicity | snapshot binds `source_revision`; not measured across revisions here |
| evidence locators | `evidence_sha256s` present on planes and bindings |
| four-plane ablations | **impossible in the retrieval instrument** (see `G2_TWIN_PLANE_ORACLE_NOT_FEASIBLE`) |
| license-audited pinned corpus | **absent** — exactly two `fourfold.json` manifests exist, both hand-written |
| deterministic Twin rebuilding | **proven, fixture scale** |
| cross-repository alignment | **absent** — needs ≥2 manifested repositories; there are two, and one is a toy example |
| motif provenance | **absent** |

## The binding constraint, named precisely

Everything absent above has **one** cause: a `fourfold.json` must be written by
hand, and only two exist. `compile_reference_project` does not discover a
project's planes; it reads a manifest that declares `code_files`, `data_files`
and `knowledge_files`.

So Gate 2's corpus obligation is not "clone more repositories" — I already
cloned two and they are useless to the Twin. It is **"make the Twin able to
ingest a repository it was not hand-configured for."** That capability does not
exist, and nothing in this programme has been blocked on corpus *licensing* or
*selection*; it has been blocked on manifest authorship the whole time.

That is the single most useful thing measured today about Gate 2's readiness,
and it is not what I would have guessed this morning.

## What this does NOT claim

- Gate 2 is **not** closer to closing. Naming a blocker precisely is not
  removing it.
- Fixture-scale determinism is **not** repository-scale determinism. A 6-file
  tree exercises none of the ordering, concurrency or size effects that make
  determinism hard.
- The verified bindings are **verified against a hand-written manifest**, so
  they inherit its authorship. That is a real limitation of the evidence, not a
  quibble.
- Nothing here revisits the twelve retrieval measurements; they stand with the
  scope `G2_TWIN_PLANE_ORACLE_NOT_FEASIBLE` gave them.

## Reproduction

```
python -c "from daedalus.twin.reference_compiler import compile_reference_project; ..."
```
Compile `tests/fixtures/ignition/voltage` three times with a fixed
`source_revision` and `created_at`; compare `snapshot.digest`,
`source_forest_sha256`, `manifest_sha256` and `source_bundle_sha256`.
