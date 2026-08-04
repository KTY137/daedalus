# G0-PRM-25D — Read-only Promotion Replay Projection

## Scope and parent

This Work Packet is stacked directly on the typed promotion effect-capability
packet:

- parent branch: `g0/promotion-effect-capability-linear`;
- parent revision: `4c5c1f4293d40ae073a267c1c5bcb4e883f6fde3`;
- parent draft PR: `#145`.

It adds one read-only restart projection over an already-open
`PromotionExecutionLedger`. It neither changes the live Kairos seam nor grants a
second effect.

## Why this projection is required

The persisted promotion execution ledger already distinguishes three states:

1. no start exists;
2. a start exists and requires reconciliation;
3. a terminal receipt exists and is replayable.

Its public `begin()` operation is intentionally writer-shaped: it accepts a
primary-checkout fingerprint and can create the missing start. That is correct at
the original mutation boundary but unsafe as the read path for a replayed
Effect Lease. Exact top-level replay must not accept caller-authored checkout
material and must not create another promotion start.

`inspect_promotion_execution()` therefore:

- accepts only the selected canonical `PromotionExecutionLedger` and one
  `PromotionAuthorization`;
- validates the complete authorization before Event-Store lookup;
- looks up only the authorization's promotion identity;
- returns `None` when no start exists;
- reuses the ledger's strict canonical start decoder;
- compares authorization, approval consumption, candidate, EvidencePacket,
  source revision, target ref and authorized target revision before decoding or
  exposing retained terminal report material;
- reuses the strict terminal decoder;
- returns the existing `PromotionExecutionBeginResult` with `execute=false`.

It accepts no start ID, checkout fingerprint, timestamp, path, ledger key,
policy decision or effect authority.

## Authority separation

The new module does not:

- open or create an Event Store;
- call `PromotionExecutionLedger.begin()` or `.complete()`;
- call `record_intent`, `mark_completed` or `mark_failed`;
- issue or consume OwnerApproval;
- issue or start an Effect Lease;
- invoke Git, Docker, worktree management or `promote_candidates`;
- reconcile a pending attempt or automatically re-execute it.

The package-internal projection deliberately reuses `_authorization_payload`,
`_intent_for`, `_decode_start` and `_decode_completion` so there is no second
wire parser or persistence authority.

## Adversarial batch

Builder and counter-review tests cover:

- absent, pending and terminal states;
- no caller-supplied primary-checkout fingerprint on replay;
- candidate, evidence, approval, revision, target and target-HEAD substitution;
- changed promotion identity without cross-reading another report;
- malformed authorization before lookup;
- corrupt persisted start bytes;
- monkeypatched writer methods proving the projection remains read-only;
- AST/source assertions excluding persistence, Git, sandbox and promotion calls;
- ordering that binds the complete start before terminal decoding.

The bounded mutation runner attacks authorization validation, candidate,
evidence and approval bindings, terminal decoding order and `execute=false`.

## Honest migration state

This packet does not wire the top-level Effect Lease into the live promotion
seam. A dependent packet must define the exact restart composition:

- fresh Effect-Lease start permits the existing live promotion lifecycle;
- completed Effect-Lease replay may return only an exactly bound retained
  terminal;
- pending promotion state must remain pending reconciliation and must not be
  automatically re-executed;
- missing or contradictory promotion state under an Effect-Lease replay must
  fail closed.

The canonical promotion row remains `local_guards`. No centralization, merge,
promotion, Gate transition or OwnerApproval is requested.

## Verification boundary

Exact-head focused, mutation, full-suite, platform and isolated-wheel execution
is requested by the dedicated workflow. GitHub Actions issue `#67` remains an
external infrastructure blocker while jobs terminate before Step 1 with no logs
or artifacts. Such runs are observations only, not passing or failing product
evidence.
