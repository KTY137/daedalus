# Fourfold v2 Execution Plan

Status: active derived projection; its dated PR-chain sections below are historical (see "Current Gate-0 execution boundary")  
Canonical authority: `docs/IKARUS_ARIADNE_MASTER_PLAN.md` revision 7  
Active gate: Gate 0 — Canonical Kernel  
Branch rule: exact reviewed or explicitly frozen parent -> short-lived focused Work Packet branch -> draft PR; never mutate `main` or `experimental` directly  
Rule: this document records revision-bound status. It cannot amend the adopted Master Plan, authorize implementation, or substitute for evidence. For current Gate-0 boundary, read `docs/STATUS.md` first.

## Operating model

Daedalus production delivery proceeds through small reviewable Work Packets. Each
packet has one primary responsibility, one exact parent revision, one acceptance
matrix, builder verification, an independent adversarial perspective,
malformed-input and stale-revision tests, proportional bypass/mutation/fault
checks, affected regressions, package and isolated-wheel checks, and the supported
Python/platform matrix. Merge and promotion remain separate owner actions.

A packet may contain several small commits, but it must not become a collection
PR. Fourfold and Polyglot work is integrated through controlled ports and
compatibility adapters with retained source identity. File-tree migration is
strangler-style: move one responsibility at a time and preserve existing import
paths until caller and packaging evidence permits retirement. Big-bang renames,
broad mixed cleanup, direct changes to `main` or `experimental`, automatic merge,
automatic promotion, and fabricated OwnerApproval are forbidden.

No dependent production packet may treat an unexecuted parent as green. While an
external blocker freezes one dependency line, independent work may continue only
where correctness does not depend on that blocked result: contracts, schemas,
tests, fixtures, documentation, conservative inventories, migration plans, and
non-authorizing review preparation. Such work cannot mint `central`, `trusted`,
Gate-closure, approval, merge, or promotion claims.

LLM statements, source inspection, and review prose are hypotheses, not hard
evidence. Evidence comes from deterministic tests and compilers, schemas, runtime
probes, authenticated receipts, retained artifacts, and explicit owner decisions.

## Responsibility-led strangler boundary

New canonical implementation converges incrementally under:

- `daedalus.kernel`: canonical Mission, Attempt, Evidence, policy, budget,
  Effect-Lease, approval, promotion, event-spine, and durable identity contracts;
- `daedalus.runtimes`: Runtime Manifests, conformance, provider/runtime admission,
  Docker sandboxing, external-effect execution, terminalization, and recovery;
- `daedalus.orchestration`: typed WorkItems, mission scheduling, isolated Attempts,
  restart/replay, and bounded workflow coordination;
- `daedalus.twin`: revision-atomic Code, Type, Data, and Knowledge planes,
  repository-bound compilation, graph deltas, and round-trip reports;
- `daedalus.evolution`: non-promoting candidate search, corpus and motif contracts,
  evaluators, campaigns, and retained negative evidence.

Existing modules outside those destinations remain compatibility imports or
adapters until an isolated migration packet proves caller and wheel compatibility.

## Fourfold and Polyglot trust rule

A Fourfold snapshot is atomic on one exact source revision. Code, Type, Data, and
Knowledge planes may be `complete`, `partial`, or `absent`. Missing semantics must
retain reasons, frontend/runtime identity, provenance, and evidence locators.

A language or format adapter with incomplete symbol, type, data, or knowledge
semantics reports `partial`. Parsing, schema validity, Tree-sitter extraction,
SCIP import, indexing, or an LLM review cannot by itself establish `trusted`.
Cross-plane claims require explicit evidence and a revision-bound lifecycle.
Mixed-revision snapshots and partially published candidate snapshots refuse.

## Gate 0 — Canonical Kernel

Gate 0 remains open. A revision-bound release report may set `closed=true` only
when every machine criterion is satisfied at one exact head, including:

- adopted machine-readable reporting, exact baseline binding, and monotonicity;
- authentic OwnerApproval and separate PromotionReceipt semantics;
- persisted Effect Leases, isolated Attempts, durable start/terminal/recovery,
  and sealed Candidate/Evidence/Base-HEAD/Target-HEAD promotion binding;
- current Runtime Manifests and RuntimeConformanceReceipts;
- Docker sandbox and capability-bound effect execution evidence;
- complete canonical inventory of effectful and repository-write entrypoints;
- no production-reachable `unregistered`, `unguarded`, `inventory_only`, or
  missing-guard-contract path;
- independently replayed positive and negative guard behavior;
- complete declared fault-injection matrix;
- concrete Primary-Checkout mutation exclusion;
- exact-head full suite, package build, isolated-wheel import, supported
  Python/platform matrix, and independent adversarial review.

No current draft changes the active gate or release state.

## Gate 1 — Renovation ignition slice

Gate 1 requires the bounded `Event.voltage -> bias_voltage` renovation across
Python, Markdown, and CSV. Its exact evidence chain is:

`MissionContract -> exactly two typed WorkItems -> isolated Attempts -> restart/replay -> Candidate Source Tree in CAS -> Candidate FourfoldSnapshot -> Graph Delta -> RoundTripReport -> behavior/schema/link checks -> EvidencePacket -> separate manual Owner promotion`

No automatic promotion is permitted. Revision 3 permits isolated deterministic
rehearsal preparation while Gate 0 is active only where it cannot mutate the
Primary Checkout, consume a production approval, or represent Gate 0 as closed.

## Gate 2 — Atomic Fourfold foundation

Gate 2 requires Code, Type, Data, and Knowledge planes on one exact revision; a
conservative Forest adapter; a repository-bound compiler; Tree-sitter/SCIP-
oriented code and type frontends; Data-Plane adapters; evidence-bound Knowledge
Claims and cross-plane lifecycle; Graph Delta and round-trip APIs; regenerable
projections; a small license-audited and revision-pinned corpus pilot; and
deterministic rebuild and provenance evidence.

Incomplete Polyglot semantics remain `partial` and may never be laundered into
`trusted`. Corpus licenses, source revisions, extraction/runtime versions,
negative examples, and failed rebuilds are retained.

## Historical Fourfold packet sequence

- WP-00: Fourfold snapshot foundation; historical PR #1 evidence does not verify
  the current Gate-0 stack and owner acceptance remains a separate action.
- WP-01: GraphProposal contract and verifier.
- WP-02: atomic Fourfold compiler.
- WP-03: bounded Data-Plane extraction.
- WP-04: candidate source and round-trip reporting.
- WP-05: Gate-1 renovation slice with exactly two WorkItems.
- WP-06: license-audited corpus and motif contracts.
- WP-07: later Genesis microsoftware slice.
- WP-08: one-axis-at-a-time Ariadne experiments that retain failures and never
  auto-promote.

## Current Gate-0 execution boundary [SUPERSEDED, retained as history]

This section described a projection bound to frozen source parent
`1636a72ebf0da87ad84c7fb95c5e7fd79e5edab7` (draft PR #218, itself the tail of a
provider-target-retention packet chain #187–#217). As of this pass:
PR #218 is `CLOSED` [MEASURED 2026-08-25, `gh pr view 218`], and the branch
`g0/provider-target-receipt-retention-preflight-frozen-1636a72` no longer
exists locally or on the remote — removed in the 2026-08-23 branch
consolidation (`docs/recovery/BRANCH_CLEANUP_20260817.md`,
`docs/recovery/cleanup_2026-08-23/`). PR #218 never reported persisted
Effect-Lease verification, effect start, retention write, canonical
production registration, Gate transition, or closure as true, so nothing this
section described was ever a capability. The next effectful packet in this
line, and the current Gate-0 execution boundary, are tracked in
`docs/STATUS.md` and `docs/GATE0_OWNER_DECISIONS_20260817.md`, not here.

## External execution blocker

Repository issue #67 remains open. Hosted GitHub Actions jobs allocate but fail
before Step 1 with `steps=null`, no logs, and no artifacts. Repeated workflow
runs on the current Gate-0 stack therefore contain no checkout, installation,
test, mutation, package, platform, runtime, or fault-matrix execution.

Zero-step failures are external infrastructure observations only. They are
neither passing evidence nor product-failure evidence. Until a trivial checkout
job records real executed steps, no packet may claim exact-head builder,
independent review, malformed/stale, mutation, full-suite, packaging, platform,
runtime, fault-matrix, or release evidence from hosted CI. (The former "Iron
Plan workflow" step no longer exists — retired 2026-08-25 along with the guard
it ran; see `docs/STATUS.md`.)

Independent preparation may continue where it does not depend on a green parent.
Dependent production wiring, Gate closure, automatic actions, merge, promotion,
OwnerApproval, and owner closure decisions remain frozen.

## Last green evidence boundary

Historical Fourfold PR #1 recorded a green Python 3.10/3.12 and hash-seed matrix
for its historical subject (predating the 2026-08-22 guard retirement, so it
still ran the since-removed Iron Plan verification step). That evidence never
verified the PR #187–#218 retention line described above, which is itself now
closed. Source review and machine-readable packet records preserve scope and
blockers but do not satisfy the Gate-0 release report.

## Explicit non-actions

This projection performs no production-code change, effect, provider execution,
receipt retention, repository mutation, OwnerApproval, PromotionReceipt, merge,
automatic promotion, or Gate transition. It authorizes no dependent production
packet and cannot be used as hard evidence.
