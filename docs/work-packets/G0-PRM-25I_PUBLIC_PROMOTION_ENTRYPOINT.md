# G0-PRM-25I — Capability-Bearing Public Promotion Entrypoint

## Scope

This packet adds a new strangler-facing promotion surface at
`daedalus.kairos.promotion_entrypoint.promote_candidates` and exports it as
`daedalus.kairos.promote_candidates_with_persisted_effect`.

The entrypoint requires the complete `PromotionEffectCapability` and
`PromotionExecutionLedger` in its explicit keyword-only contract. It accepts no
callback, provider, effect outcome, terminal receipt, Git manager or lower-level
writer authority. Its only behavior is one exact delegation to the persisted
Effect-Lease lifecycle introduced by G0-PRM-25H.

## Compatibility boundary

The historical `daedalus.kairos.gated_writes.promote_candidates` import remains
unchanged in this packet so the review batch does not combine entrypoint
creation, caller migration, registry retargeting and compatibility retirement.
The new package export is deliberately distinct. A later packet must migrate
production callers one at a time and then replace or inventory-demote the old
public bypass before the canonical row can become central.

## Prepared adversarial verification

The builder tests bind every positional and keyword subject, require exactly one
lifecycle delegation, preserve exception identity and verify the package export.
A separate AST/source review rejects direct Git, subprocess, SQLite,
OwnerApproval, promotion-ledger begin/complete, callback/provider and merge
authority in the new module.

Exact-head compilation, focused behavior tests, malformed/stale lifecycle tests,
full suite, packaging and the supported platform/Python matrix remain pending.
Repository GitHub Actions issue #67 has repeatedly ended jobs before Step 1 with
no logs or artifacts; such runs are infrastructure observations only.

## Non-claims

No OwnerApproval was issued or fabricated. No repository effect, merge,
promotion, registry centralization or automatic promotion occurred. Gate 0
remains open.
