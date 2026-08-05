# G0-RTC-07E — Provider-target receipt-retention inventory

Exact parent: `b2bda280f8f98d6e977e092c5429da3c85427a33` on `g0/provider-target-receipt-retention-linear`.

## Frozen claim

This packet adds a read-only, revision- and source-byte-bound AST inventory for the writes introduced by `ProviderTargetReceiptLedger`. It records seven exact surfaces: the canonical Event-Store writer transaction, partial unique-index schema write, intent append, the two transitive retention wrappers, CAS publication, and terminal Event-Store append.

Every row is deliberately `inventory_only`, blocking, unguarded, without a consumed Effect Lease, and without a claim that its target is outside the Primary Checkout. The report hard-codes `closed=false`.

## Adversarial preparation

The prepared batch covers deterministic reconstruction, exact source/revision binding, missing, duplicate, renamed and otherwise unclassified anchors, a closed two-call SQL set in the schema-invariant method, malformed revisions, strict UTF-8, BOM, NUL and syntax refusal, final-file and parent-directory symlink refusal, repository-root containment, canonical JSON reporting, a separate source-review perspective, seven bounded mutants, predecessor retention regressions, full suite, package build, isolated-wheel imports, and Ubuntu/Windows on Python 3.10/3.12 with two hash seeds.

Static counter-review found and corrected two defects before dependency use: the first scanner checked only the final source path rather than every parent component, and it identified the schema write without refusing additional unclassified SQL calls in the same method. The corrected scanner rejects both cases. This review history is not executable evidence.

Source inspection and LLM statements are not hard evidence. Exact-head execution remains pending while repository issue #67 terminates hosted Actions jobs before Step 1 with no logs or artifacts.

## Deliberate next boundary

This packet does not change production behavior or the canonical effect inventory. A later small packet must register the exact retention entrypoint, bind an exact guard contract, consume persisted Effect-Lease authority before any write, and prove target disjointness. Only then may the path move from `inventory_only`/`LOCAL_GUARDS` toward `CENTRAL`.

No change to `main` or `experimental`; no merge, automatic promotion, OwnerApproval, PromotionReceipt, provider execution or Gate transition.
