# Daedalus — where the truth is today

The one-page pointer table. It says where to look, never what the numbers are:
a status page that carries numbers is a status page that goes stale between
commits. Every claim below names the command that produced it.

**MEASURED 2026-08-22 at `f828ee58` on branch `main`.** `main` moves several
times an hour while lanes land; re-read the row, not the sha.

## The fork is settled

`main` in `C:/Users/nukei/Desktop/agent_env_g0` **is** the g0 trunk, and it is
the only line where code and tests live. The 2026-08-22 ruling took Option A;
the iron guard ceremony was retired in the same decision.

| | where | state |
| --- | --- | --- |
| truth (code, tests, docs) | this repo, branch `main` | active |
| pre-ruling checkpoint | tag `archive/checkpoint-2026-07-20-session` | frozen, read-only history |

[MEASURED: `git tag -l` lists the archive tag; amendment record 7 carries
`approval_ref: owner-decision-2026-08-22-unify-on-g0-and-retire-guard` and
`result_revision: 7`.] Anything written before 2026-08-22 that describes "two
lines", "the trunk branch", or "this repo is not the truth" is history. Read it
as evidence of what was measured then.

## Five hops, and what each one is for

1. `README.md` — what Daedalus is, and the rules that do not bend.
2. **this file** — where the truth is, and what is unsettled.
3. `docs/IKARUS_ARIADNE_MASTER_PLAN.md` — the sole semantic authority:
   invariants, gates, priors, delivery order. Revision 7, version 1.2.3, active
   gate **Gate 0 — Canonical Kernel** [MEASURED: file header lines 4-9].
   Its amendment chain is `docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl`,
   7 records, sequence 1..7 unbroken [MEASURED: parsed 2026-08-22].
4. `docs/architecture-narrative.md` — WHY the structure is what it is, paired
   with the mechanical snapshot `docs/architecture-state.json`.
5. `docs/adrs/` — the decision records, one namespace, `docs/adrs/README.md`
   first. ADRs are history/backlog: they never override the plan.

## What is unsettled, and where it waits

| open thing | where it waits |
| --- | --- |
| signed approval root for promotion | `docs/decisions-pending/promotion_allowed_signers.proposed` |
| control-root migration (the loop refuses to arm until it runs) | `docs/decisions-pending/control_root_migration.md` |
| sealed source pin bump for the promotion seam | `docs/decisions-pending/gated_writes_lease_handdown.patch` |
| this session's mission and its ledger | `docs/missions/MISSION_2026-08-22.md` |
| consolidation programme this page belongs to | `docs/inventory/2026-08-21/GIGA_PLAN_2026-08-22.md` |

The three pending decisions are [INHERITED] from `docs/HANDOFF.md` (top block,
2026-08-22); the files themselves are [MEASURED] present in
`docs/decisions-pending/`.

## The architecture snapshot is stale, and by more than a commit

`docs/architecture-state.json` is stamped
`repo_state.branch = "checkpoint/2026-07-20-session"`,
`head = afd2968d`, `dirty = true` — it was generated on the line that has since
been archived. `python -m daedalus.cli map --check` exits non-zero against it
and reports different live counts (`modules` 471 live vs 1311 in the snapshot,
`islands` 49 vs 25) under a different ignore configuration, which the check
itself flags as non-comparable [MEASURED 2026-08-22].

Do not copy numbers out of that JSON. Re-baselining it is a reviewed decision,
not a docs edit: `map --check` reports 1147 blocking items, and a `--refresh`
would bank 26 new islands in one unreviewed stroke. It is left stale **and
labelled** rather than quietly refreshed.

## Numbers live in receipts, not here

| you want | read |
| --- | --- |
| what the last full suite did | `runs/watchdog/mission-20260822/PROGRESS.md` |
| Gate-0 closure state | `docs/GATE0_OWNER_DECISIONS_20260817.md`, `runs/gate0-*/` |
| spend and egress coverage | `docs/SPEND_AND_EGRESS_COVERAGE.md` (`status: reconstruction`) |
| session history and handoffs | `docs/HANDOFF.md` — frozen, append-only |
| archived 2026-07-30 swarm output | `docs/archive/swarm-2026-07-30/README.md` |

`docs/` holds 487 tracked files [MEASURED 2026-08-22, `git ls-files docs`].
Most of them are evidence and history. This page and the four hops above are
the only entry points that claim to be current.
