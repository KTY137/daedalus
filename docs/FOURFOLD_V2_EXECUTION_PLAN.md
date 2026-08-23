# Fourfold v2 Execution Plan

Status: active derived projection

Canonical authority: `docs/IKARUS_ARIADNE_MASTER_PLAN.md` revision 3

Active gate: Gate 0 — Canonical Kernel

Audited integration candidate: `integration/g0-canonical-20260803`

Rule: this document records execution status and evidence; it cannot override the Iron Plan.

## Audited status — 2026-08-03

This projection was reconciled against the local checkout, the remote branch
topology, the Grand Summary, and the frozen PR #47 handoff. The active gate is
still Gate 0. Later-gate code is useful input, not delivery evidence.

| Packet | Honest implementation state | Current blocker |
| --- | --- | --- |
| WP-00 | Four-plane snapshot contracts and conservative legacy projection exist. | Independent exact-head closure and all Gate-0 prerequisites remain open. |
| WP-01 | No production `GraphProposal`/operation verifier matching this packet exists on the canonical candidate. | Contract and adversarial verifier must be implemented after the effect kernel is honest. |
| WP-02 | A deterministic bounded reference compiler exists for fixtures. | It is not yet a general atomic compiler with crash/restart and mixed-revision fault evidence. |
| WP-03 | Python/wiki/CSV/JSON-schema reference extraction exists in bounded form. | Adapter coverage, evidence locators, and real corpus measurements are incomplete. |
| WP-04 | Fourfold evidence and sealed approval contracts exist. | No complete source-candidate rebuild plus `RoundTripReport` production chain exists. |
| WP-05 | The voltage rename is a deterministic rehearsal. | The current runner copies and edits a fixture directly, imports candidate code in-process, and fabricates timing/locator fields; it is not a real Mission → Attempt → CAS → Evidence chain. |
| WP-06 | Gate-2 drafts contain corpus/motif and knowledge-correlation ideas. | Corpus review is declared rather than completed; PR #47 has seven reproduced implementation/test defects and remains excluded. |
| WP-07 | Not implemented as a sealed Gate-3 slice. | Gate-3 baseline harness does not exist. |
| WP-08 | Legacy evolution modules and synthetic estimates exist. | No production caller and no budget-equal, evaluator-isolated real evolution campaign. |

The local effect registry contains 50 rows: one `CENTRAL`, eight
`LOCAL_GUARDS`, forty `INVENTORY_ONLY`, and one `ABSENT`. Fifteen discovered
tool entrypoints are unregistered. All 49 non-central rows and all unregistered
effectful starts are explicit Gate-0 blockers. `python.offload` also still lacks
a production lease issuer, so its direct live callers fail closed. Do not infer
operability from its registry label.

## Operating model

Daedalus is developed through one active Work Packet at a time. Each packet has
one major architectural axis, one acceptance matrix, one builder, one independent
review pass, and one explicit owner decision. A packet may be split into smaller
commits, but its PR must not mix unrelated feature work, broad cleanup, dependency
migration, evaluator changes, or policy amendments. The accepted revision-2 and
revision-3 amendments remain separate ancestry and review units. Further
protected plan or gate changes require another explicit owner-approved amendment.

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

No dependent packet enters build while its parent is red or unreviewed. Read-only
research may continue, but it cannot establish another implementation truth.

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

Status: contracts and bounded projection are implemented; historical builder
evidence exists, while current exact-head independent closure remains open.

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

## Current branch/PR evidence

- Canonical local candidate: `integration/g0-canonical-20260803`, based on the
  exact Gate-0 effect branch and retaining the fault-matrix branch through a
  two-parent merge. No remote push, merge, promotion, or branch deletion has
  been performed.
- Gate-0 repairs on the candidate authenticate persisted promotion approvals,
  preserve indeterminate effect starts for reconciliation, make every
  non-central row block closure, persist enough authenticated lease material for
  restart recovery, fingerprint bounded Git source observations (including
  gitlinks/submodules), and remove the dry path's hidden metrics append.
- `OffloadExecutionPlan` now freezes one Spine intent, one source/worktree
  observation, one loopback Ollama model/runtime, one exact target, one model
  call, exact tool/verifier argv, zero spend, and a kill-switch generation. It
  is inert and grants nothing. Binding its digest through policy, lease,
  `TaskAttempt`, runtime evidence, and the provider call remains open.
- A precomputed-index routing leaf can run without cache construction, provider
  probes, embeddings, process creation, network, or filesystem writes. The
  legacy default router still uses ambient roster/policy/environment reads and
  can enter StructCore cache/process paths; a globally frozen planning boundary
  remains open.
- Ollama write mode now requires an exact component allowlist and refuses
  traversal, prefixes, symlink/reparse escapes, and cross-platform filename
  aliases at both physical write sites. No production caller may derive this
  allowlist from raw model input; the canonical plan/lease binding is not wired
  yet.
- Exact parent-head whole suite at `997f1c6`: 4,571 passed, 3 skipped, 1 xfailed,
  1,982 subtests in 1,195.98 seconds. This is retained baseline evidence, not a
  current-head pass.
- Current candidate head is `cbb435c`. Focused receipts collected while building
  this stack include: 61 plan/lease/offload contract tests; 134 Ollama/rewrite
  tests with 2 skips and 14 subtests; 157 routing/StructCore tests with 2 skips
  and 26 subtests; and 6 source-observation chain tests. These are proportional
  packet receipts, not a current-head whole-suite or Gate-0 closure receipt.
- The repository's `consolidated` test profile currently selects only 85 tests
  and omits core EffectLease, leased-offload, fault-matrix, Attempt,
  containment, cancellation, and artifact-store chains. It is a smoke profile,
  not a Gate-0 receipt.
- PR #47 (`g2/knowledge-correlation-bootstrap`) is frozen and excluded. Local
  reproduction found seven failures involving path traversal, graph node
  construction, missing source context, compressed-input identity, and a
  non-proving prompt-injection test. Its additive code is also not connected to
  the canonical runtime.
- GitHub Actions job records that fail before Step 1 are infrastructure
  evidence only; they are neither green nor red Python evidence.
- Independent architecture/security review, current-head whole-suite/package
  evidence, and explicit owner promotion remain open.

## Gate-3 experiment fixture (frozen proposal)

The first real external evolution experiment should use
`python-poetry/tomlkit@d8ed1e3cdb024dfc2c6f12b45a0dfd4d4d91f727`, with
`toml-test@08ed8697864548b3cdb4b8decbf496bef47e1c82` pinned. The baseline
reproduces a real dotted-key parent-path serialization defect and can be judged
by an independent `tomllib` parse after build/install. This remains an isolated
`EXPERIMENT` while Gate 0 is active; it cannot close Gate 3 by itself.

Required pilot arms are BM25, code-only graph, four separate plane indices, and
verified Fourfold, plus no-change and simple-mutation sanity baselines. Freeze
the model digest, seeds, context/output budgets, evaluator, hidden tests, and
hardware receipt. If Fourfold performs poorly, first audit snapshot atomicity,
plane coverage, provenance, retrieval output, token parity, and evaluator tree
identity. A clean, replicated loss remains negative evidence and must not be
relabelled as an implementation defect merely to protect the research prior.
