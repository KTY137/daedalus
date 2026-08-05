# Fourfold v2 Execution Plan

Status: active derived projection  
Canonical authority: `docs/IKARUS_ARIADNE_MASTER_PLAN.md` revision 3  
Active gate: Gate 0 — Canonical Kernel  
Projection base: `g0/provider-target-receipt-retention-preflight-linear` at `725c7540ead3705e0568faabdcd6d6029179c1f6`  
Branch rule: exact reviewed or explicitly frozen parent -> short-lived focused Work Packet branch -> draft PR; never mutate `main` or `experimental` directly  
Rule: this document records revision-bound status. It cannot amend the adopted Master Plan, authorize implementation, or substitute for evidence.

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

## Current Gate-0 execution boundary

This projection is bound to exact source parent
`725c7540ead3705e0568faabdcd6d6029179c1f6`, draft PR #218. It is documentation
only and cannot alter `GateReport.closed`.

The selected provider-target retention line remains a sequence of focused draft
packets rather than a collection PR:

- provider observation/invocation identity and exact broker authority were
  prepared through PRs #187, #192, #197, #199, #202, and #206;
- revision-bound executable target manifests and inert source verification were
  prepared through PRs #207, #209/#210, and #211;
- durable provider-target receipt retention was prepared in PR #212;
- its seven writes were exposed as blocking `inventory_only` surfaces in PR #213;
- a signed non-executing retention guard subject was prepared in PR #214;
- symlink and hard-link topology hardening was prepared in PR #215;
- current inventory binding and a process-free repository-HEAD receipt were
  prepared through PRs #216 and #217;
- PR #218 composes authority, provider receipt, current HEAD, current seven-row
  inventory, execution request, and inert EffectLease subject into a bounded
  two-fence read-only preflight. Its current head rejects hostile inventory-row
  subclasses and noncanonical retention paths before their methods or authority
  comparisons can be used.

PR #218 permanently reports persisted Effect-Lease verification, effect start,
retention write, canonical production registration, Gate transition, and closure
as false. Its receipt is not a capability.

The next dependent effectful packet must authenticate and consume the persisted
retention lease, rerun the preflight immediately before admission, prove concrete
Event Store and receipt-CAS targets outside the Primary Checkout, durably begin
the effect, and only then invoke retention through one centrally registered exact
entrypoint. Recovery must reconcile intent/CAS/terminal fault windows without
automatic provider or retention re-execution.

Parallel repository-write and runtime semantic drafts remain preparatory and
unmerged. Controlled integration must retain exact source identity, use a fresh
non-colliding Work Packet identity, and preserve narrow parentage.

## External execution blocker

Repository issue #67 remains open. Hosted GitHub Actions jobs allocate but fail
before Step 1 with `steps=null`, no logs, and no artifacts. Repeated workflow
runs on the current Gate-0 stack therefore contain no checkout, installation,
test, mutation, package, platform, runtime, or fault-matrix execution.

Zero-step failures are external infrastructure observations only. They are
neither passing evidence nor product-failure evidence. Until a trivial checkout
job and the Iron Plan workflow record real executed steps, no packet may claim
exact-head builder, independent review, malformed/stale, mutation, full-suite,
packaging, platform, runtime, fault-matrix, or release evidence from hosted CI.

Independent preparation may continue where it does not depend on a green parent.
Dependent production wiring, Gate closure, automatic actions, merge, promotion,
OwnerApproval, and owner closure decisions remain frozen.

## Last green evidence boundary

Historical Fourfold PR #1 recorded a green Python 3.10/3.12 and hash-seed matrix
plus Iron Plan verification for its historical subject. That evidence does not
verify the current Gate-0 retention line. The current parent remains
`prepared-unverified`; source review and machine-readable packet records preserve
scope and blockers but do not satisfy the Gate-0 release report.

## Explicit non-actions

This projection performs no production-code change, effect, provider execution,
receipt retention, repository mutation, OwnerApproval, PromotionReceipt, merge,
automatic promotion, or Gate transition. It authorizes no dependent production
packet and cannot be used as hard evidence.
