# Contributing to Daedalus

Daedalus is governed by `docs/IKARUS_ARIADNE_MASTER_PLAN.md`. Read that plan and
`docs/PROJECT_EXECUTION.md` before changing code, contracts, workflows, runtime
adapters, or project structure.

## Before starting

1. Find or create one GitHub Issue representing the primary Work Packet.
2. Record the active gate, objective, non-goals, dependencies, acceptance
   criteria, required evidence, and rollback.
3. Verify the exact base revision.
4. Use a short-lived branch named for the gate and deliverable.
5. Do not begin authoritative work from a later gate while an earlier gate is
   open. Isolated and read-only experiments must say so explicitly.

## Change scope

A normal pull request should implement one deliverable and one migration edge.
Do not combine contract changes, runtime effects, UI work, evolution research,
and repository-wide mechanical moves unless the Work Packet explicitly requires
that atomic change.

One writer owns a file scope at a time. Parallel agents or humans use separate
worktrees or candidate repositories and non-overlapping write scopes.

## Required pull-request information

Every pull request must include:

- primary Work Packet issue;
- Iron Plan classification: `ALIGNED`, `EXPERIMENT`, or `AMENDMENT`;
- active delivery gate;
- exact base and target branches;
- objective and non-goals;
- changed authority, effects, write roots, egress, secrets, evaluators, or
  promotion behavior;
- tests and raw evidence;
- known blockers and residual risks;
- rollback path;
- explicit statement that promotion is or is not requested.

## Trust-sensitive changes

Changes to contracts, canonical serialization, artifact identity, receipts,
effect boundaries, runtimes, sandboxing, evaluators, or promotion require
independent review. The implementation author may not provide the only approval.

Models may propose and critique. They may not grant themselves capabilities,
validate their own evidence, alter sealed evaluators, or promote candidates.

## Tests

Run the smallest causal test first, then all affected gate suites. Typical checks
include:

```bash
python tools/iron_plan_guard.py verify
python -m pytest -q
python -m build
```

Trust- and Twin-related changes additionally require the relevant deterministic,
negative, replay, wheel-install, path, sandbox, runtime, or fault suites. Record
what was not run and why. Never convert an unavailable test into a passing claim.

## Branches and merges

Direct pushes to `main` and `experimental` are not part of the intended workflow.
Use pull requests and keep the stack order explicit. Do not delete a branch that
is still a PR base or the only retained source of review evidence.

A green check is not gate closure. Closure requires the current exact-head gate
report, all required reviews, no disallowed blockers, and the explicit owner
decision required by the Iron Plan.

## Plan amendments

A change to a constitutional invariant, gate order, public concept, authority
model, or promotion rule is an `AMENDMENT`. Update the plan, append-only amendment
ledger, derived controls, and tests atomically through the documented protocol.
