# G0-WP-04 — Sealed Promotion, Runtime Evidence, and Sandbox Boundary

## Classification

- Iron Plan: `ALIGNED`
- Active gate: `0`
- Promotion: not requested
- Base: `g0/fourfold-evidence-binding`

## Objective

Close three high-risk Gate-0 gaps without claiming Gate-0 closure:

1. make `promote_candidates` refuse before any worktree, lock, or Git mutation unless a consumed `OwnerApproval`, the exact passed `EvidencePacket`, the exact ordered candidate batch, and a freshly resolved target HEAD all agree;
2. introduce a content-addressed runtime-conformance harness whose receipts report measured fixture observations rather than manifest declarations;
3. introduce a restrictive Docker command boundary for later attempts and evaluators.

## Authority and boundaries

- `OwnerApproval`, `EvidencePacket`, `RuntimeManifest`, and `RuntimeConformanceReceipt` remain canonical contracts.
- The existing Kairos integration worktree remains the promotion implementation; the new module only authorizes entry into it.
- The sandbox wrapper is an effect environment, not an orchestration or policy authority.
- No production runtime is declared conformant merely because an offline fixture receipt can be assembled.
- Gate 0 remains open while other `UNGUARDED` or `INVENTORY_ONLY` entrypoints, live runtime receipts, and the complete fault matrix remain unresolved.

## Acceptance criteria

- stale target HEAD is refused before the integration worktree manager is constructed;
- candidate, evidence, base revision, target ref, and approval consumption are digest-bound;
- failed evidence and empty/unclean candidate batches are refused;
- runtime observations exactly cover the vendor-neutral conformance checklist and are content-addressed;
- failed, stale, future-dated, wrong-manifest, or wrong-revision conformance receipts are refused;
- Docker policy requires a digest-pinned image, non-root user, read-only root, dropped capabilities, `no-new-privileges`, bounded CPU/RAM/PIDs/time, and no Docker socket;
- the candidate workspace is the only read-write bind;
- the primary checkout is not mutated by any test.

## 2026-08-03 integration correction: persisted approval authenticity

The original boundary accepted a `ConsumedOwnerApproval` dataclass whose
fields matched the candidate and evidence, but did not prove that this exact
consumption existed in the approval ledger. A caller could construct that
Python value directly and reach promotion authorization.

The corrected boundary treats capability objects as evidence transport, not
authority:

- public consumption accepts the signed `OwnerApproval` contract and performs
  signature, expiry, and expectation verification inside the persistence
  boundary;
- public consumption never accepts a caller-created
  `VerifiedOwnerApproval`;
- promotion recomputes the capability and consumption digests and compares all
  bound fields to the exact persisted row before entering the worktree path;
- a missing, corrupt, substituted, or internally inconsistent ledger record
  refuses promotion.

The approval tables still need consolidation under the canonical Spine/Event
Store authority before Gate-0 closure. This correction closes the dataclass
forgery path; it does not bless another independent production ledger.

## Deliberate non-goals

- migrating every production entrypoint to a central effect lease;
- claiming a complete OS security proof;
- live Claude/Codex/Ollama conformance;
- automatic approval consumption or promotion;
- closing Gate 0.
