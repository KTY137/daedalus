# G2-XPLANE-CONFIRM-02 - do the two KEEPs survive outside a docs-heavy web framework?

Packet ID: `G2-XPLANE-CONFIRM-02`
Artifact role: `primary`
Status: `PRE-REGISTERED; no second subject selected at the time of writing`
Active gate: `1`
Classification: `EXPERIMENT`
Owner: `repository owner`
Base revision: `f23cb946a55e8e14d09ba7f9d3ac9e0e1c1b0e11`
Dependencies: `G2-XPLANE-CONFIRM-01`
Master-plan authority: `Revision 13`
Promotion: not requested. This packet cannot open, enter or satisfy any gate.

## Why this exists

`G2-XPLANE-CONFIRM-01` returned the first two KEEPs this programme has produced
(14.3 and 14.7) on `fastapi`. Its own closing paragraph names the obvious
threat:

> The corpus obligation stands with a changed purpose: not to reach
> significance on 14.1, but to test whether 14.3 and 14.7 survive outside
> documentation-heavy Python web frameworks.

`fastapi` at its anchor tracks **981 `.md` files against 1,239 `.py`** - a
markdown-to-python ratio of **0.79**. A retrieval method that fuses a knowledge
plane into its ranking has an obvious structural advantage in a repository
where four files in nine are prose. If 14.3's KEEP is an artifact of that, it
will not survive a code-heavy subject, and this packet is how that gets found
out rather than assumed either way.

## Primary acceptance claim

> The two KEEP verdicts from `CONFIRM-01` are re-tested on a repository chosen
> to be structurally UNLIKE `fastapi`, under the same frozen protocol. The
> claim of this packet is again the protocol, not an outcome: every result is
> registered below with its reading before the subject is chosen.

## The hypotheses

**H4 (primary).** 14.3 replicates: `fusion_rrf` beats `separate_indices_bm25`
on the cross-plane stratum, CI95 excluding zero from above.

**H5.** 14.7 replicates: the advantage over `code_only_bm25` survives leakage
scrubbing, CI95 still excluding zero in the `scrubbed` variant.

**H6 (registered because it predicts against the KEEPs).** The effect size for
H4 is **materially smaller** on a code-heavy repository than `fastapi`'s
+0.1588 - specifically, below +0.08, i.e. less than half. If cross-plane fusion
is buying prose, the buy shrinks when there is less prose.

### Readings, fixed now

| H4 | H6 | reading |
| --- | --- | --- |
| holds | fails (effect stays large) | 14.3's KEEP is robust to repository shape. The strongest result this programme has. |
| holds | holds (effect shrinks a lot) | the KEEP is real but **dose-dependent on documentation density**. 14.3 survives; the interpretation narrows sharply and must say so. |
| fails | - | 14.3's KEEP does not generalise. `CONFIRM-01` gets re-labelled a single-repository result, not retracted - it was correctly measured on its own subject. |

H5 is reported the same way but is secondary: leakage-scrub survival is a
property of the *metric*, and one repository either way does not settle it.

## Scope

### Subject selection, fixed before looking

Same discipline as `CONFIRM-01`: selection on **preconditions only**, never on
any outcome quantity. One precondition is added, and it is a *structural*
property measured at the anchor, not an effect:

**Criteria, all required:**

1. OSI-permissive license (MIT, BSD-2/3, Apache-2.0), recorded with its sha256.
2. Python-majority source.
3. At least 1,200 commits reachable from the anchor.
4. Documentation and structured data tracked in-repo - without it there are no
   cross-plane commits at all and the run is impossible.
5. **`.md`-to-`.py` file-count ratio at the anchor below 0.40**, i.e. less than
   half `fastapi`'s 0.79. This is the "structurally unlike" requirement, and it
   is deliberately a ratio of tracked files rather than anything derived from a
   retrieval score.
6. `cross_plane_admissible >= 68`, the same floor as `CONFIRM-01`.
7. Not Daedalus, not `fastapi`.

**Candidate order, fixed here:**

1. `pytest-dev/pytest`
2. `psf/black`
3. `python-attrs/attrs`
4. `sqlalchemy/sqlalchemy`
5. `numpy/numpy`

**Stopping rule:** the **first** candidate satisfying all seven. Record the
census of every candidate that falls short, including *which* criterion it
missed. If all five fall short, that is the reported finding - most likely
that criteria 4 and 5 are in tension, which would itself be a real result
about what cross-plane evaluation can be run on.

**Temporal pin:** newest commit on the default branch with committer date
strictly before **2026-01-01T00:00:00Z**, identical to `CONFIRM-01`.

## Contracts and behavior

### Frozen protocol - deliberately unchanged, including a known defect

Every element is inherited from `CONFIRM-01` unchanged: `reciprocal_rank`,
CI95 percentile bootstrap, 10,000 resamples, seed 20260818, margin ±0.02,
`min_cases` 10, unmodified `taskset_xplane.py` and `PLANE_BY_SUFFIX`, the same
five arms, pre-image isolation on.

**This includes `single_plane_control_target: 30`, which `CONFIRM-01` proved is
too small.** That run's own result section records it: the placebo stratum is
capped at 30 cases regardless of repository size, so it cannot detect an effect
of -0.065, and H2 failed for that reason rather than for want of the effect.

Raising that cap is the obvious improvement and it is **NOT done here**. The
whole point of this packet is to change the SUBJECT while holding the
INSTRUMENT fixed; changing both at once is precisely what plan §14 forbids and
what I invoked against myself when declining to fix the plane rule in
`CONFIRM-01`. The control cap gets its own packet, and when it is fixed both
subjects must be re-run under the new rule.

Consequence, stated now so it is not reported as a discovery: **H2 is not
re-tested by this packet.** The control stratum will again be n=30 and again
underpowered. Any control number here is descriptive only.

## Acceptance matrix

### Analysis plan, fixed before the data

1. Build the task set with the unmodified builder; record the full census and
   the `.md`/`.py` ratio actually measured.
2. Run the harness with the same three fusion retrievers plus baselines.
3. Adapt through `to_s10` with `--gold-planes-from taskset_xplane`.
4. Report the s10 verdicts and the stratified probe, both strata, all three
   comparisons - identical outputs to `CONFIRM-01` so the two are readable
   side by side.
5. Primary test: H4 on the cross-plane stratum. Secondary: H5, H6.
6. Run the stratified probe **twice** and require byte-identical output before
   any number is reported.
7. No re-cutting. One subject, one task set, one run.

### The absolute-MRR transfer check, retained as a gate on the whole run

`CONFIRM-01` declared that a large drop in absolute MRR is a reason to distrust
the comparison. It did not fire there (`fusion_rrf` 0.4072 vs 0.4820). It is
re-declared here with a threshold, since a code-heavy subject is exactly where
transfer might fail: **if `fusion_rrf` raw MRR falls below 0.20, roughly half
`fastapi`'s, the comparison is reported as untrustworthy** and H4/H5/H6 are
recorded as not answered rather than answered negatively.

## Migration and rollback

Nothing to migrate. The packet adds no code path and no production artifact.
Outputs are a third-party clone outside the tree plus task-set, harness,
kill-input and report JSON under `runs/` and `docs/evidence/`.

Rollback is deletion of those plus this document. `CONFIRM-01`'s evidence and
the frozen `xplane88` measurement are untouched by construction, since the
protocol forbids modifying the builder, the plane rule or any retriever.

A negative result is **not** rolled back. Plan §1 requires retained negative
evidence; if H4 fails, that is the most informative thing this packet can
produce and it stays in the tree.

## Evidence, expected failures and review

- **A code-heavy repository may have too few cross-plane commits.** Criteria 4
  and 5 pull against each other: less prose means fewer commits that touch
  prose and code together. If every candidate fails criterion 6 *because* it
  passes criterion 5, that tension is the finding, and it would mean
  cross-plane evaluation is only available on documentation-heavy projects -
  which would substantially qualify `CONFIRM-01`.
- **Instrument transfer.** Both resolvers were built against Daedalus and have
  now been exercised on one other repository. A second unfamiliar tree is where
  a latent assumption is most likely to surface; the MRR floor above is the
  declared trigger.
- **One more repository is still not a corpus.** Three data points, of which
  two are Python packages with in-repo docs. Gate 2's corpus obligation -
  license audit, deterministic Twin rebuilding, cross-repository alignment,
  motif provenance - remains entirely untouched.
- **My own record today.** I have corrected myself three times on Gate 2:
  the type-plane overclaim, the pooled-estimate framing, and `CONFIRM-01`'s
  2x2 reading that did not fit its own outcome. H6 exists specifically because
  it predicts the result that would embarrass the KEEP I just reported.
