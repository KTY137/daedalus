# G1-PREP-02 — Canonical Renovation Attempt Bindings

## Status

Gate 0 remains the active authoritative gate. This packet is non-executing
Gate-1 preparation stacked on `G1-PREP-01`. It must be replayed and fully
reverified against the final accepted Gate-0 head before Gate 1 can activate.

## Objective

Bind exactly two canonical `AttemptContract` records to the exactly two typed
Renovation WorkItems without creating a second task, attempt, event-store, or
promotion authority.

The packet introduces:

- `RenovationAttemptBinding`, which binds one exact WorkItem digest to one exact
  Attempt digest and one deterministic replay key;
- `RenovationAttemptPlan`, which binds the two ordered attempt identities to one
  exact `RenovationPlan`, mission, and base revision;
- strict mapping/file parsers with recursive duplicate-key refusal and complete
  canonical-wire equality;
- an assembler that immediately re-runs consumer-side verification;
- a verifier that reconstructs all canonical inputs and requires caller-owned
  runtime-manifest and policy-decision identities.

## Exact ignition ordering

Sequence `0` is the `symbol-rename` WorkItem over Code and Type. Sequence `1`
is the dependent `representation-sync` WorkItem over Data and Knowledge.

Each Attempt must retain exactly:

- the Renovation mission ID;
- the WorkItem ID and digest as task authority;
- the exact base revision;
- the WorkItem writable paths and required evidence gates;
- the externally expected runtime-manifest and policy-decision digests;
- the mission budget;
- write-capable rather than read-only semantics.

The replay key is recomputed from the exact RenovationPlan digest, WorkItem
digest, Attempt digest, and sequence. It is an idempotency identity only. It is
not evidence that an Attempt started, restarted, completed, or was recovered.

## Authority boundary

This packet intentionally contains no:

- SQLite or alternative lifecycle ledger;
- worktree creation or candidate materialization;
- Effect Lease issuance or use;
- runtime invocation;
- EvidencePacket, nomination, OwnerApproval, or PromotionReceipt;
- merge, promotion, or Gate-closure operation.

The existing event spine remains the sole lifecycle authority. A later active
Gate-1 packet must persist these replay identities through that authority and
prove crash/restart behavior with real isolated Attempts.

## Adversarial verification request

Builder and separate source-review suites cover:

- exact two-attempt cardinality and dependency order;
- deterministic identity under input reordering;
- stale RenovationPlan and source revision;
- foreign runtime or policy authority;
- widened writable paths, weakened evidence gates, and changed budget;
- forged replay keys after otherwise valid repackaging;
- noncanonical nested arrays and recursive duplicate JSON keys;
- absence of execution, state-store, approval, and promotion authority.

The bounded mutation campaign attacks replay-key verification, external runtime
identity, and complete canonical-wire equality. Dedicated CI requests Ubuntu
and Windows, Python 3.10 and 3.12, two hash seeds, parent WorkItem/Fourfold/kernel
contracts, compile-all, Iron Plan, mutations, full pytest, and isolated-wheel
imports.

GitHub Actions issue #67 remains an external exact-head verification blocker:
hosted jobs currently terminate before Step 1 with no logs or artifacts. Such a
run is infrastructure observation only and cannot be represented as product or
Gate evidence.

Promotion: **not requested**
