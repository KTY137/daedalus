# G1-IKARUS-32 — The planner prompt names the next open advisory step

Packet ID: G1-IKARUS-32

Artifact role: primary

Classification: `ALIGNED`

Active gate: Gate 1

Owner: repository owner

Base revision: 04fde78bdfb2186d664896295d834fa56f0676c9

Working-tree context: base 04fde78b is branch `loop/stage3-failed-receipt` (stages 3-15b plus the ten integrated lanes); isolated worktree `.claude/worktrees/lane11-planner-progress`, branch `loop/lane11-planner-progress`; interpreter: the stage-3 worktree's `.venv` (Python 3.13, `daedalus[computer]` extra present) with `PYTHONPATH` pointing at this worktree, verified by `daedalus.__file__`

Dependencies: `G1-IKARUS-26` (live measurement, the negative finding this packet acts on), `G1-IKARUS-29` (plan budget), `G1-IKARUS-31` (native planner route, cancel probe)

Stage: owner loop of 2026-09-06 ("arbeite weiter an Ikarus das der noch besser wird und autonomer"), session daedalus-9d; lane claimed in `.room/room.md` at 02:10.

## Primary acceptance claim

The computer-loop prompt carries a deterministic `plan_progress` payload whenever an advisory plan is in force: the number of executed tool steps since the plan was adopted, the first plan step without an executed tool step (`next_step`, 1-based `next_step_index`), the remaining `open_steps`, and `every_step_has_a_tool_step`. The directive tells the planner to propose the one tool call that performs `next_step`, or to finish when the retained observations already establish the objective, and that re-proposing an unchanged plan is not progress. Nothing is inferred from the step wording; the payload grants no tool; every existing progress rule (identical plans, plan budget, identical observations) is unchanged and still ends a planner that ignores the hint.

Falsifiable hypothesis behind it, from measure-06 (G1-IKARUS-31): the 7B planner stopped after one successful `browser.navigate` and re-proposed one plan three times because the prompt never told it which plan step was still open. The live re-measurement below tests exactly that with the same objective, page, tools and bounded policy.

## Scope

In scope: `daedalus/orchestration/ikarus/computer_loop.py` (`_plan_progress`, `_prompt(..., progress=)`, one counter `tool_steps_since_plan`, three directive sentences), four tests in `tests/test_ikarus_computer_loop.py`, this packet, the evidence directory `docs/evidence/G1-IKARUS-32_PLANNER_PROGRESS_LIVE/`.

Out of scope and untouched: `shell.py` and every provider transport, `daedalus/runtimes/computer.py`, the policy module, the release fence, the plan budget and stall constants, the artifact shapes, the registry (no door changes).

## Contracts and behavior

- `_plan_progress(plan, tool_steps_since_plan)` returns `None` without a plan; otherwise `{"tool_steps_since_plan", "next_step_index", "next_step", "open_steps", "every_step_has_a_tool_step"}`. The index never exceeds the plan: once the count reaches the number of steps, `next_step` and `next_step_index` are `None`, `open_steps` is empty and the flag is `True`.
- `tool_steps_since_plan` starts at 0, is reset to 0 whenever a plan proposal is accepted (a revision restarts the count), and increments once per executed tool step appended to `history`. Correction rounds, invalid responses and refused proposals do not move it: only an executed tool step is progress, as in G1-IKARUS-29.
- The prompt payload gains one key, `plan_progress` (`null` without a plan); `advisory_plan` stays as it was. The directive gains: "If advisory_plan is present, plan_progress names the first advisory step without an executed tool step (next_step); propose the one tool call that performs it, or finish when the retained observations already establish the objective. Re-proposing an unchanged plan is not progress and ends the task as stalled."
- The progress payload is data for the planner, in the same trust position as `advisory_plan`: it grants no tool, and a proposal that names an unlisted tool or a tool the host refuses still fails at the same validation and admission points.
- Unchanged: `ok`, the `state` vocabulary, artifact shapes, the report keys, `task_success_verified` always `False`.

## Acceptance matrix

| Check | Result (2026-09-06, this worktree) |
| --- | --- |
| baseline before the change: `test_ikarus_computer_loop.py` + adversarial | 49 passed (9.7 s) |
| four new tests without the change | 4 failed (`AttributeError: _plan_progress`, missing `plan_progress` key) |
| four new tests with the change | 4 passed |
| loop, adversarial, autonomy, schedule and schedule-autonomy suites with the change | 147 passed (47.4 s) |
| live `computer-loop-measure-08`: qwen2.5-coder:7b, native route, bounded (`max_steps 8`, `timeout_s 900`), same objective and page as measure-06 | `step_limit`, 3 tool steps (navigate, read, read), 8 planner calls, 228.6 s; the 7B reads for the first time, still never finishes |
| live `computer-loop-measure-09`: `codex_cli` as planner via `allow_remote_context`, same objective | `completed`, 2 tool steps, 4 planner calls, 59.7 s, summary matches the page; first mission to reach `finish` |

## Measured

Host: Windows 11, the same box as G1-IKARUS-26/31 (2 GB MX330, the 7B planner runs on CPU), two other Claude sessions and a Vite dev server running concurrently. Ollama at loopback with `qwen2.5-coder:7b` (7.6B, Q4_K_M); Codex CLI 0.153.4 through `DAEDALUS_CODEX_CLI` pointing at the native `codex.exe` bundled with the VS Code extension (the npm `codex.cmd` relay is refused by `_refuse_cmd_shim`), `~/.codex/config.toml` model `gpt-6-astra`, `DAEDALUS_SUBSCRIPTION_VENDORS=openai_cli` as the owner declared it in the repository `.env` (flat rate, no ledger booking). Authority root: a shared scratch clone of this branch under the session scratchpad; control root `<SCRATCH>/control` (kill switch armed before each run); page `fixture_notes.html` served by `http.server` on a loopback port. Execution-limit policy: the bounded default (no `.env` loaded in the measurement process). Evidence in `docs/evidence/G1-IKARUS-32_PLANNER_PROGRESS_LIVE/` (home and scratch paths replaced by `<USERPROFILE>` and `<SCRATCH>`; every planner proposal retained verbatim; the report JSON carries the proposal artifact digests).

| Mission | Configuration | Result |
| --- | --- | --- |
| `computer-loop-measure-06` (G1-IKARUS-31, 2026-09-05, baseline for this packet) | qwen2.5-coder:7b, native route, `max_steps 8`, `timeout_s 900`, tools `browser.navigate/read` | navigate (ok), then one plan "Read the page and extract ..." three times: `stalled` after 4 planner calls, 1 tool step, 102.1 s. The 7B never proposed `browser.read`. |
| `computer-loop-measure-08` (this packet) | identical to measure-06 plus the `plan_progress` payload and directive | navigate (ok, page text observed); plan "Read the current page content."; **`browser.read` (ok)**; plan, plan, `browser.read` (ok); plan, plan: `step_limit` after 8 planner calls, 3 tool steps, 4 replans, 228.6 s (28.6 s per call). The hypothesis holds for the read: with the open step named, the 7B proposes the tool that performs it (calls 3 and 6), which it never did in six earlier runs. It does not hold for finishing: with `every_step_has_a_tool_step: true` and the objective's content in two observations, the 7B re-proposed the same one-step plan instead of `finish`. No stall rule fired (a plan-read-plan rhythm renews the plan budget by design, G1-IKARUS-29; the identical-plan sequence was interrupted by tool steps; two identical read observations are below the three-observation stall). Negative evidence retained: `task_success_verified` stays `False`, `planner_summary` is `None`. |
| `computer-loop-measure-09` (this packet) | `planner_provider: codex_cli`, `allow_remote_context: true`, otherwise identical policy; the freeform `_codex` chat transport (no `--output-schema`) | plan (two steps: open, then read and report); `browser.navigate` (ok); `browser.read` (ok); **`finish`** with the summary naming the title "Daedalus stage 13 notes", the three Today items and the sentinel `TANGERINE-4471`, which match the served page byte for byte: `state: completed`, `ok: true`, 4 planner calls, 2 tool steps, 0 replans, 0 repair calls, 59.7 s. The first computer-loop mission on this host to reach `finish`. Every proposal was one bare JSON object without prose or fences, so the schema-less Codex transport parsed on the first try; nothing in the shell changed. `task_success_verified` stays `False` as designed: the summary is the planner's claim, checked here by a human against the fixture, not by the loop. |

What the measurement establishes: the prompt change moves a 7B planner from "never reads" to "reads, then cannot conclude", and a stronger planner completes the same mission through the same policy, lease and evidence path in one minute. What it does not establish: task success as kernel evidence (invariant 4), Codex as a default (the loop stays local-only unless the owner sets `allow_remote_context`, and the page content did leave the machine for measure-09, as the flag says), or any comparison claim (one run each, no seeds, shared box under load).

Retained scratch facts: the `_codex` transport strips nothing and runs `codex exec --sandbox read-only` in a neutral cwd with the prompt on stdin; the planner's `timeout_s` was the mission's remaining wall time. The measurement script is retained as `measure_script_planner_progress.py`, an effectful script kept outside the effect-registry scanner's reach like the G1-IKARUS-26 scripts; it runs only against the scratch subject and control root named by its environment.

## Migration and rollback

No stored artifact changes shape; the prompt digest recorded per proposal (`prompt_sha256`) changes for every mission with a plan, which is the intended provenance of the new directive. Rollback removes the helper, the keyword, the counter and the three sentences; retained missions are unaffected.

## Evidence, expected failures, and review

Evidence: `docs/evidence/G1-IKARUS-32_PLANNER_PROGRESS_LIVE/` (two mission reports, both proposal lists verbatim, both logs, the fixture page and the measurement script; pinned `-text` in `.gitattributes`), the four tests named above, and this packet. Expected failures retained: measure-08 ends `step_limit` without `finish` (the 7B reads but cannot conclude), and both runs keep `task_success_verified: false`. Review status: no independent review yet; council or Codex review requested in the room after the commit. Nothing merged, nothing promoted, nothing committed to `main`.

Review questions:

- Is a 1-based `next_step_index` the right shape for small models, or should the payload repeat the plan with a per-step `executed` flag?
- The count assumes one tool step per plan step. A plan step that needs two tool calls advances the pointer early; the planner can still revise the plan, and the plan budget still bounds a planner that never executes. Is that asymmetry acceptable, or should the loop let the planner mark a step done explicitly (a new proposal type, which this packet deliberately did not add)?

Iron Plan: ALIGNED
Iron Gate: 1
Evidence: the acceptance matrix above; `docs/evidence/G1-IKARUS-32_PLANNER_PROGRESS_LIVE/`
