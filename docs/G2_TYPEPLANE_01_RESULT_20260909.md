# G2-TYPEPLANE-01 result: the plane rule was fixable; the task formulation is not

`[MEASURED 2026-09-09]`
Protocol: `docs/work-packets/G2-TYPEPLANE-01_PREREGISTRATION.md` (`7741574b`).
Subject: Daedalus @ anchor `d849c2a9`. Probes run twice, byte-identical.
Classification: `EXPERIMENT`. **Decides nothing. Enacts nothing.**

## The headline

The four-plane instrument was built correctly and it **cannot answer the
question it was built for** — for a reason that no amount of rule-fixing
reaches.

| | |
| --- | --- |
| type-gold cases in the four-plane task set | **1** |
| pre-registered supply gate | **30** |
| **H14 (criterion 14.4)** | **UNANSWERED — underpowered, as registered** |

## Acceptance step 2 passed: the frozen artifacts did not move

The refinement is a **new builder** (`taskset_xplane4.py`) that imports the
frozen `SELECTION`, selection rules and census machinery unchanged and rebinds
exactly one name — `plane_of` — inside a context manager, restoring it in a
`finally`.

Re-deriving the frozen task set **in the same process, after the refined
build**, returns:

```
committed taskset_xplane.json   sha256:0148e7f0e3744c40420cc90e31ee0f306930f7ac9e341289d8e5ac247e6c6386
re-derived in-process           sha256:0148e7f0e3744c40420cc90e31ee0f306930f7ac9e341289d8e5ac247e6c6386   MATCH
four-plane task set             sha256:c70c4eb9760e36049d29fa5cd1caf99246bf73ad09581b77c4c7106181f9bbad   different
```

A leaked rebinding would have shown up here as a changed digest rather than as
silent corruption of four published measurements. It did not.

## Why one case, when the probe found fifty-one

`probe_type_plane_supply.py` counted commits *touching* a schema file. The
builder additionally requires the gold to be **retrievable from the pre-image**.
Across the entire reachable history:

| schema-file changes | count |
| --- | ---: |
| **added** by the commit — absent from the pre-image | **41** |
| modified — present in the pre-image, retrievable | 11 |

Schema files in this repository are **written once and rarely edited**. After
the remaining admissibility rules and sampling, one case survives.

### The finding, stated at the level it actually holds

> The Type plane is not empty, and its emptiness was not merely a suffix-map
> defect. It is **dominated by creation events**, and a task that retrieves
> changed files *from the pre-image* is structurally blind to creations
> whatever the plane rule says.

Fixing `PLANE_BY_SUFFIX` was necessary and **insufficient**. A four-plane
instrument needs a different *task*, not a different suffix map. That is a
sharper and more useful statement than the three "the type plane is empty"
caveats it replaces.

## Step 1 also measured the other subjects

| subject | tracked `*.schema.json` |
| --- | ---: |
| `fastapi` | **0** |
| `black` | **1** |
| Daedalus | **89** |

So the Type plane, as defined by this convention, is essentially a
Daedalus-specific artifact. Any four-plane claim would have been single-subject
regardless — on the one repository the resolvers were built against, which the
pre-registration already named as not a neutral subject.

## H13 was not meaningfully testable, and my reading table failed again

The four-plane task set differs from the three-plane one in **exactly one case
out of 88**: a single `code+data` case became `code+type`. Running the arms on
it therefore re-measures the three-plane instrument under a new digest.

The run was done anyway, because Daedalus is a useful *third subject*, and it is
reported as that and not as a four-plane test:

| arm vs pooled `bm25` | cross-plane (n=58) | CI95 |
| --- | ---: | --- |
| `plane_calibrated` | -0.0016 | [-0.0987, +0.0943] |
| `pooled_plane_length` | -0.0108 | [-0.0547, +0.0294] |
| `fusion_rrf` | -0.0178 | [-0.1241, +0.0951] |
| `separate_indices_bm25` | **-0.1325** | [-0.2537, -0.0079] \* |

At n=58 only the concatenation arm resolves — precisely the underpowered regime
`GATE2_CROSS_PLANE_SUPPLY_CEILING` measured this morning. All four point
estimates are negative, which brings the running tally to **twelve
measurements** (four arms × three subjects) with a negative point estimate
against a plain pooled index, and none positive.

**H15's antecedent was "if H13 fails".** H13 did not fail — it was not
answerable. So H15 does not cleanly fire either, and this is the **third**
consecutive packet whose binary reading table did not fit its own outcome
(`CONFIRM-02`'s H2, `CONFIRM-04`'s H11, now this). The cause is the same every
time: I write `holds / fails` where the real outcome space contains
*indistinguishable* and *unanswerable*. Recorded as a standing defect in how I
write pre-registrations, not patched after the fact.

What can be said without the table: **the three-plane results stand as
written**, because the four-plane instrument turns out not to be constructible
from this task formulation. Their caveat changes from "these fuse three planes,
a four-plane run might differ" to "a four-plane run is not available here, and
the reason is the task, not the rule."

## What this does NOT establish

- **Not a KILL of 14.4.** A criterion that cannot be evaluated has not been
  refuted. `NOT_EVALUABLE` remains the honest verdict, now with a measured
  cause attached.
- **Not evidence that types do not matter.** It is evidence that *this task*
  cannot see them. A task graded on created files — or on type-checking
  outcomes rather than file retrieval — is untried and is where §5's Type plane
  claim would actually be tested.
- **Not generalisable beyond Daedalus.** `fastapi` has no schema files at all.
- **Nothing here touches Gate 2's obligations**: deterministic Twin rebuilding,
  cross-repository alignment and motif provenance remain untouched.

## Reproduction

```
python -m experiments.forest_v2.s09_eval.taskset_xplane4 \
    --repo <daedalus> --out <four-plane>.json --verify-frozen
```

`--verify-frozen` prints the re-derived frozen digest, which must equal
`taskset_xplane.json`'s. Evidence with sha256s under
`docs/evidence/G2-TYPEPLANE-01/`.
