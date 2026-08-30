# G1-IKARUS-07D1 — Canonical provider invocation payload

Status: implementation packet  
Gate: Gate 1 — Renovation ignition slice  
Depends on: G1-IKARUS-07S / #277  
Parent blocker: #188  
Design finding: #278

## Purpose

Remove the need to encode provider-specific per-call semantics in Python closure state.

The real Claude adapter currently enters `run_runtime_provider(...)` through lambdas that capture objective, workspace, paths, model, timeout and output-evidence identity. The guarded executable-object registry correctly refuses closures/default-bound ambient state, so those per-call values need an explicit data contract before the broker can safely move to an admitted fixed adapter target.

## Delivered

`daedalus/runtimes/provider_invocation_payload.py` defines a deliberately non-executing `ProviderInvocationPayload` bound to one exact `ProviderInvocationSubject.digest`.

The payload boundary:

- carries exact `provider_id`, `adapter_id` and a versioned `payload_schema_id`;
- accepts only exact JSON-like Python containers (`dict` / `list`) and scalar `str`, `int64`, `bool` and `None` values;
- refuses floats, bytes, tuples, sets, callables, container subclasses, non-string/empty/NUL keys and NUL-bearing strings;
- recursively sorts object keys and fences nesting depth, node count, string length and canonical encoded bytes;
- deep-freezes the admitted body behind read-only mapping proxies / tuples and returns fresh mutable copies only from `to_dict()`;
- hashes the full subject-bound, schema-bound payload using the repository canonical SHA primitive;
- round-trips only an exact schema with all non-authority claims fixed to false.

This creates a deterministic home for the information that currently lives in provider closure captures without executing or resolving any adapter.

## Tests

Focused tests cover:

- canonical round-trip and deterministic key ordering;
- objective/workspace/path/agent/model/timeout sensitivity;
- exact subject and payload-schema sensitivity;
- source-alias mutation after construction;
- structural immutability;
- unsupported ambient/nondeterministic Python values;
- container subclass rejection;
- depth/node/string resource fences;
- exact deserialization and authority-claim escalation refusal;
- exact invocation-subject type requirement;
- AST review proving this module imports no process/network/dynamic-loader surface and starts/grants/invokes no effect/provider.

## Deliberate non-goals

This packet does **not** sign the payload digest, alter `ProviderInvocationObservationAuthority`, invoke a provider, expose a stored callable, grant/start an Effect, remove the broker callback seam, migrate Claude, or claim live Hermes parity.

The next bounded packet (`07D2`) must bind `ProviderInvocationPayload.digest` into the existing signed invocation/observation contract *before* `begin_effect`. Only after that signed binding and exact adapter-payload schema matching are proven should the production broker consume a fixed admitted adapter target and remove loose `invoke` / `output_digests` callables.

No second provider registry, plugin authority, policy engine, runtime kernel or session subsystem is introduced.
