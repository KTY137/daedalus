# G0-RTC-06B — Persisted Runtime Trust and Quarantine

## Objective

Persist the exact externally trusted live-runtime evidence identity needed by a later Effect-Lease issuance boundary. This packet does not create trust: admission succeeds only after the existing production verifier accepts the exact live `RuntimeConformanceEnvelope` digest from an externally protected trusted set.

## Authority boundary

The root of authority remains outside the repository and outside the SQLite ledger. A caller must supply:

- the exact trusted envelope digest;
- the complete envelope, probe identity, conformance receipt and runtime manifest;
- an external ledger-integrity key of at least 32 bytes.

The integrity key is never stored in the repository or database. The ledger rechecks and persists:

- runtime ID;
- exact envelope digest;
- exact probe-identity digest;
- exact conformance-receipt digest;
- exact runtime-manifest digest;
- exact source revision;
- receipt observation, admission and expiry instants;
- monotonic active/quarantined state;
- a canonical digest over the complete persisted record;
- an HMAC-SHA256 authenticating that record digest with the external integrity key.

A locally constructed object, a changed authority string, a trusted probe identity without the exact envelope, an untrusted live receipt, or a database writer that lacks the integrity key cannot create an accepted trust record.

## State transitions

`RuntimeTrustLedger` uses SQLite with WAL, `synchronous=FULL`, `BEGIN IMMEDIATE`, foreign keys and a busy timeout.

- exact replay with identical admission and expiry is idempotent;
- replay with changed bindings or extended expiry is refused;
- only an observation strictly newer than the current active observation may rotate it;
- a stale or equal observation cannot roll the runtime back;
- expiry may never extend beyond seven days after the conformance receipt was observed;
- expiry is persisted as quarantine before authorization fails;
- explicit quarantine is monotonic and cannot be rewritten with another reason;
- no API exists to reactivate or delete a quarantined record;
- every read reconstructs the record, verifies its canonical digest and authenticates its HMAC.

## Adversarial coverage

The focused tests cover:

- external trust verification failure before persistence;
- exact active lookup and idempotent replay;
- manifest, receipt and source-revision substitution;
- stale-observation rollback;
- expiry at the exact boundary;
- replay-based expiry extension;
- receipt-freshness extension;
- future observations;
- quarantine-history rewriting;
- direct SQLite rewriting where the attacker recomputes the canonical digest but cannot forge the HMAC;
- weak integrity keys;
- timezone-naive timestamps.

## Deliberate remaining blockers

This packet does not:

- invoke Claude, Codex or Ollama;
- create a live conformance receipt;
- store provider secrets or the ledger-integrity key;
- make the repository-controlled ledger the root of trust;
- implement integrity-key rotation;
- wire `RuntimeTrustLedger.require_active()` into every runtime-bearing Effect-Lease issuance path;
- add scheduled/manual live probes;
- claim GitHub Actions evidence while jobs fail before step 1;
- close `G0-RTC-06` or Gate 0.

The next dependent packet must require an active exact trust record when issuing a production Effect Lease for an entrypoint with `runtime_id`, while retaining an explicitly non-production path for isolated contract tests.

Iron Plan: **ALIGNED**  
Iron Gate: **0**  
Promotion: **not requested**
