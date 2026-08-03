# G0-WP-04A — Fourfold-bound promotion authorization

Classification: `ALIGNED`  
Active gate: `Gate 0 — Canonical Kernel`  
Base revision: `9d7a34a2f15a2a21ecb193fb0c56fb23f0c8c34d` (`g0/effect-leases`)  
Primary claim: an authenticated owner capability cannot be consumed for a
candidate unless the candidate source-tree artifact, passed EvidencePacket,
NominationReceipt, complete candidate FourfoldSnapshot, base revision, target
ref and live target HEAD agree exactly.

## Scope

In scope:

- `daedalus/kernel/promotion.py`
- `tests/kernel/test_fourfold_promotion.py`
- the dedicated CI workflow for this packet
- this Work Packet

Forbidden in this packet:

- changing `main` or `experimental`
- applying candidate bytes or creating an integration worktree
- changing `promote_candidates()` or claiming its legacy entrypoint is guarded
- issuing a production owner approval
- changing the adopted Masterplan or its amendment ledger
- changing Fourfold extraction semantics

This is the immutable authorization half of sealed promotion. A dependent
packet must wire the resulting `AuthorizedPromotion` into the existing
integration-worktree adapter and call `assert_authorized_promotion_start()`
inside the promotion lock immediately before any repository mutation.

## Contract chain

```text
candidate source tree in CAS
  -> candidate FourfoldSnapshot (source_revision == candidate digest)
  -> deterministic/independent fourfold.snapshot EvidenceItem
  -> passed EvidencePacket
  -> NominationReceipt
  -> authenticated OwnerApproval
  -> PreparedPromotion
  -> atomic ApprovalLedger consumption
  -> AuthorizedPromotion
  -> live target-HEAD recheck
  -> later integration-worktree adapter
```

`owner_approval_ref` on an approved `PromotionReceipt` must locate the serialized
`AuthorizedPromotion`, not merely the raw signed approval. The retained artifact
therefore includes the one-use SQLite consumption and every candidate,
Fourfold, evidence, nomination, base and target binding.

## Acceptance matrix

| Case | Expected result |
| --- | --- |
| real wiki fixture compiles to four complete planes and exact snapshot evidence | prepare succeeds |
| candidate snapshot revision differs from candidate source-tree digest | refuse |
| evidence subject differs from candidate artifact | refuse |
| missing, duplicate, unverified, failed or digest-mismatched Fourfold item | refuse |
| Fourfold evidence details name a different candidate/repository/revision | refuse |
| nomination differs on candidate, evidence, policy or base revision | refuse |
| signed approval differs on nomination/candidate/evidence/base/ref/HEAD | refuse |
| target HEAD changes before ledger consumption | refuse without consuming |
| approval/nonce is replayed | atomic replay refusal |
| target HEAD changes after consumption and before mutation | refuse; new approval required |
| approved receipt points to anything except the consumed authorization artifact | refuse |

## Adversarial mutation targets

The focused suite must kill at least these targeted mutations:

1. remove the `snapshot.source_revision == candidate_artifact_sha256` check;
2. stop comparing the Fourfold evidence output digest with `snapshot.digest`;
3. stop requiring the EvidencePacket subject to equal the candidate artifact;
4. skip the live target-HEAD check before approval consumption;
5. return a reusable capability instead of consuming the approval ledger;
6. omit the post-consumption target-HEAD recheck;
7. permit a PromotionReceipt to reference the raw approval or another artifact.

Automated mutation scoring remains a later Gate-0 verification packet; this
packet records focused security mutations rather than claiming complete
mutation coverage.

## Verification commands

```bash
python tools/iron_plan_guard.py verify
python -m pytest -q \
  tests/kernel/test_owner_approval.py \
  tests/kernel/test_effect_leases.py \
  tests/kernel/test_fourfold_promotion.py \
  tests/twin/test_fourfold_contracts.py \
  tests/twin/test_projection_verifier.py \
  tests/twin/test_wiki_reference.py
python -m pytest -q
python -m build
```

The dedicated CI matrix runs the focused batch on Python 3.10 and 3.12,
Ubuntu and Windows, with `PYTHONHASHSEED=0` and `123456`; it also runs the full
suite and an isolated-wheel import check.

## Required independent review

1. Can a passed packet bind one candidate while its Fourfold item describes another?
2. Does any path consume the owner capability before every immutable binding is checked?
3. Can target movement be hidden between preparation, consumption and mutation?
4. Does the receipt retain the consumed capability rather than only a signature?
5. Does this packet accidentally make the legacy unguarded promotion path look central?
6. Are complete-plane requirements honest and compatible with Gate-2 partial semantics?

## Residual boundary

This packet does **not** close Gate 0. `python.promote_candidates` remains an
unguarded production entrypoint until a dependent packet changes that callable
to require the consumed capability and records a start receipt before creating
an integration worktree. Isolated Attempts, runtime conformance, Docker
sandboxing, all-entrypoint central wiring and the complete fault matrix also
remain open.

Iron Plan: **ALIGNED**  
Iron Gate: **0**  
Promotion: **not requested**
