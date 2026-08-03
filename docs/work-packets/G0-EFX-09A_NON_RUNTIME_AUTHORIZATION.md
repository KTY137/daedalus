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
- the issuer keyring supplied by the caller;
- concrete guard decisions;
- the current kill-switch generation;
- the exact entrypoint registry used for verification.

It delegates signature, revision, registry, scope, expiry, replay, concurrency
and terminal-state enforcement to the existing `daedalus.kernel.effects`
authority. It does not mint a lease or execute provider, subprocess, filesystem,
repository or promotion operations.

## Runtime separation

A lease with `runtime_id` or a request carrying runtime manifest/conformance
evidence is refused at construction. Runtime-bearing entrypoints must use
`RuntimeBoundEffectAuthorization`, which adds live authenticated runtime-trust
checks before grant and start. The generic path may not be used as a downgrade.

## Verification requested

The focused suite covers:

- authenticated grant, durable start, immutable terminal state and exact replay;
- runtime-path downgrade refusal;
- request/lease binding mismatch;
- signature tampering;
- stale kill-switch generation;
- missing guard evidence;
- an AST counter-review that forbids lease issuance, promotion and external run
  calls in the facade.

The bounded mutation campaign attacks runtime downgrade refusal, request binding,
guard evidence and lease authentication. CI requests Ubuntu and Windows,
Python 3.10 and 3.12, two hash seeds, Iron Plan verification, compile-all,
focused parent/facade tests, mutation execution, the repository full suite and
an isolated-wheel import.

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
