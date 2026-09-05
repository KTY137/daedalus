# G1-IKARUS-26 — The general computer loop, measured live, and its two honest defects

Packet ID: G1-IKARUS-26

Artifact role: primary

Classification: `ALIGNED`

Active gate: Gate 1

Owner: repository owner

Base revision: b59b2628ad6ed85a8b5e729a12c58512543e2e73

Working-tree context: isolated worktree `.claude/worktrees/stage3-failed-receipt`, branch `loop/stage3-failed-receipt`, stacked on commit dda7f41d

Dependencies: `G1-IKARUS-17_GENERAL_ASSISTANT_AMENDMENT` (Revision 12), the v0.1.6 path-I/O release lock (Codex, `RELEASE_DISABLED_TOOLS`)

Stage: 13 of the owner-directed 2026-09-05 loop; co-authored with Codex through the room (turns of 16:45, 16:55 and Codex's answer of 16:49).

## Primary acceptance claim

The general computer assistance strand of section 7.2 was run live for the first time (Ollama `qwen2.5-coder:7b` as the local planner, a scratch clone as the authority root, a fresh control root with an armed kill switch, a static page on a loopback origin as the target), and the two defects the measurement exposed are fixed and pinned: a configured policy whose every tool is release-locked is reported as such instead of as a missing policy (`unavailable` now carries every locked tool with the lock reason), and three consecutive identical advisory plans end the loop as `stalled` under every execution-limit mode, including the owner's `unbounded_execution`, where the measured loop otherwise ran until the kill switch. The measurement itself is retained as evidence, including the negative outcomes.

## Measured

Host: Windows 11, one GPU shared with other sessions' test load; Ollama at loopback with `qwen2.5-coder:7b` (7.6B, Q4_K_M), Playwright Chromium 1234 present, mss/cv2/Windows OCR present. Authority root: scratch clone of b59b2628 under the session scratchpad; control root `<SCRATCH>/self-renovation/control6` (kill switch) and `<USERPROFILE>/.daedalus/control/383cc917d869` (computer policy of that scratch path). Evidence: `docs/evidence/G1-IKARUS-26_COMPUTER_LOOP_LIVE/` (sanitized: home and scratch paths replaced, `MANIFEST.json` carries digests).

| Mission | Policy | Result |
| --- | --- | --- |
| `computer-loop-measure-02` | tools `file.list/read/write/mkdir`, unbounded | `unavailable` in 0.006 s: "needs an owner-configured computer policy" although the policy was configured (sha d8c8cd75); `tools: []`, `unavailable: {}`. Cause: every configured tool is in `RELEASE_DISABLED_TOOLS`; `_release_tool_spec` returned `None` and the tool was dropped without a reason. **Defect 1.** |
| `computer-loop-measure-03` | tools `browser.navigate/read`, origin `http://127.0.0.1:<port>`, unbounded (owner's policy) | call 0 plan, call 1 `browser.navigate` (ok, page text observed, sentinel present), calls 2 to 12 the same two-step plan eleven times; 13 planner calls, 10 replans, 1 tool step, 961 s (about 74 s per planner call, the model was evicted between calls). No cap applied (`enforces("attempts")` and `enforces("wall_time")` are both false under unbounded), no stall rule for plans existed. The kill switch (`stop` on the control root) ended the run at the next checkpoint, 55 s after the stop: `state: blocked`, `LoopHalted: kill switch engaged`. **Defect 2**; kill switch verified. |
| `computer-loop-measure-04` | same tools, bounded default (`max_steps 8`, `timeout_s 300`) | call 0 plan, call 1 `browser.navigate`; the two planner calls consumed the 300 s mission timeout and the browser start hit the cooperative deadline: step 1 `ok: false`, "browser initialization unavailable: ComputerRefused", `state: blocked` after 309.5 s, no uncertain effect repeated. A finite, typed outcome; also a cost measurement: on this host two 7B planner calls exhaust a 300 s mission. |
| `computer-loop-measure-05` | same tools, bounded (`timeout_s 900`), stall rule live | calls 0 and 1 the same plan, call 2 `browser.navigate` (ok, page text observed; the tool step reset the sequence), calls 3 to 5 the same plan three times: `state: stalled` after 6 planner calls, 4 replans, 1 tool step, 749 s, "Three consecutive identical advisory plans established no progress." The rule ended the run 151 s before the mission timeout would have. |

What the measurement did not establish: task completion. No run reached `finish`; the 7B planner never proposed `browser.read` after the navigation. That is a planner-quality result on this host, not a loop defect, and it is recorded as negative evidence. The retained 13 + 2 planner responses are in `measure-03_planner_proposals.json` and `measure-04_planner_proposals.json`.

A wrong intermediate diagnosis is retained on purpose: the 16:45 room turn read a py-spy dump (main thread in `urlopen` on `/v1/chat/completions` with `timeout=None`) as a request that was never answered. The 16:55 correction shows the run was replanning, one call in flight per dump. The code fact stands (under `unbounded_execution` the planner call carries no deadline: `computer_loop.py` passes `remaining=None`), the causal claim did not. Codex's position on the transport question (16:49): a fixed Daedalus-set transport limit would itself be a provider time cap, not an "external constraint" in the plan's sense; cancellation during a running provider call deserves its own packet. Not built here.

## Council record

Room (not a bus council): Codex answered at 16:49 after a static review, explicitly without repeating the live measurement. Verdict on both fixes: `ALIGNED`. Counter-cases it demanded and which are now tests: for defect 1, every tool locked, a mixed policy, a missing adapter dependency, and an available browser tool must remain executable; for defect 2, exact comparison of the parsed ordered `steps` list (no whitespace normalisation, which could equate different literals), a different plan or an intervening non-plan response resets the sequence, all three proposals stay retained, and the rule must hold under `unbounded_execution`. Codex also named the open limitation: paraphrased plans are not detected. Advisory only; nothing merged or promoted.

## Scope

In scope: `daedalus/runtimes/computer.py` (`ComputerService.capabilities`: locked tools are recorded in `unavailable` with `PATH_IO_RELEASE_REFUSAL` before the existing `continue`), `daedalus/orchestration/ikarus/computer_loop.py` (`_unavailable_summary`, the `/computer status` sentence, the identical-plan stall), `tests/test_ikarus_computer_loop.py`, `tests/runtimes/test_computer_service.py`, the evidence directory. Out of scope: the release lock itself (unchanged, Codex's v0.1.6 decision), any transport timeout, the planner prompt, the desktop and vision adapters, the web workbench.

## Contracts and behavior

- `capabilities()["unavailable"]` now includes every release-locked tool with the lock reason; `enabled` is unchanged (still `bool(available)`), `path_io_release_lock` is still always emitted and still proves nothing about a complete lock.
- `_unavailable_summary(capabilities)`: with a non-empty `unavailable` map the final summary is "Computer assistance is configured, but every configured tool is unavailable on this host: <tool: reason; ...>"; otherwise the previous "needs an owner-configured computer policy" text. The `/computer status` sentence distinguishes the same two cases; its "Unavailable:" list was already rendered.
- Identical-plan stall: `repeated_plans` counts consecutive plan proposals whose parsed `steps` lists compare equal; at `_STALL_OBSERVATIONS` (3) the loop ends with `state: stalled`, "Three consecutive identical advisory plans established no progress." The counter resets on a different plan, a tool or finish proposal, or an invalid response. It is evaluated after the proposal artifact is stored and the plan progress event is emitted, so every proposal stays retained and the report's `plan` carries revision 3. It is a progress criterion beside the existing identical-observation and identical-invalid-response rules, not a cap axis, so no execution-limit mode disables it (Revision 10 is untouched).

## Acceptance matrix

| Check | Result (2026-09-05, worktree) |
| --- | --- |
| six new tests without the code change | 4 failed (both stall tests, the locked-summary test, the service reporting test), 2 passed (the two reset counter-cases, which guard against an over-eager rule) |
| six new tests with the change | 6 passed |
| `tests/test_ikarus_computer_loop.py`, `tests/runtimes/test_computer_service.py`, `tests/runtimes/test_computer_service_files.py` | 56 passed, 7 xfailed (the pre-existing `NOT_WIRED` rows), 49.0 s |
| wider computer and Ikarus shell suites (16 files) | 417 passed, 1 failed, 7 xfailed, 34 subtests passed, 855.5 s; the failure is `tests/test_ikarus_shells.py::GermanActRequestTest::test_declining_queues_nothing`, which passes alone (61.4 s) and exercises the act-request decline path, untouched here: recorded as order-dependent, not attributed |
| live `computer-loop-measure-05` with the stall rule | `stalled` after 6 planner calls (see the measurement table); evidence `measure-05_*` |
| service test after the main tree's G1-IKARUS-25 phase 2 (file tools projected, `RELEASE_DISABLED_TOOLS` = vision.match/vision.changes; review session 6e, 17:20) | the test derives the locked set from `RELEASE_DISABLED_TOOLS` instead of `FILE_TOOLS`, so it holds on both trees; rerun: 1 passed |

## Migration and rollback

No stored artifact changes shape; `unavailable` gains entries, the summary strings change. Rollback restores the silent `continue`, the fixed summary and drops the stall counter and the six tests. Retained missions and receipts are unaffected.

## Evidence, expected failures, and review

Evidence directory above (19 files, `MANIFEST.json`); the two room turns and the correction are retained verbatim. Expected failures retained: mission 02 (unavailable), 03 (kill switch), 04 (timeout), 05 (stalled by design). Rebase note from review session 6e: the main tree's `capabilities()` reworded `path_io_release_lock` and added a Windows-only reason for file tools; the four lines before the `continue` keep their meaning there (the branch then only sees vision.match and vision.changes). Review questions: is three the right threshold for identical plans on a slow planner (a 7B model at 74 s per call reaches it in under four minutes)? Should the mission timeout be checked before, not only after, an adapter start when two planner calls can consume it? Neither is decided here.

Iron Plan: **ALIGNED**

Iron Gate: **1**

Automatic merge/promotion: **forbidden**
