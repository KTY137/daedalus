# G1-OPS-05 — Local recovery-first branch consolidation

Status: **completed; independent verification pending**

Iron Plan: **ALIGNED**
Iron Gate: **1**
Primary issue: **#42**

## Acceptance claim

Reduce the remote branch topology from 128 heads to the owner-recorded 11-head
target without GitHub Actions and without losing any retired tip.

This packet is repository maintenance, not a claim that archived feature work
was merged, verified, or promoted.

## Effect boundary

The operation was performed once from the authenticated owner checkout. It did
not install a reusable mutation entrypoint. Before deletion, every retiring tip
was verified as an ancestor of `archive/legacy-20260830@057f96cb`. The delete
was one atomic Git push with an exact `--force-with-lease=<ref>:<sha>` guard for
each of the 117 retiring refs.

## Measured result

- preflight: 128 heads, 11 keep refs, 117 retire refs;
- recoverability: 117/117 retire tips reachable through archive ancestry;
- pull-request safety: 0 open PR heads or bases outside the keep set;
- mutation: one atomic push, 117/117 deletions accepted;
- postcondition: exactly 11 remote heads;
- Actions consumption: none.

The machine-readable receipt is
`docs/recovery/LOCAL_BRANCH_CONSOLIDATION_20260830.json`. The original 123-head
mapping remains in `docs/recovery/REMOTE_BRANCH_CONSOLIDATION_20260830.json`;
the four later arm refs are recorded explicitly in the local receipt.

## Recovery

Recreate a retired ref only after owner review. Resolve its exact SHA from the
base manifest or the local receipt, verify that SHA is an ancestor of
`archive/legacy-20260830`, and create a new reviewed recovery branch. Archive
reachability does not itself authorize integration or promotion.
