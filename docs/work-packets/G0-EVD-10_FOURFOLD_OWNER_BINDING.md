# G0-EVD-10 — Fourfold evidence to OwnerApproval binding

## Objective

Connect the already adopted Fourfold semantic kernel to the existing Gate-0
trust contracts without creating a second graph authority, evidence schema,
owner authority or promotion path.

The packet uses the existing repository-bound Wiki reference compiler and
binds these exact identities:

1. candidate source-tree digest and content-addressed locator;
2. one source revision;
3. the compiled `KnowledgeForest` digest;
4. the atomic `FourfoldSnapshot` digest and its four plane statuses;
5. one canonical `EvidencePacket`;
6. one canonical `NominationReceipt`;
7. an independently authenticated `OwnerApproval` expectation.

The production bridge stops before approval issuance. The approval used in the
focused test is signed only by an explicit test-fixture key, is never persisted
or consumed, and cannot be represented as an owner decision or promotion
receipt.

## Implementation

`daedalus.kernel.fourfold_evidence` now:

- reconstructs caller-supplied snapshots, packets and nominations through their
  strict canonical parsers before comparing identities;
- requires the candidate locator to resolve to the independently supplied
  candidate digest;
- records the exact snapshot digest as deterministic evidence while retaining
  the candidate tree as the packet subject;
- records the source Forest digest, snapshot digest and every plane status in
  the evidence item;
- unconditionally requires Code, Type, Data and Knowledge to be `complete` in
  this conclusive Gate-0 path; there is no caller switch that can promote a
  partial snapshot to passed evidence;
- creates and re-verifies a nomination that binds candidate, packet, snapshot
  locator, policy, mission, attempt and revision;
- performs no file writes, provider calls, approval issuance, approval
  consumption, git operation or promotion.

## Counter-review finding

The first draft exposed `require_complete=False` while the assembler still
emitted `evaluation_status="passed"`. A caller could therefore have dressed a
partial snapshot as conclusive Gate evidence. The switch was removed entirely,
the verifier now refuses every non-complete plane unconditionally, the source
counter-review forbids a partial-evidence parameter, and the mutation campaign
attacks the unconditional refusal seam. Partial Polyglot semantics remain a
later Gate-2 concern and must be represented as partial/inconclusive there.

## Adversarial coverage

The focused suites cover:

- a real complete four-plane snapshot with 31 verified cross-plane bindings;
- source mutation changing candidate, Forest/snapshot evidence, packet and
  nomination identities;
- stale revision substitution with the same source-tree bytes;
- a foreign candidate locator;
- a valid but foreign EvidencePacket subject;
- a frozen-dataclass constructor bypass attempt;
- a partial plane entering the Gate evidence path;
- a foreign nomination packet digest;
- pairing a valid packet with another candidate's nomination;
- an AST counter-review proving the bridge has no approval-consumption,
  promotion or external-effect authority and no partial-evidence switch.

The bounded mutation runner attacks five load-bearing seams: candidate locator
identity, complete-plane enforcement, packet subject binding, nomination packet
binding and canonical packet reconstruction. Each mutation is valid only when
the baseline suite is green, and the original source is restored byte-for-byte
after every run.

## CI and packaging

The dedicated workflow requests:

- Ubuntu and Windows;
- Python 3.10 and 3.12;
- `PYTHONHASHSEED=0` and `123456`;
- Iron Plan verification and compile-all;
- the existing Wiki reference and OwnerApproval suites;
- focused canonical, malformed, stale, bypass and source-review tests;
- the bounded mutation campaign;
- the repository-wide suite;
- isolated wheel build, install and import outside the checkout.

GitHub Actions issue #67 remains an external exact-head infrastructure blocker
if hosted jobs again terminate before Step 1 with no steps, logs or artifacts.
Such a run is not product, mutation, platform, packaging or Gate evidence.

## Deliberate remaining boundary

This packet does not consume an OwnerApproval, create a PromotionReceipt, call
`promote_candidates`, modify the primary checkout, centralize another effectful
entrypoint, or set Gate 0 `closed=true`. It proves only that a real Fourfold
semantic artifact can be carried through the existing evidence and nomination
contracts and that an OwnerApproval expectation fails closed when any bound
identity changes.

Gate: **0**  
Promotion: **not requested**  
Merge: **not requested**
