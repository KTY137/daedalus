# G0-GOV-21 — Revision-3 Execution Projection Refresh

Gate: 0 — Canonical Kernel  
Classification: documentation and governance projection  
Base: `g0/repository-write-stdlib-delta-linear` at `f78e4c53fb5ac21d90a34a2fe6cd8f6da679ab14`  
Branch: `g0/execution-projection-rev3-linear`  
Promotion: not requested

## Primary acceptance claim

The derived Fourfold execution plan must describe the adopted Master Plan revision
3 and the current frozen execution boundary without broadening authority,
claiming executable verification, or authorizing dependent production work from
an unverified parent.

## Scope

This packet changes only the derived execution projection and its Work-Packet
records. It:

- updates the canonical-authority reference from Master Plan revision 2 to
  revision 3;
- replaces the old direct `experimental` branch-chain wording with exact-parent,
  short-lived Work-Packet guidance;
- distinguishes sequential dependencies from genuinely independent preparation;
- records PR #166 -> PR #167 as an inventory-only repository-write discovery
  line whose findings are neither guarded nor trusted;
- records GitHub Actions issue #67 as an external exact-head execution blocker;
- preserves the PR #1/WP-00 evidence as historical evidence rather than current
  Gate-0 closure proof.

No production Python, effect registry, scanner, runtime, sandbox, promotion,
GateReport, OwnerApproval, or release artifact changes are in scope.

## Adversarial review questions

1. Does any wording permit a dependent production build from a red or unreviewed
   parent?
2. Does any wording convert a zero-step Actions failure into product or Gate
   evidence?
3. Does the projection accidentally classify inventory findings as guarded,
   central, trusted, or Primary-Checkout-safe?
4. Does the revision-3 Gate-1 rehearsal exception get represented as Gate-0
   closure or production promotion authority?
5. Does the packet create a second semantic authority beside the adopted Master
   Plan?
6. Does any file imply OwnerApproval, merge, promotion, or gate transition?

## Verification matrix

Exact-head executable verification remains required:

```text
python tools/iron_plan_guard.py verify
python -m json.tool docs/work-packets/G0-GOV-21_EXECUTION_PROJECTION_REV3.json
python -m pytest -q tests/test_iron_plan_guard.py
python -m pytest -q
python -m build
```

The supported Python/platform CI matrix and isolated-wheel checks remain required
where the repository workflows define them. A model review is not hard evidence.

## External blocker

GitHub Actions issue #67 currently causes hosted jobs to terminate before Step 1
with `steps=null`, no logs, and no artifacts. The API cannot identify whether the
root cause is billing/quota, Actions policy, hosted-runner allocation, or payment
state. A repository/account administrator must inspect the Actions UI and account
settings. Recovery requires a trivial checkout job and Iron Plan to record real
executed steps.

Until then, this packet remains exact-head unverified. The blocker freezes only
executable verification and dependent production claims; independent static
review, documentation, tests, fixtures, schemas, and conservative inventories may
continue.

## Honest status

- Gate 0: open.
- Gate 1: not complete; only a bounded non-promoting rehearsal is authorized by
  revision 3 after its prerequisites are green.
- Gate 2: not complete.
- OwnerApproval: not issued.
- Merge/promotion: not requested.
- Exact-head verification: pending.
- Independent human review: pending.
