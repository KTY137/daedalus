# Daedalus — where the truth is today

This is the one-page navigation and state boundary. It points to the artifacts
that own each claim; it does not copy live metrics into prose. A status claim is
revision-bound evidence, never timeless truth.

**MEASURED 2026-08-25 at `2de997ef` on branch `main`.** `main` is active and may
move after this measurement. Re-run the named command or inspect the named
artifact before relying on a current result.

## The canonical line is settled

| subject | authority | state |
| --- | --- | --- |
| code, tests, current docs | this repository, branch `main` | active |
| owner working checkout | `C:/Users/nukei/Desktop/agent_env` | the single active checkout |
| pre-unification checkpoint | tag `archive/checkpoint-2026-07-20-session` | frozen, read-only history |

The 2026-08-24 unification completed the 2026-08-22 owner ruling: the former
`agent_env_g0` checkout was retired, its required content was reconciled into
`main`, and the surviving checkout became `agent_env`. Text that still presents
`agent_env_g0`, a second trunk, or a live checkpoint line as current is history,
not operating guidance.

Revision-bound evidence: commits `9831ddae` and `870bfdf7` record the merge and
single-checkout transition. Neither record grants promotion or closes a gate.

## Five hops to the authoritative material

1. `README.md` — product purpose, operating model, and the rules that do not
   bend.
2. **this file** — current line, unresolved boundaries, and where to inspect
   them.
3. `docs/IKARUS_ARIADNE_MASTER_PLAN.md` — sole semantic authority. Its current
   header is Revision 7, Version 1.2.3, status `adopted`, active delivery gate
   **Gate 0 — Canonical Kernel**.
4. `docs/architecture-narrative.md` together with
   `docs/architecture-state.json` — architectural intent plus the generated,
   revision-stamped mechanical projection.
5. `docs/adrs/README.md` and `docs/adrs/` — decisions and design history. ADRs
   do not override the master plan.

The amendment chain is
`docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl`. Program detail lives in
`docs/DAEDALUS_GESAMTPLAN.md`, within the master plan's bounds.

## Delivery state

**Gate 0 remains open.** Gate 1 is not activated, and Gate 2 research cannot be
used as evidence that an earlier gate closed. The Forest-v2 fusion work merged
on 2026-08-24 remains an isolated experiment: its measured result is
inconclusive, and its presence on `main` grants no production or promotion
authority.

The repository-level execution ledger is issue #43. The Gate-0 critical path
remains represented by issues #33 through #39. Exact closure still requires the
machine-readable report, independent reviews, and an explicit owner decision;
green tests alone are not closure.

## Current exact-head evidence boundary

GitHub Actions issue #67 is still open. Earlier hosted jobs repeatedly ended
before Step 1 with no logs or artifacts; those runs are infrastructure
observations, not product evidence. The current `main` head has no PR-triggered
workflow run attached to it. A new PR must show real checkout and command steps
before #67 can be considered recovered.

Until then, do not claim hosted CI, platform-matrix, mutation, package,
fault-matrix, or release evidence from the zero-step period. Locally recorded
runs remain useful only for the exact revision and command they name.

## Architecture snapshot boundary

`docs/architecture-state.json` is now generated from branch `main`, not from the
archived checkpoint. Its current stamp is `94eb3515`, while this status
measurement is at `2de997ef`; therefore it is stale relative to current HEAD.
That is ordinary head drift, not the old wrong-branch mismatch.

Use:

```powershell
python -m daedalus.cli map --check
```

for the live verdict. Do not copy module, island, drift, or reachability counts
from the JSON unless its revision stamp matches the subject being discussed.
Regenerate only through the mapping command; the generated fields are not
hand-edited.

## Decisions that no longer wait in the pending queue

| decision | current state | evidence location |
| --- | --- | --- |
| unify on one `main` checkout | taken and executed | commits `9831ddae`, `870bfdf7` |
| migrate the control root | taken | `docs/decisions-taken/2026-08-23/control_root_migration.md` |
| bump the sealed promotion source pin | taken | `docs/decisions-taken/2026-08-23/gated_writes_lease_handdown.patch` |
| install the promotion signer root | installed | `.agentenv/promotion_allowed_signers` |

The signer file is a trust-root input, not an OwnerApproval and not permission
to promote automatically.

## Active high-signal blockers

| boundary | tracking issue |
| --- | --- |
| hosted Actions must execute real steps | #67 |
| post-provider evidence failure must remain unknown outcome | #123 |
| recovery must authenticate the original observation/provider identity | #186 |
| invoked adapter must be mechanically bound to the authenticated provider | #188 |
| provider-observation ledger writes must be inventoried and guarded | #189 |
| release closure must bind canonical repository-write inventory | #194 |

This table is a navigation aid, not an exhaustive gate report. The exact blocker
set belongs in the current machine-readable Gate-0 report.

## Where measured results live

| question | inspect |
| --- | --- |
| latest recorded watchdog/test chronology | `runs/watchdog/mission-20260822/PROGRESS.md` and `vault/Sessions/` |
| Gate-0 owner decisions and release evidence | `docs/GATE0_OWNER_DECISIONS_20260817.md` and `runs/gate0-*/` |
| current architecture projection | `python -m daedalus.cli map --check` plus `docs/architecture-state.json` |
| spend and egress reconstruction | `docs/SPEND_AND_EGRESS_COVERAGE.md` |
| historical handoff chronology | `docs/HANDOFF.md` |
| Forest-v2 experiment evidence | `experiments/forest_v2/` and its committed result artifacts |

Most of `docs/`, `runs/`, and `vault/` is evidence or history. The authoritative
entry path is deliberately small: README → STATUS → master plan → architecture
pair → ADR index.
