# G1-IKARUS-07B — Provider executable object registry

## Purpose

Close the next bounded Hermes-parity prerequisite between the non-executing provider pre-admission evidence from G1-IKARUS-07A and a future broker-owned live provider invocation.

The packet adds one fail-closed in-process registry that proves that concrete Python function objects already loaded in the process still correspond to the exact provider targets and repository source digests authenticated by `ProviderExecutablePreAdmissionReceipt`.

This is evidence composition, not a second execution authority.

## Architectural contract

The registry MUST:

- consume an exact, canonically reconstructable `ProviderExecutablePreAdmissionReceipt`;
- accept only exact Python function objects with stable Daedalus module/qualified-name targets;
- resolve each target back to exactly one source file inside the supplied repository root;
- reject symlink/path escape and target/source substitution;
- re-hash the current repository source bytes and compare them to pre-admission evidence;
- compile those exact bytes without executing them and compare normalized code-object digests to the already-loaded functions;
- reject closures and default-bound functions for this first guarded slice rather than silently inheriting ambient executable state;
- make re-registration idempotent only for the exact same function objects;
- re-verify source bytes and loaded bytecode whenever registered evidence is checked again.

The registry MUST NOT:

- dynamically import a provider module;
- execute provider code;
- start, complete, fail, or reconcile an Effect Lease;
- mint runtime/provider/approval/promotion authority;
- expose a public callable resolver to ordinary callers;
- claim the legacy broker callback seam is removed.

## Evidence

`ProviderExecutableObjectAdmissionReceipt` records:

- the exact pre-admission digest and provider/runtime/effect subject identity;
- the authenticated invoke and output-digest targets;
- their repository source digests;
- normalized digests of the exact loaded code objects;
- positive claims only for pre-admission, source-byte, target, and bytecode verification;
- explicit false claims for provider execution, effect authorization, broker invocation, callback removal, automatic re-execution, approval, promotion, gate transition, and closure.

## Adversarial coverage

Focused tests cover:

1. successful registration without invoking either function;
2. provider/target substitution before any execution;
3. repository-source mutation after registration;
4. loaded `__code__` substitution after registration;
5. contradictory authenticated digests for two targets in one source file;
6. conservative refusal of default-bound executable state;
7. re-registration with different function objects;
8. receipt deserialization that attempts to escalate provider-execution authority;
9. subclass/type-smuggling of the pre-admission receipt;
10. AST review proving the module has no dynamic-import, process/network, provider-run, or Effect-start path and no public callable resolver.

## Hermes parity relevance

Hermes-style one-shot model execution requires a real runtime adapter, but Daedalus must not obtain that parity by letting a model/provider callback bypass the canonical Effect and provider-identity authorities. This packet therefore strengthens the existing Daedalus broker path rather than copying a second Hermes execution subsystem.

No Hermes source code is copied. The comparison target is reusable behavior: a selected runtime adapter can eventually be invoked as a bounded one-shot provider while Daedalus retains stronger identity, effect, replay, and evidence semantics.

## Remaining work

This packet deliberately leaves `provider_execution_allowed=false` and `callback_seam_removed=false`.

The next packet should make the canonical runtime broker consume this guarded registry plus the pre-admission/admission evidence as its production executable source, move raw `invoke`/`output_digests` callables behind an explicit test-only compatibility seam, and prove provider-A authority + provider-B executable substitution fails before `begin_effect` and before provider code. Recovery/replay must remain callback-free and inert.

That broker integration is the point at which issue #188 can be closed; this packet alone is not sufficient.
