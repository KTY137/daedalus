# G1-ARIADNE-04 — The retained failed receipt is the first-call result

Packet ID: G1-ARIADNE-04

Artifact role: primary

Classification: `ALIGNED`

Active gate: Gate 1

Owner: repository owner

Base revision: b59b2628ad6ed85a8b5e729a12c58512543e2e73

Working-tree context: isolated worktree `.claude/worktrees/stage3-failed-receipt`, branch `loop/stage3-failed-receipt`, from the v0.1.6 release commit

Dependencies: `G1-ARIADNE-02_CAMPAIGN_WORKBENCH`, `G1-ARIADNE-03_WINDOWS_EVALUATOR_INTERPRETER`

Stage: 3 of the owner-directed 2026-09-05 loop; the follow-up Codex asked for in the v0.1.6 freeze decision (room turns 75 and 77).

## Primary acceptance claim

When an Ariadne arm fails on a campaign-domain verdict after candidate capture (the frozen evaluator's output violates its one-line JSON contract, a budget ceiling, an inner-terminal blocker), the first `run_campaign` call returns the canonical `failed` `CampaignReceipt` that it has already committed and settled, and the HTTP facade answers 200 with that receipt. Foreign crashes and cancellations keep raising. A replay returns the identical receipt and executes nothing.

## Reproduced negative baseline (measured 2026-09-05)

- `daedalus/ariadne/campaign.py`, post-capture arm failure path: after `_complete_failed_campaign_receipt`, `campaign_committed = True`, inner-terminal verification and outer-effect settlement, the branch ended in a bare `raise`. The HTTP facade therefore mapped the first call to a 400 string; the retained receipt only appeared on the replay (Odysseus, G1-ARIADNE-02 review, "First call loses its receipt").
- New facade test red before the change with exactly the measured Windows defect shape as the fake gate output (`warning: Making stdin inheritable failed` ahead of the JSON line): `json.decoder.JSONDecodeError` -> `AriadneCampaignError("frozen evaluator output is invalid")` raised from the first call.

## Scope

In scope: the one return in the post-capture failure path, the `_is_domain_failure` predicate, the facade and HTTP tests. Out of scope: CLI exit-code semantics (`daedalus ariadne` already prints `rejected` receipts with exit 0; `failed` follows the same rule, an outcome-based exit code is a separate decision), the terminal-evidence and budget-stop paths (unchanged), the kernel campaign lifecycle, promotion.

## Contracts and behavior

- `_is_domain_failure(failure)`: `AriadneCampaignError` and its subclasses are campaign-domain verdicts; `LoopHalted` (cancellation) and every foreign exception (`RuntimeError` from a crashing gate, `OSError`) are not.
- Post-capture arm failure: unchanged commit, inner-terminal check and outer-effect settlement; then `return failed_receipt.to_dict()` for a domain failure, `raise` otherwise. The reconciliation refusals before it are unchanged and still raise.
- HTTP `/api/ariadne`: no change; a returned `failed` receipt travels as `envelope(project, ariadne=receipt)` with status 200; refusals before the campaign (400/409) are unchanged.
- Outcome vocabulary unchanged (`nominated`, `rejected`, `failed`, `cancelled`); the faulted Attempt keeps trial status `error`.

## Acceptance matrix

| Check | Result (2026-09-05, worktree) |
| --- | --- |
| worktree baseline before any change: `test_ariadne_campaign_v0.py` + `test_http_ariadne.py` | 59 passed (96.3 s) |
| new facade test before the change | red: first call raised `frozen evaluator output is invalid` |
| new facade test + HTTP failed-receipt test + existing crash contract (`RuntimeError` still raises, replay returns the failed receipt) after the change | 3 passed |
| stage suites (`test_ariadne_campaign_v0.py`, `test_http_ariadne.py`, `test_kernel_contracts_have_producers.py`, `test_cli_effect_boundary.py`) after the change | 129 passed (104.9 s), 0 failed |

## Migration and rollback

Rollback restores the bare `raise` and deletes the predicate and the two tests. Retained receipts are unaffected: the change only alters what the first call returns, never what is persisted.

## Evidence, expected failures, and review

Codex decided in the freeze (room turn 75) that this change needs its own focused packet with discriminating HTTP and replay tests; both are here. Review is requested from Codex as a free room turn (daily budget exhausted); the branch is not merged and not promoted.

Iron Plan: **ALIGNED**

Iron Gate: **1**

Automatic merge/promotion: **forbidden**
