# G2-TYPEPLANE-01 - build the four-plane instrument, then re-ask the question

Packet ID: `G2-TYPEPLANE-01`
Artifact role: `primary`
Status: `PRE-REGISTERED; no new task set built at the time of writing`
Active gate: `1`
Classification: `EXPERIMENT`
Owner: `repository owner`
Base revision: `17b6475e2a3f8c9d1b4e6a0f5c7d2e8b3a9f1c04`
Dependencies: `G2-XPLANE-CONFIRM-01, -02, -03, -04`
Master-plan authority: `Revision 13`
Promotion: not requested. This packet cannot open, enter or satisfy any gate.

## Why this exists

Three consecutive result documents have carried the same caveat, and it is time
to remove it rather than repeat it. From `CONFIRM-04`:

> The type plane is still absent (`probe_type_plane_supply.py`: 0 gold labels
> under the frozen rule), so every arm here fuses **three** planes, not four.
> **A four-plane instrument has never been run.**

That matters beyond bookkeeping. Plan §5 defines a **four**-plane Project Twin;
criterion 14.4 (`plane_has_no_marginal_contribution`) has been `NOT_EVALUABLE`
in every run this programme has produced; and Gate 4's premise — "use verified
Project Twin structure to select and compress context" — is about the whole
structure. Every negative result so far is a result about a three-plane
approximation, and saying otherwise would overclaim.

`probe_type_plane_supply.py` already established the cause and the remedy
`[MEASURED 2026-09-09, run twice, byte-identical]`: the type plane is empty
because of the **rule**, not the repository. `PLANE_BY_SUFFIX` assigns by
suffix and sends all 90 tracked `*.schema.json` files — JSON Schema, i.e.
declared contracts, precisely §5's Type plane — to `data`. Under one
refinement, Daedalus alone yields 51 commits carrying type gold and 7 spanning
all four planes.

## Primary acceptance claim

> A four-plane task set is built as a **new, separately identified artifact**;
> the frozen three-plane task sets are untouched; and every existing arm is
> re-run on it so that the programme's conclusions are stated about the
> instrument the plan actually describes.

## Scope

**In scope**
- `experiments/forest_v2/s09_eval/taskset_xplane4.py` (new: a four-plane task
  set builder that *imports* the frozen rules and overrides exactly the plane
  map)
- its task-set JSONs, under `runs/` and `docs/evidence/`
- `experiments/forest_v2/s11_fusion/fusion_retrievers.py` — `FUSION_PLANES`
  must admit `type`; **no scoring or combination change**
- tests for both
- this document and its result document

**Forbidden paths** — a diff touching these invalidates the packet
- `experiments/forest_v2/s09_eval/taskset.py::PLANE_BY_SUFFIX` and
  `taskset_xplane.py` — **the frozen rule and the frozen builder do not move.**
  The existing task sets and every published number must remain reproducible
  from them, byte for byte.
- `_score_plane`, `_rrf_combine`, `_standardise_within_plane`, and the bodies
  of all five retriever classes
- `experiments/forest_v2/s10_kill/**`
- anything under `daedalus/`

## Contracts and behavior

### The refinement, and only this one

A path whose name ends `.schema.json` is `type`. Everything else is unchanged.

Deliberately narrow, for the reason `probe_type_plane_supply.py` records: it is
an explicit, self-describing convention already used consistently (41 files
under `configs/schemas`, 41 under `daedalus/resources/schemas`), so it needs no
content sniffing and cannot silently capture an ordinary config file.

**It is a NEW builder, not an edit.** `taskset_xplane4.py` imports `SELECTION`,
the selection rules and the census machinery from `taskset_xplane.py` unchanged
and overrides only the plane function. Two task sets then exist side by side
with different digests, and any number can be attributed to one of them. Editing
the frozen rule in place would silently re-cut four published measurements, and
`G3-BASE-01` already refused the equivalent move.

### The one retriever change, and why it is not a scoring change

`FUSION_PLANES` currently lists `code`, `data`, `knowledge`. It must admit
`type` or the partitioned arms would silently drop every type document, and the
four-plane run would measure a three-plane instrument wearing a new label.

That is a **membership** change, not a scoring or combination change: no
formula, weight or constant moves. `test_type_and_presentation_are_never_indexed`
pins the current behaviour and will be updated to pin the new one — inverted
for `type`, unchanged for `presentation`.

## The hypotheses

**H13 (primary).** On the four-plane task set, at least one plane-using arm
beats plain pooled `bm25` on the cross-plane stratum, CI95 excluding zero.
This is `CONFIRM-04`'s question re-asked with the instrument the plan describes.

**H14 (14.4, evaluable for the first time).** The type plane has marginal
contribution: an arm fusing all four planes beats the same arm fusing only
`code`, `data`, `knowledge` on the subset of cases carrying type gold.

**H15 (registered because it makes the whole packet cheap to conclude).** If
H13 fails, the four-plane instrument reproduces the three-plane result, and
every prior conclusion in this programme **stands as written** rather than
needing the caveat it has been carrying. `CONFIRM-04`'s claim would then be
about the four-plane Twin, not a three-plane approximation, and its evidential
weight for a §15 amendment proposal increases accordingly.

### Readings, fixed now

| H13 | H14 | reading |
| --- | --- | --- |
| holds | holds | the type plane was the missing piece. Every prior negative is an artifact of a three-plane instrument, and they must be re-labelled as such. |
| holds | fails | something in the four-plane run helps, but not the type plane specifically. The cause must be found before any claim is made. |
| fails | holds | the type plane contributes marginally and still does not close the gap to `bm25`. 14.4 gets a KEEP; 14.1's reading is unchanged. |
| **fails** | **fails** | **H15.** The three-plane results stand as four-plane results. 14.4 gets a KILL alongside 14.1's, on its first evaluable run. |

## Acceptance matrix

1. Build the four-plane task set on **Daedalus** (the only subject measured to
   carry `*.schema.json` files; `fastapi` and `black` are checked and reported,
   not assumed). Record the full census and the four-plane composition.
2. **Prove the frozen artifacts did not move**: re-derive
   `taskset_xplane.json` and assert its digest is unchanged, in the same run.
3. Run every arm, including `bm25` and `random_uniform`.
4. Compare with `probe_arm_comparison`; run every probe twice, byte-identical.
5. Primary: H13. Then H14 by ablation, then H15.
6. **Supply gate.** If the four-plane task set carries fewer than **30** cases
   with type gold, the run is reported as **underpowered and not answering
   H14**, rather than answering it weakly. The prior probe measured 51 commits
   with type gold *before* the admissibility rules; how many survive them is
   unknown and is exactly what step 1 measures.
7. **MRR floor** 0.20 and the re-derivation guard, as in `CONFIRM-03` and `-04`.

## Migration and rollback

Nothing to migrate. A new builder, new task-set artifacts and one membership
constant. Rollback is deleting the builder, its artifacts, these documents and
reverting `FUSION_PLANES`; the frozen task sets and every published number are
untouched by construction, which acceptance step 2 proves rather than asserts.

A negative result is not rolled back — under H15 it is the most valuable
outcome this packet can produce.

## Evidence, expected failures and review

- **The type plane will be thin.** 51 commits carried type gold before
  admissibility filtering, against 531 and 700 cross-plane cases in the other
  subjects. H14 may be underpowered; step 6 makes that a reported state rather
  than a weak answer.
- **Daedalus is the subject, and it is not a neutral one.** It is the
  repository the resolvers were built against and the one whose history the
  frozen rules were tuned on. A positive H13 here would need replication
  elsewhere before it meant anything; a negative one is the less surprising and
  more transferable direction.
- **`fastapi` and `black` may have no `*.schema.json` at all**, in which case
  the four-plane instrument cannot be run on them and this packet's result is
  single-subject. That is measured in step 1 and reported, not worked around.
- **My record.** Three pre-registrations, three of my diagnoses refuted, and
  two reading tables that failed to fit their own outcome because I wrote
  "holds/fails" where "indistinguishable" belonged. This table has the same
  flaw and I am keeping the binary form only because H15 makes the ambiguous
  branch cheap: any outcome that is not a clear H13 leaves the existing
  conclusions standing.
