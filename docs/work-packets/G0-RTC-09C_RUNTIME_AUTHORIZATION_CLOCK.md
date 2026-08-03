# G0-RTC-09C — Runtime authorization clock ownership

## Purpose

Remove caller-controlled time from the runtime-bound production capability and
from the provider broker's trust recheck calls.

The lower-level `verify_runtime_bound_effect_lease(..., now=...)` function keeps
its explicit timestamp because deterministic contract, replay, expiry and fault
tests require it. `RuntimeBoundEffectAuthorization`, however, is the capability
consumed by production entrypoints. Its public `verify()` method must use the
facade-owned UTC clock so an effectful caller cannot backdate verification after
lease or runtime-evidence expiry.

This packet is stacked on `G0-RTC-09B`. It does not issue a capability, perform a
provider effect, change an effect-registry row, merge, promote or close Gate 0.

## Boundary change

`RuntimeBoundEffectAuthorization` now has a private `_verify_at(instant)` seam.
Only methods owned by the capability may supply that instant:

- public `verify()` samples `_utc_now()`;
- `grant()` samples one instant, verifies at it and persists grant at the same instant;
- `begin_effect()` samples one pre-start instant, verifies at it and persists the durable start at that same instant;
- the post-start trust check samples a fresh facade-owned instant before returning `execute=true`.

The provider broker calls `authorization.verify()` after invocation and again
before terminal completion. It can no longer supply a historical timestamp.
The existing SQLite terminal fence still owns its own current expiry check and
serializes successful completion against quarantine and evidence rotation.

## Adversarial evidence

The focused tests prove:

- the public verification signature contains only `self`;
- a capability observed after lease expiry refuses verification;
- passing a historical `now=` to the public facade raises `TypeError` rather than authenticating stale trust;
- grant and start use the private clocked seam with one exact pre-operation instant;
- the provider broker contains exactly two clockless trust rechecks and no `verify(now=...)` call;
- existing admission, durable-start, terminal-ownership and provider-broker suites remain in the requested batch.

A bounded mutation campaign applies two isolated regressions after a green
baseline:

1. reintroduce a public caller-controlled verification parameter;
2. make both provider-broker trust rechecks supply `_utc_now()` directly.

Both mutants must be killed and all target bytes restored.

## Review boundary

This packet is a source/capability hardening review. Its tests and AST checks are
not human architecture/security review, RuntimeConformanceReceipt, OwnerApproval
or operational Gate evidence. Exact-head CI must execute on the final selected
linear candidate before the packet can contribute evidence.

## External blocker

GitHub Actions issue #67 currently causes hosted jobs to terminate before Step 1
with no logs or artifacts. Such runs establish no Python-version, platform,
package, mutation or product verdict.

## Gate state

- Iron Plan: aligned by scope; exact-head execution required
- Active gate: Gate 0
- Promotion: not requested
- Gate closure: not claimed
