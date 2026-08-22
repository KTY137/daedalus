# ADR-021 — One promotion receipt authority

Renumbered 2026-08-22 from `docs/adr/ADR-0002-PROMOTION-RECEIPT-AUTHORITY.md`; the
`docs/adr/` namespace was merged into `docs/adrs/`. See `docs/adrs/README.md`.

Status: accepted for Gate-0 implementation  
Date: 2026-08-03  
Decision scope: promotion contracts and persisted execution accounting

## Context

Daedalus already has a canonical `daedalus.schemas.PromotionReceipt` with
contract type `daedalus.promotion`. It records the explicit owner-controlled
promotion decision and binds nomination, candidate, evidence, source revision,
target revision and authenticated OwnerApproval evidence. It deliberately does
not apply a candidate.

An experimental receipt-ledger branch later introduced a second public class
also named `PromotionReceipt`, with contract type
`daedalus.promotion-receipt`, to describe terminal execution. That created two
incompatible wire authorities for one public concept and violated the adopted
one-kernel invariant. The experimental branch was closed without merge.

The sealed live mutation seam now has a different remaining requirement: retain
a durable pre-effect start record and an immutable terminal execution account
without redefining the owner-decision contract.

## Decision

1. `daedalus.schemas.PromotionReceipt` remains the sole class named
   `PromotionReceipt` and the sole canonical owner-decision receipt.
2. Compatibility imports may alias that exact class but may not wrap, subclass,
   shadow or redefine it.
3. No module named `daedalus.kernel.promotion_receipts` is accepted while it
   exports a competing contract authority.
4. The later persisted mutation ledger must use distinct names:
   `PromotionExecutionStart` for the durable pre-effect intent and
   `PromotionExecutionReceipt` for the terminal execution account.
5. If `PromotionExecutionReceipt` becomes a public wire contract, it must be
   added through the canonical schema authority with its own unique contract
   type, strict parser, JSON schema, compatibility plan and migration tests. It
   must never be introduced as a second `PromotionReceipt` in a kernel helper.
6. The execution record must bind the canonical decision receipt, persisted
   approval consumption, sealed authorization, exact candidate and evidence,
   source/base revision, target ref and authorized target HEAD, measured
   integration revision, primary-checkout identity, start/finish time and
   retained terminal report.
7. A durable start record is written before the first promotion mutation. Exact
   replay returns the existing terminal record or an explicit reconciliation
   state; it never starts the mutation twice.
8. The ledger clock, not an effectful caller, owns lifecycle timestamps. Stored
   schema, canonical JSON, digest and column bindings are verified on every
   read, including pending-reconciliation queries.

## Consequences

The current canonical decision contract stays import-compatible. The discarded
receipt draft remains port material only. A dependent Work Packet may implement
execution persistence directly on the sealed PR-109 seam, but it must use the
new distinct vocabulary and satisfy the bindings above before live wiring.

This ADR grants no approval, effect, merge or promotion authority.