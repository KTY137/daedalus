---
name: enforce-iron-plan
description: Keep Daedalus architecture, implementation, reviews, experiments, and research claims aligned with the canonical Iron Plan. Use for any change involving the kernel, Ikarus, Ariadne, orchestration, knowledge or memory, Project Twin graphs, embeddings, code generation/evolution, evaluators, storage, policy, promotion, roadmaps, or architectural review.
---

# Enforce Iron Plan

Use `docs/IKARUS_ARIADNE_MASTER_PLAN.md` as the only canonical semantic
source. Treat earlier task lists and architecture documents as historical design
input.

## Workflow

1. Run `python tools/iron_plan_guard.py verify`.
2. Read `docs/IKARUS_ARIADNE_MASTER_PLAN.md`.
3. Classify the work:
   - `ALIGNED`: implements or consolidates the current gate without violating a
     hard invariant.
   - `EXPERIMENT`: challenges a research prior in an isolated, frozen,
     budgeted, independently evaluated trial with no production promotion.
   - `AMENDMENT`: changes an invariant, governing architecture, active gate,
     protected artifact, or the Iron Plan itself.
4. Name the active gate and each invariant or prior affected before editing.
5. For `ALIGNED`, wire through the canonical contracts and reuse an existing
   component where possible.
6. For `EXPERIMENT`, record hypothesis, task set, baselines, budget, seed policy,
   writable scope, evaluator, expiry, and kill rule. Preserve negative results.
7. For `AMENDMENT`, stop ordinary implementation and follow section 15 of the
   plan. Require explicit repository-owner approval.
8. Run focused verification and `python tools/iron_plan_guard.py verify`.
9. Finish with:

   `Iron Plan: ALIGNED | EXPERIMENT | AMENDMENT`  
   `Iron Gate: 0..5`  
   `Evidence: <tests, receipts, or analysis>`

## Decision rules

- Never treat prompts, embeddings, graph scores, or model judgments as the
  evidence boundary.
- Never add a top-level concept beyond Daedalus, Ikarus, and Ariadne.
- Never make AST a fifth plane. The planes are Code/AST, Type, Data, Knowledge;
  provenance, observation, evidence, and time are orthogonal lineage.
- Never identify a candidate only by a graph delta; retain its content-addressed
  source tree.
- Never use chat as workflow state or combine product personalization with
  research adaptive memory.
- Never let a candidate edit policy, evaluators, evidence, budgets, or promotion.
- Never auto-promote. Nomination and sealed owner-controlled promotion are
  separate.
- Never claim superiority without frozen, budget-equal, reproducible comparison.

## Research discipline

Allow read-only refutation. Allow conflicting prototypes only as `EXPERIMENT`.
Apply the plan's kill criteria without protecting the four-plane hypothesis from
bad results. Iron means no silent drift, not no learning.
