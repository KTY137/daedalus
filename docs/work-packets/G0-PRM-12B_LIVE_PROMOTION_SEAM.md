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

1. the cross-process promotion lock is held;
2. the target ref has just been re-read inside that lock;
3. the supplied `ConsumedOwnerApproval` has been re-authenticated against its
   exact persisted `ApprovalLedger` record using an independently supplied
   owner keyring;
4. candidate, EvidencePacket, base revision, target ref and live target HEAD
   match the persisted approval authority;
5. the exact candidate base equals the authorized live target revision.

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
is an unconditional retirement refusal. Strangler internals are excluded from
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

## Verification specification

Builder tests cover:

- lock acquisition before target resolution and persisted authorization;
- exact call order from locked target read to persisted authorization to the
  integration implementation;
- forwarding of the independent ledger and keyring;
- authorization failure before integration creation;
- stale-base refusal before the legacy retry path;
- multi-candidate and ungated-candidate refusal before lock/worktree mutation;
- lock acquisition failure without reference to an unissued authorization;
- compatibility of the existing non-promotion import surface;
- absence of a second importable legacy module;
- exact retained-resource identity and refusal of mutated bytes;
- retirement of the facade's legacy promotion member and private wildcard
  exports.

A separate AST/conformance review verifies:

- retained-source verification precedes dynamic execution;
- the fail-closed legacy-call adapter;
- the exact locked source order;
- the local registry-anchor alias points to the persisted primitive;
- stale and cardinality fences precede the retained mutation helper;
- the effect-inventory guard anchor remains mechanically observable;
- no merge or push authority is introduced.

The bounded mutation campaign attacks five distinct seams:

1. bypass retained-source integrity verification;
2. replace persisted authorization with the pure primitive;
3. remove the promotion lock;
4. permit stale post-approval regeneration;
5. permit the inherited multi-candidate retry path.

The dedicated workflow requests compile-all, Iron Plan, focused Trust/Gate and
promotion regressions, the mutation campaign, the full repository suite,
Ubuntu/Windows on Python 3.10/3.12 under two hash seeds, and isolated-wheel
import verification. The wheel test also proves the retained source resource is
packaged, identity-bound and non-importable outside the repository checkout.

## Deliberate remaining boundary

This packet does not create or persist a `PromotionReceipt`, consume an Effect
Lease for repository mutation, merge an integration branch, issue an
OwnerApproval, or mark `python.promote_candidates` centrally wired. The next
promotion packet must persist an exact PromotionReceipt only after the sealed
operation reaches its terminal state. Effect-Lease centralization remains a
separate dependent migration.

Repository-wide GitHub Actions issue #67 currently causes hosted jobs to finish
before Step 1 with no step records, logs or artifacts. Such runs are external
infrastructure observations only and cannot satisfy any verification item in
this document. This packet remains draft until exact-head commands execute.
