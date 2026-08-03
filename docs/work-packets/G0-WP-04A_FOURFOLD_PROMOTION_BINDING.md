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
- additive public exports in `daedalus/kernel/__init__.py`
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
  -> reauthenticate original signed approval against PreparedPromotion
  -> atomic ApprovalLedger consumption
  -> AuthorizedPromotion
  -> ledger-presence and live target-HEAD recheck
  -> later integration-worktree adapter
```

A `PreparedPromotion` is deliberately not independently authoritative. The
consumption call requires the original `OwnerApproval` and keyring again and
verifies every nomination, candidate, evidence, base, ref and HEAD field before
it can enter the replay ledger.

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
| forged PreparedPromotion changes candidate/evidence/base after preparation | refuse during approval reauthentication |
| another valid signed approval is substituted at consumption | refuse without consuming |
| target HEAD changes before ledger consumption | refuse without consuming |
| approval/nonce is replayed | atomic replay refusal |
| ledger consumption is absent at mutation start | refuse |
| target HEAD changes after consumption and before mutation | refuse; new approval required |
| approved receipt points to anything except the consumed authorization artifact | refuse |

## Adversarial counter-review

This pass is separated from builder reasoning but is not an independent human
or separate-model approval. It found and closed four concrete weaknesses:

1. `PreparedPromotion` initially relied on constructor discipline rather than
   validating its own retained values.
2. The pre-mutation check initially rechecked target HEAD but not durable ledger
   presence.
3. The receipt builder initially accepted an arbitrary non-empty target revision.
4. A manually constructed `PreparedPromotion` could initially reach ledger
   consumption without reauthenticating the original signed approval against
   its candidate/evidence/base bindings.

The fourth finding changed the public consumption API: raw `OwnerApproval` and
the verification keyring are mandatory at consumption and are checked again
before `ApprovalLedger.consume()`.

## Adversarial mutation targets

The focused suite is designed to kill at least these targeted mutations:

1. remove the `snapshot.source_revision == candidate_artifact_sha256` check;
2. stop comparing the Fourfold evidence output digest with `snapshot.digest`;
3. stop requiring the EvidencePacket subject to equal the candidate artifact;
4. accept zero or multiple `fourfold.snapshot` evidence items;
5. skip signed-approval reauthentication at PreparedPromotion consumption;
6. skip the live target-HEAD check before approval consumption;
7. return a reusable capability instead of consuming the approval ledger;
8. omit the ledger/target checks immediately before mutation;
9. permit a PromotionReceipt to reference the raw approval or another artifact.

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

The dedicated CI matrix is configured for Python 3.10 and 3.12, Ubuntu and
Windows, with `PYTHONHASHSEED=0` and `123456`; it also contains a full-suite and
isolated-wheel check.

## External CI blocker

At the current branch head, both the dedicated workflow and Iron Plan fail
before the first workflow step. Every job exposes an empty step list and no job
log URL, including an explicit retry. This is tracked in issue `#67`.

Consequences:

- no CI, full-suite, packaging or platform claim is currently accepted;
- the observed workflow failures are not product-code verdicts;
- the dependent mutation adapter packet remains frozen until real workflow
  steps execute;
- static review, test construction and unrelated preparatory work may continue.

## Required independent review

1. Can a passed packet bind one candidate while its Fourfold item describes another?
2. Can any manually assembled PreparedPromotion bypass the signed raw approval?
3. Does any path consume the owner capability before every immutable binding is checked?
4. Can target movement be hidden between preparation, consumption and mutation?
5. Does the receipt retain the consumed capability rather than only a signature?
6. Does this packet accidentally make the legacy unguarded promotion path look central?
7. Are complete-plane requirements honest and compatible with Gate-2 partial semantics?

## Residual boundary

This packet does **not** close Gate 0. `python.promote_candidates` remains an
unguarded production entrypoint until a dependent packet changes that callable
to require the consumed capability and records a start receipt before creating
an integration worktree. Isolated Attempts, runtime conformance, Docker
sandboxing, all-entrypoint central wiring and the complete fault matrix also
remain open.

Iron Plan: **ALIGNED by scope; workflow evidence blocked by #67**  
Iron Gate: **0**  
Promotion: **not requested**
