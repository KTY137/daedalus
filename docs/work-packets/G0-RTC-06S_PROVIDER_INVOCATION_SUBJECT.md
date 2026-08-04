# G0-RTC-06S — Exact Provider Invocation Subject

## Exact parent and narrow scope

This packet stacks directly on `g0/provider-observation-authority-linear` at
`d8910f435a4e9886c33748d6e056ac497d6a9aad`. It is a preparatory, non-executing
response to issue #188. It does not modify the broker, recovery, `main`,
`experimental`, merge state, promotion state, OwnerApproval, or any Gate state.

The packet adds one immutable `ProviderInvocationSubject`. It gives the next
integration packet a canonical object whose digest can be signed by the provider
observation authority and compared with the exact adapter selected before an
effect start.

## Bound identity

The subject binds:

- external provider identity;
- adapter identity;
- adapter artifact or source-tree digest;
- canonical non-secret adapter configuration digest;
- entrypoint and runtime identity;
- execution ID and idempotency key;
- execution-request digest;
- Effect-Lease digest;
- source revision.

The mapping has an exact field set, canonical identifier/digest/revision
validation, deterministic serialization and a content-addressed digest. No digest
is caller-supplied.

## Deliberate non-authority

This module imports no network, process or provider execution facility. The
subject contains no callback and exposes no `invoke` or `execute` method. It is
not an Effect Lease, runtime capability, provider observation, registry entry,
or permission to contact an external system.

That boundary is deliberate. A later short packet must bind the subject digest
into the signed observation authority and replace the exact production broker's
loose callback seam with an authenticated adapter selection. Until that happens,
issue #188 remains open and no claim is made that the provider named in retained
evidence is mechanically the exact implementation invoked.

## Adversarial verification prepared

Builder tests cover exact mapping round-trip, stable digest construction,
digest sensitivity for every field, missing/extra fields, malformed identifiers,
invalid digests, invalid revisions and absence of execution methods.

A separate AST/source review checks that the module imports no network/process
execution roots, calls no dynamic execution primitives, contains no `Callable`
seam, exports only the identity contract, carries every required binding
dimension, and computes its digest canonically rather than accepting one from a
caller.

CI requests two hash seeds on Ubuntu and Windows with Python 3.10 and 3.12,
Iron Plan verification, the focused tests, the full suite, package build and an
isolated-wheel import.

## Evidence and remaining boundary

No source inspection or LLM statement is hard evidence. The automation runtime
cannot execute the exact private checkout. GitHub Actions issue #67 continues to
terminate hosted jobs before Step 1, with no checkout, logs or artifacts.

The dependent broker/authority integration, provider/adapter substitution tests,
bounded mutations, caller migration and issue #189's persistence-entrypoint
inventory remain separate work. No automatic merge, promotion, OwnerApproval or
Gate transition is authorized.
