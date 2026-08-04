# G0-PRM-21 — Live Promotion Execution on Strict Projection

## Scope

This packet composes the live manual promotion seam with the hardened raw Event-Store projection from `G0-PRM-20`. It is stacked directly on exact head `72487d8572f4e6599f9144c4d2b3256d304d9dd5` and selectively ports the already separated live-accounting work instead of merging or enlarging its sibling draft.

It creates no OwnerApproval, performs no automatic merge or promotion, and does not claim Gate-0 closure.

## Boundary sequence

The live seam now requires an injected `PromotionExecutionLedger` in addition to the persisted ApprovalLedger and owner keyring. It:

1. snapshots exactly one candidate and authenticates the persisted owner capability without repository effects;
2. fingerprints the source-visible primary checkout;
3. commits `PromotionExecutionStart` before promotion-lock or worktree mutation;
4. returns an exact retained terminal report on replay;
5. refuses automatic re-execution while a start is pending reconciliation;
6. re-reads live target HEAD and re-authenticates the same capability under the promotion lock;
7. requires the live authorization digest and candidate base to match the persisted start;
8. records success, refusal or fault with the exact integration branch/revision and after-fingerprint.

All replay and pending reads flow through the strict raw projection inherited from `G0-PRM-20`. Duplicate JSON keys, noncanonical bytes, payload-digest substitution, invalid event sequences, reserved-key collisions and same-name weakened index substitution therefore fail before live replay material is trusted.

## Fault discipline

Entry into the retained mutation implementation is explicit. A known error before that point may be retained as refusal. Every known or unexpected error after entry is retained as fault. A malformed or oversized returned report is never copied into canonical evidence; only bounded known identities and the exception class are retained.

The primary checkout fingerprint follows no symlink, rejects non-regular entries, binds paths, bytes and executable bits, excludes only `.git` and `.daedalus`, and requires two stable observations. Primary-checkout drift cannot be represented as success.

## Adversarial verification prepared

The combined matrix retains the independent raw-reader/index counter-review and adds live-seam review for:

- missing execution authority before effects;
- persisted start before lock entry;
- exact terminal replay and pending restart;
- substituted or stale live authorization;
- post-mutation revision and report faults;
- primary-checkout mutation;
- redirected checkout roots and symlinks;
- raw projection corruption and index substitution.

Three bounded mutation campaigns cover the Core execution ledger, strict projection and live seam. The workflow also requests Linux/Windows, Python 3.10/3.12, two hash seeds, full suite and isolated-wheel checks.

## Remaining boundary

The canonical effect inventory still needs a separate small packet for the strengthened promotion seam and execution begin/complete writes. The promotion path also remains non-central until EffectLease, current RuntimeConformanceReceipt and Docker-sandbox composition are mechanically enforced. Exact-head CI and independent human review remain mandatory.

Iron Plan: **ALIGNED BY SCOPE**  
Active gate: **Gate 0**  
Promotion: **not requested**
