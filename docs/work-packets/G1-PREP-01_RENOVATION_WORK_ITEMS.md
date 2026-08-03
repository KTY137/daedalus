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
- direct-constructor bypass objects that do not survive canonical reconstruction;
- reordered, tuple-repacked, duplicate-key, or otherwise noncanonical wires.

## Counter-review findings

The first builder version relied on the generic dataclass serializer for nested
`WorkItemContract` records. That representation omitted the nested canonical
contract headers and could not be reconstructed by the strict parser. The plan
now owns an explicit wire representation and serializes every nested item
through `WorkItemContract.to_dict()`.

The consumer also now reconstructs the plan, mission, and base snapshot before
checking their external bindings. A caller cannot gain authority from an object
created by bypassing a dataclass constructor.

A separate AST/source review checks that the planning layer imports no process,
network, temporary-workspace, Effect-Lease, OwnerApproval, or promotion
authority and retains the exact cardinality, dependency, path-ownership,
complete-plane, reconstruction, and canonical-wire fences.

## Adversarial verification

Builder and source-review tests cover stale identities, malformed and
noncanonical wires, recursive duplicate keys, dependency inversion, plane
substitution, overlapping write ownership, weakened provenance, and a forged
constructor-bypass object.

A bounded mutation runner attacks three high-value seams:

1. accept a work-item count other than two;
2. accept overlapping writable-path ownership;
3. accept a noncanonical plan wire.

Every mutation requires a green focused baseline, must be killed, and must leave
the source byte-identical after restoration.

A local contract smoke using the inspected public base-contract forms completed
14 focused builder/review tests. This is preparatory builder evidence only, not
an exact-head full-suite, platform, packaging, mutation, or Gate verdict.

## External verification blocker

GitHub Actions issue #67 remains open. Hosted jobs terminate before checkout
with no steps, logs, or artifacts. The dedicated Ubuntu/Windows, Python
3.10/3.12, hash-seed, mutation, full-suite, Iron Plan, and isolated-wheel jobs
must execute on the exact head before this packet can be treated as verified.

## Deliberate boundary

This packet does not create Attempts, CAS candidates, GraphDelta,
RoundTripReport, EvidencePacket, OwnerApproval, or PromotionReceipt. It does not
start Gate 1 authoritatively while Gate 0 remains open. It is preparatory work
allowed under the documented external CI blocker and must be replayed and fully
verified against the final accepted Gate-0 head before Gate-1 activation.
