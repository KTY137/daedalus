# G0-PRM-24 — Typed Promotion Manager Wiring

## Scope

This packet installs the corrected manager-audit and restart-replay adapters in the live `daedalus.kairos.gated_writes` module. It changes only the manager-observation seam around the already sealed promotion callable. It does not add effect-registry rows, consume an EffectLease, issue OwnerApproval, invoke Git, create a worktree, merge a branch or promote automatically.

The packet is stacked on exact parent `0a676cc6f3944c564acc0a42a9a844b9eeb43a49`.

## Existing strangler preserved

The public module continues to:

1. load `_gated_writes_legacy.py.src` as package data;
2. verify its exact Git blob identity;
3. execute the retained helpers into the historic module namespace;
4. delete the historical unpersisted promotion callable;
5. define the sealed persisted-authority `promote_candidates` replacement.

The two manager adapters are installed only after that sealed replacement exists and after `__all__` is frozen. No second retained source file or parallel promotion implementation is introduced.

## Typed installation

`install_promotion_manager_boundary` keeps the public `PromotionExecutionLedger` global bound to the canonical class. The public callable is replaced by a scoped wrapper that wraps only a caller-supplied ledger that already passes the canonical type boundary. An arbitrary object remains arbitrary and is refused by the sealed parent rather than being laundered through a proxy subclass.

`install_promotion_manager_replay_boundary` then selects `_ReplayAuditedExecutionLedger` as the per-call wrapper. The replay proxy subclasses the audit proxy, which subclasses the canonical ledger class. The exact already-open Event Store delegate remains authoritative; the wrapper does not open a second database.

Both installer aliases are deleted after installation and were never included in `__all__`.

## Effect ordering

Constructing `GitWorktreeManager` before the persisted execution start is acceptable only because its constructor is a read-only topology validation step: it resolves repository/worktree paths and inspects existing filesystem state without creating directories, lock files, branches or subprocesses. Actual lock-file and worktree mutation remains after `PromotionExecutionLedger.begin` returns `execute=true`.

By contrast, constructing `PromotionExecutionLedger` itself is effectful because it opens a writable Event Store and installs a SQLite uniqueness index. That constructor is therefore already tracked separately by `G0-PRM-23` as `kernel.promotion_execution.open`; this wiring packet does not pretend it is inert.

## Verification prepared

Live-wiring tests prove:

- the existing retained-resource strangler remains active;
- the public ledger global is still the canonical class;
- the live manager state selects the typed replay proxy;
- the public callable is the scoped wrapper over the sealed parent;
- an untyped ledger is refused without mutation;
- manager state resets after every call;
- installer aliases are not exported or retained.

Source counter-reviews require the exact order: sealed callable, export freeze, manager installation, replay installation. The mutation campaign removes either installer, reverses installation order and retains either private installer alias. Existing manager-audit, replay and promotion-effect inventory campaigns remain part of the dependent verification batch.

## Honest remaining boundary

The live manager observation path is installed, but Gate 0 is not closed. The canonical effect registry still lacks rows for `PromotionExecutionLedger.__init__`, `begin` and `complete`, and `python.promote_candidates` remains `local_guards`. No promotion surface may be upgraded to `central` until the persisted EffectLease, exact Runtime Manifest, current RuntimeConformanceReceipt and Docker sandbox are mechanically composed.

No OwnerApproval is created and no promotion is requested.

Iron Plan: **ALIGNED BY SCOPE**  
Active gate: **Gate 0**  
Manager production wiring: **implemented, verification pending**  
Effect centralization: **not claimed**  
Promotion: **not requested**
