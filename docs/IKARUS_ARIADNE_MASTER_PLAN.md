# Ikarus & Ariadne: Der eiserne Daedalus-Masterplan

Plan-ID: `daedalus-master-plan`  
Revision: 8
Version: 1.3.0
Status: adopted  
Date: 2026-08-02
Owner: repository owner  
Active delivery gate: Gate 1 — Renovation ignition slice  
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
| `docs/DAEDALUS_GESAMTPLAN.md` | program authority | detail the build program within this plan's bounds |
| ADRs, TODOs, handoffs, inventories | history/backlog | supply evidence and proposals |

A capability policy cannot broaden the plan, and the plan cannot grant a
capability. For effects, the stricter mechanical policy wins. For product
meaning and sequencing, this plan is the final authority; the Gesamtplan
details the build program within these bounds, and where they conflict,
this plan wins. Measured drift between the Gesamtplan and the tree is
recorded as work, never papered over.

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

Daedalus has two product modes:

- **Renovation** — understand, repair, refactor, synchronize, and evolve an
  existing repository.
- **Genesis** — compile a user-approved product specification and visual design
  contract into a new repository, then prove by round-trip distillation that
  the materialized source satisfies the intended four-plane structure.

The long-term user experience is natural-language software construction:
Ikarus turns intent into an inspectable target Project Twin and bounded mission;
Daedalus materializes and verifies candidates; Ariadne improves the reusable
motifs, operators, retrieval policies, and orchestration recipes that produced
them. “One prompt to software” is an outcome of verified composition and repair
loops, not permission to skip specifications, evidence, or owner review.

The research ambition is to outperform AlphaEvolve and other relevant systems
on openly specified, budget-equal evaluations. That is a target, never an
assumed fact. The system must publish failures, ablations, costs, and negative
results alongside wins.

## 3. Three public concepts

Only three top-level product/research concepts are public:

- **Daedalus** — the complete trustworthy system. Its semantic/intelligence
  core is the revision-bound four-plane Project Twin; its trust/runtime kernel
  is the canonical Mission / Policy / Execution / Evidence spine.
- **Ikarus** — the persistent assistant and orchestration layer that turns
  intent into typed product specifications, target Twins, missions, and
  explainable evidence.
- **Ariadne** — the controlled evolution layer that searches over source
  candidates, graph transformations, motifs, context strategies, prompts,
  models, and orchestration recipes without bypassing the trust kernel.

The Project Twin is shared substrate, not a fourth public product. Existing
components may survive as internal modules. Do not create another mythological
product, another control plane, or a parallel source of truth.

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
    section 16.

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
only through the kill criteria in section 14.

A repository corpus may contain many immutable Project Twins. Corpus ingestion
retains source revision, extraction versions, licenses, provenance, evaluation
evidence, and temporal cutoffs. Reusable **motifs** are evidence-bearing
abstractions over aligned subgraphs; they never erase the concrete repositories
from which they were learned. A generated program is a source artifact whose
structure may be proposed by retrieving, composing, interpolating, or mutating
motifs, but the source artifact and its rebuilt candidate Twin remain the
authoritative candidate pair.

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

## 7. Ikarus and the orchestration layer

Ikarus is persistent in goals and evidence, not an unconstrained immortal chat.
It compiles user intent into a typed `ProductSpec` or change objective, a
target Project Twin or bounded Twin delta, and then a `MissionContract`. It
creates an artifact DAG, selects stateless or explicitly versioned recipes,
monitors budgets and attempts, and presents decisions and evidence.

Coordination is artifact-first:

`ProductSpec -> TargetTwin -> MissionContract -> WorkItems -> Attempts -> Artifacts -> EvidencePacket`

For Renovation, the base repository and exact base Twin are mandatory inputs.
For Genesis, the absence of a base repository is explicit; the target Twin,
design contract, accepted technology constraints, and selected corpus motifs
become frozen inputs. Genesis still produces an isolated source candidate,
rebuilds a candidate Twin, and compares target versus actual before nomination.

The orchestration layer answers who works, with which runtime, context,
capabilities, budget, workspace, and review chain. It may use Claude, Codex,
Ollama, other LLM runtimes, deterministic tools, and human decisions through
one vendor-neutral runtime contract. Models never obtain authority by being
selected as the speaking voice.

Typed events and artifacts are authoritative. Chat is an interface, not the
workflow database. Product memory (preferences, projects, explanations) and
research adaptive memory (operators, priors, trial outcomes) are separate,
versioned, provenance-bearing stores with explicit projection rules.

## 8. Ariadne and the evolution layer

The orchestration layer executes one bounded software mission. The evolution
layer improves the representations, motifs, operators, context strategies, and
orchestration recipes used across missions. Both layers communicate only
through versioned artifacts, contracts, measurements, and receipts.

LLMs are creative search operators, not truth authorities. They may:

- translate intent into candidate specifications;
- propose typed graph bindings or graph transformations;
- retrieve and recombine distant corpus motifs;
- materialize a target graph as source code;
- generate repairs, tests, critics, and alternative implementations;
- propose prompt, context, model-assignment, or workflow variants.

Deterministic or independently controlled evaluators verify structural
validity, compilation, tests, behavior, security properties, visual contracts,
resource usage, and round-trip target-versus-actual Twin conformance. LLM
criticism is advisory evidence unless an experiment explicitly measures it.

Every campaign follows this controlled loop:

1. Freeze an `ExperimentSpec`, budget, tasks, metrics, baselines, and seed policy.
2. Build the base Forest for an exact source revision.
3. Select formulation, parent, one operator axis, model, and evaluation fidelity.
4. Compile a minimal Context Capsule from verified project evidence.
5. Run an isolated, capability-bounded trial.
6. Store the candidate source tree in content-addressed storage.
7. Build a candidate Forest, four-plane candidate Twin, and revision-aware delta.
8. Run the evaluation cascade from cheap graph/schema validity through build,
   tests, runtime probes, visual checks where relevant, held-out tasks, and
   target-versus-actual Twin conformance.
9. Emit a signed/traceable receipt and archive all outcomes.
10. Nominate successful candidates; never auto-promote them.
11. Promote only through the sealed owner-controlled path.

Campaigns factorize evolution: change one major axis at a time unless a
pre-registered interaction experiment justifies more. Code, prompts, operators,
evaluators, and orchestration do not silently co-evolve in one campaign.

## 9. Generation, corpus composition, and round-trip compilation

Generation is not a single model call. The canonical pipeline is:

`intent -> ProductSpec -> TargetTwin -> GraphProposal -> verified operations -> MaterializationPlan -> source candidate -> rebuilt Twin -> RoundTripReport`

A `GraphProposal` is an LLM- or algorithm-produced hypothesis bound to an exact
base or target snapshot, model/runtime manifest, context capsule, budget, and
declared operations. It cannot enter an authoritative snapshot until a verifier
checks endpoint existence, revision compatibility, relation rules, provenance,
scope, and evidence. A `MaterializationPlan` translates verified graph intent
into bounded source edits. The resulting repository is always distilled again;
the system never trusts the generator’s claim that it implemented the target.

Each operator declares:

- accepted artifact types and required Project-Twin slice;
- writable paths, tools, model, budget, and timeout;
- deterministic preconditions and generated candidate identity;
- evaluation ladder and rejection conditions;
- provenance, replay inputs, and expected failure modes.

Initial operator families are repair, refactor, representation search, test
generation, schema/document synchronization, motif retrieval/composition,
cross-plane propagation, UI/design materialization, and targeted algorithm
search. Operator discovery itself is a later bounded research problem, not a
reason to skip the kernel.

### 9.1 Repository atlas and motif library

The Atlas is a regenerable query/index layer over immutable repository Twins,
not a second source of truth. It may provide lexical, vector, graph, and learned
retrieval. Motif extraction must retain:

- source repositories, revisions, licenses, and temporal cutoffs;
- concrete supporting subgraphs and negative examples;
- required preconditions and preserved invariants;
- known compatible contexts, failure modes, and evaluator evidence;
- abstraction and alignment algorithm versions.

Interpolation means constrained graph alignment, composition, mutation, and
repair. It is not arithmetic averaging of arbitrary software graphs.

### 9.2 Buy-versus-build boundary

Daedalus owns four-plane semantics, revision atomicity, cross-plane verification,
motif abstraction, graph mutation contracts, target-to-source materialization
contracts, round-trip evaluation, evidence, and promotion. External libraries
should supply commodity infrastructure behind adapters where they reduce risk:
parsing/indexing, graph storage/query, vector retrieval, workflow checkpointing,
tool transport, sandboxing, optimization, quality-diversity archives, and
experiment visualization. Library state is a projection or runtime backend,
never a competing authority.

Current implementation priors include Tree-sitter/SCIP/Joern for code
intelligence, SQLGlot/OpenLineage for data lineage, Kùzu/rustworkx for graph
query and algorithms, PyTorch Geometric for later heterogeneous graph research,
MCP and LiteLLM for transport, LangGraph or an equivalent durable executor
behind Daedalus contracts, Docker-compatible sandboxes, DSPy/Optuna/pyribs for
bounded optimization, and MLflow-like experiment projection. These are priors,
not permanent dependencies; adoption requires an adapter contract, failure
mode, replacement path, and measured benefit.

## 10. Mandatory build and review chain

Implementation proceeds as a sequence of bounded **Work Packets**. One Work
Packet changes one major architectural axis and has one primary acceptance
claim. A packet freezes:

- packet ID, active gate, classification, owner, base revision, and dependencies;
- exact in-scope and forbidden paths;
- contracts or behavior being added, changed, migrated, or deleted;
- deterministic acceptance tests, refusal tests, fault injections, and budgets;
- migration, rollback, evidence, expected failures, and review questions.

The required chain is:

1. **Plan.** Verify the Iron Plan; write the Work Packet and acceptance matrix.
2. **Baseline.** Reproduce current behavior and record failing/absent evidence.
3. **Build.** Implement in an isolated branch/worktree without widening scope.
4. **Builder verification.** Run focused unit, contract, determinism, packaging,
   and integration tests. A model’s self-report is not evidence.
5. **Independent review.** A separate reviewer examines contracts, bypasses,
   provenance, failure semantics, architecture drift, and unnecessary code.
6. **Adversarial verification.** Run malformed-input, stale-revision,
   cancellation, timeout, crash/restart, policy-bypass, and mutation tests
   proportional to the packet’s risk.
7. **System CI.** Run affected legacy suites plus the packet acceptance matrix
   on supported platforms/interpreters. Baseline failures are named separately.
8. **Evidence handoff.** Publish exact commits, commands, results, residual
   risks, rollback, and the next packet’s prerequisites.
9. **Owner decision.** Merge/promote only after required checks and explicit
   owner approval. A draft or green candidate is not promotion.

No packet begins its dependent build phase until the parent packet is green,
reviewed, or explicitly frozen as a documented blocker. Stacked research
branches may gather read-only evidence, but may not silently establish a second
implementation truth. Feature work, broad refactors, dependency migration,
policy amendment, and evaluator change belong in separate packets unless their
interaction is the pre-registered subject of an experiment.

The derived execution projection is
`docs/FOURFOLD_V2_EXECUTION_PLAN.md`. Claude and other builders may update it
for status and evidence, but it cannot override this plan or declare a gate
complete.

## 11. Delivery gates

Work advances in order. A later-gate experiment may be prototyped only when it
does not create a competing kernel and is explicitly labelled experimental.

### Gate 0 — Canonical Kernel (closed 2026-08-26, scoped owner decision)

Deliver:

- one Event Store plus content-addressed artifact store;
- canonical Mission, Attempt, Evidence, Campaign, policy, receipt, four-plane
  snapshot, graph-proposal, and round-trip-report schemas;
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

### Gate 1 — Renovation ignition slice (active)

Prove one vertical Renovation mission: propagate `Event.voltage -> bias_voltage` across
Python, Markdown, and CSV. Ikarus produces one MissionContract; the four planes
produce two typed WorkItems; attempts run in isolation; restart/replay works;
tests, schema checks, and link checks produce an EvidencePacket. No auto-merge.

### Gate 2 — Forest v2 and corpus seed

Add function/method resolution, data/schema extraction, knowledge crosslinks,
revision atomicity, evidence locators, and four-plane ablations. Ingest a small
license-audited, temporally pinned repository corpus and prove deterministic
Twin rebuilding, cross-repository alignment, and motif provenance. Do not scale
the corpus before the full graph beats simpler representations.

### Gate 3 — Baseline and Genesis lab

First freeze public tasks, evaluator versions, budgets, model/hardware reporting,
seed policy, and statistical reporting. Required baselines are Random Search,
Best-of-N, a single-LLM loop, simple local mutation, BM25, embeddings,
code-only graph, four separate indices, evaluator-only selection,
archive/MAP-Elites, and a transparent AlphaEvolve-like proxy. Measure success
rate, best-so-far AUC, wall time, tokens, compute, variance, diversity,
regressions, and human intervention.

Only after that baseline harness is sealed, prove one bounded Genesis slice:
compile an owner-approved ProductSpec and visual contract for a small software
application into a target Twin, retrieve declared motifs, materialize an
isolated repository, build/run it, inspect rendered output where relevant,
rebuild its Twin, and emit a RoundTripReport. The slice may require repair
iterations but may not change its evaluator, target, or budget mid-run.

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

## 12. Current priority

Until Gate 0 exits, the default answer to new feature work is: wire it through
the canonical kernel or keep it as a disposable, isolated experiment. The
active implementation sequence is Fourfold snapshot contracts, conservative
legacy projection, GraphProposal/verification, atomic compiler, Data Plane,
round-trip reporting, then the Gate 1 Renovation slice. Genesis, the corpus,
motif learning, graph ML, and autonomous evolution do not become production
paths early merely because their interfaces can be sketched.

### Revision 3 — Sealed Gate-0 promotion and bounded Gate-1 rehearsal

The repository owner explicitly authorized continuing the current execution
through a bounded Gate-1 rehearsal while Gate 0 remains the active delivery
gate. This amendment makes the following constraints authoritative:

1. `promote_candidates` may enter an integration worktree only after a consumed,
   authenticated, one-use `OwnerApproval` exactly binds the ordered candidate
   batch, a passed `EvidencePacket`, the base revision, target ref, and a freshly
   resolved target revision. Any mismatch refuses before lock acquisition,
   worktree creation, branch creation, ledger mutation, or Git mutation.
2. Content-addressed runtime-conformance observations and a restrictive sandbox
   policy are required Gate-0 evidence inputs. Offline fixtures prove contract
   behavior only; they do not prove live Claude, Codex, Ollama, host, container,
   or network isolation.
3. A single Gate-1 Voltage-rename Renovation slice may be implemented as an
   isolated, deterministic, non-promoting rehearsal stacked on a green Gate-0
   Work Packet. It may emit candidate, Fourfold delta, evidence, and approval
   artifacts, but it cannot close Gate 0, change the active gate, consume an
   approval for production promotion, or mutate the primary checkout.
4. Gate-0 closure still requires the remaining effectful-entrypoint migration,
   live runtime receipts, the complete fault matrix, independent architecture
   and security review, and an explicit owner closure decision.

### Revision 8 — Scoped Gate-0 closure (2026-08-26)

By explicit owner instruction of 2026-08-26, Gate 0 is closed as a SCOPED
owner decision recorded in `docs/GATE0_CLOSURE_DECISION_20260826.md`, which
disposes every blocker the machine report named at the closure revision. The
mechanical report deliberately keeps saying `closed:false` while scoped rows
remain open: the instrument is not rewritten by this decision, and the scoped
rows keep being counted. The closure carries four binding obligations into the
Gate-1 era (caller-injection half two with live envelope admission and receipt
bundle persistence; no new effect path outside the canonical contracts; the
scoped rows stay reported; Docker host procurement stays an open owner
position). `security_boundary_claimed` stays false on purpose — closing the
gate does not advertise a complete security guarantee, which this repository's
own review rules class as a defect.

## 13. Forbidden default directions

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
- new graph planes without demonstrated marginal evidence;
- a greenfield rewrite that discards measured failures and working modules;
- dependent feature packets built on an unreviewed or red parent packet;
- corpus ingestion that drops source license, revision, or temporal provenance;
- treating visual similarity or an LLM critique as sufficient UI acceptance.

Any of these may appear only in an isolated falsification experiment with an
explicit hypothesis and no production promotion.

## 14. Kill criteria

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
  in cross-project transfer;
- motif composition does not outperform direct generation after equalizing
  model, tokens, repair budget, and evaluator access;
- Genesis round-trip conformance fails to predict buildable, usable software;
- corpus licensing/provenance or extraction cost prevents reproducible reuse;
- orchestration evolution gains vanish when evaluated on unseen repositories
  and fixed models.

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

## 15. Alignment protocol for every change

Before editing:

1. Read this plan and verify its digest.
2. Classify the work as `ALIGNED`, `EXPERIMENT`, or `AMENDMENT`.
3. Name the active gate and the invariant/prior touched.
4. Create or select exactly one Work Packet and freeze its acceptance matrix.
5. Reproduce the relevant baseline before changing implementation.
6. Prefer deletion, consolidation, or wiring over a new subsystem.

Before handing off:

1. Complete the build/review chain in section 10 or name the exact blocked step.
2. Say in one line whether the work is `ALIGNED` / `EXPERIMENT` / `AMENDMENT`.
3. Report:

   `Iron Plan: ALIGNED | EXPERIMENT | AMENDMENT`  
   `Iron Gate: 0..5`  
   `Evidence: <tests, receipts, or analysis>`

An experiment also records its spec, scope, budget, evaluator, and expiry.
Historical governance tests must reconstruct their base state from pinned Git
history or retained content digests. A current policy artifact must never
impersonate a pre-adoption or pre-amendment state merely because it is easier to
copy from the working tree.

## 16. Amendment protocol

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


Retirement note (2026-08-22, revision 7): the mechanical guard (tools/iron_plan_guard.py (removed 2026-08-22), hooks, commit hooks, CI) is retired by owner decision. This plan stays the design authority as a document; changes are owner commits that append a record to the amendment chain by hand. The checkpoint line is frozen at tag archive/checkpoint-2026-07-20-session (e37294c3ff3b); its work is harvested onto main.
