# G2-PREP-GD01 — Deterministic Fourfold GraphDelta

## Purpose

This non-authoritative Gate-2 preparation packet adds a canonical, read-only
comparison between two already-built `FourfoldSnapshot` identities.

```text
base FourfoldSnapshot + candidate FourfoldSnapshot -> GraphDelta
```

The packet is independent of GraphProposal acceptance and source
materialization. It cannot edit either snapshot, apply a proposal, write a
candidate tree, publish a Forest, merge, promote or close a gate. Gate 0 remains
the active authoritative gate.

## Exact comparison boundary

`GraphDelta` binds:

- one repository identity;
- exact base and candidate snapshot digests;
- exact base and candidate revisions;
- exactly four ordered `PlaneDelta` records;
- a complete, sorted set of semantic `BindingDelta` records;
- derived semantic-change, evidence-change and aggregate-change flags;
- provenance over both snapshots and every retained delta record.

A consumer must call `require_graph_delta()` with the exact snapshots. The delta
is recomputed under its retained timestamp and trace identity and compared as a
complete canonical record.

## Plane deltas

Each `PlaneDelta` retains exact base/candidate plane digests and partitions:

- added, removed and retained node IDs;
- added, removed and retained internal relation digests;
- added, removed and retained evidence digests;
- base/candidate status and partial/absent reason.

The partitions are canonical, unique and pairwise disjoint. Absent planes cannot
claim retained or removed base content, or added or retained candidate content.

Node, relation or status changes are classified as semantic. Evidence-set or
reason changes are classified as evidence changes. A revision-only rebuild with
identical semantic and evidence sets is therefore represented as an exact new
snapshot identity with `changed=false`.

## Cross-plane binding deltas

A `BindingDelta` uses a revision-independent semantic key over source plane/node,
target plane/node and relation while retaining the exact revision-bound
before/after `CrossPlaneBinding` records.

The derived change vocabulary is:

- `added`;
- `removed`;
- `evidence_changed`;
- `unchanged`.

This avoids reporting every binding as removed and re-added merely because a
candidate uses a different source revision. Evidence drift on one unchanged
semantic binding remains visible. A relation replacement is deliberately one
removed semantic binding plus one added semantic binding.

## Independent counter-review findings fixed

### Internal relation and coverage-reason drift

The first builder version compared plane nodes and evidence only. It omitted the
plane's internal `relation_sha256s` and the canonical reason attached to partial
or absent states. A relation or coverage-explanation change could therefore
produce a different snapshot while the delta claimed no change.

The contract now partitions internal relation digests and retains both reasons.
Relation drift is semantic; reason drift is evidence drift. Isolated review
fixtures ensure those dimensions cannot be hidden by simultaneous node or
status changes.

### Exact identity no-op refusal

A later review reproduced a failure on the most conservative comparison:
`compute_graph_delta(snapshot, snapshot)`. Both semantic roles correctly retained
the same snapshot digest, but `ContractProvenance` forbids duplicate input
digests, so construction failed before a canonical no-op delta could exist.
That breaks exact deterministic-rebuild checks, where equality rather than a
changed candidate is the expected result.

The delta now keeps base and candidate roles in their explicit contract fields
and retains each provenance evidence identity once. A focused exact-identity
fixture requires a canonical `changed=false` result, strict wire round trip and
successful recomputation. A dedicated mutation restores the duplicate input and
must be killed.

These are model-assisted source-review findings, not independent human review or
hard Gate evidence.

## Adversarial verification requested

Builder and separate review tests cover:

- exact snapshot-identity no-op comparison;
- revision-only rebuilds with no semantic/evidence delta;
- added, removed and retained nodes;
- internal relation drift;
- status and reason drift;
- binding addition/removal;
- binding evidence change without false remove/add classification;
- relation replacement as removed plus added;
- exact deterministic recomputation;
- cross-repository refusal;
- stale candidate substitution;
- noncanonical nested wire arrays;
- derived flag integrity;
- overlapping partitions and impossible absent-plane content;
- source review forbidding application, publication and promotion calls.

The bounded mutation campaign attacks seven seams:

1. cross-repository comparison;
2. internal relation changes;
3. reason changes;
4. binding evidence changes;
5. strict delta-wire comparison;
6. mandatory recomputation before consumption;
7. exact-identity provenance deduplication.

Each mutation requires a green focused baseline, must be killed by the focused
tests and must restore the source byte-exactly.

Dedicated CI requests Ubuntu and Windows, Python 3.10 and 3.12, two hash seeds,
Iron Plan verification, compile-all, Fourfold parent tests, builder/review tests,
mutation execution, the repository full suite and an isolated-wheel import.

## Deliberate remaining boundary

This packet does not provide:

- GraphProposal application;
- candidate source materialization;
- behavioral or schema acceptance criteria;
- RoundTripReport;
- a trusted evidence resolver;
- general repository compiler coverage;
- publication or promotion authority.

A later RoundTrip packet must bind this exact delta to a materialized candidate,
rebuilt candidate snapshot and behavior/evidence results. It may not infer
success from `changed=true` alone.

## External verification blocker

GitHub Actions issue #67 remains active: hosted jobs terminate before Step 1
with no step records or logs. Such runs cannot establish a product verdict. This
packet remains draft until exact-head commands execute.

## Gate state

- Active authoritative gate: Gate 0
- Gate-2 status: preparation only
- Promotion: not requested
- Gate closure: not claimed
