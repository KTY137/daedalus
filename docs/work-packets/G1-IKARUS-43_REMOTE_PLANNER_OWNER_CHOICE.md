# G1-IKARUS-43 — A remote planner is an explicit owner choice, and no observation passes the secret floor into any planner prompt

Packet ID: G1-IKARUS-43

Artifact role: primary

Classification: `ALIGNED`

Active gate: Gate 1

Owner: repository owner

Base revision: c48ceb70deae2de8fcb23d2679f2432ed8600f9e

Working-tree context: base c48ceb70 is branch `loop/lane11-planner-progress` (G1-IKARUS-32..35, 42); same worktree and interpreter recipe as G1-IKARUS-32

Dependencies: `G1-IKARUS-33` (planner facts and the egress line), `G1-IKARUS-19` (`configure_computer` compare-and-replace), forward plan A4 line 10 (`docs/superpowers/plans/2026-09-06-daedalus-forward-plan.md`), owner decision sheet `docs/decisions-pending/OWNER_DECISIONS_20260906.md` line 10

Stage: owner loop of 2026-09-06, session daedalus-6c (before the restart daedalus-9d). Owner answer 08:42 in the loop: "nimm die most advanced general option"; explicit answer to the decision sheet 08:48 via the review session: "Ja, mit den drei Bedingungen".

## Primary acceptance claim

The owner can choose the planner from the chat with `/computer planner <provider> [model]`. A remote provider (`codex_cli`, `claude_code_cli`, `deepseek`) is stored only after the reply has shown the egress warning and the owner repeats the command with `confirm-remote`; the confirmation is per command and never persisted (section 4.1 widening). The local providers (`ollama_http`, `ollama`) narrow and need no confirmation. The change goes through `configure_computer` with the current policy digest, exactly like `/computer configure`; nothing changes a default. Independently of the planner, every executed observation is scanned by `secret_floor_rule` right after execution (per step, path `computer-observation-NNNN.json`) and the whole prompt is scanned before every planner call (`computer-prompt.json`); a hit ends the mission `blocked` before any planner sees the material, the observation stays retained locally as evidence, and the step is marked `withheld_from_planner`. `/computer status` renders the planner line before the first mission.

The three owner conditions and where each is pinned: (a) visible warning before the first mission: `test_choosing_a_remote_planner_requires_a_transient_confirmation_with_the_warning`, `test_status_names_the_planner_and_the_planner_command`; (b) secret floor on every observation and every prompt before every planner call, local and remote: `test_an_observation_that_trips_the_secret_floor_never_reaches_a_planner_prompt`, `test_the_whole_prompt_is_floored_before_every_planner_call`; (c) no silent default switch: the command is the only new path, the confirmation is transient, and the local choice test pins that narrowing needs none (`test_choosing_the_local_planner_narrows_without_confirmation_and_names_the_model`).

## Scope

In scope: `daedalus/orchestration/ikarus/computer_loop.py` (module-level `secret_floor_rule` import; `_PLANNER_PROVIDERS`, `_LOCAL_PLANNERS`; per-observation and whole-prompt floor; `_planner_line`, `_remote_planner_warning`; the `planner` chat command; the planner line and command in `status`), five tests in `tests/test_ikarus_computer_loop.py`, one paragraph in `docs/IKARUS_COMPUTER.md`, this packet.

Out of scope and untouched: the policy module (its provider set is mirrored, not changed), `configure_computer`, the transports (`_codex`, `_claude`, Ollama), the desktop UI (C8 renders the line and the command), any default.

## Contracts and behavior

- `/computer planner <provider> [model] [confirm-remote]`: unknown provider or wrong arity is refused before any read; a missing policy is refused with a pointer to `/computer setup`; a remote provider without `confirm-remote` replies with the warning and `computer.planner_change: "confirmation_required"` and changes nothing; otherwise the current configuration is copied, only `planner_provider`, `planner_model` and `allow_remote_context` are replaced, and `configure_computer(root, payload, owner_confirmed=True, expected_policy_sha256=<current digest>)` stores it; the reply carries the planner line and `planner_change: "applied"`.
- Secret floor: `secret_floor_rule("computer-prompt.json", prompt)` before every planner call (before the proposal intent is recorded, so no intent and no artifact carry a withheld prompt); `secret_floor_rule("computer-observation-NNNN.json", <outcome JSON>)` after every executed step, before any further planner call. Both end the mission `blocked` with a summary naming the floor (and the step). The step artifact and the report retain the observation; `withheld_from_planner` is `True` on that step and `False` on every other. The existing floors on the objective (before admission), on retained notes and on the planner response are unchanged.
- The floor runs for local planners too: credentials do not enter model context without policy authorization (section 7.2), and the loopback route is still model context.
- Unchanged: the planner route check (`_require_context_route`), which already refuses a non-boolean or absent `allow_remote_context` for a remote provider; the report shape apart from the additive `withheld_from_planner`.

## Acceptance matrix

| Check | Result (2026-09-06, this worktree) |
| --- | --- |
| five new tests without the change | 5 failed (no `planner` command, no floor on observations, no planner line in status) |
| five new tests with the change | 5 passed |
| loop, adversarial, history, autonomy, schedule and schedule-autonomy suites | 187 passed (38.5 s) |
| import census (`tests/test_imports_graph.py`) after the module-level `sensitivity` import | 10 passed, 4 skipped |
| five live Codex-planner missions on the reference page (activation evidence) | 5 of 5 `completed`, 4 calls and 2 tool steps each, 67 to 94 s, all summaries complete, no absent token |
| `computer_loop.py` line endings | LF |

## Measured

Live, 2026-09-06 10:08 to 10:16, five missions in a row with `planner_provider: codex_cli`, `allow_remote_context: true` (Codex CLI 0.153.4 native binary through `DAEDALUS_CODEX_CLI`, `~/.codex/config.toml` model `gpt-6-astra`, owner-declared flat rate), the measure-09 objective, page, tools (`browser.navigate`, `browser.read`) and bounded policy (`max_steps 16`, `timeout_s 900`), on the scratch subject with the kill switch armed; other sessions' suites and a staged merge were running on the box. Evidence `docs/evidence/G1-IKARUS-43_REMOTE_PLANNER_LIVE/` (five reports, five proposal lists, five logs, `summary.json`, the retention script; paths scrubbed; pinned `-text`).

| Mission | Terminal | Planner calls | Tool steps | Elapsed | Absent tokens (G1-IKARUS-44) | Largest prompt |
| --- | --- | --- | --- | --- | --- | --- |
| computer-loop-43-codex-r1 | completed | 4 | 2 | 90.8 s | none | 7,680 chars |
| computer-loop-43-codex-r2 | completed | 4 | 2 | 67.0 s | none | 7,683 chars |
| computer-loop-43-codex-r3 | completed | 4 | 2 | 93.5 s | none | 7,661 chars |
| computer-loop-43-codex-r4 | completed | 4 | 2 | 86.5 s | none | 7,678 chars |
| computer-loop-43-codex-r5 | completed | 4 | 2 | 89.1 s | none | 7,687 chars |

Every run proposed plan, `browser.navigate`, `browser.read`, `finish`, in that order, and every finish summary names the page title, the three Today items, the dentist time and the sentinel (checked programmatically against the served page; `summary_tokens_absent_from_observations.absent` is empty in all five). Every report carries `planner: {"provider": "codex_cli", "model": null, "remote_context": true}` and the chat line "Kontext hat den Rechner verlassen: ja". The secret floor ran on ten observations and twenty prompts without a hit (the page carries no secret). Read together with G1-IKARUS-34 (local 7B: 0 of 10 finishes) this is the activation evidence for the owner's choice: the general planner completes the reference mission 5 of 5 times through the same policy, lease and evidence path. Not claimed: task success as kernel evidence (`task_success_verified` stays false), other objectives, or a comparison beyond this one page (same objective, no seeds beyond the mission id, a loaded box; Codex's own sampling is the only variation). The command path itself is exercised by the unit tests; these runs configured the policy through `configure_computer` with the same payload the command builds.

## Migration and rollback

Additive command and one additive step field; stored policies are untouched until the owner runs the command. Rollback removes the command, the two floor checks and the status line; a policy already switched to a remote planner stays as the owner stored it (the digest names it) and `/computer planner ollama_http` narrows it back without confirmation.

## Evidence, expected failures, and review

Evidence: the acceptance matrix; owner decision sheet line 10 (review session daedalus-b4, 08:48). Expected failure retained: none new. Review: the forward plan session (daedalus-b3) records that C2 (`G1-IKARUS-36`, reproduced finish, n≥5 per arm) depends on this packet's floor test instead of building its own; independent review of this implementation still owed (Odysseus report on 32..35 pending in the room; findings go into a fix-forward commit).

Iron Plan: ALIGNED
Iron Gate: 1
Evidence: the acceptance matrix above
