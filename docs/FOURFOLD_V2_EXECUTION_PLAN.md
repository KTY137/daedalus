# Fourfold v2 Execution Plan

Status: active derived projection  
Canonical authority: `docs/IKARUS_ARIADNE_MASTER_PLAN.md` revision 3  
Active gate: Gate 0 — Canonical Kernel  
Projection base: `g0/repository-write-stdlib-delta-linear` at `f78e4c53fb5ac21d90a34a2fe6cd8f6da679ab14`  
Branch rule: exact reviewed or explicitly frozen parent -> short-lived focused Work Packet branch -> draft PR; never mutate `main` or `experimental` directly  
Rule: this document records execution status and evidence; it cannot override the Iron Plan.

## Operating model

Daedalus is developed through one active Work Packet per dependency line. Within
one dependency line, packets remain sequential: one major architectural axis,
one acceptance matrix, one builder, one independent review pass, and one explicit
owner decision. Independent lines may prepare read-only inventories, tests,
fixtures, schemas, or documentation while another line is externally blocked,
but they may not establish a second implementation truth or begin dependent
production work from an unverified parent.

A packet may be split into smaller commits, but its PR must not mix unrelated
feature work, broad cleanup, dependency migration, evaluator changes, or policy
amendments. The owner-requested revision-2 amendment in WP-00 remains a retained
foundational transaction. The adopted revision-3 amendment additionally permits
one bounded, isolated, non-promoting Gate-1 rehearsal while Gate 0 remains active;
it does not relax Gate-0 closure, review, runtime-evidence, or owner-decision
requirements.

Every packet follows:

1. freeze packet scope and base revision;
2. reproduce the baseline and known failures;
3. implement in an isolated branch/worktree;
4. run focused unit, contract, determinism, packaging, and integration tests;
5. perform independent architecture/security review;
6. run proportional fault injection and stale-revision tests;
7. run affected legacy suites and platform matrix;
8. publish evidence, residual risk, rollback, and next prerequisites;
9. merge only after owner approval.

No dependent packet enters build while its parent is red or unreviewed unless the
parent is explicitly frozen as a documented external blocker and the new packet
is genuinely independent. Read-only research and preparation may continue, but
cannot establish another implementation truth or be represented as executable
verification.

## Review roles

The roles are logical responsibilities; one runtime may not approve its own work.

- **Planner:** freezes Work Packet, contracts, exclusions, acceptance matrix.
- **Builder:** implements only the packet scope and records assumptions.
- **Contract reviewer:** checks canonical identity, serialization, provenance,
  revision binding, refusal semantics, and migration compatibility.
- **Adversarial reviewer:** searches for bypasses, stale-state acceptance,
  evaluator contamination, unbounded effects, and false success.
- **Verifier:** runs deterministic commands and retains outputs/receipts.
- **Owner:** accepts, rejects, or requests another bounded packet.

LLM reviewers provide hypotheses and criticism. Tests, compilers, schemas,
runtime probes, and owner decisions remain the evidence/promotion boundary.

## WP-00 — Fourfold snapshot foundation

Status: implemented and builder-verified in PR #1; required CI is green; independent review and explicit owner decision remain open.

Scope:

- canonical `PlaneSnapshot`, `CrossPlaneBinding`, and `FourfoldSnapshot`;
- exact four-plane membership and source-revision binding;
- explicit `complete`, `partial`, and `absent` states;
- conservative `KnowledgeForest -> FourfoldSnapshot` projection;
- strict parsing, immutable inputs, deterministic digest, packaging matrix.

Acceptance:

- same canonical input produces identical JSON/digest across hash seeds;
- missing Data Plane is `absent` with reason, never silently empty-success;
- unknown node kinds and dangling/unverified bindings refuse;
- built wheel imports `daedalus.twin`;
- existing kernel-contract tests remain green;
- Iron Plan tests and history verification are green.

Rollback: remove `daedalus.twin`, its tests, package entry, and focused workflow;
no production path currently depends on it.

## WP-01 — GraphProposal contract and verifier

Prerequisite: WP-00 green and reviewed.

Build:

- `GraphOperation` tagged union with a deliberately small first vocabulary:
  `add_binding`, `remove_binding`, `rename_concept`, `replace_relation`;
- `GraphProposal` bound to base snapshot digest, objective, model/runtime
  manifest, context capsule, budget, writable semantic scope, and provenance;
- `ProposalVerificationReport` with accepted/rejected operations and exact reasons;
- deterministic verifier for revision, endpoint, plane, relation, duplicate,
  scope, evidence, and invariant checks;
- proposals never mutate `FourfoldSnapshot` directly.

Tests:

- strict round-trip and canonical ordering;
- malformed/unknown operation refusal;
- stale snapshot, wrong revision, dangling endpoints, cross-scope operations;
- model rationale cannot substitute for evidence;
- partial acceptance is explicit and cannot masquerade as full validity;
- fuzz/property tests over operation ordering and duplicate injection.

Review focus: prevent a second graph authority and prevent “verified” from
meaning merely schema-valid.

## WP-02 — Atomic Fourfold compiler

Prerequisite: WP-01 green and reviewed.

Build:

- `FourfoldCompiler` orchestrates existing extractors without replacing them;
- one exact source revision, extractor manifest, and content-addressed source;
- all plane results staged before one snapshot publication;
- failed or unavailable extractors yield explicit partial/absent plane records;
- no mixed-revision or partially published Twin;
- compiler receipt records extractor versions, timings, failures, and evidence.

Tests:

- crash between every compile stage;
- stale cache and mismatched extractor revision;
- deterministic rebuild on Linux/Windows fixtures where available;
- cancellation and restart;
- CAS corruption/refusal;
- legacy Forest equivalence for currently supported facts.

## WP-03 — Data Plane minimum viable extractor

Prerequisite: WP-02 green and reviewed.

Initial bounded formats:

- Python dataclasses/Pydantic-like declarations already visible to the parser;
- CSV headers and fixtures;
- JSON Schema;
- SQL parsed through an adapter such as SQLGlot when installed;
- HDF5 structure through an optional adapter when installed.

Build schema/table/field/format nodes, transformations, and evidence locators.
Do not build a general data lake or infer runtime truth from names alone.

Ignition fixture must represent `Event.voltage` in Python, Markdown, and CSV.

## WP-04 — Round-trip candidate reporting

Prerequisite: WP-03 green and reviewed.

Build:

- `TargetTwin`/bounded target delta;
- `MaterializationPlan` mapping verified graph intent to source paths;
- isolated candidate source artifact;
- candidate Twin rebuild;
- `RoundTripReport` comparing required, satisfied, missing, contradicted, and
  extra structure;
- behavioral gates remain separate from structural conformance.

Tests include a generator that falsely claims success, source changes that do
not alter the intended graph, graph changes that break behavior, and stale-base
candidate replay.

## WP-05 — Gate 1 Renovation ignition slice

Prerequisite: WP-04 green and Gate-0 effect path sufficient for the slice.

Mission: propagate `Event.voltage -> bias_voltage` across Python, Markdown, and
CSV without auto-merge.

Evidence chain:

`MissionContract -> two typed WorkItems -> isolated Attempts -> source artifact -> candidate Twin -> schema/tests/link checks -> EvidencePacket -> owner review`

Required fault cases: dropped file, stale base, partial rename, wrong CSV header,
broken documentation link, worker false success, restart after first WorkItem,
and denied promotion without owner approval.

Revision 3 permits this slice only as an isolated deterministic rehearsal stacked
on a green Gate-0 Work Packet. It may produce candidate and evidence artifacts,
but it may not consume approval for production promotion, mutate the primary
checkout, change the active gate, or close Gate 0.

## WP-06 — Corpus seed and motif contracts

Prerequisite: WP-05 green; still experimental until Gate 2.

Use a small license-audited and temporally pinned corpus. Store immutable Twin
manifests and source provenance. Define motif contracts before learned models:

- concrete supporting subgraphs;
- alignment mapping;
- parameters and required invariants;
- compatible contexts and negative examples;
- quality/evaluator evidence;
- licenses and extraction versions.

Baselines: lexical retrieval, embeddings, code-only graph, four independent
indices, fused four-plane graph, and randomized cross-plane edges.

## WP-07 — Genesis microsoftware slice

Prerequisite: sealed Gate-3 baseline harness and WP-06 evidence.

Input: an owner-approved small ProductSpec plus visual/design contract.
Output: target Twin, declared retrieved motifs, isolated repository, runnable
software, screenshots/accessibility evidence where applicable, rebuilt Twin,
and RoundTripReport.

The first slice should be deliberately small: one local CRUD/data-view
application or similarly objective software with deterministic acceptance tests.
No framework-wide “build anything” claim is allowed from one demo.

## WP-08 — Ariadne evolution experiments

Prerequisite: Genesis and Renovation baselines.

One campaign changes one axis:

- graph proposal operator;
- context/retrieval policy;
- motif composition policy;
- model assignment;
- orchestration recipe;
- source repair strategy.

Use fixed tasks, evaluator, budgets, seeds, and model set. Compare Random,
Best-of-N, single-LLM repair, evaluator-only selection, Optuna-like search,
MAP-Elites/quality-diversity archive, and a transparent AlphaEvolve-like proxy.
Retain all failures and never auto-promote.

## Dependency adoption order

Do not add the complete research stack at once.

1. keep the stdlib canonical contracts;
2. add optional parser/data adapters only with fixtures and failure behavior;
3. introduce a graph query backend only after snapshot/adapter stability;
4. add durable workflow execution only behind Mission/Event contracts;
5. add optimization/QD libraries only after frozen evaluators exist;
6. add graph ML only after deterministic retrieval and ablation baselines.

Each dependency packet records license, version, platform support, serialization
boundary, failure mode, replacement path, and measured benefit.

## Current Gate-0 execution boundary

This projection is bound to source parent
`f78e4c53fb5ac21d90a34a2fe6cd8f6da679ab14` and records status only. It is not
release evidence and cannot alter `GateReport.closed`.

The selected repository-write discovery line is PR #166 -> PR #167. Both are
inventory/preparation packets: the canonical scanner integration, revision-bound
target and guard classification, Primary-Checkout disjointness proof, Gate-report
binding, production migration, and exact-head executable verification remain
open. No finding on that line is `guarded`, `central`, or `trusted` merely because
it was discovered.

GitHub Actions issue #67 is the active external execution blocker. Hosted jobs
continue to terminate before Step 1 with `steps=null`, no logs, and no artifacts.
Those runs prove neither success nor product failure. Until a trivial checkout
job and Iron Plan both record real executed steps, no packet may claim focused,
mutation, full-suite, packaging, platform, runtime, fault-matrix, or release
evidence from those runs.

While issue #67 remains open, independent work is limited to work that does not
depend on an unexecuted parent: static/adversarial review, contracts, schemas,
tests, fixtures, documentation, conservative inventories, migration plans, and
read-only evidence preparation. Dependent production wiring, `central`/`trusted`
classification, Gate closure, merge, promotion, OwnerApproval, and owner closure
decisions remain frozen.

Gate 0 still requires, at minimum, all production effectful entrypoints to be
registered and centrally guarded, live Runtime Manifests and current
RuntimeConformanceReceipts, Docker-sandbox evidence, the complete fault matrix,
Primary-Checkout mutation exclusion, independent architecture/security review,
and an explicit owner closure decision. Gate 1 and Gate 2 cannot be represented
as complete before those machine-readable prerequisites are satisfied.

## Historical WP-00 evidence

- Branch: `core/fourfold-v2`
- Base: `experimental`
- Draft PR: #1
- Fourfold matrix: Python 3.10/3.12 x two hash seeds, all green.
- Iron Plan history/contract workflow: green.
- The revision-2 amendment transaction ran Iron Plan verification, the full
  governance contract suite, and focused Fourfold/kernel tests before commit.
- The historical adoption fixture now uses pinned Git history rather than
  copying the current plan as its pre-adoption base.
- Adversarial builder review found and fixed an assurance escalation: a legacy
  cross-plane edge without retained evidence is now refused rather than marked
  `verified`; regression tests run in the complete `tests/twin` package.
- Independent architecture/security review and owner decision remain open.
