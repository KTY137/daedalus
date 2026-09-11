# Fourfold v2 Execution Plan

Status: active derived projection; its dated Gate-0 and PR-chain sections below are historical
Canonical authority: `docs/IKARUS_ARIADNE_MASTER_PLAN.md` revision 11
Active gate: Gate 1 - Renovation and owner-directed Genesis
Branch rule: exact reviewed or explicitly frozen parent -> short-lived focused Work Packet branch -> draft PR; never mutate `main` or `experimental` directly  
Rule: this document records revision-bound status. It cannot amend the adopted Master Plan, authorize implementation, or substitute for evidence. For the current Gate-1 boundary, read the Master Plan and `docs/STATUS.md` first.

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


## Loop status 2026-09-05 (STATUS, revision-bound; not a gate decision)

Owner-directed 10-minute loop, deliver in stages, Codex as co-author and
reviewer. Uncommitted on `codex/ikarus-computer-assistant-20260905`:

- Stage 1 `G1-ARIADNE-03`: the Ariadne frozen evaluator could never nominate
  on the Windows host (venv launcher stub wrote a warning into the merged gate
  log). Fixed at the spawn site; unfaked integration test; council-reviewed.
- Stage 2 `G1-KERNEL-01`: shared `daedalus/kernel/interpreter.py`; Genesis
  switched by Codex; NUL-stdin containment experiment retained as evidence;
  three Ariadne-02 review findings closed; council live path now installs the
  budget net first (an unpriced bypass by this session is disclosed there).
- Stage 2b `G1-COUNCIL-01`: `cli.council` registered as an effectful door.
- Stage 3 `G1-ARIADNE-04` (isolated worktree branch `loop/stage3-failed-receipt`,
  commit 9d37ff0d, not merged): a campaign-domain arm failure returns the
  retained `failed` receipt on the first call instead of re-raising; stage
  suites 129 passed; Codex review requested.
- Stage 4 `G1-ARIADNE-05` (same branch, commit 93ee7507): honest working-tree
  base binding as a receipt provenance input, read/verify race closed, no
  dirty-target refusal (raw byte compares lie under line-ending filters);
  stage suites 143 passed.
- Stage 5 `G1-SELF-00` (EXPERIMENT, same branch): the canonical Ariadne
  campaign nominated a one-file repair of Daedalus itself against a clone at
  the release commit; nomination retained, nothing applied or promoted. Two
  refusals retained: linked worktrees are not accepted as subjects by the HEAD
  verifier; an override control root against a repository with an existing
  spine refuses as partial state.
- Stage 6 `G1-ARIADNE-06`: the two refusals above name cause and remedy;
  the worktree exclusion is recorded as deliberate (measured pointer-rewrite
  attack; Momus critique).
- Stage 7 `G1-GENESIS-REHEARSAL-01` (EXPERIMENT): `daedalus genesis "kanban
  board"` on this host reaches preview-ready with all gates passing in 0.5 to
  1.2 s each and no launcher warning, against the morning's 16 to 31 s and a
  runtime timeout with the launcher stub. Stage 8 A/B with the stub: also
  preview-ready, 2.2x to 4.0x slower per contained gate, warning line in every
  output, no timeout on a quiet host; the stub is a proven cost, not the
  proven cause of the morning timeouts.
- Stage 9 (same packet): all four Genesis targets measured on this host;
  web/desktop/mobile preview-ready (PWA labelling retained as blockers), cli
  refuses the kanban blueprint before any effect and succeeds for the
  item-collection product with its black-box gate.
- Stages 10-11 `G1-EDA-HOST-STATUS-01` (EXPERIMENT): the existing chip-design
  slice on this host reports only tclsh available (Vivado/Vitis/XSCT/Quartus/
  Yosys/OpenROAD/simulators honestly unavailable, no fallback); effect-free
  scan/inspect/plan on a generated minimal XPR bind deterministic identities
  and leave the fixture unchanged. No second self-Renovation target: the only
  refuted claim found lives in CLAUDE.md, a protected file a candidate may
  not touch.
- Owner lifted the budget at 15:15 (unbounded_execution policy for this
  session's processes). Stage 12 `G1-ARIADNE-07`: the live two-seat council
  (Codex, Claude; 24 checkable claims, two rounds, through the registered
  `cli.council` door, both seats in the ledger) over the stage 3-6 diff is
  answered in code and eleven tests (commit dda7f41d, same branch).
- Stage 13 `G1-IKARUS-26`: the general computer loop of section 7.2 was run
  live for the first time (local Ollama 7B planner, scratch clone, fresh
  control root, static page on a loopback origin). Two defects measured and
  fixed with six tests: a configured policy whose every tool is release-locked
  (v0.1.6 path-I/O lock) was reported as a missing policy; and identical
  advisory plans were no stall, so under the owner's unbounded policy the
  planner repeated one plan eleven times until the kill switch ended the run
  (55 s after the stop; verified). No run reached `finish`: the 7B planner
  never proposed `browser.read` after navigating; on this host two planner
  calls consume a 300 s bounded mission. Codex reviewed statically (room,
  16:49): both fixes ALIGNED; paraphrased plans and cancellation inside a
  running provider call stay open.
- Stage 14 (owner order 17:33, "starte 10 opus agenten"): ten Opus lane
  agents in isolated worktrees, exclusive paths, each with a packet; verified
  one by one and stacked on this branch by cherry-pick with the registry
  re-derived once per batch. Integrated: `G1-IKARUS-29` (plan budget of four
  plans per step, wall-time check before the effect), `G1-ARIADNE-08` (blob
  bytes at a commit without the git binary, pure stdlib, not wired; the two
  Odysseus defects, REF_DELTA depth reset and NTFS-junction `.git`, fixed
  forward with forged-pack tests, 65 passed), `G1-ARIADNE-09` (one exit-code contract for both Ariadne CLI
  doors, sysexits 64/70, JSON error line), `G1-TESTS-01` (the flaky shell
  test spawned a real vendor CLI; pinned voice, 259 s to 8.6 s), `G1-SELF-01`
  (EXPERIMENT: second self-Renovation nomination, `daedalus/build.py`
  docstring names a class that does not exist, repo-own resolver as frozen
  gate; nothing applied), `G1-HW-01` (EXPERIMENT: effect-free KiCad
  status/scan/inspect/plan, 148 tests, all toolchains honestly absent on this
  host), `G1-IKARUS-30` (desktop and OCR adapters measured live through
  `ComputerService`, 17 effects, four adapter findings, no image retained),
  and the adversarial review of stage 13 (both claims hold; manifest digests
  were unpinned against CRLF checkouts, now `-text` pinned with a test over
  every evidence manifest), and `G1-KERNEL-02` (an in-flight provider call
  runs on a daemon worker so the caller can stop waiting on a cancellation
  probe; no socket teardown, `timeout_s` untouched, no new cap axis; the
  budget interposer's per-thread mark is carried to the worker; measured on
  the way: Ollama's `/v1` endpoint ignores `keep_alive` and pins
  `context_length` 4096, evicting a natively warmed instance, so routing the
  computer planner through the native path is the next packet). Also integrated: `G1-EDA-HOST-STATUS-02` (EXPERIMENT: deterministic
  Vivado batch and Vitis HLS Tcl emitted inline or to stdout from the effect-free
  `plan`, pure-Python `info complete` check agreeing 35/35 with tclsh 8.6, all
  vendor tools honestly absent; a first version wrote a file from `plan` beside
  the door's anchor and was fixed forward with an isolation suite). All ten
  lanes are integrated.
- Stage 15 `G1-IKARUS-31`: schema-constrained Ollama calls (the computer
  planner) take the native `/api/chat` route with keep_alive, num_ctx and the
  output cap as num_predict; the loop hands the planner a cancellation probe
  (G1-KERNEL-02); the transport is an explicit caller decision. Live: 25.5 s
  per planner call against 74 to 125 s before; measured residual: a mixed
  chat/planner session still reloads on 3 of 4 transport switches, so the
  native route for all voices is the follow-up; the 7B planner still never
  proposes `browser.read` after navigating.
- `docs/AMENDMENT_PROPOSAL_013_HARDWARE_TARGETS_AND_SELF_RENOVATION.md` drafted
  (Ikarus persistence, self-Renovation with leakage rule, KiCad and
  Vivado/Vitis targets); awaiting owner approval; the master plan is untouched.

Gate 1 remains active. Nothing here closes a gate, promotes, or merges.
