# G1-IKARUS-45 — The prompt shows a bounded view of the history; the report keeps it all

Packet ID: G1-IKARUS-45

Artifact role: primary

Classification: `ALIGNED`

Active gate: Gate 1

Owner: repository owner

Base revision: 4a77970f05eea30d55450249d4a40688fb60db99

Working-tree context: base 4a77970f is branch `loop/lane11-planner-progress` (G1-IKARUS-32..35, 42..44); same worktree and interpreter recipe as G1-IKARUS-32

Dependencies: `G1-IKARUS-42` (measure-11c: one ordinary page read overflows the local window, `prompt_chars`/`planner_context_tokens` in every artifact), `G1-IKARUS-26`/`29` (the stall rules the view must not undercut), Momus design critique of 2026-09-06 04:10 (design A rejected as first specified; the constraints below are his conditions for building it after a measured overflow)

Stage: owner loop of 2026-09-06, session daedalus-31. Built only after measure-11c produced the overflow Momus asked to measure first.

## Primary acceptance claim

When the planner's context window is known (the loopback Ollama route), each prompt shows a bounded VIEW of the retained observations: the view fits `planner_context_tokens × 4 − <directive, tools, plan, context> − 512` characters whenever the shape allows, observations older than the verbatim window (the identical-observation stall threshold, 3) have their allow-listed text fields cut to a 400-character prefix, and if that is not enough the window's observations share the remaining budget equally with a 2,000-character floor. Every `ok: false` observation stays verbatim whatever its age. Every cut is marked in place (`text_elided`, `text_full_sha256`, `text_full_chars`, `text_shown_chars`, `elided_by_prompt_view`) and the directive tells the planner that elided content is retained but not shown and must not be claimed as verified. The retained history, the step artifacts and the report are never mutated: the view is a pure function of the history (`_prompt_view`). Each proposal artifact carries the `compaction` block of its call; the report carries an aggregate (`applied_calls`, `unfit_calls`, `elided_chars_max`, `elided_steps`, `verbatim_window`, `budget_chars_last`). When three identical reads stall the mission and any of those reads had been elided in an earlier prompt, the summary says so and the report carries `stall_after_elision: true`, so a view-induced re-read is not filed as a planner stall. Without a known window (remote CLI planners) nothing is elided and the report says `reason: "no known window"`. The overflow counter of G1-IKARUS-42 keeps counting whatever is actually sent.

Momus's constraints, each pinned: never mutate `history` (`test_prompt_view_is_pure_bounded_and_marks_every_elision` deep-compares before and after); a byte budget derived from `num_ctx`, not `_MAX_CONTEXT_CHARS`, with a per-observation share (same test, equal shares, floor); an explicit per-tool allow-list with a version (`_ELIDABLE_TEXT_FIELDS`, `_COMPACTION_VERSION = "v1"`, in every compaction block); `ok: false` verbatim regardless of age (`test_prompt_view_keeps_failed_observations_verbatim_and_needs_no_change_when_it_fits`); `verbatim_window ≥ _STALL_OBSERVATIONS` (`ValueError` below it, same test); explicit elision markers in the payload; a distinct stop attribution (`test_a_stall_on_elided_reads_is_attributed_to_the_view`); a compaction block in the report (`test_the_loop_bounds_the_prompt_to_the_local_window_and_reports_it`); no change for planners without a known window (`test_a_remote_planner_gets_the_full_history`). His falsifier, measure-09 with the view on, is trivially unaffected: Codex has no known window and receives the full history, as the remote test pins; the five G1-IKARUS-43 runs (7.7 KB prompts) would not have been elided under the local budget either.

## Scope

In scope: `daedalus/orchestration/ikarus/computer_loop.py` (`_COMPACTION_VERSION`, `_ELIDABLE_TEXT_FIELDS`, three constants, `_no_compaction`, `_prompt_view`, one directive sentence, the per-call budget and view in the loop, the compaction block in proposal artifacts and the report, the stall attribution), six tests in `tests/test_ikarus_computer_loop.py` plus the retargeted G1-IKARUS-42 overflow test (it now bypasses the view explicitly to keep pinning the counter and its chat line), this packet, evidence `docs/evidence/G1-IKARUS-45_BOUNDED_PROMPT_VIEW/`.

Out of scope and untouched: the adapters' own caps (the browser's 20,000-character page text), `_MAX_CONTEXT_CHARS` and the token-axis stop, the stall thresholds, OCR rows and desktop observations (not in the v1 allow-list), any summarisation of content, the remote planners.

## Contracts and behavior

- `_prompt_view(history, *, budget_chars, verbatim_window=3) -> (view, compaction)`: pure; `budget_chars None` returns shallow copies and `applied False, reason "no known window"`; a history that fits returns unchanged copies and `applied False`; otherwise pass 1 (older, `ok: true` observations to `_OLD_OBSERVATION_TEXT_CHARS`), then pass 2 (window observations share `budget − others − fixed parts − 200 per entry` equally, floor `_MIN_WINDOW_TEXT_CHARS`). `fits` reports whether the result is within budget; with the floor it can be `false`, which the report counts as `unfit_calls` and the G1-IKARUS-42 overflow counter still records.
- Allow-list v1: `browser.navigate.text`, `browser.read.text`, `file.read.text`. Adding a field or tool is a new version string.
- Markers: `<field>_elided: true`, `<field>_full_sha256`, `<field>_full_chars`, `<field>_shown_chars` beside the shortened field; `elided_by_prompt_view: true` on the entry. The artifact locator of the full observation is already part of every history entry and stays in the view.
- Budget per call: `planner_window × 4 − len(prompt without observations) − 512`, floored at 0; `planner_window` is `num_ctx_value()` on the loopback route, `None` elsewhere.
- Report: `compaction {version, applied_calls, unfit_calls, elided_chars_max, elided_steps, verbatim_window, budget_chars_last[, reason]}` and `stall_after_elision`; proposal artifacts: `compaction` of that call.
- Stated honesty limit, in the report's own words: the planner was shown less than the loop retained, exactly how much less is in the compaction block, and any postcondition it claims to have verified against an elided observation is unverified. The stall attribution names the view when it applies.

## Acceptance matrix

| Check | Result (2026-09-06, this worktree) |
| --- | --- |
| six new tests without the change | 6 failed (`AttributeError: _prompt_view`) |
| six new tests with the change, plus the retargeted overflow test | 7 passed |
| loop, adversarial, history, autonomy, schedule and schedule-autonomy suites | 201 passed (227 s, box under another session's load) |
| live `computer-loop-measure-12`: measure-11c's configuration (7B, big page, `max_steps 16`, `timeout_s 900`) with the view on; pre-registered primary claim: every prompt within the budget (`prompt_overflow_calls 0`, `unfit_calls 0`) and markers on the elided observation; secondary observation only: whether the 7B reads or finishes (G1-IKARUS-34 predicts no finish; the sentinel of `big.html` lies beyond the adapter's 20,000-character cap, so no planner can report it) | RESULT_MEASURE12 |
| `computer_loop.py` line endings | LF |

## Measured

MEASURED_PLACEHOLDER

## Migration and rollback

No stored artifact changes shape for older missions; new proposal artifacts and reports carry additive blocks. Rollback removes `_prompt_view` and its call site (the prompt then shows the full history again and the G1-IKARUS-42 counter reports the overflow), the directive sentence and the two report fields.

## Evidence, expected failures, and review

Evidence: the acceptance matrix; `docs/evidence/G1-IKARUS-45_BOUNDED_PROMPT_VIEW/` (measure-12 report, proposals with per-call compaction blocks, log; paths scrubbed). Expected failure retained: measure-12 is expected not to finish (a planner-capability result, G1-IKARUS-34), and its sentinel cannot be read from the served page by design of the fixture. Review: Momus set the constraints before the build; no independent review of the implementation yet. Review questions: is 400 characters the right prefix for old observations, and should the window share prefer the newest observation instead of equal shares?

Iron Plan: ALIGNED
Iron Gate: 1
Evidence: the acceptance matrix above
