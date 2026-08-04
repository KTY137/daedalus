# G0-PRM-25J — Read-Only Promotion Operator Recovery Plan

## Scope

This packet converts the strict persisted Effect-Lease/promotion reconciliation
projection into one machine-readable operator plan. It is read-only: it does not
grant, begin, finish, terminalize, retry, invoke Git, mutate a worktree or call
promotion.

## Complete state table

The exact retained reconciliation disposition selects exactly one action:

| Disposition | Operator action | Owner decision required |
| --- | --- | --- |
| `fresh` | `none` | no |
| `effect-only-pending-reconciliation` | `owner-decision-before-effect-cancellation` | yes |
| `promotion-pending-reconciliation` | `forensic-promotion-reconciliation` | yes |
| `effect-terminalization-required` | `terminalize-effect-from-retained-evidence` | no |
| `complete` | `replay-retained-report` | no |

Every plan states `automatic_external_reexecution=false`. The plan binds the
promotion authorization digest and all retained effect/promotion start and
terminal receipt digests, then hashes its canonical wire form.

## Authority boundary

The plan deliberately does not define an owner decision format or perform the
effect-only cancellation. Those are separate writer-authority packets. It also
does not infer that a pending promotion may be retried; promotion-pending state
requires forensic reconciliation first.

## Prepared adversarial verification

The behavior matrix covers all five dispositions, exact digest binding,
canonical plan hashing and malformed authority types before projection. A
separate AST/source review permits one read-only reconciliation call and rejects
lease writers, terminalization, promotion, Git, subprocess and SQLite authority.
A bounded five-mutant campaign attacks automatic re-execution, owner-decision
removal, state/action substitution, receipt omission and plan-digest omission.

Exact-head compilation, focused tests, mutation execution, full suite,
packaging and the supported platform/Python matrix remain pending. Repository
GitHub Actions issue #67 has repeatedly ended jobs before Step 1 with no logs or
artifacts; those runs are infrastructure observations only.

## Non-claims

No OwnerApproval or recovery decision was created. No effect was cancelled,
terminalized, retried or promoted. No merge, registry centralization or Gate
transition occurred. Gate 0 remains open.
