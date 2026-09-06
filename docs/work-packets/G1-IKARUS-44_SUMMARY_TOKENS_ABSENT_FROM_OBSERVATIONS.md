# G1-IKARUS-44 — Digit-bearing claims of a finish summary that no retained observation contains

Packet ID: G1-IKARUS-44

Artifact role: primary

Classification: `ALIGNED`

Active gate: Gate 1

Owner: repository owner

Base revision: d4e4b83437b1d4437004692fb41c11eb701ef141

Working-tree context: base d4e4b834 is branch `loop/lane11-planner-progress` (G1-IKARUS-32..35, 42, 43); same worktree and interpreter recipe as G1-IKARUS-32

Dependencies: `G1-IKARUS-32` (the retained measure-09 report is the pre-registered falsifier), Momus design critique of 2026-09-06 04:10 (design B: proceed with changes; renamed, observations-only corpus, versioned tokenizer, chat line only on a hit, offline power test as the decision rule)

Stage: owner loop of 2026-09-06, session daedalus-6c. Reserved in the room at 09:02 with the decision rule stated before the implementation ran.

## Primary acceptance claim

After a mission ends, the report carries `summary_tokens_absent_from_observations`: the digit-bearing tokens (numbers, codes such as `TANGERINE-4471`, times, URLs; tokenizer `v1`) of the planner's `finish` summary that appear in none of the retained observations (`steps[].outcome` only), with `checked`, `absent` and, for present tokens, `grounded_in` (the steps that contain them). The chat rendering adds one sentence only when `absent` is non-empty and says in that sentence that this is a fabrication detector without confirming power. Without a `finish` the field is `None`. It is computed after the loop ended, changes no state, never enters a prompt, and `task_success_verified` stays false whatever it says.

Decision rule, fixed at reservation: the check ships only if it is silent on the retained measure-09 report and loud on a fabricated variant of the same summary; otherwise it has no power and is not built.

## Measured (offline, the pre-registered falsifier)

`docs/evidence/G1-IKARUS-32_PLANNER_PROGRESS_LIVE/computer-loop-measure-09_browser_bounded_codex-planner.json`, unmodified: `checked 2` (`15:00`, `TANGERINE-4471`), `absent []`, `grounded_in {"TANGERINE-4471": [1, 2], "15:00": [1, 2]}` (both the navigate and the read observation carry the page text). The fabricated variant (`TANGERINE-4472`, `16:30`, plus "Source: http://127.0.0.1:9/invented.html"): `absent` contains `TANGERINE-4472`, `16:30` and the invented URL. Discrimination shown; the rule admits the check. Honest limit: the entire retained record holds exactly one `finish` (measure-09, `codex_cli`); all ten G1-IKARUS-34 runs and measure-08/10 have `planner_summary: null`, so n=1 for the silent case and the loud case is synthetic.

## Scope

In scope: `daedalus/orchestration/ikarus/computer_loop.py` (`_ABSENCE_CHECK_VERSION`, `_ABSENCE_TOKEN`, `summary_tokens_absent_from_observations`, one report field, one conditional chat sentence), four tests in `tests/test_ikarus_computer_loop.py`, this packet.

Out of scope and untouched: the prompt (nothing of this reaches a planner), the stall rules, states, `task_success_verified`, the history projection (the field lives in the retained report and can be projected later), any evaluator or EvidencePacket.

## Contracts and behavior

- Tokenizer `v1`: matches of `[A-Za-z0-9][A-Za-z0-9:_./-]{3,}` with trailing `.,;:` stripped, at least four characters and at least one digit, unique in order of first appearance. The regex is the specification; a change is a new version string, so older reports stay comparable.
- Corpus: the canonical JSON of each retained `steps[].outcome` (sorted keys, case-folded), one entry per step in step order. Never the objective, plan, proposals, owner context or tool arguments (pinned: a summary repeating the objective's numbers is still `absent` when no observation carries them).
- Containment is case-insensitive substring per observation; `grounded_in` lists the steps that contain the token, so a write-then-read self-loop is visible as grounding in the read step only.
- Known false positives, stated: `4,471` vs `4471`, `15:00` vs `3pm`, URL encoding, derived counts, rounding, unit conversion. Known gaming, stated: a planner can state only observed tokens and omit the claim; the check has no view of completeness.
- Never to be quoted as: evidence of task success, an evaluator or gate, a Gate-3 measurement, or a pass/fail field of an EvidencePacket.

## Acceptance matrix

| Check | Result (2026-09-06, this worktree) |
| --- | --- |
| four new tests without the change | 4 failed (`AttributeError: summary_tokens_absent_from_observations`) |
| four new tests with the change, including the pre-registered falsifier over the retained measure-09 report | 4 passed |
| loop, adversarial, history, autonomy, schedule and schedule-autonomy suites | 191 passed (60.0 s) |
| `computer_loop.py` line endings | LF |

## Migration and rollback

Additive report field and one conditional chat sentence; older reports have no field and render unchanged. Rollback removes the function, the field and the sentence.

## Evidence, expected failures, and review

Evidence: the acceptance matrix and the retained measure-09 report it replays. Expected failure retained: none; the synthetic loud case is a fixture, not a live fabrication. Review: Momus proposed the design and its decision rule; no independent review of the implementation yet.

Iron Plan: ALIGNED
Iron Gate: 1
Evidence: the acceptance matrix above
