# G2-XPLANE-CONFIRM-01 - pre-registration of the confirmatory cross-plane run

Packet ID: `G2-XPLANE-CONFIRM-01`
Artifact role: `primary`
Status: `PRE-REGISTERED; no new data measured at the time of writing`
Active gate: `1`
Classification: `EXPERIMENT`
Owner: `repository owner`
Base revision: `1cccb42b7ea8e4e1a1b6f0f8a52b3ed4e3e4ad3f`
Dependencies: `G3-BASE-01, forest_v2 s09/s10/s11`
Master-plan authority: `Revision 13`
Promotion: not requested. This packet cannot open, enter or satisfy any gate.

## Why this document exists before the data

`docs/GATE2_CROSS_PLANE_SUPPLY_CEILING_20260909.md` records a stratified
re-analysis of the retained `xplane88` run. Its own honesty section says what it
is:

> I chose which comparison to foreground **after** seeing the numbers. The
> stratification itself was pre-registered in the task set's design, which is
> what makes this a legitimate re-analysis rather than fishing - but the honest
> status is **hypothesis-generating**, not confirmatory. A confirmatory run
> needs its own pre-registration naming the cross-plane stratum as primary
> before it is cut.

This is that pre-registration. It is written and committed **before any second
repository is cloned, any task set is built, or any retriever is run**, and its
commit precedes those artifacts in the history so the ordering is checkable
rather than asserted.

Plan §14 requires exactly this discipline: *"Freeze an ExperimentSpec, budget,
tasks, metrics, baselines, and seed policy"* before the trial, and *"Reject
results when code, prompts, memory, model, search policy, and evaluator changed
together."*

## Primary acceptance claim

> A confirmatory run on a second, independently selected repository,
> under a protocol frozen before the data exists, either replicates the
> `xplane88` stratified signature or refutes it. The claim of this packet
> is the PROTOCOL, not an outcome: every result below is registered in
> advance with its reading, so no outcome can be reinterpreted afterwards.

## The hypothesis, stated as a prediction that can fail

The `xplane88` re-analysis found, on 58 cross-plane and 30 single-plane control
cases:

| comparison | cross-plane | control |
| --- | ---: | ---: |
| `fusion_rrf` vs `code_only_bm25` | **+0.1147** | **-0.1871** (excludes 0) |
| `fusion_rrf` vs `separate_indices_bm25` | +0.1147 | -0.1891 (excludes 0) |
| `fusion_rrf` vs `bm25` | **-0.0178** | +0.0640 |

**H1 (primary).** On a second, independent repository, `fusion_rrf` beats
`code_only_bm25` on the cross-plane stratum: the CI95 of the paired mean
difference in reciprocal rank excludes zero from above.

**H2 (the placebo, and the reason to care).** On the same repository's
single-plane control stratum, `fusion_rrf` is *worse* than `code_only_bm25`:
the CI95 excludes zero from below.

**H3 (the binding negative).** `fusion_rrf` does **not** beat `bm25` on the
cross-plane stratum. Plan criterion 14.1 requires beating `code_only` **and**
`bm25`; the re-analysis says the second fails. This is registered as a
prediction so that a *positive* result here counts as evidence against my own
current reading, not as a surprise to be explained away.

### What each outcome means, decided now

| H1 | H2 | reading |
| --- | --- | --- |
| holds | holds | the concentration signature replicates. Still not a KEEP for 14.1 unless H3 also flips. |
| holds | fails | fusion helps everywhere; the "cross-plane" story is wrong even though the number is good. |
| fails | holds | the cost replicates and the benefit does not. This is the strongest available argument for a KILL proposal on 14.1/14.3. |
| fails | fails | `xplane88` was noise. Both write-ups get retracted, not reinterpreted. |

## Scope

### Repository selection, fixed before looking

Selection is on **preconditions only**, never on any outcome quantity. The
distinction that matters: cross-plane *supply* is a precondition (the run is
impossible below ~68 cases), while the *effect size* is the outcome. Choosing on
supply is legitimate and is what plan §11's "chosen for cross-plane density"
means; choosing on effect would be fatal.

**Criteria, all required:**

1. OSI-permissive license (MIT, BSD-2/3, or Apache-2.0), recorded verbatim with
   the file it was read from.
2. Python-majority source. The plane rule and both resolvers are Python-shaped;
   a non-Python subject would change the instrument and the comparison.
3. At least 1,200 commits reachable from the anchor, so the identical
   `history_limit` window applies.
4. Documentation and structured data tracked **in the same repository**.
   Cross-plane commits are impossible by construction otherwise.
5. Not Daedalus, and no Daedalus code vendored into it.

**Candidate order, fixed here and not to be reordered afterwards:**

1. `tiangolo/fastapi`
2. `pallets/flask`
3. `psf/requests`
4. `python-attrs/attrs`
5. `pydantic/pydantic`

**Tie-break / stopping rule:** take the **first** candidate in that order whose
cross-plane admissible count is **>= 68** under the unmodified
`taskset_xplane.py` rules. If a candidate falls short, record its census and
move to the next. Do not test a sixth candidate; if all five fall short, the
finding is that the required density does not exist in mainstream Python
projects either, and that is reported as the result.

**Temporal pin:** the anchor is the newest commit on the default branch with a
committer date strictly before **2026-01-01T00:00:00Z**, recorded by SHA and
date. A fixed cutoff, chosen before selection, prevents an anchor being nudged
until the numbers improve.

## Contracts and behavior

### Frozen protocol

Everything below is inherited unchanged from the `xplane88` run. Any deviation
invalidates the comparison and must be reported as a deviation, not folded in.

| element | value |
| --- | --- |
| primary metric | `reciprocal_rank` |
| decision rule | CI95 percentile bootstrap |
| resamples | 10,000 |
| seed | 20260818 |
| equivalence margin | ±0.02 |
| min cases | 10 |
| task-set rules | `taskset_xplane.py`, unmodified, same `SELECTION` |
| plane rule | `taskset.py::PLANE_BY_SUFFIX`, **unmodified** (schemas stay `data`) |
| arms | `fusion_rrf`, `code_only_bm25`, `separate_indices_bm25`, `bm25`, `random_uniform` |
| pre-image isolation | on |

The plane rule stays unmodified **on purpose**, even though
`probe_type_plane_supply.py` showed it mislabels 90 schema files here. Changing
the instrument and the subject in the same step is exactly what plan §14
forbids. The type-plane refinement is a separate packet with its own baseline.

## Acceptance matrix

### Analysis plan, fixed before the data

1. Build the task set with the unmodified builder. Record the full census.
2. Split the cases into cross-plane and single-plane control by the **same
   mechanical rule** used in the re-analysis: a case is control iff its gold
   sits in exactly one Twin plane.
3. Report all three comparisons in all three strata (pooled, cross-plane,
   control). **The pooled number is reported but is not the primary**, and its
   demotion is registered here rather than argued afterwards.
4. Primary test: H1 on the cross-plane stratum.
5. No re-cutting. One task set, one run, one analysis. If the run reveals a
   defect in the harness, the run is discarded and re-registered - not repaired
   mid-flight and reported.

## Evidence, expected failures and review

### Declared threats to validity

- **Between-repository variance.** The `n>=68` floor came from a `1/sqrt(n)`
  projection assuming an unchanged per-case difference distribution. A different
  repository is precisely where that assumption is weakest. 68 is a floor, not
  an estimate, and an inconclusive result at n≈70 is an expected outcome rather
  than a failure.
- **Instrument transfer.** Both resolvers were built against Daedalus. Poorer
  performance on an unfamiliar tree affects *all arms*, but not necessarily
  equally; a large drop in absolute MRR is a reason to distrust the comparison
  and must be reported.
- **One repository is not a corpus.** Whatever this returns, it is a second
  data point, not the "small license-audited corpus" Gate 2 requires.
- **My own priors.** I have written two Gate-2 documents today and corrected
  myself twice. H3 exists specifically so that the outcome which contradicts my
  current reading is registered in advance and cannot be quietly reframed.

## Migration and rollback

Nothing to migrate: this packet adds no code path, no production
artifact and no state. Its outputs are a cloned third-party repository
outside the tree, one task-set JSON and one results JSON, all under
`runs/` and `docs/evidence/`.

Rollback is deletion of those artifacts plus this document. The frozen
`xplane88` measurement is untouched by construction -- the protocol
forbids modifying the builder, the plane rule or any retriever -- so a
rollback cannot disturb any existing number.

The one thing that must NOT be rolled back is a negative result. Plan
section 1 requires retained negative evidence; if H1 fails, this packet's
record of that failure stays in the tree.

### What this packet cannot do

It cannot close, open, enter or satisfy Gate 2. It cannot promote anything, and
it produces no candidate. A KILL verdict on any criterion remains a **proposal
to open an amendment** under plan §15, never an action.
