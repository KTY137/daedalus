# G0-RTC-07J — Provider Target Receipt Retention Read-Only Preflight

Exact parent: `415b07394ac4c5d2fc7481e27c9c47b40119d859` from draft PR #217. Draft PR: #218.

## Purpose

This packet composes the previously separated, inert retention subjects without opening the effectful retention path. It requires one exact signed retention-operation authority, the provider-target structural verification receipt, the separate retention execution request and Effect Lease subject, the refreshed retention-write inventory, and a process-free repository-HEAD receipt.

The implementation snapshots every supplied subject digest, rebuilds the expected signed subject, and authenticates its authority and exact `GuardDecision` before any repository read. It then live-reverifies the HEAD receipt, rebuilds the retention inventory from current source bytes, requires exact inventory equality, and live-reverifies the same HEAD receipt again. Every supplied digest and exact inventory field is rechecked before a canonical preflight receipt is returned.

The receipt therefore reports `repository_head_stable_across_inventory=true` only for that bounded two-fence observation. A later effectful packet must re-run the preflight immediately before effect admission; this receipt is not a capability.

## Exact retained shape

The wire form accepts only a lowercase 40-hex revision, a retention source no larger than 2 MiB, the currently reviewed seven effectful surfaces, exact authority/subject guard evidence, and two disjoint repository-relative retention scope paths. Unknown fields, widened claims, overlapping scope paths, stale revisions, source-byte drift, and subject mutation fail closed.

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

A later small central-admission packet must authenticate and consume a live persisted retention Effect Lease, re-run this exact preflight, prove concrete Event Store and CAS paths outside the Primary Checkout, and begin the effect durably before invoking any retention write.

## Adversarial batch

Prepared coverage includes strict round-trip and Draft 2020-12 schema checks, authority refusal before repository reads, stale HEAD before inventory, HEAD movement during inventory, current source-byte and inventory substitution, exact guard-evidence binding, digest mutation, exact revision/size/surface/path constraints, unsupported wire claims, independent AST authority/order/no-writer review, fourteen bounded mutations, predecessor regressions, full suite, package build, isolated-wheel import, and Ubuntu/Windows on Python 3.10/3.12 with two hash seeds.

Hosted workflow run `30978661059` created twelve jobs; all terminated with `steps=null`, no logs, and no artifacts. Source inspection and model statements are not hard product evidence. Repository issue #67 remains the external execution-infrastructure blocker, and the zero-step run is recorded only as blocker evidence.

No direct change to `main` or `experimental`; no merge, automatic promotion, OwnerApproval, provider execution, receipt retention, or Gate transition.
