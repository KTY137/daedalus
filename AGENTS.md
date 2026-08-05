# Daedalus agent constitution

This file governs every agent working in this repository. Read
`docs/IKARUS_ARIADNE_MASTER_PLAN.md` before architecture, product,
orchestration, memory, graph, generation, evolution, evaluator, storage, or
runtime work.

## Mandatory workflow

1. Run `python tools/iron_plan_guard.py verify`.
2. Classify the request as `ALIGNED`, `EXPERIMENT`, or `AMENDMENT`.
3. State which delivery gate and constitutional invariant or research prior the
   work touches.
4. Implement through the canonical kernel. Prefer wiring, consolidation, and
   deletion over a new subsystem.
5. Preserve unrelated user changes and retain negative experimental evidence.
6. Verify the effect in proportion to risk.
7. End the handoff with:

   `Iron Plan: ALIGNED | EXPERIMENT | AMENDMENT`  
   `Iron Gate: 0..5`  
   `Evidence: <tests, receipts, or analysis>`

## Symbol work goes through Serena

When Serena is reachable, resolve symbols with it rather than by text search:
`get_symbols_overview` before reading an unfamiliar source file,
`find_symbol` instead of grepping for a declaration, `find_referencing_symbols`
instead of guessing at call sites. Reach for `Grep` when you want text and for a
whole-file `Read` when you have already seen the file's shape.

This is a cost and recall rule, not a safety rule. `.claude/hooks/serena-first.py`
enforces it at the Grep/Read boundary and deliberately enforces nothing when
Serena is down; that hook is not a boundary in the §1 sense. When Serena is
unavailable, text search is the correct tool and no rule is being bent.

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
- Never silently edit the plan, its lock, these instructions, or guardrails.

## Scientific freedom

The four-plane Project Twin and latent cross-plane discovery are the strongest
current research priors, not revealed truth. Read-only critique is always
allowed. A conflicting implementation is allowed only as a frozen, bounded,
isolated `EXPERIMENT` with independent evaluation and no production promotion.
If a kill criterion fires, stop the track and propose an evidence-backed
amendment.

## Protected changes

Only an explicitly owner-approved `AMENDMENT` may change protected policy
artifacts. Follow section 15 of `docs/IKARUS_ARIADNE_MASTER_PLAN.md`; do not
disable, weaken, or route around a guard. If a tool cannot comply, stop and
report the exact gap.

## Review rules

Treat these as release-blocking defects:

- a new effectful entrypoint that bypasses policy;
- another event store, artifact identity, graph authority, or promotion path;
- candidate access to its evaluator or policy;
- unverifiable claims, hidden budget asymmetry, or missing negative evidence;
- partial revisions presented as an atomic Project Twin;
- a hook or instruction advertised as a complete security guarantee.
