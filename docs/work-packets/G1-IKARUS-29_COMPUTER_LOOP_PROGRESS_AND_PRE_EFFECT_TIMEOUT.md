# G1-IKARUS-29 — Plan progress without text comparison, and the mission budget checked before the effect

Packet ID: G1-IKARUS-29

Artifact role: primary

Classification: `ALIGNED`

Active gate: Gate 1

Owner: repository owner

Base revision: cfe8d34b8ef1438156e6fa3e6982f5a30d91696f

Working-tree context: isolated worktree `.claude/worktrees/agent-abc6266ba7ab1753f`, branch `loop/lane1-computer-loop`, own `.venv` (Python 3.13.14, `uv pip install -e . pytest`, no `daedalus[computer]` extra)

Dependencies: `G1-IKARUS-26_COMPUTER_LOOP_LIVE` (stage 13), whose review section named both items below as undecided

Stage: lane 1 of the ten-agent 2026-09-05 fleet. Packet ID moved from 27 to 29 by the coordinator: session cbd944a5 had already announced `G1-IKARUS-27_REPLACEMENT_CRASH_RECONCILIATION.md`.

## Primary acceptance claim

The two questions G1-IKARUS-26 left open are answered in `computer_loop.py`, and both answers are
progress criteria rather than section-4.1 cap axes, so no execution-limit mode disables them.

1. A planner that paraphrases one plan instead of repeating it byte-for-byte is still making no
   progress. Consecutive plan proposals with no intervening executed tool step are **counted**, not
   compared: at `_MAX_PLANS_PER_STEP` (4) the mission ends `stalled` with a summary naming the plan
   budget. Codex's objection to whitespace normalisation and paraphrase detection stands untouched —
   the new rule never looks at plan text. The identical-plan rule of G1-IKARUS-26 stays and still
   fires first at 3. All proposals stay retained.
2. An exhausted mission wall-time budget is a mission outcome, not a tool defect. The budget is
   re-read from the clock immediately before `service.execute(...)`; when it is gone the mission ends
   `timeout` with no step artifact, no step intent and no adapter call.

## Measured

Host: Windows 11, ten lane agents running suites concurrently on one box. Interpreter: this
worktree's `.venv` (Python 3.13.14). The venv deliberately has no `daedalus[computer]` extra
(`import cv2` → `ModuleNotFoundError`), which is the cause of every baseline failure named below.

Planner route, verified by reading (not relayed), because it decides item 2's shape:
`_model_proposal` → `_require_context_route` (pins a numeric loopback `ollama_http` endpoint) →
`shell._llm` → `shell._ollama` → `providers/_openai_compat.chat_completion` against
`<host>/v1`. The loop's `remaining` is passed through as that call's `timeout_s`, so under a
`wall_time`-enforcing policy the provider call already carries the mission's remaining deadline;
under `unbounded_execution` it is `None` (the stage-13 finding, unchanged here).

Reported by the coordinator and recorded, not acted on in this lane's files: the `/v1` shim drops
`keep_alive` and `options.num_ctx`, and `warm_model_async` (`keep_alive_value()` = `30m`) gives up
after its 60 s timeout because the cold load on this host takes longer, so the planner's `/v1` calls
run with no keep-alive in effect and `/api/ps` was empty afterwards. Consequence accepted here: a
single cold planner call can exceed 60 s, therefore the pre-effect check reads the **clock** and
never a call count, and `test_a_single_planner_call_may_consume_the_whole_budget` pins that one call
alone can end a bounded mission. The transport lever belongs to lane 2
(`daedalus/providers/_openai_compat.py`); this packet changes nothing there.

Why measure-04 got past the existing post-planner check, measured by reading `computer.py`
(read-only; that file belongs to another lane): `ComputerService._deadline` is anchored in
`__init__` at `time.monotonic() + policy.timeout_s`, while the loop anchors `started_at` after
`capabilities()`, the context snapshot, the mission artifact store and the ledger claim. The loop's
budget is therefore systematically **more generous** than the adapter's by the setup gap. In
`computer-loop-measure-04` the loop's post-planner check saw less than 300 s elapsed and allowed the
effect; the adapter's own deadline had already passed, so `check_cancelled()` refused inside the
browser start and the run reported `ok: false`, `state: reconciliation_required`,
`"browser initialization unavailable: ComputerRefused"` after 309.5 s. The retained report
(`docs/evidence/G1-IKARUS-26_COMPUTER_LOOP_LIVE/measure-04_browser_bounded_timeout.json`) shows
`elapsed_s` 309.46, `planner_calls` 2, `tool_steps` 1.

This packet does not close that anchor gap, and says so rather than implying otherwise: closing it
means changing where `ComputerService` starts counting, which is outside this lane's paths. The
pre-effect check makes the **exhausted** case deterministic and effect-free; it does not fire in the
sliver where the loop's clock still has budget and the adapter's does not.

## Scope

In scope: `daedalus/orchestration/ikarus/computer_loop.py` (one new constant, one counter, two new
break conditions), `tests/test_ikarus_computer_loop.py`, this packet.

Out of scope and untouched: `daedalus/runtimes/computer.py` (read only, for the anchor finding),
`daedalus/providers/_openai_compat.py` and `shell.py` (lane 2's transport lever), the planner prompt,
the release lock, the desktop/vision adapters, the web workbench. No new evidence directory: this
packet adds no live run of its own and reuses G1-IKARUS-26's retained measurement.

## Contracts and behavior

- `_MAX_PLANS_PER_STEP = 4`. `plans_since_tool_step` increments on every accepted plan proposal and
  is reset to 0 only when a tool step is appended to `history`. At the bound the loop ends with
  `state: stalled` and the summary
  `"4 consecutive advisory plans proposed no tool step; the plan budget for one step is exhausted."`
  The check sits after the proposal artifact is stored and after the plan progress event is emitted,
  exactly where the identical-plan check sits, so every proposal stays retained and `plan` carries
  its revision. It is evaluated after the identical-plan check, which therefore still fires first
  at 3 and keeps naming the more specific cause.
- Deliberate asymmetry with the identical-plan rule, and the one design decision worth challenging:
  an invalid planner response and its correction round do **not** renew the plan budget, while they
  do reset the identical-plan sequence. The identical rule asks "is this literally the previous
  plan"; the budget asks "has anything been executed". A correction round executes nothing.
- The budget is per step, not per mission: a plan-execute-plan-execute rhythm is unaffected.
- Neither rule consults `limit_policy.enforces(...)`. They are progress criteria beside the existing
  identical-observation and identical-invalid-response rules, so `unbounded_execution` (Revision 10)
  does not disable them and Revision 10 is untouched.
- Pre-effect wall time: immediately before `tool = proposal["tool"]`, if
  `limit_policy.enforces("wall_time") and clock() - started_at >= timeout`, the loop ends
  `state: timeout` with
  `"The mission timeout elapsed before the tool step; no effect was started."` It runs after the
  `finish` branch, so a `finish` at an exhausted budget still reports its own state. Because it
  precedes `step += 1`, the step artifact, the `STEP_KIND` intent and `service.execute` are all
  skipped: nothing is left open for reconciliation.
- Unchanged: `ok`, `state` vocabulary, artifact shapes, the four pre-existing wall-time checks, the
  order of cancellation checkpoints, and the fact that `task_success_verified` is always `False`.

## Acceptance matrix

| Check | Result (2026-09-05, this worktree) |
| --- | --- |
| seven new tests against the unchanged loop (`git show cfe8d34b:` swapped in) | 4 failed, 3 passed — the three that pass are guards, not discriminators: the tool-step renewal case, the single-call boundary case (it exercises the pre-existing post-planner rule) and the `unbounded_execution` counter-case |
| whole file against the unchanged loop | 4 failed, 37 passed — the 37 include the two rewritten G1-IKARUS-26 counter-cases, which is the evidence that shortening them did not turn them into tests that only pass with this change |
| seven new tests with the change | 7 passed |
| `tests/test_ikarus_computer_loop.py` complete | 41 passed, 13.7 s |
| every suite that imports `computer_loop` (8 files) | 23 failed, 158 passed, 5 skipped, 550.3 s |
| the same 23 failures at base revision cfe8d34b | 20 (`test_ikarus_computer_schedule_autonomy.py`, `test_ikarus_computer_autonomy.py`) reproduce identically: base 20 failed / 56 passed / 1 skipped, with the change 20 failed / 56 passed / 1 skipped; the other 3 (`test_ikarus_autonomy_review.py`) reproduce identically at base: 3 failed / 11 passed both ways. Nothing is attributed to this change. |
| cause of those baseline failures | this worktree's venv has no `daedalus[computer]` extra (`cv2` missing, no Playwright), so vision/browser tools report `unavailable` and the real-browser and OCR-receipt rows cannot run. Environment, not code. |
| `tests/runtimes/test_computer_service*.py`, `tests/test_ikarus_computer_history.py`, `tests/test_ikarus_computer_context.py` (first sweep) | 3 failed, 96 passed, 1 skipped, 7 xfailed, 155.2 s; two are the same missing-`cv2` rows, the third (`test_parallel_owner_notes_have_no_lost_updates`) is a `FileLockUnavailable` under ten-agent load and passes alone |
| live run with the new rules | **not performed.** No new live measurement was made; the design is bound to G1-IKARUS-26's retained runs. Stated as a gap, not as evidence. |

## Migration and rollback

No stored artifact changes shape and no summary string that existed before is altered; two new
terminal summaries appear for two states that already existed (`stalled`, `timeout`). Retained
missions, receipts and replay results are unaffected. Rollback drops the constant, the counter, the
two break conditions and the seven tests, and restores the two G1-IKARUS-26 counter-cases to their
longer sequences.

Behavioural change a reviewer should notice: a mission that previously ran five or more plans without
executing anything now ends at the fourth. That is the intended new behaviour, and it is why the two
G1-IKARUS-26 counter-cases were re-expressed. Their original sequences (five and four plans without a
tool step) now stall; their claims — an over-eager rule must not fire on 2+1+2, and an invalid
response must reset the identical-plan sequence — are preserved inside the budget and still
discriminate, as the base-revision run above shows.

## Evidence, expected failures, and review

Evidence is the base-versus-change test runs in the matrix above, reproducible with
`git show cfe8d34b:daedalus/orchestration/ikarus/computer_loop.py`. Expected failures retained:
the four new tests fail at base by design; the 23 environment failures are named, reproduced at base,
and not fixed here.

Review questions, none decided here:

1. Is 4 the right budget? It was the owner's suggestion and it is tight: with the identical rule at
   3, the two rules now sit one apart, and the identical rule's remaining discriminating power is
   only that it stops one call earlier and names a better reason. A reviewer could argue the
   identical rule is now nearly subsumed and should be dropped, or that the budget should be 6 so the
   two rules stay clearly separate. It was kept because G1-IKARUS-26 required it and because its
   summary is the more useful diagnosis.
2. Should a correction round renew the plan budget? This packet says no. The opposite choice would
   let an alternating plan/invalid-response planner run forever under `unbounded_execution`.
3. The `ComputerService._deadline` anchor gap is open and belongs to whoever owns
   `daedalus/runtimes/computer.py`. Until it closes, a mission can still surface an expired adapter
   deadline as a tool failure rather than as a mission timeout.
4. No live 7B run exercised the new rules. G1-IKARUS-26 measured its stall rule live; this packet did
   not, because the fleet was saturating the host and the planner route currently has no effective
   keep-alive.

Iron Plan: **ALIGNED**

Iron Gate: **1**

Automatic merge/promotion: **forbidden**
