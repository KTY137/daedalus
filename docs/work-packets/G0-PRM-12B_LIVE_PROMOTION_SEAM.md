# G0-PRM-12B — Seal the Live Promotion Seam

## Gate and parent

- Active gate: Gate 0
- Exact parent: `710ca96784be8dd5e75ad78ef7ecf58427f88f11`
- Parent branch: `g0/persisted-promotion-authorization-linear`
- Promotion: not requested

## Acceptance claim

The public `daedalus.kairos.gated_writes.promote_candidates` mutation seam may
enter the integration-worktree implementation only while all of the following
are simultaneously true:

1. the submitted candidate sequence has been copied into one immutable local
   promotion snapshot before any worktree manager or lock is created;
2. each snapshot contains a canonical `AttemptResult`, canonical
   `PatchArtifact`, one real passed terminal `GateResult`, exact matching
   task/branch/base identities and SHA-256 that is recomputed from the exact
   patch bytes later passed to `git apply`;
3. the cross-process promotion lock is held;
4. the target ref has just been re-read inside that lock;
5. the supplied `ConsumedOwnerApproval` has been re-authenticated against its
   exact persisted `ApprovalLedger` record using an independently supplied
   owner keyring;
6. candidate, EvidencePacket, base revision, target ref and live target HEAD
   match the persisted approval authority;
7. the exact candidate base equals the authorized live target revision;
8. the retained integration implementation receives the same immutable local
   snapshot used for authorization, never the caller's mutable candidate
   object.

Any mismatch returns a structured refusal before integration-worktree creation.
No integration branch is merged automatically.

## Compatibility strangler

The previous large Kairos gating implementation is retained byte-identically as
the non-importable package resource
`daedalus/kairos/_gated_writes_legacy.py.src`. Before executing those bytes, the
public module recomputes their exact Git blob identity and compares it with the
reviewed blob `e31d24ec67f7c208ace34f5dd2e9fefe4e654a86`. Packaging drift or a
substituted resource therefore fails during import rather than becoming an
unreviewed effectful implementation.

After that verification, the public module executes the retained source into
its own canonical namespace and deletes the historical `promote_candidates`
definition before installing the sealed replacement. Existing classes,
functions, import paths, pickle module names and retained function globals
therefore remain `daedalus.kairos.gated_writes`; no second runtime module or
Big-Bang rename is introduced.

The resource is not a Python module, is excluded from the static `*.py` effect
scan, and cannot be imported as `daedalus.kairos._gated_writes_legacy`. No
reference to the historical promotion function is retained. A small internal
facade exists only so monkeypatch-based compatibility tests can reach the exact
retained helpers used by the sealed callable; its `promote_candidates` member
is an unconditional retirement refusal. Strangler internals, including the
kernel-owned candidate snapshot validator, remain private and are excluded from
`__all__`.

The public source retains the historical `authorize_promotion` registry anchor
by binding that local name to `authorize_persisted_promotion` inside the lock.
The registry wording and anchor should move to the stronger canonical name in a
later dedicated inventory packet rather than being mixed into this mutation
batch.

Historical callers that omit `approval_ledger` or `owner_keyring` remain call
compatible only through a refusal adapter. The adapter may reproduce a precise
stale-head or candidate-mismatch diagnostic with the pure binding primitive,
but even a successful diagnostic preflight is converted into a persisted
owner-authority refusal and cannot acquire a lock or create a worktree.

## Adversarial finding: authorized bytes versus regeneration

The inherited multi-candidate path regenerates a candidate when its base becomes
stale after an earlier candidate lands in the integration branch. That behavior
is appropriate during proposal construction, but not after OwnerApproval: the
regenerated patch has a new identity that was never present in the approved
candidate batch or EvidencePacket.

This packet therefore narrows the legacy live seam to exactly one clean,
non-empty candidate and requires its captured base to equal the authorized live
target HEAD. A stale candidate is refused with an explicit requirement for new
evidence and a new OwnerApproval. Gate 1's two WorkItems must converge into one
combined CAS Candidate Source Tree before the later manual promotion boundary;
they must not use legacy post-approval regeneration.

## Adversarial finding: declared digest versus applied material

A later context-separated builder counter-review found four connected trust
failures in the pre-hardening code:

1. `candidate_batch_sha256()` accepted the `PatchArtifact.diff_sha256` field
   without recomputing it from `diff_bytes`, while the retained mutation path
   later applied `diff_bytes`. A constructed artifact could therefore bind the
   owner's approval to one declared digest and apply different bytes.
2. `AttemptResult.base_revision` could disagree with
   `PatchArtifact.base_revision`. The authorization digest used the artifact
   base, while integration-worktree creation used the result base.
3. a caller-created `AttemptResult(state="clean")` without a real passed
   terminal gate could enter the digest path.
4. `GatedCandidate` is a mutable compatibility dataclass. A caller thread could
   replace its `result` after authorization but before `_promote_locked`
   re-read the candidate.

The kernel now validates and copies one exact candidate snapshot. It recomputes
SHA-256 over the immutable patch bytes, checks result/artifact task, branch and
base equality, requires a real passed non-cancelled/non-timeout `GateResult`,
normalizes exact revisions, rejects malformed or duplicate changed-path
metadata and passes the same frozen snapshot to authentication and mutation.
The public Kairos module imports this validator under a private alias so the
hardening does not create a second public API surface.

This counter-review was performed from a separate adversarial context by the
same automation/model instance. It is builder-side evidence and may share blind
spots with the implementation. It does not satisfy the required independent
external review.

## Verification specification

Builder tests cover:

- lock acquisition before target resolution and persisted authorization;
- exact call order from locked target read to persisted authorization to the
  integration implementation;
- forwarding of the independent ledger and keyring;
- authorization failure before integration creation;
- stale-base refusal before the legacy retry path;
- multi-candidate and ungated-candidate refusal before lock/worktree mutation;
- recomputation of candidate SHA-256 from the exact patch bytes;
- refusal of result/artifact base, task and branch splits;
- refusal of fabricated clean results without a passed terminal gate;
- refusal of malformed or duplicate changed-path metadata;
- immunity to caller-side candidate-result replacement after authorization;
- lock acquisition failure without reference to an unissued authorization;
- compatibility of the existing non-promotion import surface and absence of a
  newly exported snapshot helper;
- absence of a second importable legacy module;
- exact retained-resource identity and refusal of mutated bytes;
- retirement of the facade's legacy promotion member and private wildcard
  exports.

A context-separated AST/conformance counter-review verifies:

- retained-source verification precedes dynamic execution;
- the fail-closed legacy-call adapter;
- the exact locked source order;
- snapshot construction occurs before manager/lock construction;
- the same sealed snapshot is passed to authorization and retained mutation;
- the local registry-anchor alias points to the persisted primitive;
- stale and cardinality fences precede the retained mutation helper;
- the effect-inventory guard anchor remains mechanically observable;
- no merge or push authority is introduced.

The bounded mutation campaign attacks nine distinct seams:

1. bypass retained-source integrity verification;
2. replace persisted authorization with the pure primitive;
3. remove the promotion lock;
4. permit stale post-approval regeneration;
5. permit the inherited multi-candidate retry path;
6. authorize the snapshot but apply the caller's mutable original candidate;
7. trust the declared patch digest instead of the exact patch bytes;
8. permit `AttemptResult` and `PatchArtifact` to name different bases;
9. accept a candidate without a real passed terminal gate.

The dedicated workflow requests compile-all, Iron Plan, focused Trust/Gate and
promotion regressions, the mutation campaign, the full repository suite,
Ubuntu/Windows on Python 3.10/3.12 under two hash seeds, and isolated-wheel
import verification. The wheel test also proves the retained source resource is
packaged, identity-bound and non-importable outside the repository checkout.

## Deliberate remaining boundary

This packet does not independently parse patch bytes to compare their complete
path set with `changed_paths`; the exact patch bytes themselves are now
owner-bound and the retained `git apply` path remains authoritative. A later
Candidate Source Tree packet should eliminate this patch-metadata duality
entirely. Until then, changed-path metadata is treated as reviewed descriptive
binding, not as a filesystem confinement proof.

This packet also does not create or persist a `PromotionReceipt`, consume an
Effect Lease for repository mutation, merge an integration branch, issue an
OwnerApproval, or mark `python.promote_candidates` centrally wired. The next
promotion packet must persist an exact PromotionReceipt only after the sealed
operation reaches its terminal state. Effect-Lease centralization remains a
separate dependent migration.

Repository-wide GitHub Actions issue #67 currently causes hosted jobs to finish
before Step 1 with no step records, logs or artifacts. Such runs are external
infrastructure observations only and cannot satisfy any verification item in
this document. This packet remains draft until exact-head commands execute and
an independent external review is completed.
