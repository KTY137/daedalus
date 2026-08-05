# G0-RTC-07F — Provider-target receipt-retention contract

Exact parent: `bf678e837a374787c0198ba6047777001a991f41` on `g0/provider-target-receipt-retention-inventory-linear`.

## Frozen claim

This packet defines one signed, short-lived, non-executing guard contract for the future `provider.target-receipt.retain` entrypoint. The subject binds the exact provider-target verification receipt identity, the retention-inventory report digest, the inventory source revision and source-byte digest, a separate retention execution request, a separate local filesystem-write Effect Lease, and exactly two disjoint writable scope paths for the canonical Event Store and receipt CAS.

The inventory source revision must equal the authenticated receipt source revision. The provider execution lease, execution ID and idempotency key may not be reused for retention. The retention lease must be local, single-concurrency, source-revision-bound, kill-switch-bound and free of runtime, egress, tool, secret or cost authority. The signed authority expires after at most 15 minutes.

## Explicit non-authority

The wire subject hard-codes `provider_execution_allowed=false`, `retention_effect_started=false` and `primary_checkout_disjointness_verified=false`. This packet does not authenticate the provider-target receipt, authenticate the inventory artifact, persist or begin an Effect Lease, inspect concrete target topology, open SQLite, publish CAS bytes, append an Event-Store record, execute a provider, promote a candidate or close a Gate.

A future central packet must compose all missing evidence: authenticate the receipt and inventory, verify and begin the persisted retention lease, prove the concrete Event-Store and CAS targets are outside the Primary Checkout, consume the returned guard decision, and only then invoke the retention ledger.

## Adversarial preparation

The prepared batch covers exact subject and authority round trips, stale lease and stale inventory-revision refusal, malformed inventory identities, wrong-entrypoint refusal, malformed and overlapping scope paths, separate provider/retention identities, unrelated scope rejection, runtime-bound lease rejection, kill-switch binding, wire-claim escalation, signature tampering, unknown keys, expiry, subject and inventory-revision substitution, exact input types, an independent source-review perspective, ten bounded mutants, predecessor regressions, full suite, package build, isolated-wheel imports, and Ubuntu/Windows on Python 3.10/3.12 with two hash seeds.

Static counter-review found and corrected two omissions before dependency use. Equal empty kill-switch references originally satisfied the comparison; the contract now explicitly requires both references to be non-empty. The first signed subject also bound inventory and source-byte digests without binding the inventory source revision; the corrected subject validates that revision and requires exact equality with the receipt revision in both construction and deserialization. This review history is not executable evidence.

Source inspection and LLM statements are not hard evidence. Exact-head execution remains pending while repository issue #67 terminates hosted Actions jobs before Step 1 with no logs or artifacts.

No change to `main` or `experimental`; no merge, automatic promotion, OwnerApproval, PromotionReceipt, provider execution or Gate transition.
