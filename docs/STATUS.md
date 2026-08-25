# Daedalus — where the truth is today

The one-page pointer table. It says where to look, never what the numbers are:
a status page that carries numbers is a status page that goes stale between
commits. Every claim below names the command that produced it.

**MEASURED 2026-08-25 at `2de997ef` on branch `main`.** `main` moves several
times an hour while lanes land; re-read the row, not the sha.

## The fork is closed, and there is one checkout

Work happens in `C:/Users/nukei/Desktop/agent_env`, branch `main`. That is the
whole answer. The 2026-08-22 ruling took Option A and retired the iron guard
ceremony; the 2026-08-24 unification merge `9831ddae` ("the checkpoint line
comes home") brought the archived line onto `main`, and `agent_env_g0` — the
second checkout that ruling was written against — is now a leftover directory
with no `.git` at all [MEASURED 2026-08-25: `git rev-parse` inside it fails
with *not a git repository*].

| | where | state |
| --- | --- | --- |
| truth (code, tests, docs) | `C:/Users/nukei/Desktop/agent_env`, branch `main` | active |
| pre-ruling checkpoint | tag `archive/checkpoint-2026-07-20-session` | frozen, read-only history |
| `C:/Users/nukei/Desktop/agent_env_g0` | not a repository | leftover directory, safe to ignore |

[MEASURED: `git tag -l` lists the archive tag; amendment record 7 carries
`approval_ref: owner-decision-2026-08-22-unify-on-g0-and-retire-guard` and
`result_revision: 7`; `git worktree list` shows `agent_env` as the primary
checkout.] Anything written before 2026-08-22 that describes "two lines", "the
trunk branch", or "this repo is not the truth" is history — and anything
written between 2026-08-22 and the unification that routes work to
`agent_env_g0`, **including this page's own earlier revision and the session
hook that still prints it**, is now wrong rather than merely old.

## Five hops, and what each one is for

1. `README.md` — what Daedalus is, and the rules that do not bend.
2. **this file** — where the truth is, and what is unsettled.
3. `docs/IKARUS_ARIADNE_MASTER_PLAN.md` — the sole semantic authority:
   invariants, gates, priors, delivery order. Revision 7, version 1.2.3, active
   gate **Gate 0 — Canonical Kernel** [MEASURED: file header lines 4-9].
   Its amendment chain is `docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl`,
   7 records, sequence 1..7, every `previous_record_sha256` matching its
   predecessor [MEASURED: parsed 2026-08-25]. The plan's own bytes on disk do
   **not** hash to the digest record 7 pinned; the Git blob does, exactly.
   Check a pinned document against `git show HEAD:<path>`, never against the
   file on disk — `docs/PLAN_DIGEST_EOL_FINDING.md` measures why.
4. `docs/architecture-narrative.md` — WHY the structure is what it is, paired
   with the mechanical snapshot `docs/architecture-state.json`.
5. `docs/adrs/` — the decision records, one namespace, `docs/adrs/README.md`
   first. ADRs are history/backlog: they never override the plan.

## What is unsettled, and where it waits

| open thing | where it waits |
| --- | --- |
| a vocabulary rung for "centrally started, no contract covers this effect" | `docs/decisions-pending/AMENDMENT_DRAFT_classification_rung.md` |
| B5 evidence authentication, commit 4 | `docs/decisions-pending/B5_HANDOFF_COMMIT4.md` + `b5_evidence_authentication_draft.patch` |
| section 16 does not say which bytes a plan digest is taken over | `docs/PLAN_DIGEST_EOL_FINDING.md` |
| the architecture baseline: what a re-baseline must decide first | `docs/ARCHITECTURE_BASELINE_20260825.md` |
| every surviving trace of the 2026-08-22 guard retirement, classified | `docs/GUARD_RETIREMENT_TRACES_20260825.md` -- 89 tracked files still name it; 3 agent charters ordered it as their first action (repaired), CI and CODEOWNERS repaired, policy and plan text left for the owner |
| **the plan mandates a command the plan retires** | §15 step 2 (line 550) says "Run `python tools/iron_plan_guard.py (removed 2026-08-22) verify`"; the retirement note (line 585) withdraws that guard, CI included. The note was appended without editing §15, so the constitution currently requires running a file it also deleted. Only an owner amendment can close this; no lane should pick a side [MEASURED 2026-08-25] |
| `.agentenv/agentenv.json` names six paths that no longer exist | its `policy.high_risk_paths` still lists `tools/iron_plan_guard.py (removed 2026-08-22)`, `tools/iron_plan_hook_runner.py (removed 2026-08-22)`, `tests/test_iron_plan_guard.py (removed 2026-08-22)`, `.codex/`, `.agents/skills/enforce-iron-plan/`, `.githooks/`. That file is the **mechanical veto policy** under the plan's authority table — the one artifact here that is not merely descriptive — and it is protected: `.agentenv/` is in its own `high_risk_paths`. Owner-shaped [MEASURED 2026-08-25] |
| a lane wrote 94 files under `.github/`, which the policy calls high-risk | the 170 dead guard steps were removed from `.github/workflows/` on 2026-08-25. `.github/` is listed in `policy.high_risk_paths`, and `policy.write_allow` is `["docs/", "tests/", "README.md"]`. Whether that policy binds a Claude session or only the local write lane is unsettled — every measured caller of `path_write_blocked` is a provider/offload path — but the owner's classification of `.github/` is not ambiguous, and this is recorded rather than glossed |
| signed approval root for promotion | OVERTAKEN, not decided today -- satisfied by the commit that added `.agentenv/promotion_allowed_signers`; the file moved into `docs/decisions-taken/2026-08-25/` on that date by a lane, which is a filing date, not a decision date |
| control-root migration | TAKEN 2026-08-23 -- `docs/decisions-taken/2026-08-23/control_root_migration.md` |
| sealed source pin bump for the promotion seam | TAKEN 2026-08-23 -- `docs/decisions-taken/2026-08-23/gated_writes_lease_handdown.patch` |
| the current mission and its ledger | `docs/missions/MISSION_2026-08-23.md` |
| consolidation programme this page belongs to | `docs/inventory/2026-08-21/GIGA_PLAN_2026-08-22.md` |

The pending rows are [MEASURED 2026-08-25] present in `docs/decisions-pending/`.
The signer row is worth reading even though it is closed: it records that
`.agentenv/promotion_allowed_signers` is committed **and enforced** through
`daedalus.kernel.promotion_trust_root`, so promotion is not blocked on a
signature but on `runs/spine/gate_discrimination.json` being stale at HEAD —
a measurement, not a pen stroke. It also notes, in passing, that the old reader
name `daedalus.spine.promotion_approval` no longer exists.

## The architecture snapshot cannot currently be reproduced

`docs/architecture-state.json` has moved onto `main` since the last revision of
this page — it is now stamped `repo_state.branch = "main"`, `head = 94eb3515`,
`dirty = true`, a handful of commits behind HEAD. Being behind is the least
interesting thing wrong with it. `python -m daedalus.cli map --check` exits
non-zero and names three separate defects [MEASURED 2026-08-25 at `2de997ef`]:

1. **It is self-inconsistent.** `counts.modules` says 520 while its own
   `modules` list holds 521, and the digest written beside the mechanical lists
   no longer matches them. That is the signature of a hand-edited snapshot, and
   the check says so: pre-seeding an item into `islands` is not a way to accept
   it, because an acceptance is dated and reviewed.
2. **Its scope declaration was missing.** The baseline records a
   `.daedalusignore` with digest `de1f022b`; the file had been dropped by the
   unification merge without a delete commit, so the gate refused to compare at
   all. Restored 2026-08-25 from `9831ddae^2`, byte-identical. **That restores
   configuration parity, and nothing else** — `daedalus/mapping/drift.py:180`
   states that the ignore configuration "cannot narrow what the gate sees",
   because the gate reads the tree through `reach`, which walks the filesystem
   itself. **That turned out to be true only of the path the test takes.**
   `map --check` and `map --refresh` enter through `render.analyse_once`, which
   builds a structcore index, and that index *does* apply the declaration — a
   lane's `map --refresh` the same day produced a 509-module snapshot with no
   `runs/`, `vault/` or `docs/recovery/` in it. See
   `docs/ARCHITECTURE_BASELINE_20260825.md`, addendum.
3. **The counts are still not comparable, for a worse reason.** Live:
   `modules` 1637, `islands` 78, `unreached` 115, `unknown` 29, `doc_drift` 35,
   `test_only` 42, `shims` 8. Snapshot: 520, 68, 101, 26, 32, 36, 7. The gap is
   **not** that the live run walks trees the baseline skipped — the committed
   baseline lists `docs/recovery/`, `experiments/` and `runs/` entries of its
   own [MEASURED: an earlier revision of this page claimed otherwise; it was
   refuted by opening the JSON]. The gap is that **1082 of the 1119 `.py` files
   under `runs/` are untracked** [MEASURED 2026-08-25]. Two thirds of the
   census is one machine's lane debris, so two checkouts at the same revision
   produce different island counts. The baseline is not aging; it is
   machine-local by construction.

Do not copy numbers out of that JSON. Re-baselining it is a reviewed decision,
not a docs edit — and a refresh taken today would bank one machine's untracked
lane debris as the architecture. The decision that has to come first is what
the census is taken over; `docs/ARCHITECTURE_BASELINE_20260825.md` lays out
four options and recommends deriving it from tracked files.
`map --check` reports **22 blocking items** today. The snapshot is left stale
**and labelled** rather than quietly refreshed.

## Numbers live in receipts, not here

**CI cannot be one of those receipts right now, for three independent reasons.**
They are listed in repair order, because fixing the cheap one first repairs
blind against a wall and then reads the result as success.

1. **No job is ever started.** The newest run (`32813771976`, 2026-08-25 05:40,
   a probe explicitly named "whether hosted Actions can execute real steps")
   completed as `failure` after 2 seconds with `"steps": []` — the job list is
   empty, so nothing ran [MEASURED 2026-08-25, `gh run view --json jobs`].
   Every run back to 2026-08-23 shows the same 4-second failure. This is an
   owner action in GitHub Billing, not a repository edit.
2. **94 of the 98 workflows called a deleted script.** They ran
   `python tools/iron_plan_guard.py verify`; that file was deleted by the
   unification commit `79825b57` on 2026-08-22 when the guard ceremony was
   retired, and no workflow marked the step `continue-on-error`. In 26 of the
   94 that step sat above `pytest`, in 68 it sat below [MEASURED 2026-08-25
   over all 98 files; this corrects an earlier entry on this page that
   generalized "before pytest" from a single sampled workflow]. **Removed
   2026-08-25** — 170 step lines across 94 files, completing the retirement
   note in plan revision 7, which names CI explicitly. That removal is not a
   CI repair; reason 1 still stands, and `tests/test_workflow_references.py`
   now keeps the rot from returning.
3. **Almost nothing reaches `main`.** 93 workflows do carry a `push` trigger,
   but every one of them is pinned to its own lane branch (`g0/…`,
   `g1/ignition-slice`, `core/fourfold-v2`) — and those branches were removed
   in the 2026-08-23 consolidation; 4 of 5 sampled no longer exist locally or
   on the remote. Exactly one workflow reaches `main`, on a `schedule`
   [MEASURED 2026-08-25, YAML-parsed over all 98 files].

Until a job starts, a red CI badge means nothing and a green one is not
available. Read local receipts.

| you want | read |
| --- | --- |
| what the last full suite did | `runs/watchdog/mission-20260824/PROGRESS.md` |
| whether the docs still point at files that exist | `python tools/docs_reference_check.py` |
| Gate-0 closure state | `docs/GATE0_OWNER_DECISIONS_20260817.md`, `runs/gate0-*/` |
| spend and egress coverage | `docs/SPEND_AND_EGRESS_COVERAGE.md` (`status: reconstruction`) |
| session history and handoffs | `docs/HANDOFF.md` — frozen, append-only |
| archived 2026-07-30 swarm output | `docs/archive/swarm-2026-07-30/README.md` |

`docs/` holds 683 tracked files [MEASURED 2026-08-25, `git ls-files docs`].
Most of them are evidence and history. This page and the four hops above are
the only entry points that claim to be current; `docs/README.md` is the map of
which of the other 683 are which.
