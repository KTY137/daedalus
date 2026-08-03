# G0-RCP-04A — Fourfold Evidence Binding

## Classification

- Iron Plan: `ALIGNED`
- Iron Gate: `0`
- Base: `g0/effect-leases`
- Promotion: forbidden
- Primary-checkout mutation: forbidden

## Objective

Prove that the Gate-0 trust chain protects the identity of a real, revision-bound Fourfold artifact rather than only synthetic hashes.

The packet compiles the existing bounded wiki fixture and binds:

```text
candidate source bundle digest
+ source revision
+ KnowledgeForest digest
+ FourfoldSnapshot digest
→ canonical EvidencePacket digest
→ authenticated OwnerApproval
```

The implementation reuses the existing `EvidencePacket`, `EvidenceItem`, `FourfoldSnapshot`, and `OwnerApproval` contracts. It does not introduce another evidence schema or graph authority.

## Scope

The new adapter:

1. accepts an already compiled `FourfoldSnapshot`;
2. uses the reference compiler's `source_bundle_sha256` as the content-addressed candidate identity;
3. requires that exact candidate digest to be retained in the snapshot's compiler provenance;
4. stores the exact `FourfoldSnapshot.digest` as deterministic evidence output;
5. retains repository ID, source revision, candidate digest, Forest digest, snapshot digest, all plane statuses, and the verified binding count in structured evidence details;
6. permits conclusive promotion evidence only when all four planes are `complete`;
7. verifies the candidate/provenance binding, packet identity, and plane completeness again before returning it;
8. performs no effect, approval consumption, checkout write, or promotion.

`partial` and `absent` remain valid and honest Fourfold snapshot states for discovery. This promotion-facing adapter refuses to upgrade either state into an overall `passed` packet.

## Acceptance criteria

- The real wiki fixture compiles to four complete planes and 31 verified bindings.
- The evidence packet binds exactly one candidate digest and locator.
- The Fourfold evidence item output equals the real snapshot digest.
- The snapshot provenance binds the same candidate source-bundle digest carried by the packet.
- Plane completeness and verified-binding count are retained in canonical evidence details.
- A `partial` or `absent` plane cannot produce or verify as passed promotion evidence.
- A source mutation changes both candidate source-bundle and snapshot identity.
- Evidence for the old candidate is refused against the changed candidate.
- Snapshot A cannot be repackaged beside Candidate B, even when Candidate B's locator is internally consistent.
- A structurally valid snapshot whose provenance omits the candidate digest is refused.
- A snapshot compiled under another revision is refused.
- Missing or repackaged Fourfold evidence is refused.
- Candidate locator repackaging is refused.
- `OwnerApproval` verifies only against the exact candidate and EvidencePacket digest.
- A moved target HEAD is refused during the final live-head verification step.

## Adversarial review

The separate review perspective found two independent trust gaps.

First, the initial implementation accepted any structurally valid `FourfoldSnapshot`, including snapshots whose planes were honestly `partial` or `absent`, and then emitted a conclusive `passed` packet. That would allow incomplete polyglot semantics to be mistaken for promotion-grade evidence. The boundary now rechecks all four plane statuses during both assembly and verification. A focused mutation that removes this check is killed by `test_partial_snapshot_cannot_be_upgraded_to_passed_promotion_evidence`.

Second, the adapter originally placed a candidate digest and snapshot digest into the same packet without proving that the compiler produced that snapshot from that candidate. Snapshot A could therefore be repackaged with Candidate B while the packet remained internally consistent. The reference compiler already retains `source_bundle_sha256` in `FourfoldSnapshot.provenance.input_digests`; the adapter now requires that deterministic compiler binding during assembly and verification. `test_snapshot_cannot_be_repackaged_with_another_candidate_bundle` and `test_structurally_valid_snapshot_without_candidate_provenance_is_refused` kill removal of this check.

## Deliberate boundary

This packet does **not**:

- consume the OwnerApproval;
- call `promote_candidates`;
- register a new effectful entrypoint;
- mutate a source tree outside temporary test fixtures;
- claim Gate 0 is closed;
- implement the Gate-1 rename or graph delta.

The later sealed promotion packet must still atomically consume the approval and re-read the live Target HEAD immediately before mutation.

## Evidence commands

```bash
python tools/iron_plan_guard.py verify
python -m pytest -q \
  tests/kernel/test_fourfold_evidence.py \
  tests/kernel/test_fourfold_candidate_provenance.py \
  tests/kernel/test_fourfold_approval_integration.py \
  tests/kernel/test_owner_approval.py \
  tests/twin/test_wiki_reference.py \
  tests/twin/test_reference_hardening.py
python -m build
```
