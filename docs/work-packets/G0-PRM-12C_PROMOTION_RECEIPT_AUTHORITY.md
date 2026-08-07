# G0-PRM-12C — Promotion receipt authority guard

Active gate: Gate 0  
Classification: architecture/security hardening  
Base revision: `e3853cf42e03250768a8b649b4f6aa8a3205ddd9`  
Dependency: G0-PRM-12B sealed live promotion seam

## Primary claim

The repository has exactly one canonical class named `PromotionReceipt`, and
future terminal mutation accounting cannot silently create a competing receipt
or wire authority.

## In scope

- adopt ADR-0002;
- pin `daedalus.schemas.PromotionReceipt` as the sole named authority;
- reject duplicate class definitions and the obsolete
  `daedalus.kernel.promotion_receipts` module path;
- reject a second `daedalus.promotion-receipt` contract type in production
  Python;
- retain the kernel package statement that it is not a second contract
  authority;
- request supported-platform, full-suite and isolated-wheel verification.

## Forbidden scope

- no change to the canonical promotion fields or signature semantics;
- no PromotionExecutionReceipt implementation yet;
- no SQLite ledger, Git command, worktree, provider, Effect Lease or runtime
  invocation;
- no OwnerApproval issuance or consumption;
- no candidate application, ref update, merge or promotion;
- no Gate-0 closure claim.

## Acceptance matrix

1. AST scan finds `PromotionReceipt` only in `daedalus/schemas.py`.
2. The canonical class keeps contract type `daedalus.promotion`.
3. Any kernel compatibility export, if later added, resolves to the exact
   canonical class object.
4. Production Python contains neither a competing
   `daedalus.promotion-receipt` contract type nor a
   `daedalus/kernel/promotion_receipts.py` authority module.
5. The kernel package still declares that canonical wire contracts remain in
   `daedalus.schemas`.
6. Iron Plan, compile-all, focused authority tests, affected promotion tests,
   full repository suite and isolated-wheel import execute on supported Python
   and platform cells.

## Adversarial review questions

- Can a new class hide behind an alias, subclass or nested class definition?
- Can a second contract type be introduced under a different module name?
- Does a compatibility import preserve exact object identity?
- Does this packet accidentally claim terminal-execution semantics that the
  current canonical decision receipt does not provide?

## Residual boundary

Gate 0 still lacks a redesigned durable promotion-execution ledger wired to the
single sealed mutation seam. That dependent packet must use
`PromotionExecutionStart` / `PromotionExecutionReceipt`, bind the canonical
owner-decision receipt and satisfy ADR-0002. This packet only prevents receipt
authority drift.