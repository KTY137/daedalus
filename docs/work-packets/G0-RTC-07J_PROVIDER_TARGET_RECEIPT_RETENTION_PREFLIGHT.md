# G0-RTC-07J — Provider Target Receipt Retention Read-Only Preflight

Exact parent: `415b07394ac4c5d2fc7481e27c9c47b40119d859` from draft PR #217.

## Purpose

This packet composes the previously separated, inert retention subjects without opening the effectful retention path. It requires one exact signed retention-operation authority, the provider-target structural verification receipt, the separate retention execution request and Effect Lease subject, the refreshed retention-write inventory, and a process-free repository-HEAD receipt.

The expected signed subject is rebuilt first. Its authority and exact `GuardDecision` are authenticated before any repository read. The implementation then live-reverifies the HEAD receipt against the provider receipt revision and rebuilds the retention inventory from current source bytes. Only exact equality returns a canonical preflight receipt.

## Deliberate non-authority

The packet does not inspect persisted Effect-Lease state, grant or begin an effect, register a canonical entrypoint, open SQLite, publish CAS bytes, append Event-Store state, invoke `ProviderTargetReceiptLedger.retain`, execute a provider, issue OwnerApproval, merge, promote, or change a Gate.

The receipt permanently reports:

- `provider_execution_allowed=false`;
- `persisted_effect_lease_verified=false`;
- `retention_effect_started=false`;
- `retention_write_performed=false`;
- `canonical_entrypoint_registered=false`;
- `gate_transition_authorized=false`;
- `closed=false`.

A later small central-admission packet must consume a live persisted retention Effect Lease and this exact preflight result immediately before mutation. Concrete Event Store and CAS paths must be proven outside the Primary Checkout at that boundary, and every write must occur after the durable effect start.

## Adversarial batch

Prepared coverage includes strict round-trip and schema checks, authority refusal before repository reads, stale-HEAD refusal, current source-byte and inventory substitution, exact guard-evidence binding, unsupported wire-claim refusal, independent AST authority/order review, eight bounded mutations, predecessor regressions, full suite, package build, isolated-wheel import, and Ubuntu/Windows on Python 3.10/3.12 with two hash seeds.

Source inspection and model statements are not hard evidence. Repository issue #67 continues to terminate hosted GitHub Actions jobs before Step 1 with `steps=null`, no logs, and no artifacts. Any repeated zero-step run remains infrastructure evidence only.

No direct change to `main` or `experimental`; no merge, automatic promotion, OwnerApproval, provider execution, receipt retention, or Gate transition.
