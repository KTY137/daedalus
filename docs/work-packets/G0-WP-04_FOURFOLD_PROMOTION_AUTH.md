# G0-WP-04 — Fourfold-bound promotion authorization

Status: builder implementation  
Classification: ALIGNED  
Active gate: Gate 0 — Canonical Kernel  
Base revision: `9d7a34a2f15a2a21ecb193fb0c56fb23f0c8c34d` (`g0/effect-leases`)  
Primary claim: an owner capability can authorize only the exact nominated candidate whose deterministic evidence names its exact candidate Fourfold snapshot.

## Dependencies

- G0-WP-01 deterministic gate reporting
- G0-WP-02 authenticated one-use `OwnerApproval`
- G0-WP-03 persisted `EffectLease`
- WP-00 Fourfold snapshot and real wiki reference compiler

## In scope

- verify exact candidate, candidate locator, evidence packet, policy decision, base revision and repository identity;
- require the candidate `FourfoldSnapshot.source_revision` to equal the candidate source artifact digest;
- require `EvidencePacket.subject_sha256` and a deterministic/independent passed evidence item to name the exact candidate snapshot digest;
- require configured Fourfold planes to be `complete` rather than accepting `partial` as trusted;
- authenticate the original owner approval against nomination, candidate, evidence, base revision, target ref and current target HEAD;
- require a direct content-addressed owner-approval locator for the supplied canonical approval;
- consume the approval atomically before returning an approved canonical `PromotionReceipt`;
- retain the snapshot and consumed-capability digests in receipt provenance.

## Explicitly out of scope

- no Git ref update, merge, checkout replacement or deployment;
- no automatic owner approval, merge or promotion;
- no production caller migration;
- no relaxation of current unguarded/inventory-only effect-registry blockers;
- no claim that Gate 0 is closed;
- no general Gate-2 repository compiler or Graph Delta implementation.

The later sealed-application packet must re-read and compare the live target HEAD inside the same transaction that performs the repository mutation. This packet returns authorization evidence only.

## Acceptance matrix

| Case | Required result |
| --- | --- |
| real wiki fixture compiles to a complete Fourfold snapshot | authorization succeeds with authenticated approval and persisted consumption |
| approval replay | refused atomically |
| target HEAD differs from the approval | refused before capability consumption |
| candidate snapshot revision differs from candidate artifact digest | refused |
| snapshot repository differs from the requested repository | refused |
| evidence subject differs from snapshot digest | refused |
| no deterministic/independent evidence output equals snapshot digest | refused |
| a required plane is `partial` or `absent` | refused |
| nomination repackages candidate or evidence locators | refused |
| approval locator does not address the supplied approval payload | refused before consumption |
| malformed timestamp or required-plane set | refused |

## Adversarial mutation seeds

The following mutations must be killed by the focused tests:

1. remove the candidate-snapshot revision comparison;
2. remove the evidence-subject comparison;
3. accept an evidence packet without snapshot output evidence;
4. treat `partial` required planes as complete;
5. skip target-HEAD comparison;
6. return an approved receipt without consuming the approval;
7. accept an arbitrary owner-approval locator;
8. return success on replay.

## Verification commands

```bash
python tools/iron_plan_guard.py verify
python -m pytest -q tests/kernel/test_promotion_authorization.py
python -m pytest -q \
  tests/kernel/test_owner_approval.py \
  tests/kernel/test_effect_leases.py \
  tests/twin/test_fourfold_contracts.py \
  tests/twin/test_wiki_reference.py \
  tests/test_kernel_contracts.py
python -m pytest -q
python -m build
```

CI additionally runs the focused contract batch on Python 3.10 and 3.12 on Linux and Windows under two hash seeds, plus an isolated-wheel import smoke.

## Independent review questions

1. Does the boundary accidentally turn a `PromotionReceipt` into a repository effect?
2. Can candidate/evidence/nomination objects be recombined across revisions or repositories?
3. Is the candidate snapshot identity unambiguously tied to the source artifact rather than only to a graph claim?
4. Is any `partial` semantic state silently elevated to trusted?
5. Is approval consumption ordered after all non-effectful validation and before success is returned?
6. What target-HEAD race remains for the later sealed mutation packet?

## Rollback

Remove `daedalus/kernel/promotion.py`, its exports, focused tests and workflow. No production entrypoint is migrated in this packet.

Iron Plan: **ALIGNED**  
Iron Gate: **0**  
Promotion: **not requested**
