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
3. stores the exact `FourfoldSnapshot.digest` as deterministic evidence output;
4. retains repository ID, source revision, candidate digest, Forest digest, and snapshot digest in structured evidence details;
5. verifies the packet again before returning it;
6. performs no effect, approval consumption, checkout write, or promotion.

## Acceptance criteria

- The real wiki fixture compiles to four complete planes and 31 verified bindings.
- The evidence packet binds exactly one candidate digest and locator.
- The Fourfold evidence item output equals the real snapshot digest.
- A source mutation changes both candidate source-bundle and snapshot identity.
- Evidence for the old candidate is refused against the changed candidate.
- A snapshot compiled under another revision is refused.
- Missing or repackaged Fourfold evidence is refused.
- Candidate locator repackaging is refused.
- `OwnerApproval` verifies only against the exact candidate and EvidencePacket digest.
- A moved target HEAD is refused during the final live-head verification step.

## Deliberate boundary

This packet does **not**:

- consume the OwnerApproval;
- call `promote_candidates`;
- register a new effectful entrypoint;
- mutate a source tree;
- claim Gate 0 is closed;
- implement the Gate-1 rename or graph delta.

The later sealed promotion packet must still atomically consume the approval and re-read the live Target HEAD immediately before mutation.

## Evidence commands

```bash
python tools/iron_plan_guard.py verify
python -m pytest -q \
  tests/kernel/test_fourfold_evidence.py \
  tests/kernel/test_fourfold_approval_integration.py \
  tests/kernel/test_owner_approval.py \
  tests/twin/test_wiki_reference.py \
  tests/twin/test_reference_hardening.py
python -m build
```
