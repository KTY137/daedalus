# G0-PRM-25I — Promotion Public Boundary Installer

## Scope

This packet is stacked directly on `G0-PRM-25H` at exact parent
`5f01a5cfe456cf7340c89d520a7577cc87cd524d`. It prepares the narrow live
strangler needed to make the persisted Effect-Lease lifecycle the only public
route to the retained promotion implementation. It does not yet append the
installer call to `daedalus.kairos.gated_writes`, change the canonical effect
registry, issue OwnerApproval, execute promotion, merge, or promote.

## Boundary design

`install_promotion_effect_public_boundary(globals())` is intended to run only
after the existing sealed promotion callable and the manager audit/replay
wrappers have been constructed. The installer:

1. verifies that the lifecycle module and the supplied module namespace are the
   same canonical `gated_writes` module;
2. captures the current sealed public delegate exactly once;
3. replaces the lifecycle module's direct module reference with a minimal
   immutable facade;
4. permits the facade to enter the retained delegate only while a private
   `ContextVar` capability is active;
5. replaces the historic public name with a compatibility facade that refuses
   calls lacking `promotion_effect_capability` before the delegate scope opens;
6. preserves inert name, module, documentation, annotations, and visible
   signature metadata without publishing the effectful delegate through
   `__wrapped__`;
7. persists a deterministic machine-readable installation receipt and refuses
   marker, public-callable, namespace, or facade substitution on replay.

The installer itself performs no repository effect. The retained delegate is
not attached to the public facade, its receipt, or the public export set.

## Adversarial batch

Prepared tests cover exact installation, deterministic receipt reconstruction,
missing capability refusal, one exact lifecycle/delegate call, direct delegate
and direct lifecycle bypasses, malformed namespace/lifecycle state, forged
installation markers, public entrypoint and facade substitution, malformed
candidate iterators, wrong-capability failures, exception cleanup, context
isolation across threads, mutated receipt projections, and post-install
lifecycle callable substitution.

A separate AST/source review requires the module to remain inert, prohibits
Git, subprocess, SQLite, worktree, OwnerApproval, Event-Store, merge and ref
update authority, checks capability-before-scope ordering, requires one guarded
delegate call and one lifecycle call, and rejects `functools.wraps` or a public
`__wrapped__` bypass.

The bounded mutation campaign contains eight unique seams:

- false direct-delegate safety claim;
- namespace substitution acceptance;
- capability-presence guard removal;
- direct-delegate scope guard removal;
- invalid scope token;
- leaked scope after return/failure;
- exposed `__wrapped__` delegate;
- ignored public-entrypoint tampering.

## Honest boundary after this packet

The installer is deliberately not invoked by the live module in this packet.
A dependent small packet must append the one installer call after the current
manager wrappers, verify old direct calls fail closed, inventory every
production caller, and prove no retained alias or import path reaches the
sealed delegate without the outer lifecycle. Only after exact runtime,
conformance, Docker-sandbox and effect-registry composition may the canonical
promotion row move from `local_guards` to `central`.

Repository Actions issue #67 still prevents hosted jobs from reaching Step 1.
Until a real checkout job records steps, no exact-head test, mutation,
full-suite, packaging, platform-matrix, Iron Plan, or Gate evidence is claimed.
The source, tests, review, mutation fixtures and documentation remain useful
independent preparation.

Iron Plan: **ALIGNED BY SCOPE; EXACT-HEAD EXECUTION REQUIRED**  
Iron Gate: **0**  
Live installation: **not performed**  
OwnerApproval: **not issued**  
Promotion: **not requested**
