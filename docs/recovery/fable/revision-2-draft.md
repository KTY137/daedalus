# Lane report: revision-2-draft

**SUPERSEDED 2026-08-26.** This lane measured the Gesamtplan against the
`work/g0-trunk-20260817` worktree (`closed=false`, 60 blockers) as a basis for
an amendment *proposal*. Gate 0 has since closed (scoped) via master plan
revision 8 — see `docs/GATE0_CLOSURE_DECISION_20260826.md`. No amendment based
on this draft was adopted; the text below is retained unchanged as dated
evidence, not as a live proposal.

Lane: `revision-2-draft` (Fable long-context lane 1 of 5)
Date: 2026-08-17
Classification: **ALIGNED** (read-only analysis producing an AMENDMENT *proposal*; no protected
file was touched; the only write is this report in the unprotected `docs/recovery/fable/` directory).
Iron Gate: 0.

---

## 1. Inputs and evidence base

| Input | Evidence |
|---|---|
| Constitution, revision 1, read **completely** | `docs/IKARUS_ARIADNE_MASTER_PLAN.md` lines 1–369 (full file) |
| Constitution base digest | `a47d84ee736fcaebd76f4309f4e0653f536415b9bda9e04940920ca1896026d4` — attested by the active SubagentStart/PreToolUse iron-plan hook this session; **matches** `result_plan_sha256` of ledger record sequence 1. Not independently recomputed (the Bash guard string-matches protected path names), so: hook + ledger cross-check, marked verified-by-two-independent-artifacts. |
| Amendment ledger tail | `docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl` line 1 (single record): `sequence: 1`, `record_sha256: 3ccedd9a36e21d1764d16766431450e422628129faa9e7a68684bfeccf3793ea`, `result_revision: 1`, `version: "1.0.0"` |
| Gesamtplan, read **completely** | `docs/DAEDALUS_GESAMTPLAN.md` lines 1–1583 (full file, two paged reads) |
| Amendment mandate (Schritt A, Punkt 3) | `docs/DAEDALUS_GESAMTPLAN.md:1241-1247` — the six bullets (a)–(f) this draft implements |
| Gate-0 trunk reality check | Glob over `C:/Users/nukei/Desktop/agent_env_g0` (branch `work/g0-trunk-20260817` per briefing): `daedalus/gates/` (34 modules incl. `report.py`, `report_v3.py`, `release.py`, `baseline.py`, `fault_matrix.py`, `trust_bundle.py`), `daedalus/kernel/` (25 modules incl. `approvals.py`, `effects.py`, `sandbox.py`, `promotion.py`, `runtime_conformance.py`), `daedalus/runtimes/` (32 modules incl. `fault_matrix.py`, `broker.py`, `trust.py`), `daedalus/twin/` (incl. `contracts.py`, `legacy_forest.py`, `reference_compiler.py`, `extractors/tree_sitter_adapter.py`). **No matches** for `daedalus/orchestration/`, `daedalus/evolution/`, `daedalus/atlas/`. |

ASSUMED (not measured): that the trunk worktree at commit `60b2bfe` is the state the revision's
STATUS notes should describe (per briefing); the trunk's gate-report schema version (file
`report_v3.py` exists, suggesting the Gesamtplan's `daedalus-gate-report/1` id is already stale —
flagged as conflict K3, not asserted).

## 2. Drafting decisions (defaults an owner can override)

1. **Numbering stability.** All insertions are subsections (`4.1`, `5.1`, `9.1`) or in-place
   amendments. No top-level section is renumbered, because `AGENTS.md` ("Follow section 15 of
   docs/IKARUS_ARIADNE_MASTER_PLAN.md") and the plan's own cross-references (§4 item 10 → "section
   15"; §5 → "section 13") depend on the numbering. Renumbering would force an atomic edit of
   AGENTS.md/CLAUDE.md projections in the same amendment. (Owner choice K9.)
2. **Language.** New constitutional text is drafted in **English**, matching the body language of
   revision 1. (Owner choice K10.)
3. **Dual status of the Fourfold Twin.** The Gesamtplan's assertive sentence ("Der Fourfold Project
   Twin ist Daedalus' semantischer Kern", `DAEDALUS_GESAMTPLAN.md:30-32`) is reconciled with §5's
   "prior, not dogma" by splitting *contract* from *claim*: the snapshot/contract family is the
   canonical IR of the architecture; the *performance* claim remains a PRIOR fully subject to §13
   kill criteria. The Gesamtplan itself concedes this at line 1453 ("wird der Fourfold-/Latent-Ansatz
   gemäß den bestehenden Kill Criteria reduziert oder neu entworfen"). (Owner ratification K2.)
4. **Invariants untouched.** §4 items 1–10 are copied forward **byte-identical**. All new
   INVARIANT-class rules live in the new §4.1 and are explicitly marked as *additions of revision 2*.
   (Mandate (f); additive extension flagged as K7.)
5. **Tool names stay out of the constitution.** The constitution names *roles and boundaries*
   ("graph projection store", "workflow executor", "search backend"); concrete tools (Kùzu 0.11.3,
   LangGraph, LiteLLM, Optuna, pyribs, MLflow, DSPy, PyG) remain in the Gesamtplan as
   BACKLOG/implementation guidance. (Owner choice K13.)
6. **No citation-marker leakage.** The Gesamtplan's `fileciteturn…`/`citeturn…` artifacts must not
   be copied into the constitution; all draft text below is free of them.

---

## 3. Section-by-section diff plan (ready to paste)

Every unit quotes the exact current heading, states the action, and gives the full replacement or
insertion text. Text not listed here is carried forward **verbatim**.

### 3.0 Header block — REPLACE

Current (lines 3–10):

> `Plan-ID: daedalus-master-plan` / `Revision: 1` / `Version: 1.0.0` / `Status: adopted` /
> `Date: 2026-07-30` / `Owner: repository owner` / `Active delivery gate: Gate 0 — Canonical Kernel` /
> `Amendment chain: docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl`

Replacement:

```markdown
Plan-ID: `daedalus-master-plan`  
Revision: 2  
Version: 1.1.0  
Status: adopted  
Date: <owner-approval date>  
Owner: repository owner  
Active delivery gate: Gate 0 — Canonical Kernel  
Amendment chain: `docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl`
```

Notes: `Version: 1.1.0` because every change is additive/precising (owner choice K11 if 2.0.0 is
preferred). `Active delivery gate` stays Gate 0 — the Gesamtplan confirms Gate 0 as the only active
implementation focus (`DAEDALUS_GESAMTPLAN.md:273-275`).

### 3.1 `## 0. Authority model` — AMEND (one addition)

Keep the table and the rule-type list verbatim. Append one row-adjacent paragraph after the
rule-type list:

```markdown
`docs/DAEDALUS_GESAMTPLAN.md` is the owner-adopted consolidation and implementation
guide behind this revision. It is history/backlog class: it supplies deliverables,
sequencing detail, stack guidance, and evidence, and it does not override this plan.
```

Rationale: without this line the Gesamtplan floats with undefined authority next to the
constitution, which is exactly the "parallel source of truth" §3 forbids.

### 3.2 `## 1. What “iron” means` — UNCHANGED

### 3.3 `## 2. North star` — AMEND (append one paragraph)

Append after the existing second paragraph:

```markdown
Daedalus serves two operating modes on one kernel. **Renovation** distills,
understands, and changes existing software. **Genesis** compiles a natural-language
product intent into a `ProductSpec`, a target Fourfold graph, materialized software,
and a re-distilled actual graph that is verified against the target. Both modes are
defined in section 9.1 and share the same attempt, artifact, evaluation, and
promotion chain; neither creates a second product system.
```

(Mandate (d), anchor; source `DAEDALUS_GESAMTPLAN.md:42-63,232`.)

### 3.4 `## 3. Three public concepts` — AMEND (append internal-vocabulary paragraph)

Keep the three bullets and the closing paragraph **verbatim**. Append:

```markdown
Internally, the kernel is described by a fixed architectural vocabulary that names
layers, not products:

- the **Fourfold Project Twin** is the semantic core — the canonical, revision-bound
  representation of a project (section 5);
- the **Trust Kernel** is the operative boundary — the single path through which
  every effect, artifact identity, event, and promotion passes (section 4.1);
- the **Orchestration Layer** is the mission-execution substrate, surfaced to users
  through Ikarus (section 7);
- the **Evolution Layer** is the evaluator-driven variation substrate, surfaced as
  the Ariadne workload (section 8).

The canonical architecture sentence is:

> The Fourfold Project Twin is Daedalus' semantic core. The Trust Kernel controls
> all effects. The Orchestration Layer executes concrete missions. The Evolution
> Layer improves graphs, software candidates, and orchestration recipes through
> LLM-generated variants and evaluator-driven selection.

These four names are internal descriptions of Daedalus itself. They are not
additional public mythologies, not control planes, and not sources of truth, and
they grant no authority beyond sections 0 and 4.
```

(Mandates (a)(b)(c); source `DAEDALUS_GESAMTPLAN.md:30-32`. Conflict K1 — owner must ratify that
these are internal layer names, not a fourth/fifth public concept.)

### 3.5 `## 4. Constitutional invariants` — UNCHANGED (byte-identical)

Items 1–10 are carried forward without any edit (mandate (f)).

### 3.6 NEW `### 4.1 The Trust Kernel: the operative boundary` — INSERT after §4's list, before §5

```markdown
### 4.1 The Trust Kernel: the operative boundary

The Trust Kernel is the operative boundary that enforces invariants 1–10 on every
production-capable path. It consists of:

- policy decisions and the mechanical capability policy (section 0);
- persisted effect leases: intent is recorded before any external effect, with
  scope, TTL, budget, and kill-switch binding;
- the one canonical event store and the content-addressed artifact store;
- sandboxed, capability-bounded execution for attempts and evaluators;
- owner approval as a canonical, candidate- and evidence-bound contract
  (`OwnerApproval`), structurally required for promotion.

Authority is explicit:

    Authoritative:
    - source revision / content-addressed candidate tree
    - FourfoldSnapshot
    - Mission, Attempt, Policy, Evidence, and Campaign contracts
    - event store, artifact store, OwnerApproval

    Regenerable projections (never authority):
    - graph databases, experiment trackers, vector indexes,
      workflow checkpoints, UI state, search indexes

The following operative rules are INVARIANT-class. Rules (i)–(v) restate invariants
1–5 and 8 in operative form; rules (vi)–(viii) are additions of revision 2:

  (i)    there is exactly one canonical contract and event chain;
  (ii)   no LLM judgment is a hard correctness or promotion gate;
  (iii)  no candidate sees or modifies its evaluator;
  (iv)   there is no automatic promotion;
  (v)    execution backends and projections cannot broaden policy;
  (vi)   no production path writes directly into the primary checkout — all
         writes happen in isolated, content-addressed attempt workspaces;
  (vii)  an Ariadne campaign varies exactly one major evolution axis unless a
         pre-registered interaction experiment says otherwise;
  (viii) a later gate must not mask an unfinished earlier gate: release
         promotion requires the active gate machine-readably closed, while
         integration progress requires only that the blocker set shrinks
         monotonically against a revision-bound baseline.

Until Gate 0's exit report is closed, the Trust Kernel is a delivery target, not a
proven security boundary; section 1's honesty rule about guards applies unchanged.
```

(Mandate (b); sources `DAEDALUS_GESAMTPLAN.md:69-78` (Steuerungsregeln), `146-204` (Trust-Kernel
box + Autoritätsgrenzen), `982-1000` (two CI modes/baseline), `280-287` (Schließreihenfolge).
Conflict K7 — rules (vi)–(viii) are *new* INVARIANT-class content and need explicit owner approval.)

### 3.7 `## 5. The Project Twin: the strongest falsifiable prior` — RETITLE + AMEND

New heading:

```markdown
## 5. The Fourfold Project Twin: semantic core and strongest falsifiable prior
```

Keep the plane table, the orthogonal-lineage paragraph, and the Forest paragraph **verbatim**, then
replace the closing paragraph ("This hypothesis is a “god-key” candidate…") with:

```markdown
The Fourfold Project Twin has two distinct statuses, and conflating them is an
error:

- **As contract**, the Fourfold snapshot family (section 5.1) is the canonical
  intermediate representation of the architecture. Planes, revision atomicity,
  explicit absence, and the cross-plane trust ladder are binding contract shape.
- **As performance claim** — that this representation beats simpler ones — it
  remains the strongest falsifiable PRIOR. It is a “god-key” candidate, not dogma,
  and earns its centrality only through the kill criteria in section 13.

The existing deterministic Forest is the lower IR base. The Fourfold compiler
adapts and extends it; it does not replace it and does not run beside it as a
duplicate. A `DesignContract` for product look and accessibility lives inside the
Knowledge plane, bound to Type and Code nodes and rendered runtime evidence; it is
not a fifth plane.
```

Then INSERT new subsection:

```markdown
### 5.1 Canonical Fourfold contracts

A `FourfoldSnapshot` atomically binds one source revision, its source-tree locator,
four `PlaneSnapshot`s (code, type, data, knowledge), verified cross-plane edges,
and the compiler manifest, under a canonical content digest.

Contract-level hard rules:

- every plane snapshot carries the snapshot's source revision — no mixed revisions;
- a plane that is unknown, partial, or failed is explicitly marked, never omitted;
- the snapshot's content digest equals its canonical serialized body;
- every trusted cross-plane edge carries at least one evidence locator and a
  verifier manifest digest.

Cross-plane relations move only along the trust ladder:

    proposed
    → syntactically_supported
    → source_verified
    → evaluator_verified
    → trusted
    → expired | rejected

A model or embedding may create a relation only as `proposed`. `trusted` requires at
minimum: same source revision, valid source locators, a reproducible verifier, an
evidence artifact, a relation type from the contract, and no contradicted hard
invariant. Unverified similarity expires or is retested; it never silently persists.

These contracts extend the existing canonical schema family; they are not a
parallel model set.
```

(Mandate (a); sources `DAEDALUS_GESAMTPLAN.md:98-107,234-247,360-381,572-621`.
STATUS grounding: the Gate-0 trunk already contains `daedalus/twin/contracts.py`,
`daedalus/twin/legacy_forest.py`, and `daedalus/twin/reference_compiler.py` — the
adapter-around-the-Forest approach prescribed by `DAEDALUS_GESAMTPLAN.md:1289` is started.)

### 3.8 `## 6. Latent Atlas and cross-plane discovery` — AMEND (one sentence)

Keep all text verbatim; append to the second paragraph (after "…expire or are retested."):

```markdown
The full lifecycle and minimum verification requirements for such proposals are the
trust ladder in section 5.1.
```

### 3.9 `## 7. Ikarus, orchestration, and knowledge` — RETITLE + AMEND

New heading:

```markdown
## 7. Ikarus and the Orchestration Layer
```

Keep the existing three paragraphs verbatim, then append:

```markdown
The Orchestration Layer is the kernel's mission-execution substrate: mission
planning, durable workflows, attempt contracts, and runtime selection. Two boundary
rules are binding:

- **Executors are backends.** A durable-workflow engine may execute plans,
  checkpoint, and interrupt for humans, but the canonical event store and the
  mission state machine remain Daedalus-authoritative. Workflow checkpoints are
  regenerable projections.
- **Interrupt-safe effects.** Resuming an interrupted workflow may re-run work;
  therefore every effect ahead of an interrupt is idempotent or protected by an
  intent-before-effect lease and receipt through the Trust Kernel.

Runtimes are admitted only by declaration plus proof: a runtime manifest declares
capabilities, effects, sandbox, and conformance requirements, and a current
conformance receipt bound to exact manifest, adapter, tool, and image digests is
required before any productive effect.
```

(Mandate (c); sources `DAEDALUS_GESAMTPLAN.md:132-144,206,712-771`.)

### 3.10 `## 8. Ariadne evolution loop` — RETITLE + AMEND

New heading:

```markdown
## 8. Ariadne and the Evolution Layer
```

Insert before the existing "Every campaign follows this controlled loop:" list:

```markdown
The Evolution Layer is the kernel's variation substrate: campaigns, operators,
candidate archives, selection, and sealed evaluators. LLMs hold exactly three
proposal roles across the dual layer — orchestration (plan, compress context,
implement, repair, explain), graph intelligence (propose cross-plane relations,
target graphs, graph deltas, motif compositions), and evolution (stochastic
mutation and recombination operators for code, graphs, prompts, retrieval, and
orchestration recipes). In every role the control chain is:

    LLM proposes
    → contracts constrain
    → sandbox contains
    → compiler materializes
    → evaluators measure
    → owner promotes

Search and archive backends (parameter search, quality-diversity archives,
experiment UIs) are regenerable projections below the campaign contracts and
receipts; a graph proposal is never trusted evidence, and no proposal operation
grants effects.
```

In the existing numbered loop, two terminology edits (existing text otherwise verbatim):

- Step 2: "Build the base Forest for an exact source revision." →
  "Build the base Fourfold snapshot (Forest-based IR) for an exact source revision."
- Step 7: "Build a candidate Forest and revision-aware delta." →
  "Build a candidate Fourfold snapshot and revision-aware delta."

(Mandate (c); sources `DAEDALUS_GESAMTPLAN.md:34-40,208-231,623-651`. The step edits are the only
touch of pre-existing §8 wording — flagged K12.)

### 3.11 `## 9. Code generation and evolution framework` — UNCHANGED, then INSERT §9.1

Keep §9 verbatim. Insert new subsection after it:

```markdown
### 9.1 Operating modes: Renovation and Genesis

Daedalus has exactly two operating modes, sharing one kernel:

    Renovation:
    existing repository → FourfoldSnapshot → verified change

    Genesis:
    ProductSpec → TargetFourfoldSpec → generated repository
    → actual FourfoldSnapshot → verified candidate

**Renovation** starts from a distilled base snapshot of an existing revision.
**Genesis** starts from a target graph with no base source revision. After their
different starting points, both run through the same attempt, content-addressed
artifact, evaluation, and sealed-promotion chain. There is no second product
system.

Genesis is never “one prompt magically yields a product.” Its controlled path is:

    Intent
    → ProductSpec
    → TargetFourfoldSpec
    → GraphProposal
    → motif composition
    → materialization plan
    → isolated repository
    → build and runtime tests
    → re-distillation
    → target/actual graph comparison
    → repair cycles
    → EvidencePacket
    → owner acceptance

Binding rules:

- a `ProductSpec` and `TargetFourfoldSpec` are canonical contracts; source code is
  a materialization of them, and every candidate is re-distilled and verified
  against the target graph (round-trip verification);
- Genesis is a controlled target architecture until Gate 4; a broad
  “software from one sentence” capability becomes production-capable only after
  Gate 4 and is demonstrated, under owner acceptance, at Gate 5;
- look and accessibility requirements enter through the Knowledge-plane
  `DesignContract` with deterministic and visual evidence — never through an
  unverifiable aesthetic judgment;
- no Genesis step auto-promotes; invariant 5 applies unchanged.
```

(Mandate (d); sources `DAEDALUS_GESAMTPLAN.md:42-63,232-247,253-262,382-391,441-466,1563-1567`.)

### 3.12 `## 10. Delivery gates` — AMEND each gate's deliverables (mandate (e))

Intro paragraph: keep verbatim, append one sentence:

```markdown
Each gate closes only through a machine-readable gate report; integration work in
between must keep the report's blocker set monotonically shrinking against a
revision-bound adoption baseline (section 4.1, rule viii).
```

#### `### Gate 0 — Canonical Kernel (active)` — AMEND

Keep the existing deliverable list and exit sentence verbatim; append:

```markdown
Revision 2 makes the following Gate 0 deliverables explicit:

- this plan revision itself, adopted through the amendment protocol;
- a machine-readable gate report with a release check (`closed == true`) separated
  from a monotonic-progress check against a stored, revision-bound adoption
  baseline;
- `OwnerApproval` as a canonical contract bound to candidate, evidence, base HEAD,
  and target HEAD; promotion without a valid approval digest is structurally
  impossible;
- effect intents persisted as leases (scope, TTL, budget, kill switch) before any
  external effect;
- offload/write paths routed exclusively through isolated attempt workspaces; the
  primary checkout is never a write target;
- runtime manifests plus conformance receipts for every admitted runtime;
- an OS-level sandbox for attempts and evaluators with resource limits and
  process-tree kill, exercised by the fault-injection matrix (write outside
  workspace, primary-checkout mutation, egress without lease, secret enumeration,
  timeout, orphaned child after cancellation, evaluator manipulation, budget
  overrun, kill switch under load);
- any half-integrated path (inventory-only, unguarded) either fully guarded or
  explicitly absent — no half-productive entrypoints.

Gate 0 exits only when the gate report shows no unregistered, unguarded, or
inventory-only production entrypoints, no missing guard contracts, no runtime
conformance or fault-injection failures, no primary-checkout mutations, and
owner-approval enforcement — in addition to the fail-closed/fail-open demonstration
above.
```

(Sources `DAEDALUS_GESAMTPLAN.md:264-306,1123-1139,1274-1284`. STATUS grounding: the Gate-0 trunk
already carries `daedalus/gates/report.py`, `report_v3.py`, `release.py`, `baseline.py`,
`fault_matrix.py`, `daedalus/kernel/approvals.py`, `sandbox.py`, `runtime_conformance.py`,
`daedalus/runtimes/fault_matrix.py` — the report schema id and field list must be reconciled with
the trunk before adoption; see conflict K3.)

#### `### Gate 1 — Ignition slice` — AMEND

Keep the existing paragraph verbatim; append:

```markdown
The fixture is real, not mocked: a Python source defining `Event.voltage`, Markdown
documenting it, a CSV schema declaring it, and tests for behavior, schema
consistency, and symbol links. Acceptance is predicate-based: atomic source
revision; zero stale trusted references to the old symbol; the new symbol present
at all expected locations; all behavioral, schema, and link checks green; primary
checkout unchanged; zero automatic promotion attempts; and a replay whose digest
matches the original run.
```

(Sources `DAEDALUS_GESAMTPLAN.md:308-356`.)

#### `### Gate 2 — Forest v2` — RETITLE + AMEND

Proposed new heading (conflict K4 — owner decides the name):

```markdown
### Gate 2 — Fourfold Project Twin v2
```

Keep the existing two sentences verbatim ("Add function/method resolution… simpler
representations."); append:

```markdown
Gate 2 consolidates the semantic core over the existing Forest base: atomic
`PlaneSnapshot` assembly for all four planes; code and type overlays; data-plane
extraction; knowledge claims with evidence locators; the full cross-plane
proposal/verification lifecycle of section 5.1; a rebuildable graph projection
store that is never canonical (full drop-and-rebuild must pass); revision-aware
graph deltas; and the Genesis compiler contract only — `ProductSpec`,
`DesignContract`, `TargetFourfoldSpec`, `MaterializationPlan`, and a
round-trip report — with no unbounded builder. A small corpus-ingestion pilot
proves the extractors on foreign repositories.
```

(Sources `DAEDALUS_GESAMTPLAN.md:358-391,268`.)

#### `### Gate 3 — Baseline lab` — AMEND

Keep the existing paragraph verbatim; append:

```markdown
Gate 3 additionally delivers: sealed evaluator manifests and evaluator images
frozen before candidate execution; Renovation and small Genesis task fixtures; a
legally clean corpus of roughly 20–50 explicitly selected, permissively licensed
repositories, each with locator, revision, license expression, ingestion manifest,
extractor versions, snapshot digest, build/test evidence, known limitations, and
allowed reuse mode; and a three-level reuse taxonomy — `RepositoryTwin` (concrete,
revision-bound implementation), `MotifCandidate` (recurring, unproven subgraph),
`VerifiedMotif` (parameterized structure with evidence, compatibility conditions,
and known failure modes). Search, archive, and reporting backends are projections
regenerated from campaign receipts.
```

(Sources `DAEDALUS_GESAMTPLAN.md:393-421,488-490`.)

#### `### Gate 4 — One research hypothesis` — AMEND

Keep the existing paragraph verbatim; append:

```markdown
The pre-registered question is: does a verified Fourfold Project Twin, under equal
token, model, and cost budget, yield better context or operator selection than
BM25, embeddings, code-only graphs, and separate per-plane indices? A positive
finding requires all of: tasks, models, seeds, and budgets frozen in advance; the
strongest simple baseline compared; a pre-registered primary metric whose 95 %
confidence interval of the difference lies above zero; a cost/quality frontier
that does not worsen; the result holding on held-out repositories; the gain not
explained by extra context tokens alone; and edge-rewiring and plane-ablation
controls behaving as predicted. Only after this hypothesis wins may advanced
variants activate — versioned LLM-program optimization, heterogeneous graph
models, motif-based composition, latent similarity spaces, graph diffusion — each
as one registered campaign axis and never as a trusted-edge decider. A negative
result is archived and triggers section 13, not explained away.
```

(Sources `DAEDALUS_GESAMTPLAN.md:423-437,1438-1453`.)

#### `### Gate 5 — Public proof` — AMEND

Keep the existing paragraph verbatim (including the AlphaEvolve claim-bounding); append:

```markdown
Gate 5 additionally delivers one end-to-end controlled Genesis demonstrator: a
fixed `ProductSpec` including features, constraints, and a look/accessibility
specification, compiled through the section 9.1 path. The demonstrator does not
pass because source files were produced; the candidate must build, start, satisfy
the agreed scenarios, be re-distilled as an actual twin, and satisfy the hard
target-graph constraints — with owner acceptance and no unsupervised promotion.
```

(Sources `DAEDALUS_GESAMTPLAN.md:271,439-466`. Scope growth flagged K5.)

#### OPTIONAL STATUS block at the end of §10 (owner choice K8)

```markdown
STATUS (revision 2, non-binding planning values, not exit criteria): estimated
effort Gate 0: 6–9, Gate 1: 3–4, Gate 2: 8–12, Gate 3: 6–9, Gate 4: 7–11,
Gate 5: 4–6 person-weeks; total ≈ 35–52 plus 15–20 % reserve.
```

### 3.13 `## 11. Current priority` — AMEND (append)

Keep verbatim; append:

```markdown
Consolidation proceeds as a strangler rewrite inside this repository: new
canonical contracts and adapters are placed in front of legacy modules, and a
legacy path is deleted only when a replacement exists, golden behavior matches,
all callers are migrated, no effect entrypoint remains, replay succeeds, and
rollback is documented. There is no greenfield restart and no second long-lived
integration branch.
```

(Sources `DAEDALUS_GESAMTPLAN.md:28,1171-1186,1355-1364,1534-1538`.)

### 3.14 `## 12. Forbidden default directions` — AMEND (append four bullets)

Keep the existing list verbatim; append:

```markdown
- a projection or execution backend (graph database, experiment tracker, workflow
  checkpointer, vector store) acting as a source of truth;
- a production path that writes directly into the primary checkout;
- an unbounded Genesis builder, or Genesis presented as production capability,
  before Gate 4 evidence exists;
- a second long-lived integration branch or parallel rewrite repository.
```

(Sources `DAEDALUS_GESAMTPLAN.md:71-74,821,1524,1534-1538`.)

### 3.15 `## 13. Kill criteria` — UNCHANGED (byte-identical)

The Gesamtplan explicitly defers to these ("gemäß den bestehenden Kill Criteria",
`DAEDALUS_GESAMTPLAN.md:1453`). No edit.

### 3.16 `## 14. Alignment protocol for every change` — UNCHANGED

### 3.17 `## 15. Amendment protocol` — UNCHANGED

---

## 4. Draft ledger record (sequence 2)

To be appended to `docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl` **at adoption** (values in
`<…>` are computed then; field order/canonicalization must match the guard's serializer):

```json
{"accepted_at":"<ISO-8601>","approval_ref":"<owner approval reference>","base_plan_sha256":"a47d84ee736fcaebd76f4309f4e0653f536415b9bda9e04940920ca1896026d4","base_revision":1,"owner":"repository-owner","plan_id":"daedalus-master-plan","previous_record_sha256":"3ccedd9a36e21d1764d16766431450e422628129faa9e7a68684bfeccf3793ea","record_sha256":"<computed>","result_plan_sha256":"<sha256 of adopted revision-2 file>","result_revision":2,"schema":"daedalus-master-plan-amendment/1","scope":["fourfold-semantic-core","trust-kernel","dual-layer-orchestration-evolution","renovation-genesis","gate-deliverables","gesamtplan-authority-classification"],"sequence":2,"status":"accepted","summary":"Precise the Fourfold Twin as semantic core, name the Trust Kernel as operative boundary, adopt the Orchestration/Evolution dual layer, define Renovation and Genesis, extend per-gate deliverables; invariants 1-10 unchanged.","version":"1.1.0"}
```

## 5. Adoption mechanics checklist (per §15 — NOT executed by this lane)

1. Owner reviews this draft and the conflict list (section 6) and decides each K-item.
2. Amendment session starts with
   `DAEDALUS_IRON_PLAN_AMENDMENT=a47d84ee736fcaebd76f4309f4e0653f536415b9bda9e04940920ca1896026d4`
   (current full-plan sha256, hook- and ledger-attested).
3. Atomic change set: `docs/IKARUS_ARIADNE_MASTER_PLAN.md` (revision 2 text),
   `docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl` (one record, section 4), guard tests
   (`tests/test_iron_plan_guard.py` or trunk equivalent), and derived projections only if the
   owner chooses renumbering (with the subsection strategy, AGENTS.md's "section 15" reference
   survives unchanged — verify anyway).
4. Run `python tools/iron_plan_guard.py verify` plus the guard unit tests and the relevant
   fault-injection suite.
5. Branch per Gesamtplan: `plan/revision-2`, squash-merged with owner approval — **but see K6:**
   the Gesamtplan's `experimental`-branch model conflicts with the real trunk
   `work/g0-trunk-20260817`; the owner must name the actual integration target first.

## 6. Genuine conflicts — owner decisions required (NOT silently resolved)

| # | Conflict | Constitution says | Gesamtplan says | Draft default (needs ratification) |
|---|---|---|---|---|
| K1 | Public concepts vs dual-layer naming | §3: only three public concepts; no new mythology/control plane (`IKARUS_ARIADNE_MASTER_PLAN.md:68-79`) | Central sentence names Fourfold Twin, Trust Kernel, Orchestration Layer, Evolution Layer (`DAEDALUS_GESAMTPLAN.md:30-32`) | Treat the four as internal layer vocabulary inside Daedalus (§3 addition, 3.4) — owner must confirm none becomes a public product name |
| K2 | Twin status | §5: strongest falsifiable prior, "not dogma", subject to §13 (`:111-131`) | "ist Daedalus' semantischer Kern" — assertive (`:30,98`) | Dual status: contract canonical, performance claim stays PRIOR under unchanged §13 (3.7) |
| K3 | Gate-0 exit wording | "Exit only when a fault-injection matrix demonstrates fail-closed protected effects and fail-open read-only inspection" (`:227-228`) | Machine-readable `daedalus-gate-report/1` with `closed==true`, eight empty lists, `owner_approval_enforced` (`DAEDALUS_GESAMTPLAN.md:289-306,1126-1139`) — schema has **no field** for fail-open read-only inspection; trunk already has `daedalus/gates/report_v3.py`, so `/1` may be stale | Keep BOTH criteria (report AND fail-closed/fail-open sentence); owner decides schema id/version and whether fail-open inspection becomes a report field |
| K4 | Gate 2 name | "Gate 2 — Forest v2" (`:237`) | "Fourfold Project Twin v2" (`:268,360`) | Rename to "Fourfold Project Twin v2" (Forest stays the named IR base) |
| K5 | Gate 5 scope | Public proof only (`:262-269`) | Public proof **plus** end-to-end Genesis demonstrator with look spec (`:271,439-466`) | Adopt the addition; owner should confirm the enlarged exit bar |
| K6 | Branch model vs reality | Constitution silent on branches | `experimental` as sole integration branch; `plan/revision-2` from it; baseline tag dated 2026-07-31; gantt start 2026-08-03 (`:821-926,1459-1502`) | Real trunk is `work/g0-trunk-20260817`@60b2bfe (briefing); repo checkout sits on `checkpoint/2026-07-20-session`; no `experimental` branch verified. Owner must map the Gesamtplan branch names onto reality before the plan-PR; dates are already stale. Draft keeps branch policy OUT of the constitution (only the "no second long-lived integration branch" bullet, 3.14) |
| K7 | New INVARIANT-class rules | Mandate (f): existing invariants unchanged | Steuerungsregeln add: no primary-checkout writes, one axis per campaign, no gate masking (`:69-78`) | Added as §4.1 rules (vi)–(viii), explicitly marked as revision-2 additions — constitutional extension requiring explicit owner approval |
| K8 | Effort estimates in the constitution | None present | Per-gate PW + timeline (`:264-271,1455-1502`) | Include as one explicitly non-binding STATUS block (3.12) or omit — owner picks |
| K9 | Numbering strategy | AGENTS.md + plan reference "section 15"/"section 13" by number | New content needs a home | Subsection insertion (4.1, 5.1, 9.1), no renumbering |
| K10 | Language | English | German | New text in English |
| K11 | Version | 1.0.0 | — | 1.1.0 (additive); owner may prefer 2.0.0 |
| K12 | "Forest" → "Fourfold snapshot" in §8 loop steps 2/7 | Existing prior text | Gesamtplan terminology (`:337,1289`) | Minimal two-phrase edit (3.10) — the only touch of pre-existing prior wording; owner sign-off |
| K13 | Tool names in the constitution | Constitution names no tools | Pins Kùzu 0.11.3 (upstream archived 2025-10-10), LangGraph, LiteLLM, Optuna, pyribs, MLflow, DSPy, PyG (`:474-508`) | Constitution names roles/boundaries only; tools stay Gesamtplan/BACKLOG |

Additional note (not a conflict): the Gesamtplan lists "Masterplan-Revision" itself as a Gate-0
deliverable (`:266`), so Gate 0 cannot machine-readably close before this amendment is adopted —
the ordering in section 5 above respects that.

## 7. Honesty ledger

- Both plan documents were read in full (369 and 1583 lines). No section of either was skipped.
- The base plan sha256 was **not recomputed** by this lane (Bash guard risk on protected path
  names); it is attested independently by the active hook and by ledger record 1's
  `result_plan_sha256` — two artifacts, one value.
- Trunk observations are file-existence evidence only (Glob); no module semantics were verified
  here. Whether `report_v3.py` supersedes the `daedalus-gate-report/1` schema is UNDETERMINED —
  raised in K3 rather than assumed.
- Nothing in this report modifies any protected artifact. Adoption requires the full §15 protocol.

Iron Plan: ALIGNED (this report proposes an AMENDMENT; it does not perform one)
Iron Gate: 0
Evidence: file reads cited above; Glob listings of `agent_env_g0/daedalus/{gates,kernel,runtimes,twin}`; amendment ledger record sequence 1.
