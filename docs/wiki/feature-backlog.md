---
title: Feature backlog
type: backlog
status: living
updated: 2026-07-30
---

# Feature backlog

Harvested from the session of 29–30 July 2026 before compaction. Every entry is
something that was decided, designed or discovered in conversation and would
otherwise exist only in a transcript. Status is honest: **built** means it runs
and has tests, **partial** means code exists but is unwired or untested,
**designed** means a plan exists, **idea** means it was argued for and nothing
was written.

Related: [[Graph delta as fitness]], [[Type graph]], [[Data layer]],
[[Knowledge layer]], [[Observation layer]], [[Agents hold no state]].

## The four graphs

| # | Layer | Edges | Status |
|---|---|---|---|
| 1 | Code | imports, calls, clones | built (pre-existing) |
| 2 | Type | has_field, field_type, consumes, produces, inherits, alias_of | **built**, opt-in `DAEDALUS_INDEX_TYPES` |
| 3 | Data | reads, writes, includes, figures + artefact schemas | **partial** — `structcore/artifacts.py` exists, unwired to the index |
| 4 | Wiki | wikilinks, doc→code, doc→type | **built**, opt-in `DAEDALUS_INDEX_WIKI` |

Not a fifth layer: **provenance** (`declared` / `inferred` / `mined` / `observed`)
is a stamp on edges across all four. Nor are **worlds** — a derived partition
over the union, and a separately evaluated algorithm.

## Open, with a measurement attached

- **Type-graph ceiling test** — the one number that says whether layer 2 earns
  its keep: over the minted corpus, for each missed `must_include` label, is the
  defining symbol reachable via type edges but NOT via import+call edges?
  Backtest-clean. *Nobody has run it.* Independently confirmed by research that
  no published ablation isolates a type layer.
- **Dataflow / inference sidecar** — `scip-python` (Pyright) for unannotated
  code and dict payloads. Off by default; changes the cost class from one
  `ast.parse` to a Node process over the repo.
- **Dict-key mining** — `x["literal"]` accesses into pseudo-fields with
  `provenance=mined`. Days of work against weeks; measure before the sidecar.
- **Behavioural tracer** — `coverage.py` for liveness, MonkeyType-style runtime
  type recording for real dict shapes. `daedalus/observe/shape.py` is the
  descriptor; the tracer that calls it does not exist.
- **Contradiction detector** — the payoff of fusing static and behavioural:
  declared-but-never-observed, observed-but-never-declared, field never read,
  artefact written but never read, artefact read but produced by nothing.

## Multi-language and provenance

- **LaTeX tier 0 first** — smallest piece, largest domain value: closes
  paper → figure → script → data. Extends the docref lane to `.tex` instead of
  inventing a subsystem.
- **SCIP consumers**, verified active 2026-07-30: `scip-python` (Pyright),
  `scip-clang` (C/C++, therefore ROOT — needs `compile_commands.json`),
  `scip-java`, `scip-typescript`, `scip-go`, `scip-ruby`. `scip-rust` is
  immature (10 stars). **None exist for Fortran, Verilog or LaTeX** — those stay
  tier 0/1 and must report `not_supported`, never a numeric zero.
- **ROOT reflection** — `TClass`/`TDataMember` knows every data member of every
  class. More precise than any static pass; needs ROOT installed, so an
  enrichment and never a dependency.

## Fitness and evolution

- **Graph delta**, built: three layers (references / literals / AST structure),
  12/12 on the hand corpus. Held-out detection **95.3%** (286/300) on the clean
  arm; false alarm **0 of 38 real commits** on pure-deletion. Both regenerable:
  `python -m daedalus.eval.graph_delta . --held-out` and `--specificity`.
  *Supersedes the earlier 75.3% / 0.9% / 0.7% figures, which had no committed
  command and cannot be reconciled — see [[Night shift 2026-07-30]].*
  Remaining blind spot: **14 of 68 `change_constant` mutants** move no layer.
- **Mutation generator**, built — six AST operators, deterministic,
  trivial-compiler-equivalence check, and no-go filters that **now actually
  run**. They were defined, documented as built, and called from nowhere until
  2026-07-30; wiring them refuses 62 sites on the no-go function list and 3
  inside `__main__` blocks, published on `generate.last_filtered`.
- **Semantics-preserving generator — partial.** The other half of the cold
  start: rename a local, reorder independent statements, reformat. Good patches
  by construction, exactly as mutants are bad ones. `daedalus/preservation.py`
  (15.3k) exists on branch `experiment/deepseek-lab`, unmerged and under
  adversarial review. Without it a new project has no specificity arm.
- **Intent plus delta, never delta alone.** A fix that deletes a check and a
  defect that deletes a check are structurally identical; only declared intent
  separates them. A candidate declaring "this is a distillation" flips the
  question to "did anything disappear that another layer still depends on".
- **Aristaeus lane — evolution with no model at all.** Dead-code removal,
  duplicate merging, expression simplification: exact oracles, dense fitness,
  zero tokens. The one place pure evolution genuinely produces code.
- **Division of labour**: the LLM is the MUTATION OPERATOR (a prior over
  plausible programs), the machine is the EVALUATOR. Never the reverse — a judge
  from the same model family gets gamed by its own proposer.

## Write-lane constraints

`MAX_REWRITE_CHARS` is 24,000 and rewrites are whole-file only. Of 149 modules,
107 fit; the four largest and most active are blocked:

| Module | Size | Role |
|---|---|---|
| `structcore/typegraph.py` | 53.1k | type layer |
| `daedalus/eval/graph_delta.py` | 28.6k | fitness function |
| `structcore/artifacts.py` | 27.5k | data layer |
| `daedalus/tools/vet.py` | 26.2k | capability gate |

This argues for a patch-based write path, and independently for the distillation
lane: a module too large for an external agent is too large for a human.

## Cold start — a project with no history

Three candidate sources that need no history:

1. **Declared features** — the kitchen's feature list. Belongs to the KITCHEN,
   never to an agent: an agent holding its own todo list is invisible state.
2. **The wiki as substrate** — specs, references and constraints exist before
   code. A page with `doc_edges > 0` and `code_edges == 0` is a *documented but
   unimplemented* intention, and it is DISCOVERED rather than declared. The
   reverse (code with no page) is undocumented. `wiki_code_links` already
   computes both; the query does not exist yet.
3. **Manufactured corpora** — mutants for the bad arm, semantics-preserving
   transforms for the good arm. Thresholds are per-project; the detector is
   portable, the numbers are not.

Measured candidates (drift, hotspots, docrefs) arrive later, when code exists.
The transition from declared to measured is observable rather than asserted.

## Orchestration

- **The Pass** — the restaurant view: every kitchen (project) with its workers
  (models) at stations (roles), plus a ticket rail. The home screen, because the
  first question is "who is cooking and is anything burning".
- **Two candidate sources in one queue**, each with visible provenance:
  MEASURED (what is wrong) and DECLARED (what is wanted). The picker today only
  has the first.
- **Temporary vs static agents** — resolved: agents hold no state, knowledge
  does. See [[Agents hold no state]].
- **Shift / working window** — built: `daedalus/shift.py` + prompt hook +
  ticker. The same object an autonomous Ikarus loop reads to decide whether to
  continue.

## Product surfaces

- **Four spaces**: Chat · Mission Control · Graphs (one forest, N lenses) ·
  Wiki. Loop telemetry currently mislabelled under "Knowledge" and must move.
- **Design direction**: projected line art over a lit void, not frosted cards;
  the rotating 3D forest as the hero; lenses that MORPH rather than swap; mono
  for measurement and one display face; no grotesk body text.
- **React Bits is mandatory** for UI work (shadcn MCP, installed user-wide).
  MIT + Commons Clause: usable in the product, **never redistributable**, so
  fetch per project and never vendor.
- **Tauri app is the product.** Daedalus-as-MCP-server is a FEATURE, not the
  architecture — and it must pass its own `vet` gate, which is the interesting
  test.
- **GUI lane**: `daedalus/gui/probe.js` + `lint.py` built; anti-slop metrics
  calibrated on a labelled corpus of two rejected designs and one approved.

## Safety and policy, decided

- **Egress widened** 2026-07-30 to let external review lanes read `daedalus/`.
  `default_deny` stays on, the deny list still beats the allow list,
  `external_write_lanes` stays `[]`.
- **Open exposure**: `runs/council/room.md` is egress-allowed because `.md` is on
  the allow list. It contains the full cross-vendor transcript.
- **Wiki write path is BLOCKED** pending a named human-PUT gate list, the
  `vault_rel` validator (built), If-Match, and a Cerberus review.
  `kairos.gated_writes` is a provider-attempt pipeline, not a write fence.
- **Vet hardening** after an adversarial DeepSeek review: allowances now bind to
  `body_sha256` rather than to a name, and invisible/bidi characters are
  stripped before scanning and reported.

## Known blockers

- **Ignition**: the loop picks, attempts and gates but promotes nothing — the
  gate-discrimination receipt is measured at a different revision, and
  regeneration needs a green sandbox baseline.
- **`knowledge_links` was unwired** — fixed 2026-07-30, gated behind
  `DAEDALUS_INDEX_WIKI`.
- **`daedalus/kairos/evolution.py` is an ISLAND** — nothing imports the code
  evolution engine. Surfaced by the architecture memory hook.
- ~~**Budget accounting stops under concurrency**~~ — **RETRACTED 2026-07-30.**
  The observation was real (forty concurrent calls, zero ledger entries) and the
  diagnosis was wrong. Budget accounting monkeypatches `urllib.request.urlopen`
  process-wide and is installed at the product entry points (`cli.py`,
  `claude_bridge.py`); the fan-out scripts constructed the provider directly and
  never installed it. Measured: without the guard 76→76 entries, with it 76→78.
  Nothing to do with concurrency.
- **The ledger is blind to direct provider callers** — the real, smaller finding
  underneath the retraction. Any script, test harness or new integration that
  constructs a provider itself spends unpriced, and crossing that boundary is
  silent. Install-at-entry-point is deliberate, so this is a documentation and
  ergonomics gap rather than a defect in `budget.py` — which stays untouched,
  being on `high_risk_paths`.
