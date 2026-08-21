# Ikarus & Ariadne: Der eiserne Daedalus-Masterplan

Plan-ID: `daedalus-master-plan`  
Revision: 2  
Version: 1.0.0  
Status: adopted  
Date: 2026-07-30  
Owner: repository owner  
Active delivery gate: Gate 0 — Canonical Kernel  
Amendment chain: `docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl`

This is the sole semantic authority for Daedalus architecture, product order,
and research direction. Version 0.2, older TODOs, roadmaps, ADRs, handoffs,
architecture notes, and named subsystems remain valuable design history and
evidence. They do not override this document.

## 0. Authority model

| Artifact class | Authority | May do |
| --- | --- | --- |
| this master plan | sole semantic authority | define goals, invariants, priors, and delivery order |
| `.agentenv/agentenv.json`, `.agentenv/tool-allowances.json` | mechanical veto policy | restrict or deny capabilities |
| root instructions, skills, and hooks | derived projection | load the plan, report drift, block ordinary mutation |
| tests, receipts, and experiments | evidence | refute status claims and research priors |
| ADRs, TODOs, handoffs, inventories | history/backlog | supply evidence and proposals |

A capability policy cannot broaden the plan, and the plan cannot grant a
capability. For effects, the stricter mechanical policy wins. For product
meaning and sequencing, only this plan is authoritative.

Rule types are explicit:

- `INVARIANT`: cannot change silently;
- `GATE`: a deterministically testable delivery state;
- `PRIOR`: a falsifiable design hypothesis;
- `STATUS`: a revision-bound measurement, never timeless truth;
- `BACKLOG`: non-authoritative proposed work.

## 1. What “iron” means

The plan prevents silent drift; it does not prevent learning.

> Never violate hard invariants. Deviate from research priors only inside an
> isolated, measured experiment.

Hard invariants require an approved amendment before they change. Research
priors are deliberately falsifiable. A prior may be challenged without an
amendment when the challenge is read-only or an isolated experiment with a
frozen specification, bounded capabilities, explicit budget, independent
evaluation, and no production promotion. Negative evidence must be retained.

No model prompt or local hook is a security boundary. Until Gate 0 closes,
the guards in this repository prevent ordinary accidental drift and make
deliberate changes explicit; they do not claim to cover every external client,
`--no-verify`, direct filesystem writer, or contained candidate repository.

## 2. North star

Build a trustworthy system that can understand a software project across code,
types, data, and knowledge; formulate useful changes; run controlled
experiments; learn from evidence; and promote only verified improvements.

The research ambition is to outperform AlphaEvolve and other relevant systems
on openly specified, budget-equal evaluations. That is a target, never an
assumed fact. The system must publish failures, ablations, costs, and negative
results alongside wins.

## 3. Three public concepts

Only three top-level product/research concepts are public:

- **Daedalus** — the durable Mission / Policy / Execution / Evidence kernel.
- **Ikarus** — the persistent Jarvis-like assistant and orchestration surface
  that turns intent into typed missions and explains evidence.
- **Ariadne** — the controlled code-generation and evolution workload running
  on the kernel.

Existing components may survive as internal modules. Do not create another
mythological product, another control plane, or a parallel source of truth.

## 4. Constitutional invariants

These invariants apply to every production-capable path:

1. **One kernel.** Mission, Attempt, Evidence, Campaign, policy decisions,
   budgets, and promotion status have one canonical contract and event spine.
2. **Artifact identity.** Authoritative sources remain the truth. Candidate
   source trees and code are content-addressed artifacts; a graph delta is not
   candidate identity.
3. **Isolation.** Candidate execution is capability-bounded and cannot modify
   its evaluator, policy, evidence, budget ledger, or promotion mechanism.
4. **Evidence boundary.** Models and embeddings may propose; deterministic or
   independently controlled evaluators decide whether evidence is valid.
5. **Sealed promotion.** No candidate auto-merges or self-promotes. Promotion
   requires an evidence packet, policy checks, and explicit owner approval.
6. **Atomic revisions.** Cross-plane snapshots, evidence locators, and their
   source revision are consistent and reproducible; partial graph states do
   not masquerade as a revision.
7. **Provenance.** Material actions and claims carry origin, revision, inputs,
   cost, outcome, and evidence. Failures and rejected candidates remain
   inspectable.
8. **Bounded effects.** Spend, egress, write roots, concurrency, secrets, and a
   kill switch are enforced at effect boundaries, not entrusted to prompts.
9. **Honest claims.** Comparative claims use frozen tasks, equal budgets,
   declared hardware/models, repeated trials, uncertainty, and relevant
   baselines. No benchmark is trained on its hidden test.
10. **No silent constitution change.** This plan, its amendment chain, active
    instructions, and guards change only through the amendment protocol in
    section 15.

## 5. The Project Twin: the strongest falsifiable prior

The central research prior is a revision-bound four-plane Project Twin:

| Plane | Contains | Does not become |
| --- | --- | --- |
| Code / AST | files, symbols, functions, methods, syntax and control structure | a fifth “AST plane” |
| Type | declared/inferred types, constraints, contracts, interfaces | a universal correctness oracle |
| Data | schemas, tables, fields, formats, fixtures, lineage | an unbounded data lake |
| Knowledge | documentation, ADRs, issues, concepts, claims, wiki links | an authority above source/evidence |

Observation, provenance, evidence, and time are orthogonal lineage dimensions,
not additional semantic planes.

The **Forest** is the immutable, compiled intermediate representation of one
project revision. It is not a scheduler, chat memory, archive, or oracle.
Sources and candidate trees live in content-addressed storage; the Forest
references them and exposes typed intra-plane and verified cross-plane edges.

This hypothesis is a “god-key” candidate, not dogma. It earns its centrality
only through the kill criteria in section 13.

## 6. Latent Atlas and cross-plane discovery

Embeddings may consume schema-light **Node Cards**: stable node identity,
revision, plane, source locator, compact content, local neighborhood, and
provenance. A shared embedding space can retrieve possible relations without a
single giant ontology, but it never receives a literally schema-free graph:
identity, revision, plane, provenance, and relation-candidate shape are the
minimum contract.

The latent layer is a hypothesis machine. It proposes typed cross-plane
bindings with score and rationale. A verifier checks source evidence, revision
compatibility, type/rule constraints, and task relevance before an edge becomes
trusted. Unverified similarities remain proposals and expire or are retested.

Canonical formula:

> 4fold Project-Twin IR + latent cross-plane discovery + evidence-bound
> promotion

Forest is the teacher; the latent atlas is the hypothesis machine; the
evaluator is the truth boundary.

## 7. Ikarus, orchestration, and knowledge

Ikarus is persistent in goals and evidence, not an unconstrained immortal chat.
It compiles user intent into a typed `MissionContract`, creates an artifact DAG,
selects stateless or explicitly versioned recipes, monitors budgets and
attempts, and presents decisions and evidence.

Coordination is artifact-first:

`MissionContract -> WorkItems -> Attempts -> Artifacts -> EvidencePacket`

Typed events and artifacts are authoritative. Chat is an interface, not the
workflow database. Product memory (preferences, projects, explanations) and
research adaptive memory (operators, priors, trial outcomes) are separate,
versioned, provenance-bearing stores with explicit projection rules.

## 8. Ariadne evolution loop

Every campaign follows this controlled loop:

1. Freeze an `ExperimentSpec`, budget, tasks, metrics, baselines, and seed policy.
2. Build the base Forest for an exact source revision.
3. Select formulation, parent, one operator axis, model, and evaluation fidelity.
4. Compile a minimal Context Capsule from verified project evidence.
5. Run an isolated, capability-bounded trial.
6. Store the candidate source tree in content-addressed storage.
7. Build a candidate Forest and revision-aware delta.
8. Run the evaluation cascade from cheap validity checks to held-out tests.
9. Emit a signed/traceable receipt and archive all outcomes.
10. Nominate successful candidates; never auto-promote them.
11. Promote only through the sealed owner-controlled path.

Campaigns factorize evolution: change one major axis at a time unless a
pre-registered interaction experiment justifies more. Code, prompts, operators,
evaluators, and orchestration do not silently co-evolve in one campaign.

## 9. Code generation and evolution framework

Generation is not a single model call. Each operator declares:

- accepted artifact types and required Project-Twin slice;
- writable paths, tools, model, budget, and timeout;
- deterministic preconditions and generated candidate identity;
- evaluation ladder and rejection conditions;
- provenance, replay inputs, and expected failure modes.

Initial operator families are repair, refactor, representation search, test
generation, schema/document synchronization, and targeted algorithm search.
Operator discovery itself is a later bounded research problem, not a reason to
skip the kernel.

## 10. Delivery gates

Work advances in order. A later-gate experiment may be prototyped only when it
does not create a competing kernel and is explicitly labelled experimental.

### Gate 0 — Canonical Kernel (active)

Deliver:

- one Event Store plus content-addressed artifact store;
- canonical Mission, Attempt, Evidence, Campaign, policy, and receipt schemas;
- one vendor-neutral Agent Contract / Runtime Manifest for capabilities,
  mission envelopes, tools, egress, workspace, cost, and conformance receipts;
- centralized start/guard path for every effectful runtime entrypoint;
- enforceable write/egress/spend/secrets/concurrency/kill policies;
- real adapter fixtures for start, stream, tool events, structured output,
  timeout, cancellation, workspace isolation, and cost;
- policy coverage tests for Claude, Codex, Ollama, Web/API, MCP/File Bridge,
  Python entrypoints, and isolated worktrees;
- no new feature path or state store outside the canonical contracts.

Exit only when a fault-injection matrix demonstrates fail-closed protected
effects and fail-open read-only inspection.

### Gate 1 — Ignition slice

Prove one vertical mission: propagate `Event.voltage -> bias_voltage` across
Python, Markdown, and CSV. Ikarus produces one MissionContract; the four planes
produce two typed WorkItems; attempts run in isolation; restart/replay works;
tests, schema checks, and link checks produce an EvidencePacket. No auto-merge.

### Gate 2 — Forest v2

Add function/method resolution, data/schema extraction, knowledge crosslinks,
revision atomicity, evidence locators, and four-plane ablations. Do not scale
before the full graph beats simpler representations.

### Gate 3 — Baseline lab

Freeze public tasks, evaluator versions, budgets, model/hardware reporting,
seed policy, and statistical reporting. Required baselines are Random Search,
Best-of-N, a single-LLM loop, simple local mutation, BM25, embeddings,
code-only graph, four separate indices, evaluator-only selection,
archive/MAP-Elites, and a transparent AlphaEvolve-like proxy. Measure success
rate, best-so-far AUC, wall time, tokens, compute, variance, diversity,
regressions, and human intervention.

### Gate 4 — One research hypothesis

Test **Graph-conditioned Representation Search** first: use verified Project
Twin structure to select and compress context or operators, then compare against
budget-equal retrieval and evaluator-only baselines. Freeze generator, model,
token budget, and evaluator. Controls include edge rewiring, relation-label
permutation, cross-plane bridges off, stale snapshots, and an oracle graph. One
hypothesis, one pre-registered protocol, complete ablations.

### Gate 5 — Public proof

Release reproducible task definitions, evaluator code/version, receipts,
cost/latency tables, ablations, failures, and a claim bounded by observed
evidence. AlphaEvolve is closed, so a broad framework comparison is not
scientifically available. “Beats AlphaEvolve” is permitted only for directly
comparable public artifact scores under budget-equal measurements; otherwise
state the narrower proxy/task result.

## 11. Current priority

Until Gate 0 exits, the default answer to new feature work is: wire it through
the canonical kernel or keep it as a disposable, isolated experiment. The next
product proof is the Gate 1 ignition slice, not a broader assistant demo.

## 12. Forbidden default directions

Do not add these to the production architecture:

- new public mythological subsystems or parallel control planes;
- direct legacy-to-legacy wiring that bypasses canonical contracts;
- a universal graph score, diffusion number, or “intelligence” scalar;
- an unbounded AST hairball or a fifth AST graph;
- chat transcripts as orchestration state;
- shared mutable memory for product personalization and research adaptation;
- an LLM judgment as a hard correctness or promotion gate;
- simultaneous unregistered co-evolution of code, prompts, evaluators, and policy;
- automatic merge/promotion or candidate access to its evaluator;
- a marketing clone whose comparison protocol is not reproducible;
- new graph planes without demonstrated marginal evidence.

Any of these may appear only in an isolated falsification experiment with an
explicit hypothesis and no production promotion.

## 13. Kill criteria

Stop or redesign the four-plane/latent track when replicated, budget-equal
experiments show any of the following:

- the full representation does not beat code-only or BM25 retrieval;
- degree-preserving randomized cross-plane edges perform equivalently;
- four independent indices perform equivalently to cross-plane fusion;
- a plane has no marginal contribution in ablation;
- graph movement does not predict or cause behavioral improvement;
- graph-conditioned prioritization does not beat random or evaluator-only choice;
- the gain disappears after temporal and knowledge-leakage scrubbing;
- extra context tokens explain the whole gain;
- graph construction/query cost worsens the quality/cost frontier;
- revision-atomic snapshots cannot be maintained at usable cost;
- embedding proposals cannot achieve useful precision after verification cost;
- benefits disappear on held-out repositories, under equal context budgets, or
  in cross-project transfer.

A kill result does not silently delete this plan. Archive the evidence, stop the
affected track, and submit an amendment replacing the failed prior.

For every comparative campaign, seal the evaluator from the candidate, use
identical problem definitions and compute/token budgets, cover multiple task
classes, and run at least 5–10 seeds when stochastic variance matters. Report
algorithm quality, sample efficiency, repository evolution, and product
reliability separately. Reject results when code, prompts, memory, model,
search policy, and evaluator changed together.

Prevent leakage from gold patches, private tests, post-cutoff issue/commit text,
post-task graph edges, previous solutions in adaptive memory, base/candidate
snapshot mixing, evaluator paths or outputs, and model-generated hypotheses
re-entering the Knowledge plane as facts.

## 14. Alignment protocol for every change

Before editing:

1. Read this plan and verify its digest.
2. Classify the work as `ALIGNED`, `EXPERIMENT`, or `AMENDMENT`.
3. Name the active gate and the invariant/prior touched.
4. Prefer deletion, consolidation, or wiring over a new subsystem.

Before handing off:

1. Run `python tools/iron_plan_guard.py verify`.
2. Report:

   `Iron Plan: ALIGNED | EXPERIMENT | AMENDMENT`  
   `Iron Gate: 0..5`  
   `Evidence: <tests, receipts, or analysis>`

An experiment also records its spec, scope, budget, evaluator, and expiry.

## 15. Amendment protocol

Ordinary tasks must not edit the plan, amendment chain, active instructions, or
guards. To amend:

1. Propose the exact diff, reason, alternatives, affected invariants/priors,
   migration, rollback, evidence, and owner.
2. Obtain explicit repository-owner approval.
3. Start the amendment session with
   `DAEDALUS_IRON_PLAN_AMENDMENT=<current full plan sha256>`.
4. Increment the plan revision monotonically.
5. Append exactly one accepted record to
   `docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl`. It records base/result
   SHA-256, previous-record hash, approval reference, scope, and evidence.
6. Update the plan, ledger, derived controls, and tests atomically.
7. Run policy verification and the relevant fault-injection suite.

The environment token only unlocks the protected files for that process. It
does not waive owner approval, the amendment record, review, or evidence.
Rollback is a new amendment, never a history rewrite.
