# G0-WP-03 — Persisted Effect Leases

## Scope

This Work Packet adds the authorization and persistence boundary that must
exist before a central runtime entrypoint may perform an external effect. It
does **not** migrate legacy callers and does not claim that Gate 0 is closed.
A lease may be issued only for a registry row already marked `CENTRAL`; current
`UNGUARDED` and `INVENTORY_ONLY` rows therefore remain blocked rather than
being silently legitimized by the new API.

The package continues the strangler Filetree migration under
`daedalus/kernel/`. `EffectLeaseRequest` and `EffectLease` inherit the existing
`CanonicalContract`; `EffectScope`, `PolicyDecision`, canonical JSON, digests
and provenance remain defined by the existing Gate-0 wire language.

## Contract chain

```text
EffectLeaseRequest
  -> exact allow PolicyDecision
  -> exact CENTRAL EntrypointSpec and registry digest
  -> signed EffectLease
  -> authenticated persisted grant
  -> atomic STARTED receipt before external effect
  -> one of COMPLETED | FAILED | CANCELLED
```

An `EffectLease` binds:

- the request and policy-decision identities and digests;
- the exact entrypoint registry digest;
- entrypoint and declared effect set;
- bounded `EffectScope`;
- idempotency namespace;
- kill-switch generation;
- runtime manifest and conformance digests when a runtime is involved;
- issuer key, issue time, expiry and provenance;
- an HMAC-SHA256 signature using an external kernel key.

## Persistence and replay

`EffectLeaseLedger` uses SQLite with WAL, `synchronous=FULL`, foreign keys and
`BEGIN IMMEDIATE` transactions. The lease is authenticated before it enters
the ledger. An execution start is recorded before the caller receives
`execute=true`.

Repeating the same execution and idempotency key returns the original start
receipt with `execute=false`. Reuse across another lease or a changed scope is
refused. Active execution count is checked atomically against
`EffectScope.max_concurrency`. Lease revocation blocks new starts; terminal
records remain possible so cleanup and failure evidence are not lost.

## Scope enforcement

The execution request may only narrow a lease:

- effects are a subset of the leased effects;
- writable paths are compared by POSIX path components, not string prefixes;
- egress endpoints, tools and secret references are exact subsets;
- requested spend cannot exceed the lease ceiling;
- kill-switch reference and generation must match;
- effect-specific dimensions must be explicit.

This is a lexical workspace boundary. Symlink, mount and real-filesystem
containment remain the responsibility of the later sandbox packet; the lease
layer never claims to be an OS sandbox.

## Adversarial review

The batch includes negative and concurrent coverage for:

- non-central and unknown entrypoints;
- stale registry, policy, request, revision and kill-switch bindings;
- signature tampering and unknown issuer keys;
- future, expired and overlong leases;
- unauthenticated grant attempts;
- start without a persisted lease;
- path-prefix attacks and traversal;
- effect, path, tool, endpoint, secret and cost escalation;
- guard denial before execution persistence;
- replay with changed scope or another lease;
- concurrent starts above the active-slot ceiling;
- revocation, duplicate terminal transitions and corrupted SQLite;
- expiry between initial verification and the atomic start transaction.

Focused mutation runs removed the TTL check, replaced component containment
with string-prefix containment, removed effect-subset validation and changed a
replay result to `execute=true`. Every mutation was killed by the focused
suite.

## Local verification

- Iron Plan verification: passed.
- focused Effect Lease tests: 24 passed.
- Gate/Trust/Fault batch including OwnerApproval: 133 passed after this packet.
- package compilation: passed.
- isolated wheel verification: required in CI.

## Deliberate remaining blockers

No existing production entrypoint is changed to `CENTRAL` by this packet.
`python.offload`, `python.promote_candidates`, providers, bridges and legacy
CLI starts retain their current registry classifications. The next packets
must migrate one bounded caller at a time, preserve intent-before-effect and
prove Primary Checkout integrity. Runtime conformance and Docker containment
also remain separate required Gate-0 packets.
