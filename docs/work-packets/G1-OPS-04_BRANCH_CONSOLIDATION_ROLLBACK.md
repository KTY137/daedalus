# G1-OPS-04 — Branch consolidation rollback

Status: **implemented; verification pending**

Iron Plan: **ALIGNED**
Iron Gate: **1**
Primary issue: **#42**
Rollback targets: **#297, #299, #300, #301 and direct reintroductions through
`d8e496e8`**

## Acceptance claim

Remove the unexecuted repository-write automation introduced for the
2026-08-30 branch cleanup before it can close pull requests, commit a manifest,
or delete refs outside Daedalus' canonical effect boundary.

## Baseline and retained failure

The one-shot and PR-closed attempts all failed before Step 1 with an empty step
list, or were skipped by their job condition. Consequently no recovery manifest
was written and no branch was deleted. Post-merge review then identified
release-blocking policy bypass, TOCTOU, reachability, fork-ref, rerun, and
partial-batch failure modes. #300 added archive tags and therefore repaired the
original reachability defect, but left the effect-boundary, compare-and-swap,
rerun, and atomic-batch defects open. #301 and later direct commits restored or
retriggered variants of the same noncanonical path. The latest restored
one-shot workflow was manually disabled and had zero runs; its PR-close trigger
was removed at `4aabe8d8`. A final-runner variant then produced two failed runs,
each retried once, with `runner_id=0` and empty step lists. Both workflow IDs
were disabled before removal. The failed approach and exact hosted-run metadata
remain in `docs/recovery/BRANCH_CONSOLIDATION_ARM_20260830.md` and
`docs/recovery/BRANCH_CONSOLIDATION_FAILED_RUNS_20260830.json`.

## In scope

- remove every remaining branch-consolidation workflow and trigger;
- remove the standalone effectful GitHub mutation script;
- capture and retire historical Actions run IDs that could re-execute the old
  privileged workflow SHA;
- retain an honest non-executable failure record;
- verify that no remaining workflow or tool references the retired entrypoint.

## Out of scope

- deleting or moving any Git ref;
- closing or merging any pull request;
- changing the Masterplan, policy, evaluator, ledger, or promotion path;
- claiming that SHA strings alone preserve unreachable Git objects.

## Acceptance matrix

1. `git grep` finds no executable branch-consolidation workflow or runner.
2. Workflow YAML parsing and the existing desktop packaging tests remain green.
3. `git diff --check` is clean.
4. Branch and PR counts are unchanged by this packet.
5. Every captured historical run returns HTTP 404 after its run surface is
   retired; the retained evidence records all attempts and empty step lists.
6. Independent review confirms that the packet adds no effectful entrypoint.
7. Workflow ID `345762808` is disabled with zero post-restoration runs before
   its YAML is removed.
8. Workflow ID `345773763` is disabled; both of its run IDs are captured and
   return HTTP 404 after retirement.

## Rollback

Never wholesale-revert this packet: restoring the retired trigger and workflow
files can execute the unsafe repository-write path on the revert push itself.
Supersede it only through a new owner-approved Work Packet that introduces a
different canonical repository-write operation with compare-and-swap ref
deletion, durable object reachability, full-batch preflight, authenticated
receipts, and no restoration of these retired entrypoints.
