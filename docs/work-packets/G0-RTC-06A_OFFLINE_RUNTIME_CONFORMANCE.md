# G0-RTC-06A — Offline Runtime Conformance Profiles

## Objective

Add a strict, versioned Gate-0 profile and evidence-binding layer for the three
production runtime families currently named by the effect registry:

- `claude_code_cli`
- `codex_cli`
- `ollama_http`

This packet does **not** claim that any installed vendor binary currently
conforms. It creates the deterministic PR-CI half of the runtime-conformance
boundary while making it mechanically impossible to reuse that evidence as a
live production authorization.

## Authority split

The existing `RuntimeManifest` remains a declaration. The existing
`RuntimeConformanceReceipt` remains the content-addressed result of concrete
observations. This packet adds:

1. `RuntimeProfile` — strict checked-in adapter metadata and conservative
   capability declarations;
2. `RuntimeProbeIdentity` — exact binding to profile, manifest, adapter source,
   executable/image, environment, fixture suite, source revision, and probe
   authority;
3. `RuntimeConformanceEnvelope` — exact binding of manifest, probe identity,
   and receipt with one of two authorities:
   - `offline-fixture`
   - `live-runtime`

`verify_runtime_envelope()` defaults to `require_live=True`. A passed offline
fixture therefore raises instead of authorizing a production Effect Lease.
Because canonical objects can still be constructed in memory, production
verification additionally uses `verify_production_runtime_envelope()` and an
externally protected exact set of trusted live-probe digests. Merely changing
the authority string cannot create trust.

## Deterministic fixture coverage

The test fixture is under `tests/fixtures`, not in the shipped runtime package.
It exercises the provider-neutral protocol for every checked-in runtime profile:

- start marker;
- ordered streaming deltas;
- structured tool event;
- structured final output;
- timeout and process reaping;
- cancellation with complete POSIX process-group termination;
- bounded workspace write plus outside-root refusal;
- exact non-negative token/cost usage.

The same fixed timestamps and exact source identities reproduce identical
manifest, probe, receipt, and envelope digests under both supported hash seeds.

## Fail-closed cases

Tests refuse:

- duplicate or unknown JSON fields;
- missing or extra runtime profiles;
- capability-schema drift;
- cross-runtime evidence substitution;
- stale receipts;
- receipts repackaged without the probe-identity digest;
- offline evidence presented as production-authorizing evidence;
- a live-labelled probe absent from the external trusted-probe set.

## Deliberate remaining blockers

Gate 0 remains open. This packet does not provide:

- current Claude/Codex/Ollama binary or image observations;
- authenticated live provider execution;
- live streaming/tool/cost evidence;
- proven cancellation and process-tree kill for each vendor adapter;
- expiring scheduled live receipts;
- lease issuance based on a trusted `live-runtime` envelope;
- non-Linux process-tree evidence;
- independent security review or owner closure.

Those remain on issue `G0-RTC-06`. A future live probe must run behind the
persisted Effect Lease and sandbox boundaries, retain no secrets in evidence,
and produce a `live-runtime` identity bound to the exact binary/image and
environment. It may not relabel this offline fixture.

## Work Packet boundary

- no network access;
- no vendor CLI invocation;
- no secret access;
- no production filesystem write API;
- no new effectful production entrypoint;
- no promotion, merge, or OwnerApproval;
- no Gate-1 or Gate-2 activation.

Iron Plan: **ALIGNED**  
Active gate: **Gate 0**  
Promotion: **not requested**
