# Fourfold v2 Execution Plan

Status: active derived projection  
Canonical authority: `docs/IKARUS_ARIADNE_MASTER_PLAN.md` revision 3  
Active gate: Gate 0 — Canonical Kernel  
Projection base: `g0/provider-target-receipt-retention-preflight-linear` at `b7cb2fe21dd365ea73fae778e77ac7ccdc595321`  
Branch rule: exact reviewed or explicitly frozen parent -> short-lived focused Work Packet branch -> draft PR; never mutate `main` or `experimental` directly  
Rule: this document records revision-bound execution status and evidence. It cannot amend or override the adopted Master Plan.

## Operating model

Daedalus production delivery proceeds through small, reviewable Work Packets. A
packet has one primary responsibility boundary, one exact parent revision, one
acceptance matrix, builder verification, an independent adversarial perspective,
proportional malformed/stale/bypass/fault checks, affected regressions, packaging,
and supported-platform checks. Merge and promotion remain separate owner actions.

A packet may contain several small commits, but it must not become a collection
PR. Fourfold and Polyglot work is integrated through controlled ports or adapters
with retained source identity and explicit completeness states. File-tree
migration is strangler-style: one responsibility moves at a time while existing
import paths remain compatibility adapters until callers and packaging evidence
permit retirement.

No dependent production packet may treat an unexecuted or failed parent as green.
When an external blocker freezes a dependency line, independent work may continue
only where correctness does not depend on that blocked result: static and
adversarial review, contracts, schemas, tests, fixtures, documentation,
conservative inventories, migration plans, and non-authorizing evidence
preparation. Such preparation is not executable verification and cannot mint
`central`, `trusted`, Gate-closure, approval, merge, or promotion claims.

Every implementation packet follows this order:

1. freeze scope, exclusions, exact parent, and acceptance matrix;
2. reproduce the revision-bound baseline and known blockers;
3. build in an isolated short-lived branch or worktree;
4. run focused unit, contract, determinism, restart/replay, and integration checks;
5. perform independent architecture/security/adversarial review;
6. run malformed-input, stale-revision, bypass, mutation, and proportional fault tests;
7. run affected legacy suites, package build, isolated-wheel import, and platform matrix;
8. retain machine-readable evidence, residual risks, rollback, and next prerequisites;
9. request owner review without automatic merge or promotion.

LLM statements, source inspection, and review prose are hypotheses and criticism,
not hard evidence. Hard evidence comes from deterministic tests, compilers,
schemas, runtime probes, signed or authenticated receipts, retained artifacts,
and explicit owner decisions.

## Responsibility-led strangler boundary

New canonical implementation converges incrementally under:

- `daedalus.kernel` for canonical contracts, event spine, policy, evidence,
  attempts, leases, approvals, promotion authority, and durable identity;
- `daedalus.runtimes` for Runtime Manifests, conformance, provider/runtime
  admission, sandboxing, external-effect execution, and recovery;
- `daedalus.orchestration` for mission planning, typed WorkItems, scheduling,
  restart/replay, and bounded workflow coordination;
- `daedalus.twin` for revision-atomic Code, Type, Data, and Knowledge planes,
  graph deltas, round-trip reports, and repository-bound compilation;
- `daedalus.evolution` for non-promoting candidate search, corpus/motif contracts,
  evaluators, campaigns, and retained negative evidence.

Existing modules outside those boundaries may remain as compatibility imports and
adapters. A Work Packet may move one responsibility and add one adapter. Big-bang
renames, broad file moves, import-path deletion without compatibility evidence,
and mixed architectural cleanup are forbidden.

## Fourfold and Polyglot trust rule

A Fourfold snapshot is atomic on one exact source revision. Code, Type, Data, and
Knowledge planes may be `complete`, `partial`, or `absent`; missing semantics must
retain reasons, frontend/runtime identity, provenance, and evidence locators.

A language or format adapter with incomplete symbol, type, data, or knowledge
semantics reports `partial`. It may never claim `trusted` merely because parsing,
schema validation, indexing, Tree-sitter extraction, SCIP import, or an LLM review
succeeded. Cross-plane claims require explicit evidence and a revision-bound
lifecycle. Mixed-revision snapshots and partially published candidates refuse.

## Gate sequence

### Gate 0 — Canonical Kernel

Gate 0 remains open. Its release report may set `closed=true` only when all
revision-bound machine criteria are satisfied at one exact head, including:

- adopted and monotonic machine-readable Gate baseline/reporting;
- authentic OwnerApproval and separate PromotionReceipt semantics without a
  fabricated approval or automatic promotion path;
- persisted Effect Leases, isolated Attempts, durable start/terminal/recovery
  semantics, and sealed candidate/evidence/base-HEAD/target-HEAD promotion binding;
- Runtime Manifests and current RuntimeConformanceReceipts;
- Docker sandbox evidence and capability-bounded effect execution;
- a complete canonical inventory of effectful and repository-write entrypoints;
- no production-reachable `unregistered`, `unguarded`, `inventory_only`, or
  missing-guard-contract route;
- independently replayed positive and negative guard behavior;
- complete fault-injection coverage for declared failure windows;
- concrete Primary-Checkout mutation exclusion;
- full suite, packaging, isolated-wheel, supported Python/platform matrix, and
  independent adversarial review on the exact release subject.

No current draft, including this projection, changes the active gate or release
state.

### Gate 1 — Renovation ignition slice

Gate 1 requires the bounded `Event.voltage -> bias_voltage` renovation across
Python, Markdown, and CSV. The exact evidence chain is:

`MissionContract -> exactly two typed WorkItems -> isolated Attempts -> restart/replay -> Candidate Source Tree in CAS -> Candidate FourfoldSnapshot -> Graph Delta -> RoundTripReport -> behavior/schema/link checks -> EvidencePacket -> separate manual Owner promotion`

No automatic promotion is permitted. Revision 3 allows isolated deterministic
rehearsal preparation while Gate 0 is active only where it cannot mutate the
Primary Checkout, consume a production approval, or represent Gate 0 as closed.

### Gate 2 — Atomic Fourfold foundation

Gate 2 requires Code, Type, Data, and Knowledge planes on one exact revision; a
conservative Forest adapter; a repository-bound compiler; Tree-sitter/SCIP-
oriented code/type frontends; Data Plane adapters; evidence-bound Knowledge
Claims and cross-plane lifecycle; Graph Delta and round-trip APIs; regenerable
projections; a small license-audited and revision-pinned corpus pilot; and
deterministic rebuild/provenance evidence.

Incomplete Polyglot semantics remain `partial` and can never be laundered into
`trusted`. Corpus licenses, source revisions, extraction/runtime versions, and
negative examples are retained.

## Historical Fourfold work packets

| Packet | Purpose | Current projection |
| --- | --- | --- |
| WP-00 | Fourfold snapshot foundation | implemented historically in PR #1; independent owner decision remains separate |
| WP-01 | GraphProposal contract/verifier | prerequisite for general graph changes; not Gate-2-complete |
| WP-02 | atomic Fourfold compiler | required for one-revision publication and deterministic rebuild |
| WP-03 | minimum viable Data Plane | must cover bounded Python/CSV/schema subjects without inferred truth |
| WP-04 | candidate round-trip reporting | must distinguish structural conformance from behavior |
| WP-05 | Gate-1 renovation slice | requires exactly two WorkItems and manual promotion |
| WP-06 | corpus and motif contracts | license-audited, pinned, experimental until Gate 2 |
| WP-07 | Genesis microsoftware slice | later gate; no broad build-anything claim |
| WP-08 | Ariadne experiments | one changed axis per campaign; retain all failures; never auto-promote |

## Current Gate-0 execution boundary

This projection is bound to exact source parent
`b7cb2fe21dd365ea73fae778e77ac7ccdc595321`, draft PR #218. It is status
documentation only and cannot alter `GateReport.closed`.

The current selected provider-target retention line is a sequence of small draft
packets rather than one collection PR:

- signed provider invocation/observation identity and exact runtime broker
  authority were prepared through PRs #187, #192, #197, #199, #202, and #206;
- revision-bound executable target manifests and inert structural source
  verification were prepared through PRs #207, #209/#210, and #211;
- durable provider-target receipt retention was prepared in PR #212;
- the seven retention writes were made visible as blocking `inventory_only`
  surfaces in PR #213;
- a signed, non-executing retention guard subject was prepared in PR #214;
- topology hardening rejected symlink and hard-link alias exposure in PR #215;
- the inventory binding was refreshed to current bytes/revision in PR #216;
- the generic process-free repository HEAD receipt was ported in PR #217;
- PR #218 composes signed authority, current HEAD, current inventory, provider
  receipt, execution request, and inert EffectLease subject into a bounded
  two-fence read-only preflight, then hardens exact scope strings and exact
  retention-surface types at current head `b7cb2fe...`.

PR #218 permanently reports that persisted Effect-Lease verification, effect
start, retention write, canonical production registration, Gate transition, and
closure are false. Its receipt is not a capability. The next dependent effectful
packet must authenticate and consume the persisted retention lease, rerun the
preflight immediately before admission, prove concrete Event Store and receipt
CAS targets outside the Primary Checkout, durably begin the effect, then invoke
retention under a centrally registered exact entrypoint. Recovery must reconcile
intent/CAS/terminal fault windows without automatic provider or retention
re-execution.

Parallel repository-write and runtime semantic drafts remain preparatory and
unmerged. They cannot be aggregated into a collection PR or represented as a
single verified release line. Controlled ports must retain exact source identity,
new non-colliding Work Packet identity, and narrow parentage.

## External execution blocker

Repository issue #67 remains open. Hosted GitHub Actions jobs allocate but fail
before Step 1 with `steps=null`, no logs, and no artifacts. On the immediately
preceding PR #218 head, workflow run `30979140519` created the requested focused,
predecessor, mutation, full-suite, package/isolated-wheel, Python, and platform
jobs, but no checkout or command executed. The current hardened head has no
accepted executable evidence.

These zero-step failures are external infrastructure observations only. They are
neither passing evidence nor product-failure evidence. Until a trivial checkout
job and the Iron Plan workflow record real executed steps, no packet may claim
exact-head builder, independent review, malformed/stale, mutation, full-suite,
packaging, platform, runtime, fault-matrix, or release evidence from hosted CI.

Independent preparation may continue where it does not depend on a green parent.
Dependent production wiring, Gate closure, automatic action, merge, promotion,
OwnerApproval, and owner closure decisions remain frozen.

## Current last green evidence boundary

Historical Fourfold PR #1 recorded a green Python 3.10/3.12 and hash-seed matrix
plus Iron Plan verification for its exact historical subject. That historical
evidence does not verify the current Gate-0 stack. For the current retention line,
no exact-head hosted executable evidence is available after issue #67 began.

The current parent therefore remains `prepared-unverified`. Source review and
machine-readable packet records preserve scope and blockers, but they do not
satisfy the Gate-0 release report.

## Explicit non-actions

This projection performs no production-code change, effect, provider execution,
receipt retention, repository mutation, OwnerApproval, PromotionReceipt, merge,
automatic promotion, or Gate transition. It authorizes no dependent production
packet and cannot be used as hard evidence.
