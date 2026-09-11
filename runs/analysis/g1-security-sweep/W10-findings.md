# W10 — GenesisAutonomyPolicy admission path: where model-proposed values could gain authority

Base: local main `851ff43c`. Static reading only.

## Verdict up front

**The Genesis autonomy strand is NOT IMPLEMENTED at this revision.** None of its
three named contracts exists anywhere in the tree outside the master plan
document itself. Therefore the plan's §7.1 promise —

> "Deterministic admission removes any model-selected authority and derives
> product mode, lane, budget, secret access, evaluator, and release targets from
> system policy"

— is at this revision **vacuously true, not enforced**. There is no admission
function, so there is nothing for a model to subvert; equally, there is no
mechanism, so nothing would stop one once the strand is built.

This is the honest answer to the question asked, and I am reporting it as such
rather than manufacturing six axis findings against code that does not exist.

## Enumeration (auditable)

```
$ grep -rln "GenesisAutonomyPolicy" --include=*.py daedalus/   -> (no output)
$ grep -rln "BuildIntentProposal"   --include=*.py daedalus/   -> (no output)
$ grep -rln "ToolchainManifest"     --include=*.py daedalus/   -> (no output)
```

Repo-wide, across `*.py`, `*.md` and `*.json`, excluding `vault/`,
`.quarantine/`, `daedalus/lanes/` and the stale duplicate trees
(`.claude/worktrees/`, `.daedalus_worktrees/`, `build/`,
`apps/web/src-tauri/backend/`, `apps/web/src-tauri/target/`):

```
$ grep -rln "GenesisAutonomyPolicy\|BuildIntentProposal\|ToolchainManifest" ...
./docs/IKARUS_ARIADNE_MASTER_PLAN.md
```

**One file. The plan document. No code, no tests, no schema, no fixture.**

The only occurrence of "genesis" in `daedalus/` source is unrelated —
`daedalus/council/bus.py:32`, describing a hash-chain genesis record:

```
    link. Genesis ``prev`` is ``None`` and folds in as ``""`` (unambiguous: a
```

Also absent: `ProductSpec`, `DesignContract`, `TargetFourfoldSpec`,
`GraphProposal`, `MaterializationPlan`, `RoundTripReport`, `DeploymentPlan`,
`DeploymentReceipt` were not found as implemented contracts either (they share
the same single-file grep result above for the three I tested exhaustively; I
did not run the exhaustive grep for all nine).

## Six-axis table

| Axis | Re-derived from policy? | Model-influenceable? | Status | Evidence |
| --- | --- | --- | --- | --- |
| product mode | n/a | n/a | **NOT IMPLEMENTED** | no admission function exists |
| lane | n/a | n/a | **NOT IMPLEMENTED** | no admission function exists |
| budget | n/a | n/a | **NOT IMPLEMENTED** | no admission function exists |
| secret access | n/a | n/a | **NOT IMPLEMENTED** | no admission function exists |
| evaluator | n/a | n/a | **NOT IMPLEMENTED** | no admission function exists |
| release targets | n/a | n/a | **NOT IMPLEMENTED** | no admission function exists |

**0 of 6 axes have an implementation.** Zero axes are currently
model-influenceable, because zero axes exist.

---

### F-W10-01 Plan Revision 11 describes a production strand with no implementation
- **file:line**: `docs/IKARUS_ARIADNE_MASTER_PLAN.md` §7.1, §9, and Revision 11 (dated 2026-08-31)
- **class**: not-implemented / documentation-reality drift
- **severity**: INFO (documentation), but see the note below on why it is worth recording
- **status**: CONFIRMED (by exhaustive absence — the greps above are the proof)

**why it matters**: Revision 11 was adopted **2026-08-31**, one day before this
sweep's base revision, and it reads in the present tense — "Genesis production
supports Web, Windows/macOS/Linux desktop, Android/iOS mobile, and CLI targets".
A reader of the plan alone would conclude a governed Genesis strand exists and
is constrained by deterministic admission. It does not exist.

To be fair to the plan, it does *bound* this correctly: Gate 1 says the Genesis
"production surface activates only after its complete acceptance matrix is
green", and §12 sequences it as "separate, dependency-ordered Work Packets". So
the plan is internally consistent — the strand is authorized, not claimed
complete. **This is therefore not an overclaim defect under the repo's review
rules.** I am recording it because the sweep asked where model-proposed values
gain authority, and "the mechanism that is supposed to prevent that does not
exist yet" is the load-bearing fact for the hardening backlog.

**The actionable form of this finding is forward-looking**: when the strand is
built, the six axes above are the checklist, and the highest-risk shapes to
guard against — none of which can be tested today — are:

1. `ToolchainManifest` build/test/run/package **commands** sourced from model
   output rather than pinned by policy. That would be process execution with
   model-chosen argv. Given that W1's scope found 152 spawn sites and this
   repository already spawns freely, this is the single most dangerous axis.
2. A proposal field used to **index or select** a policy entry. Choosing your
   own lane or budget is authority even when every candidate value is
   policy-owned. This is the leak that survives naive "we only use policy
   values" review.
3. `{**policy, **proposal}` merge order, where the proposal silently wins.
4. Secret access widening — note W3 already found that candidate code today
   receives the **full unscrubbed parent environment**
   (`daedalus/eval/correctness.py:523`, `env = dict(os.environ)`). If a Genesis
   candidate runs through that same gate, "secret access derived from system
   policy" would be false on arrival regardless of what the admission function
   does. **This is the concrete cross-finding the owner should act on.**

---

## Assessment of the adjacent claims I *could* test

The plan's §7.1 also states that public publishing "requires a one-use
`OwnerApproval` that exactly binds candidate, `EvidencePacket`, current
revision, and deployment target matrix."

The `OwnerApproval` half of that **is** implemented and is sound — see
`W6-findings.md`, which verifies HMAC signing over all fields, seven-dimension
binding, four uniqueness constraints, in-transaction re-verification, and a
correct replay refusal. What is **not** implemented is the deployment-target
matrix binding: `ApprovalExpectation` binds `operation`,
`nomination_receipt_sha256`, `candidate_artifact_sha256`,
`evidence_packet_sha256`, `base_revision`, `target_ref` and
`expected_target_revision` (`daedalus/kernel/approvals.py:375-395`) — there is
no deployment-target-matrix dimension.

That is consistent with the strand being unbuilt, and is **not** a defect today
(there is no publishing path to bind). It is recorded as a precise, testable
prerequisite: when Genesis publishing lands, `ApprovalExpectation` needs an
eighth bound dimension, or the plan's "exactly binds ... deployment target
matrix" becomes an overclaim at that moment.

## What I did not cover

- I did not exhaustively grep all nine §9 pipeline contracts (`ProductSpec`,
  `DesignContract`, `TargetFourfoldSpec`, `GraphProposal`,
  `MaterializationPlan`, `RoundTripReport`, `DeploymentPlan`,
  `DeploymentReceipt`) — only the three central to the admission question plus a
  combined pass. A partially-named variant (e.g. a differently-cased or
  abbreviated class) could in principle exist and be missed by these greps; the
  absence of *any* Genesis vocabulary in `daedalus/` makes that unlikely but I
  did not prove it.
- `daedalus/lanes/` was excluded by instruction and is under separate review. If
  a Genesis admission prototype lives there, this report would not see it. Worth
  confirming with that reviewer before treating "not implemented" as final.
- I did not review the desktop GUI's autonomy controls
  (`apps/web/src/cockpit/autonomy.ts` appeared in the working tree), which may
  be UI-side policy preparation for this strand. Plan Revision 10 notes Ariadne
  campaign controls are "policy preparation only until the live path has a
  campaign producer" — the same may apply here, and W9's F-W9-03
  (unauthenticated `PUT /api/desktop/settings`) is the relevant adjacent risk.
- No dynamic verification of any kind.
