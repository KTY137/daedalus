# G0-RTC-06B — Persisted Runtime Trust and Quarantine

## Objective

Persist the exact externally trusted live-runtime evidence identity needed by a later Effect-Lease issuance boundary. This packet does not create trust: admission succeeds only after the existing production verifier accepts the exact live `RuntimeConformanceEnvelope` digest from an externally protected trusted set.

## Authority boundary

The root of authority remains outside the repository and outside the SQLite ledger. A caller must supply the exact trusted envelope digest and the complete envelope, probe identity, conformance receipt and runtime manifest. The ledger then rechecks and persists:

- runtime ID;
- exact envelope digest;
- exact probe-identity digest;
- exact conformance-receipt digest;
- exact runtime-manifest digest;
- exact source revision;
- admission and expiry instants;
- monotonic active/quarantined state;
- a canonical digest over the complete persisted record.

A locally constructed object, a changed authority string, a trusted probe identity without the exact envelope, or an untrusted live receipt cannot be admitted.

## State transitions

`RuntimeTrustLedger` uses SQLite with WAL, `synchronous=FULL`, `BEGIN IMMEDIATE`, foreign keys and a busy timeout.

- exact replay with identical admission/expiry is idempotent;
- replay with changed bindings or extended expiry is refused;
- admitting a new exact envelope for the same runtime quarantines the previous active envelope;
- expiry is persisted as quarantine before authorization fails;
- explicit quarantine is monotonic and cannot be rewritten with another reason;
- no API exists to reactivate or delete a quarantined record;
- every read reconstructs and verifies the persisted record digest.

## Adversarial coverage

The focused tests cover:

- external trust verification failure before persistence;
- exact active lookup;
- manifest, receipt and source-revision substitution;
- stale-envelope rotation;
- expiry at the exact boundary;
- replay-based TTL extension;
- quarantine-history rewriting;
- direct SQLite row tampering;
- overlong trust TTL;
- timezone-naive timestamps.

## Deliberate remaining blockers

This packet does not:

- invoke Claude, Codex or Ollama;
- create a live conformance receipt;
- store provider secrets;
- make the repository-controlled ledger the root of trust;
- wire `RuntimeTrustLedger.require_active()` into every runtime-bearing Effect-Lease issuance path;
- add scheduled/manual live probes;
- claim GitHub Actions evidence while jobs fail before step 1;
- close `G0-RTC-06` or Gate 0.

The next dependent packet must require an active exact trust record when issuing a production Effect Lease for an entrypoint with `runtime_id`, while retaining a test-only path for isolated contract tests.

Iron Plan: **ALIGNED**  
Iron Gate: **0**  
Promotion: **not requested**
