# The multigraph verdict, and the refined path through the gates

Date: 2026-07-31 · Author: Athena · Class: analysis + BACKLOG proposal.
NON-AUTHORITATIVE: `docs/IKARUS_ARIADNE_MASTER_PLAN.md` (rev 1) is the sole
semantic authority; this document refines sequencing INSIDE its gates and
changes no invariant, no prior, no gate definition. Numbers are stamped
[MEASURED]/[INHERITED]/[ASSUMED] per repo convention.

The owner's question, verbatim in spirit: *"data graph and code graph are both
the same ast graph? or different? also connection to the knowledge graph? —
verify if the multigraph idea can work, or if we are stupid."* And the product
frame: *"a codebase builder with integrated documentation / knowledge
management / synthesis of knowledge."*

---

## 1. The verdict: not the same graph — and this repo already proves it with a number

The four planes share **sources** but must not share **node identity**. That is
not taste; the repository has already measured what happens when the
distinction collapses.

**Code plane = the AST projection. Yes.** Files, symbols, functions, control
structure, import edges — parsed by tree-sitter, indexed by `structcore`. This
plane is genuinely AST-derived and it is the one plane where "it's the AST
graph" is true.

**Type plane ≠ AST, and the proof is arithmetic, not philosophy.** A type is
ONE node even when 2,000 AST sites mention it. `daedalus/structcore/forest.py`
(docstring, committed 007a237) records what a naive merge does:

- Uncapped, "two functions that mention the same type are adjacent" makes
  **53.6% of all function pairs adjacent** [MEASURED, before the layer was
  built] — the merged graph is effectively complete, i.e. the lens dissolves
  the graph instead of enriching it. This single number is the empirical
  refutation of "same graph".
- A type node has **no bytes on disk**, so packing it makes
  `dss._estimated_tokens` invent costs and the token accounting becomes
  fiction — which is why `type`/`field` deliberately never joined
  `FILE_NODE_KINDS`.
- Type nodes in `modules`/`import_edges` would inflate the denominator of
  `graph.fenced_dominance`, the safety stand-down would stop firing, and every
  task would ride the premium lane — **real money spent for a wrong reason**.

So the type layer exists as `type_nodes`/`type_edges`: a lens whose evidence
re-scores file nodes, never a peer node set. Same source text, different graph.

**Data plane ≠ AST at all.** The plan's Data plane is *data-at-rest structure*
— schemas, tables, fields, formats, fixtures, lineage — NOT the compiler's
dataflow graph. This distinction answers the owner's question at its root:

- If "data graph" meant **dataflow** (DFG), it would indeed be derivable from
  the same AST and would belong inside the code plane — that is exactly what
  Code Property Graphs do (Yamaguchi et al. 2014: AST+CFG+PDG merged, and it
  won at vulnerability discovery).
- The plan chose the **schema reading**, and for a codebase *builder* that is
  the right choice, because a data entity's members often have **no AST node
  anywhere**: a CSV header, a wire-format field, a column named only in a
  Markdown table. The same entity is *declared* in many places (ORM class, SQL
  migration, CSV header, doc table) — so its identity cannot be any one AST
  node, and cross-plane bindings to every declaration site are precisely the
  value the plane adds.

Gate 1 is deliberately shaped as the existence proof: propagating
`Event.voltage -> bias_voltage` across Python + Markdown + CSV is a graph
traversal only if the data entity is its own node with verified bindings. If
data were "just the AST", that mission would be a rename refactor and its CSV
and Markdown halves would be invisible.

**Knowledge plane ≠ AST, obviously — and it is the owner's product thesis.**
Docs, ADRs, issues, concepts, claims. Partially real today: markdown documents
are Forest node kinds (9273ab2), the wikilink parser exists but is unwired
[MEASURED: `markdown.py` parses `[[wikilinks]]`, `index.py` never calls it].

**The connection mechanism — the actual novelty and the actual risk.** Planes
connect by **edges, not node merging**:

    class Event (code) --declares--> Event (type) --persists-as-->
    events.csv:voltage (data) <--documents-- docs/hardware.md §Voltage (knowledge)

The latent atlas proposes such bindings from embeddings over Node Cards; a
verifier checks source evidence, revision compatibility and constraints before
an edge is trusted; unverified similarity expires. Forest = compiled IR, atlas
= hypothesis machine, evaluator = truth boundary (plan §6). The `forest.py`
extension contract ("new node kinds and relation layers without changing this
contract" — document, type and field were each added exactly that way, at zero
schema cost [MEASURED]) means the remaining planes are additions to ONE
snapshot, not a second system.

**Are we stupid? No — but the design's failure mode is named, and it is not
incoherence.** It is **redundancy**: on a repo with little real schema/fixture
material the data plane may ablate to zero marginal contribution, and
cross-plane fusion may lose to four separate indices. The plan already carries
the kill criteria (§13: full representation must beat code-only/BM25;
degree-preserving edge randomization must NOT perform equivalently; every
plane must show marginal contribution). Nobody in the cited literature ships
the combination four-plane IR + verified cross-plane bindings +
evidence-bound promotion as a code-evolution substrate — CPG proves multi-layer
pays for analysis, CodexGraph/RepoGraph/LocAgent prove small edge sets win for
agent retrieval, and the type/field layer for agents is frontier [INHERITED
from docs/research/TYPE_GRAPH_AND_KNOWLEDGE_SPACE_PLAN.md research sweep].
That is the bet, and Gate 2's ablation requirement is the instrument that
falsifies it cheaply before Gate 3 scales it.

## 2. The product sentence, mapped onto the three names

*"A codebase builder with integrated documentation, knowledge management and
synthesis of knowledge"* requires no new subsystem — it is the existing
trinity read left to right:

| Owner's phrase | Plan concept | What exists today [MEASURED 2026-07-31] |
| --- | --- | --- |
| codebase builder | **Ariadne** (evolution workload) | Lane B attempts in worktrees, evaluation cascade, Best-of-N baseline; no promotion path (by design, until sealed promotion lands) |
| integrated documentation | **Knowledge plane** | markdown as Forest node kind (committed); wikilink parser unwired; wiki UI planned (Teil B, Momus GO-WITH-CHANGES) |
| knowledge management | **Product memory + Forest knowledge crosslinks** | journal live; certified ledger built-and-dead (island); crosslinks Gate 2 |
| synthesis of knowledge | **Latent atlas + verified bindings** | embeddings module exists, vector index empty [MEASURED: vectors.db absent]; verification loop = Gate 2/4 |
| one Superagent surface | **Ikarus** | chat spine + CLI (29 subcommands); MissionContract type does not exist yet — Gate 1 forces its first instance |

"Beat AlphaEvolve" stays bounded by plan §10: AlphaEvolve is closed, so the
permitted claim is budget-equal public-artifact scores or an explicitly
narrower proxy result. The flex the owner wants is Gate 5's receipts, not a
marketing sentence.

## 3. Current position, measured today (2026-07-31)

- **Gate 0 ACTIVE.** HEAD 51fe781, branch checkpoint/2026-07-20-session.
- **Ignition blocker measured:** `gate_discrimination --head-only` refused with
  `COULD NOT MEASURE: baseline_red -- baseline pytest exit 1` [MEASURED
  overnight]. That is correct fail-closed behavior; the red test's identity is
  being re-measured now.
- **Funnel lane repaired today:** the claims123 run (123 agents) died upward —
  scan 5/100, research 8/15, review 6/6 blocked on `Invalid \escape`
  [MEASURED]: models quoting backslash-bearing source emit invalid JSON
  escapes and `extract_json` destroyed the whole answer. Fixed losslessly with
  a lookbehind-guarded escape repair recorded as `handoff.harness_repairs`;
  plus `coerce_report` no longer refuses an evidence-bearing answer for a
  missing summary (recorded as `summary_was_defaulted`). 13 new regression
  tests; 126 provider-suite tests green [MEASURED].
- **Two funnel defects still open:** the fan-out counts a blocked unit as
  `ok`, and resume serves a persisted blocked answer forever (never retried).
  Recon in flight; fix belongs in the fan-out lane before the next paid run.
- **Sealed promotion:** owner decided the trust root — signed tag
  (`git tag -s promote/<candidate_sha>`, verified via `git verify-tag` +
  committed allowed-signers file), regeneration VOIDS an approval. Not yet
  implemented; steps in docs/GATE0_SEALED_OWNER_APPROVAL.md §6.

## 4. The refined path — strictly inside the gates, in order

### Gate 0 — finish the kernel (everything below is ALIGNED, nothing new)

1. **Green the baseline, fire the ignition, produce the receipt.** The
   standing done-criterion. A receipt or a measured blocker, nothing else.
2. **Implement sealed promotion** per the owner's trust-root decision
   (invariant 5). Receipt shape unchanged (detached-signature upgrade path
   stays open).
3. **Close the named choke-point defects:** `attempt.py` READ_ONLY_REPO_VERBS
   argument-shape validation (`--ext-diff`/`--textconv` escape demonstrated);
   the cleanup-before-ledger-resolution crash window (two-intent fix agreed,
   never implemented); the inert Python lint gate must report itself inert
   instead of returning green (a guard whose absence no test detects is
   decoration).
4. **Run the fault-injection matrix** — fail-closed protected effects,
   fail-open read-only inspection. This is the exit test; Gate 0 does not
   close on vibes.

### Gate 1 — the ignition slice IS the owner's product sentence in miniature

One mission: `Event.voltage -> bias_voltage` across Python, Markdown, CSV.
Ikarus compiles ONE MissionContract (its first real instance — "the ticket has
no type" today); the planes produce two typed WorkItems; attempts run
isolated; EvidencePacket from tests + schema checks + link checks; no
auto-merge. Deliberately small: Gate 1 needs **minimal plane extraction for
one data entity across three file kinds** — code plane exists, markdown nodes
exist, the one genuinely new piece is a CSV/schema extractor. It does NOT need
the full Forest v2, and building more here would be drift.

### Gate 2 — Forest v2: where the multigraph is built and put on trial

Function/method resolution, generalized data/schema extraction, knowledge
crosslinks (wire the existing wikilink parser), revision atomicity, evidence
locators — and the **four-plane ablations**. The type-graph plan (Teil A
implemented and Momus-hardened; committed 007a237/2fc037e) slots here as the
type lens. The rule that keeps us honest: **do not scale before the full graph
beats simpler representations.** If a plane ablates to zero here, it dies here
— archived, amended, cheap.

### Gate 3 — baseline lab (this is where the RTX box earns its place)

Frozen public tasks, evaluator versions, budgets, seeds, and the §10 baseline
set (Random, Best-of-N, single-LLM loop, BM25, embeddings, code-only graph,
four separate indices, evaluator-only, MAP-Elites, AlphaEvolve-like proxy).

### Gate 4 — one hypothesis: Graph-conditioned Representation Search

Pre-registered, frozen generator/model/budget/evaluator, controls including
edge rewiring and label permutation. One hypothesis, complete ablations.

### Gate 5 — public proof, claim bounded by observed evidence.

## 5. RTX machine: move the lanes, not the project

Recommendation, with the plumbing already in the tree:

- **Do not relocate the repo.** The laptop is the reproducibility floor — the
  "can it run on a potato" test is a named plan value (honest claims §4.9
  require declared hardware; §13 reports product reliability separately).
- **Do move the compute.** The dark RTX lane already exists as env vars
  (`DAEDALUS_RTX_OLLAMA_HOST`/`_TOKEN`, accelerators.py:31-35, unset
  [MEASURED 2026-07-28]) and the tailnet bench (100.119.126.9:11434) is
  already what the council room defaults to. Local-model inference, funnel
  swarms and every Gate 3 baseline run belong there; setting the env vars
  costs nothing and every receipt stamps its hardware.
- **Two facts before any full move:** (a) every minted eval task hardcodes an
  absolute repo path and error-rows on any other machine [MEASURED, eval
  section of the architecture narrative] — fix that for §13's held-out-repo
  checks regardless of hardware; (b) RTX-over-tailnet is an **egress lane,
  not "local"** — offload's `lane='trusted'` derives from the provider name,
  not the resolved host, which is an open Gate 0 safety item. The lane move
  must go through the egress policy, never around it.

## 6. What this document does NOT do

It does not amend the plan, touch a protected artifact, or start a Gate 2+
deliverable early. Every listed action is either already-mandated Gate 0 work,
the Gate 1 slice as §10 defines it, or scheduling advice inside later gates.
The multigraph remains a PRIOR: central, falsifiable, and on trial exactly
where the plan says it goes on trial.
