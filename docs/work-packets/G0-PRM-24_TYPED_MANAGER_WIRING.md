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

The parent public module remains a byte-identical prefix through its frozen `__all__`. The appended wiring consists only of a private `functools.wraps` import, the two private adapter imports, the ordered installer calls, a small function-facade factory, one public-callable assignment and deletion of all temporary private aliases. No second retained source file or parallel promotion implementation is introduced.

## Typed installation

`install_promotion_manager_boundary` keeps the public `PromotionExecutionLedger` global bound to the canonical class. It wraps only a caller-supplied ledger that already passes the canonical type boundary. An arbitrary object remains arbitrary and is refused by the sealed parent rather than being laundered through a proxy subclass.

`install_promotion_manager_replay_boundary` then selects `_ReplayAuditedExecutionLedger` as the per-call wrapper. The replay proxy subclasses the audit proxy, which subclasses the canonical ledger class. The exact already-open Event Store delegate remains authoritative; the wrapper does not open a second database.

## Function-compatible public facade

Directly exposing the bound `_BoundaryState.promote_candidates` method would preserve call behavior but change the historic public API from a function into a bound method. That changes introspection, signature discovery, monkeypatch expectations and any code that depends on `inspect.isfunction` or the original `__wrapped__` chain.

The live module therefore creates a small `functools.wraps` facade after both adapters are installed. The facade delegates to the scoped manager wrapper but copies the sealed parent function's name, qualified name, module, annotations and docstring, and exposes the sealed parent through `__wrapped__`. Consequently:

- `promote_candidates` remains a normal function;
- `inspect.signature(promote_candidates)` remains the sealed parent signature;
- `inspect.unwrap(promote_candidates)` resolves to the sealed persisted-authority function;
- the scoped manager wrapper remains the actual call target;
- the factory, `wraps` alias and both installer aliases are deleted after construction;
- none of those private helpers enter the frozen export set.

## Effect ordering

Constructing `GitWorktreeManager` before the persisted execution start is acceptable only because its constructor is a read-only topology validation step: it resolves repository/worktree paths and inspects existing filesystem state without creating directories, lock files, branches or subprocesses. Actual lock-file and worktree mutation remains after `PromotionExecutionLedger.begin` returns `execute=true`.

By contrast, constructing `PromotionExecutionLedger` itself is effectful because it opens a writable Event Store and installs a SQLite uniqueness index. That constructor is therefore already tracked separately by `G0-PRM-23` as `kernel.promotion_execution.open`; this wiring packet does not pretend it is inert.

## Verification prepared

Live-wiring tests prove:

- the existing retained-resource strangler remains active;
- the public ledger global is still the canonical class;
- the live manager state selects the typed replay proxy;
- the public callable remains a function-compatible facade over the sealed parent;
- exact name, module, qualified name, signature and unwrap behavior are retained;
- an untyped ledger is refused without mutation;
- manager state resets after every call;
- installer, factory and `wraps` aliases are not exported or retained.

The independent source counter-review verifies the parent file's exact Git-blob prefix and restricts the append to the private imports, ordered calls, function facade and alias deletions. The mutation campaign removes either installer, reverses installation order, removes the public facade and retains private aliases. Existing manager-audit, replay and promotion-effect inventory campaigns remain part of the dependent verification batch.

## Honest remaining boundary

The live manager observation path is installed, but Gate 0 is not closed. The canonical effect registry still lacks rows for `PromotionExecutionLedger.__init__`, `begin` and `complete`, and `python.promote_candidates` remains `local_guards`. No promotion surface may be upgraded to `central` until the persisted EffectLease, exact Runtime Manifest, current RuntimeConformanceReceipt and Docker sandbox are mechanically composed.

No OwnerApproval is created and no promotion is requested.

Iron Plan: **ALIGNED BY SCOPE**  
Active gate: **Gate 0**  
Manager production wiring: **implemented, verification pending**  
Effect centralization: **not claimed**  
Promotion: **not requested**
