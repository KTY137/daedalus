# Daedalus Project Execution

This document is the operational index for repository work. It does not replace
`docs/IKARUS_ARIADNE_MASTER_PLAN.md`; the Iron Plan remains the sole semantic
authority for architecture, invariants, product order, and delivery gates.

## Current control state

| Dimension | Current state |
| --- | --- |
| Active delivery gate | **Gate 0 — Canonical Kernel** |
| Authoritative plan | `docs/IKARUS_ARIADNE_MASTER_PLAN.md` |
| Integration truth | `experimental` after reviewed, plan-compliant merges |
| Gate-1 status | Rehearsal evidence only; blocked on Gate-0 closure |
| Gate-2 status | Experimental evidence only; no closure or promotion claim |
| Promotion | Owner-only, evidence-bound, never automatic |

A later gate may produce read-only or isolated evidence while Gate 0 is open,
but it may not claim authoritative activation, closure, promotion, or completion.

## Execution ledger

GitHub Issues are the canonical operational backlog. Every implementation pull
request must link exactly one primary Work Packet issue. Cross-cutting evidence
may be referenced by additional issues, but a PR must still have one accountable
owner and one primary deliverable.

| Work Packet | Purpose | Current evidence | State |
| --- | --- | --- | --- |
| `G0-PKG-01` | Consolidate the bounded Gate-0 package and artifact identity | PRs #1 and #16 | In review / consolidation |
| `G0-GOV-02` | OwnerApproval and sealed promotion authority | PRs #5 and #13 | Implemented evidence; closure pending |
| `G0-EFX-03` | Persisted Effect Leases and central effect routing | PRs #6 and #13 | Partial; production entrypoints remain |
| `G0-RCP-04` | Durable receipts, replay, and idempotency | PRs #13 and #16 | Partial; complete ledger proof pending |
| `G0-SBX-05` | Sandbox security boundary | PR #13 | Partial; host/runtime validation pending |
| `G0-RTC-06` | Runtime conformance for Claude, Codex, and Ollama | PR #13 | Partial; live receipts pending |
| `G0-FLT-07` | Complete fault matrix | PR #15 | Deterministic foundation; host campaign pending |
| `G0-RPT-08` | Exact-head machine-readable Gate-0 report | PR #3 | Implemented foundation; closure report pending |
| `G0-CLO-09` | Independent reviews and owner closure decision | none | Blocked |
| `G1-IGN-01` | Controlled `voltage -> bias_voltage` renovation | PR #14 | Rehearsal only; blocked by Gate 0 |
| `G2-TWIN-01` | Project Twin / Genesis consolidated evidence line | PR #30 | Experimental; blocked by Gate 0 and Gate 1 |

The table is an index, not a status authority. The linked issue, exact commit,
CI evidence, review receipts, and gate report determine the actual state.

## Pull-request topology

### Active delivery line

Gate 0 is the only active delivery line. Gate-0 changes must reduce the blocker
set monotonically and may not introduce a new unregistered effectful entrypoint.

### Historical and stacked evidence

The following pull requests currently form a stacked evidence history:

- #1 — Fourfold v2 foundation and plan amendment;
- #2 — temporary workspace bootstrap; not intended for merge;
- #3, #5, #6, #7, #13, #15, #16 — Gate-0 implementation and evidence slices;
- #14 — non-promoting Gate-1 rehearsal;
- #30 — sole active consolidated Gate-2 experimental line.

Do not close, merge, retarget, or delete a branch merely because it is old. First
record whether its commits are contained by a successor, whether its CI evidence
must be retained, and whether another open PR still uses it as a base.

## Required issue states

Use these state names consistently in issue titles, project fields, or comments:

- `Backlog` — accepted work, not yet ready;
- `Ready` — dependencies and acceptance criteria are complete;
- `In progress` — one owner is actively working the packet;
- `In review` — implementation is frozen except for review fixes;
- `Blocked` — a named dependency prevents progress;
- `Done` — acceptance criteria and required evidence are satisfied;
- `Archived` — retained as history, not an active merge candidate.

`Done` never implies gate closure unless the exact gate report and owner decision
also say so.

## Work-Packet contract

Every Work Packet must define:

1. identifier and active gate;
2. exact objective and non-goals;
3. base revision and write scope;
4. hard invariants;
5. dependencies and blockers;
6. acceptance criteria and test thermometer;
7. effect, egress, secret, and promotion impact;
8. required reviewers;
9. rollback path;
10. evidence locators or exact CI runs.

One writer owns a Work Packet at a time. Parallel writers require separate
worktrees or candidate repositories and disjoint write scopes.

## Branch policy

Use short-lived branches tied to a Work Packet:

```text
g0/<deliverable>
g1/<deliverable>
g2/<experimental-deliverable>
plan/<amendment>
chore/<repository-governance>
exp/<bounded-experiment>
```

No direct push to `main` or `experimental`. Avoid long-lived generic feature
branches. A branch without an issue, owner, or declared outcome is housekeeping
debt and should be classified before further work.

## Review and merge rules

A pull request is merge-eligible only when:

- its Work Packet issue is linked and current;
- the Iron Plan classification and active gate are stated;
- scope and non-goals are explicit;
- exact tests and evidence are attached;
- review conversations are resolved;
- trust, runtime, effect, evaluator, or promotion changes have independent review;
- rollback is defined;
- the target branch and stack order are unambiguous;
- no later-gate claim hides an unfinished earlier gate.

A green CI run is evidence, not owner approval and not promotion authority.

## Housekeeping sequence

Repository cleanup must happen in this order:

1. map each open PR to a Work Packet;
2. identify the sole active merge candidate for each line;
3. verify successor commit containment;
4. mark historical PRs as superseded or archival evidence;
5. close no-merge helpers;
6. retarget or merge the required stack in plan order;
7. delete branches only after all dependent PRs are closed and evidence is retained.

This sequence prevents visual cleanup from destroying the actual dependency or
evidence chain.
