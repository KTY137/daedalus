# Status entrypoint reconciliation

- Work Packet ID: `G0-DOCS-STATUS-20260825`
- Classification: `ALIGNED`
- Active gate: Gate 0 — Canonical Kernel
- Base revision: `2de997efe73f417f2cb82260ab944c2ff9562efa`
- Delivery branch: `docs/status-reconcile-20260825`
- Authority change: none

## Problem

`docs/STATUS.md` still described the retired `agent_env_g0` checkout as the
canonical working tree, described the architecture projection as originating
from the archived checkpoint, and listed decisions as pending after their
artifacts had landed. That made the repository's prescribed first navigation
hop contradict the current `main` history.

## Scope

The packet may change only:

- `docs/STATUS.md`;
- this Work Packet.

It may reconcile revision-bound navigation and evidence pointers. It may not
change production code, tests, hooks, policy, trust roots, effect inventory,
Gate reports, OwnerApproval, promotion behavior, or gate state.

## Acceptance contract

1. The canonical delivery line is `main` and the single owner checkout is
   recorded as `C:/Users/nukei/Desktop/agent_env`.
2. The former `agent_env_g0` checkout and checkpoint line are described only as
   history.
3. The master-plan header remains Revision 7, Version 1.2.3, Gate 0.
4. The architecture snapshot is described from its actual `main` stamp
   `94eb3515`, while remaining explicitly stale against the packet base.
5. GitHub Actions issue #67 remains unresolved until a workflow records real
   steps; zero-step failures are never upgraded into product evidence.
6. Landed control-root, source-pin, and promotion-signer artifacts are not
   presented as pending decisions.
7. Gate-2 experimental results are not represented as Gate-0 or Gate-1
   authority.
8. No live metric is copied into the status page without a command or exact
   artifact owning it.

## Verification

- Read the rendered Markdown and inspect all repository-relative paths.
- Compare the status claims with the master-plan header,
  `docs/architecture-state.json`, `.agentenv/promotion_allowed_signers`, and
  commits `9831ddae` / `870bfdf7`.
- Open a PR from this branch. Its workflow allocation is the current recovery
  probe for issue #67; only jobs containing real steps count.

## Rollback

Revert the two documentation commits. No runtime state, schema, policy, or
artifact migration is involved.
