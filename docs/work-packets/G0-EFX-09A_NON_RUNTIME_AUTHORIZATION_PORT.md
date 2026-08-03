# G0-EFX-09A — Port strict non-runtime effect authorization

## Classification and frozen base

- Classification: `ALIGNED`
- Active gate: Gate 0 — Canonical Kernel
- Exact base branch: `g0/trust-bundle-canonical-wire-linear`
- Exact base revision: `9ad9bab822d625ed3c4516a1353b033279811588`
- Source packet: the isolated sibling design in PR #91
- Promotion: not requested

This packet ports the previously isolated non-runtime Effect-Lease capability
facade onto the selected authenticated release/evidence line. It deliberately
does not change an effect-registry row, issue a lease from ambient authority,
perform an external effect, merge, promote or claim Gate closure.

## Primary acceptance claim

A newly migrated non-runtime production entrypoint can receive one complete
capability object that authenticates and durably consumes an existing signed
Effect Lease without gaining access to caller-controlled clocks or a runtime
trust downgrade.

## Authority retained by the facade

`NonRuntimeEffectAuthorization` retains exactly:

- one signed `EffectLease`;
- its exact `EffectLeaseRequest` and `PolicyDecision`;
- the existing persisted `EffectLeaseLedger` authority;
- an immutable copy of the issuer keyring supplied by composition;
- concrete guard decisions;
- a callable live kill-switch generation authority;
- the exact entrypoint registry used for lease verification.

The facade owns verification, grant, start and terminal timestamps. It reads the
kill-switch generation at every material boundary, rechecks after the durable
start commit before returning `execute=true`, and requires live authority before
publishing a `COMPLETED` terminal receipt or output digests. Failed and cancelled
bookkeeping remains possible after revocation.

The facade refuses every lease with `runtime_id` and every request retaining a
runtime manifest or conformance receipt. Runtime-bearing effects remain solely
under `RuntimeBoundEffectAuthorization`.

## In-scope files

- `daedalus/kernel/authorization.py`
- `daedalus/kernel/__init__.py`
- `tests/kernel/test_effect_authorization.py`
- `scripts/run_non_runtime_authorization_mutations.py`
- `.github/workflows/g0-non-runtime-authorization-port.yml`
- this Work Packet

No other production path is in scope.

## Acceptance and refusal matrix

The focused suite must demonstrate:

1. authenticated grant, durable start, one terminal state and inert exact replay;
2. cross-lease terminal-receipt refusal before ledger mutation;
3. refusal of runtime-bearing leases and runtime evidence;
4. exact request and policy binding plus signature verification;
5. mandatory concrete guards;
6. stale, dynamically advanced and malformed kill-switch authority refusal;
7. durable cancellation when authority disappears after the start commit;
8. refusal of completed output publication after revocation while cancellation
   remains recordable;
9. expired grant/start refusal through facade-owned time;
10. public method signatures expose no caller-controlled lifecycle timestamp;
11. source review confirms no lease issuance, provider execution or promotion
    authority exists in the facade.

The bounded mutation campaign attacks twelve corresponding seams: runtime
boundary, request binding, guard presence, live generation, authentication,
post-start revocation, completed-output authority, receipt ownership and four
caller-clock regressions.

## Required verification

When executable infrastructure is available, the packet requires:

- Iron Plan verification;
- compile-all;
- focused parent and facade tests;
- all bounded mutants killed with byte-exact restoration;
- full repository pytest;
- Ubuntu and Windows on Python 3.10 and 3.12 with two hash seeds;
- isolated wheel installation and import outside the checkout.

A model review or source inspection is advisory and cannot replace these runs.

## Deliberate remaining boundary

This packet does not itself centralize any production entrypoint. Each actual
migration remains a separate Work Packet that must consume this capability,
commit the start receipt before work, treat `execute=false` as inert replay and
persist an exact terminal receipt for every known outcome. Runtime-bearing
providers remain on the runtime-bound path.

## External infrastructure blocker

GitHub issue #67 currently records hosted jobs terminating before Step 1 with no
logs or artifacts. Such runs are infrastructure observations only and must not
be represented as CI, mutation, platform, packaging or Gate evidence. This
packet remains draft until its exact-head commands execute.
