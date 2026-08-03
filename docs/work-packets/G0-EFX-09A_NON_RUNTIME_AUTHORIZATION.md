# G0-EFX-09A — Strict non-runtime effect authorization

## Purpose

This packet adds the narrow capability facade that later non-runtime production
entrypoints must consume while they are migrated from `LOCAL_GUARDS` or
`INVENTORY_ONLY` to the persisted Effect Lease boundary. It is additive and
keeps the existing `LeasedEffectAuthorization` import compatible during the
strangler migration.

The packet does not mark any registry row `CENTRAL`, perform an external effect,
issue a lease from ambient credentials, promote a candidate, merge a branch or
claim Gate 0 closure.

## Authority

`NonRuntimeEffectAuthorization` retains exactly:

- one signed `EffectLease`;
- the exact `EffectLeaseRequest` and `PolicyDecision` bound by that lease;
- the persisted `EffectLeaseLedger`;
- an immutable copy of the issuer keyring supplied by the trusted composition
  boundary;
- concrete guard decisions;
- a callable live kill-switch generation authority;
- the exact entrypoint registry used for verification.

It delegates signature, revision, registry, scope, expiry, replay, concurrency
and terminal-state enforcement to the existing `daedalus.kernel.effects`
authority. It does not mint a lease or execute provider, subprocess, filesystem,
repository or promotion operations.

The facade owns all authoritative lifecycle timestamps. Its public verification,
grant, start and terminal methods accept no caller-supplied clock. This prevents
a production caller from backdating a grant/start to keep an expired lease
usable or from forging terminal chronology. Explicit timestamps remain only on
the lower-level ledger for deterministic contract and fault tests.

The kill-switch generation is not retained as a construction-time integer. The
facade reads the live authority at construction for fail-fast validation and
again at every verification, grant and start boundary. A successful durable
start is rechecked before `execute=true` can escape; loss of authority at that
point records `CANCELLED` before the exception is returned. `COMPLETED` terminal
receipts and output digests also require live authority, while `FAILED` and
`CANCELLED` remain recordable after revocation.

## Runtime separation

A lease with `runtime_id` or a request carrying runtime manifest/conformance
evidence is refused at construction. Runtime-bearing entrypoints must use
`RuntimeBoundEffectAuthorization`, which adds live authenticated runtime-trust
checks before grant and start. The generic path may not be used as a downgrade.

## Independent counter-review findings

The first builder revision delegated terminalization directly to the shared
ledger. Although the ledger validates that a start receipt exists, a capability
holding the same ledger could have been handed a valid start receipt belonging
to another lease. The facade now requires
`start_receipt.lease_sha256 == authorization.lease.digest` before terminalizing.
A focused regression test and dedicated mutant pin this cross-capability
boundary.

A later authority review found that the facade publicly accepted `now`,
`granted_at`, `started_at` and `finished_at`. Those parameters are appropriate
for deterministic low-level ledger tests but are unsafe on the production
capability facade: an effectful caller could select a still-valid historical
instant after real expiry. The public clock parameters were removed. Tests now
prove expiry using the facade-owned clock and inspect every public method
signature. Four additional mutants attempt to reintroduce caller-controlled
verification, grant, start and terminal timestamps.

The latest separate review found a revocation gap: the facade captured
`current_kill_switch_generation` as an immutable integer. A long-lived
capability could therefore continue presenting the lease's old generation after
the real kill switch advanced. The correction replaces the cached value with a
live reader, rechecks after durable start, and fences successful terminal/output
publication. Tests exercise revocation before start, between the committed
start receipt and authority release, and before completion. Mutants attempt to
cache the signed lease generation, remove the post-start fence and complete
under revoked authority.

These reviews are separate source/authority perspectives, not human security
approval and not Gate evidence by themselves.

## Verification requested

The focused suite covers:

- authenticated grant, durable start, immutable terminal state and exact replay;
- cross-lease terminal-receipt refusal;
- runtime-path downgrade refusal;
- request/lease binding mismatch;
- signature tampering;
- stale and dynamically advanced kill-switch generations;
- malformed live generation authority values;
- revocation between durable start and effect-authority release;
- completed-output refusal after revocation while cancellation remains durable;
- missing guard evidence;
- expired grant and start refusal using the facade-owned clock;
- exact public signatures with no caller-controlled lifecycle timestamps;
- an AST counter-review that forbids lease issuance, promotion and external run
  calls in the facade.

The bounded mutation campaign attacks runtime downgrade refusal, request binding,
guard evidence, live generation freshness, lease authentication, the post-start
revocation fence, completed-output fencing, cross-lease terminalization and four
caller-clock regressions. CI requests Ubuntu and Windows, Python 3.10 and 3.12,
two hash seeds, Iron Plan verification, compile-all, focused parent/facade tests,
mutation execution, the repository full suite and an isolated-wheel import.

## Dependent migration path

After this packet is verified, each non-runtime production entrypoint remains a
separate Work Packet. A row may become `CENTRAL` only when its public effectful
path consumes this capability, commits the start receipt before work, handles
`execute=false` without repeating the effect, and persists a terminal receipt
on every known outcome.

Likely dependent packets include sealed promotion, file-bridge publication and
worktree operations. Provider rows with runtime identities remain on the
runtime-bound path instead.

## Current external blocker

Repository-hosted jobs are currently affected by the exact-head runner problem
tracked in issue #67: jobs can terminate before Step 1 with no logs. Such a run
is infrastructure evidence only and cannot verify this packet. The branch and
PR must remain draft until real commands execute and the requested checks are
green.

## Gate state

- Iron Plan: aligned by scope; exact-head execution required
- Active gate: Gate 0
- Promotion: not requested
- Gate closure: not claimed
