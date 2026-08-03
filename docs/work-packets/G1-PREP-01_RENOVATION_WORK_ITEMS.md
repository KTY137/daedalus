# G1-PREP-01 — Typed Renovation WorkItems

## Classification

- active authoritative gate: Gate 0
- target gate: Gate 1 preparation only
- base: exact `g0/release-assessment-linear` revision
- authority: contracts only; no execution, effects, evidence acceptance, nomination, merge, or promotion

## Acceptance claim

Represent the adopted ignition slice with one existing canonical `MissionContract`
and exactly two typed `WorkItemContract` records:

1. `symbol-rename` owns Code and Type;
2. `representation-sync` owns Data and Knowledge and depends on the rename.

The enclosing `RenovationPlan` binds the exact mission digest, base revision,
complete Fourfold snapshot digest, both work-item digests, disjoint writable
paths, required deterministic evidence, and the complete four-plane coverage.

## Refusal matrix

The packet refuses:

- one, three, duplicate, or same-kind work items;
- stale mission, source revision, or Fourfold snapshot;
- partial or absent base planes;
- missing or inverted dependency order;
- plane-scope substitution and overlapping path ownership;
- provenance that omits or adds retained authority inputs;
- reordered, tuple-repacked, duplicate-key, or otherwise noncanonical wires.

## Deliberate boundary

This packet does not create Attempts, CAS candidates, GraphDelta,
RoundTripReport, EvidencePacket, OwnerApproval, or PromotionReceipt. It does not
start Gate 1 authoritatively while Gate 0 remains open. It is preparatory work
allowed under the documented external CI blocker and must be replayed and fully
verified against the final accepted Gate-0 head before Gate-1 activation.
