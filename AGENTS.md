# Daedalus agent constitution

This file governs every agent working in this repository. Read
`docs/IKARUS_ARIADNE_MASTER_PLAN.md` before architecture, product,
orchestration, memory, graph, generation, evolution, evaluator, storage, or
runtime work.

## Working agreement

1. Read `docs/IKARUS_ARIADNE_MASTER_PLAN.md` before architecture, product,
   orchestration, memory, graph, generation, evolution, evaluator, storage, or
   runtime work. It is the design authority as a document; nothing enforces it
   mechanically anymore (owner decision 2026-08-22).
2. Say in one line whether a change is aligned with the plan, an isolated
   experiment, or a change to the plan itself. Changes to the plan are owner
   commits that append a record to the amendment chain by hand.
3. Implement through the canonical kernel. Prefer wiring, consolidation, and
   deletion over a new subsystem.
4. Preserve unrelated user changes and retain negative experimental evidence.
5. Verify the effect in proportion to risk and say what you measured.

## Non-negotiable boundaries

- Daedalus is the kernel, Ikarus the assistant/orchestrator, Ariadne the
  controlled evolution workload. Do not mint another top-level mythology.
- Sources and content-addressed candidate trees are authoritative artifacts.
  Forest/graph deltas are representations, not candidate identity.
- Models and embeddings propose. Independent evidence verifies. Candidates do
  not modify policy, evaluator, ledger, evidence, or promotion.
- No automatic merge or promotion.
- Chat is an interface, not orchestration state.
- Product memory and research adaptive memory stay separated.
- Claims require reproducible, budget-equal baselines and retained failures.
- Never silently edit the plan or these instructions; say what you changed.

## Scientific freedom

The four-plane Project Twin and latent cross-plane discovery are the strongest
current research priors, not revealed truth. Read-only critique is always
allowed. A conflicting implementation is allowed only as a frozen, bounded,
isolated `EXPERIMENT` with independent evaluation and no production promotion.
If a kill criterion fires, stop the track and propose an evidence-backed
amendment.

## Plan changes

The plan and this file change by owner decision, recorded as an
appended record in `docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl`.
No tool enforces this; honesty does.

## Review rules

Treat these as release-blocking defects:

- a new effectful entrypoint that bypasses policy;
- another event store, artifact identity, graph authority, or promotion path;
- candidate access to its evaluator or policy;
- unverifiable claims, hidden budget asymmetry, or missing negative evidence;
- partial revisions presented as an atomic Project Twin;
- a hook or instruction advertised as a complete security guarantee;
- a guard that blocks reading or measuring (the retired one did).
