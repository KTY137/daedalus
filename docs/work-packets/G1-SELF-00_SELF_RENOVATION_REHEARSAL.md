# G1-SELF-00 — Self-Renovation rehearsal: Ariadne nominates a repair of Daedalus itself

Packet ID: G1-SELF-00

Artifact role: primary

Classification: `EXPERIMENT`

Active gate: Gate 1

Owner: repository owner

Base revision: b59b2628ad6ed85a8b5e729a12c58512543e2e73

Working-tree context: executed from the isolated worktree branch `loop/stage3-failed-receipt` (commit 93ee7507, stages 3 and 4 included) against a local clone of the repository at the release commit

Dependencies: `G1-ARIADNE-01_CANONICAL_CAMPAIGN_REHEARSAL`, `G1-ARIADNE-03_WINDOWS_EVALUATOR_INTERPRETER`, `G1-ARIADNE-05_WORKING_TREE_BASE_BINDING`

Stage: 5 of the owner-directed 2026-09-05 loop; first measured step toward the owner's "improves itself" goal, inside the constitution.

## Primary acceptance claim

The canonical Ariadne controlled-repair campaign can take the Daedalus repository itself as its Renovation subject and nominate a candidate that corrects a measured-stale claim in Daedalus's own source, through the unchanged kernel (Mission/Attempt/EffectLease/CAS/Evidence/NominationReceipt), with equal budgets, an independent deterministic evaluator, a subject that stays untouched, and no promotion. Nomination followed by an owner decision is the ceiling; Daedalus does not merge or apply anything to itself.

## Experiment record (plan section 15)

- Spec: the frozen `ExperimentSpec`/`CampaignContract` of G1-ARIADNE-01 (three arms: no-change baseline, deliberate negative control, exact-text repair; one attempt per arm; metric `exact_match`).
- Scope: one file, `daedalus/providers/codex_cli.py`; one exact-text replacement of the docstring claim that the npm `.CMD` shim is "the ONLY form" of Codex on this box, which the 2026-09-05 measurements refuted (a native `codex.exe` ships in the VS Code extension bundle).
- Budget: `timeout_s=60` per arm; realized usage `cost_microusd 0`, `wall_time_ms 1587` for the whole campaign; no model, no vendor, no network.
- Evaluator: the frozen exact-match evaluator (`EVALUATOR_SHA256`), executed under Windows containment with the base interpreter (G1-ARIADNE-03).
- Expiry: 15 minutes after the frozen campaign timestamp (Ariadne-01 protocol).
- Isolation: subject = `git clone` of the main checkout at `b59b2628` under the session scratch directory; control root = a fresh scratch `DAEDALUS_KILLSWITCH` root; the shared tree, its control root and its spine database were not touched.
- Promotion: forbidden; the nomination is retained evidence for the owner, nothing was applied.

## Measured result (2026-09-05, 14:5x)

| Field | Value |
| --- | --- |
| campaign_id | `self-renovation-03` |
| outcome | `nominated`, selected arm `repair` (seed 2) |
| trials | baseline `failed` (`exact-match-failed`), negative-control `failed` (`exact-match-failed`), repair `passed` |
| nomination receipt | `1b2fb0bb0ea569910a3f8edeb856b24778b0d78b112c9d9b1adcb25a0ae9cc1b` |
| candidate tree | `49f7abe2b5a290775fdc12d4954f1a211953bd0395f76c8d9653be38f09e4392` |
| base tree | `2b63376bf4b0d357b7f0510e27b8530a8535685534525b6481547f754d8baa6b` |
| budget equality | configured equal, realized usage recorded, within budget |
| subject clone after the campaign | `git status --porcelain` empty |
| user-profile path in the receipt | none |

Retained under `docs/evidence/G1-SELF-00_SELF_RENOVATION_REHEARSAL/`: the sanitized receipt, the candidate diff (base vs candidate from the CAS), and `attempts.json` with the two refused attempts below.

## Retained negative evidence (the two refusals before the success)

1. `self-renovation-01`, subject = the linked git worktree: refused before any state with `repository HEAD is unavailable or unsafe: Git metadata directory must be a real directory`. `head_revision._identity` requires `.git` to be a directory; a linked worktree has a `.git` file with a `gitdir` pointer. Ariadne cannot take a linked worktree as subject today, which contradicts the direction "isolated worktrees make parallel writes safe". Momus (design critique, 14:49) rejected extending the verifier to follow the gitdir pointer: `tests/test_git_is_a_process_launcher.py:82` measured the attack in which a candidate rewrites `<worktree>/.git` to point at a gitdir it authored, and `tests/gates/test_repository_head_revision.py::test_worktree_gitfile_is_not_misrepresented_as_verified` pins the refusal on purpose; the repository's answer is capture-then-use of the pointer before candidate code runs (`daedalus/kernel/attempt_execution.py::_read_gitdir_pointer`). The exclusion is therefore **deliberate**. G1-ARIADNE-06 makes the refusal name the layout and the remedy (clone the repository or use its common checkout). A worktree-subject design, if ever needed, is a Cerberus-gated packet with pointer capture, git's back-pointer check, reparse-point refusal on every component and a head receipt schema `/2`; not an extension of `_resolve_once`.
2. `self-renovation-01` (reused id) and `self-renovation-02`, subject = the main checkout with a scratch control root: the outer lease was acquired and terminalised, then `partial persisted Campaign state is unsafe`. The spine database is repository-local (`runs/spine/spine.sqlite3`) while the source-tree CAS lives under the control root; an override control root against a repository that already has a spine finds a database without a CAS and refuses fail-closed (`kernel/campaigns.py:283-286`). Correct refusal, opaque message; G1-ARIADNE-06 makes the kernel refusal name the split.

## Scope and boundaries

In scope: executing the existing production path against a clone of Daedalus and retaining the evidence. Out of scope: any change to code in this packet, any application of the candidate, any claim that Daedalus "improves itself" beyond one nominated one-file repair under owner control. The amendment proposal 013 strand G1-SELF-01 (self-Renovation with the leakage rule) is the production packet this rehearsal informs; it still requires owner approval.

## Contracts and behavior

No contract changes. The campaign ran through `daedalus ariadne` (registered CLI door), `python.ariadne_campaign` outer lease, `python.attempt` leases per arm, source-tree CAS, evaluator observations with interpreter provenance (schema `/2`), the working-tree base binding (G1-ARIADNE-05), and the canonical `CampaignReceipt`/`NominationReceipt`.

## Acceptance matrix

| Check | Result |
| --- | --- |
| subject untouched after the campaign | `git status --porcelain` empty |
| three arms, equal configured budgets, realized usage recorded | `configured_equal` true, `within_budget` true |
| independent evaluator verdicts | baseline and negative control `exact-match-failed`, repair `passed` |
| candidate identity content-addressed and diffable from CAS | candidate diff retained |
| no promotion, no apply, no merge | none performed; the clone and the shared tree are unchanged |
| refusals retained as negative evidence | `attempts.json` |

## Migration and rollback

Nothing to roll back in the repository; the scratch clone and control root are session-temporary, the retained evidence is documentation. Deleting the evidence directory removes the rehearsal record only.

## Evidence, expected failures, and review

Codex review requested as a free room turn. Expected failure kept: the worktree-subject refusal is a limitation of the current HEAD verifier, not of the rehearsal.

Iron Plan: **EXPERIMENT** (frozen spec, bounded, isolated, independently evaluated, no promotion)

Iron Gate: **1**

Automatic merge/promotion: **forbidden**
