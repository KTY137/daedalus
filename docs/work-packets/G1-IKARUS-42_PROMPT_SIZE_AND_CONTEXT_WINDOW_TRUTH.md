# G1-IKARUS-42 — Every planner call reports its prompt size against the planner's context window

Packet ID: G1-IKARUS-42

Artifact role: primary

Classification: `ALIGNED`

Active gate: Gate 1

Owner: repository owner

Base revision: 1463bde2a11690cab181bec68df9099eb7a2ff9b

Working-tree context: base 1463bde2 is branch `loop/lane11-planner-progress` (G1-IKARUS-32..35); same worktree and interpreter recipe as G1-IKARUS-32

Dependencies: `G1-IKARUS-31` (native Ollama route sends `num_ctx_value()`), `G1-IKARUS-33` (planner facts in the report), Momus critique of 2026-09-06 04:10 (measure before compacting; see Council and review record below)

Stage: owner loop of 2026-09-06, sixth tick, session daedalus-9d.

## Primary acceptance claim

Each planner call records its prompt size (`prompt_chars`) in the proposal intent and the proposal artifact, together with the planner's configured context window (`planner_context_tokens`, from `num_ctx_value()` for the loopback Ollama route, `None` for remote CLI planners) and whether the prompt exceeded that window under a stated estimate (`context_window_exceeded_estimate`, four characters per token). The final report carries `prompt_chars_max`, `planner_context_tokens`, `context_estimate: "chars/4"` and `prompt_overflow_calls`; the chat rendering adds one sentence only when at least one call overflowed. Nothing is truncated, compacted or stopped by this packet: the provider's window is an external constraint the plan says to report honestly (section 4.1), and the existing `context_limit` stop under the token axis is untouched.

Why: a `browser.read` observation may carry 20,000 characters and a `file.read` up to `max_file_bytes`; the local planner runs at 6,144 tokens. A prompt beyond that is truncated by the provider from the front, which drops the directive, and until now no artifact said so. Momus (04:10) rejected history compaction as specified because its premise was unmeasured: no retained receipt had ever exceeded 26 KB. This packet creates or destroys that premise with a measurement.

## Design disagreement recorded

Momus asked that prompt-overflow protection stop being conditional on `limit_policy.enforces("tokens")`, calling that a cost axis. Not adopted here: a loop-owned stop at a character bound is a Daedalus-owned input-token cap in the sense of section 4.1, which the owner may disable; what the plan requires for the external window is honest reporting, which this packet adds under every execution-limit mode. Whether the loop should additionally refuse to send a prompt the local model provably cannot read in full is left as a review question, not decided silently.

## Scope

In scope: `daedalus/orchestration/ikarus/computer_loop.py` (`_planner_context_tokens`, `_CHARS_PER_TOKEN_ESTIMATE`, per-call bookkeeping, two artifact fields, four report fields, one chat sentence), three tests in `tests/test_ikarus_computer_loop.py`, this packet, evidence `docs/evidence/G1-IKARUS-42_PROMPT_SIZE/`.

Out of scope and untouched: any compaction or truncation of history (G1-IKARUS-43 candidate, only if this measurement shows overflow), the token-axis stop, the providers, the adapters, the registry.

## Contracts and behavior

- `_planner_context_tokens(capabilities)`: `int(num_ctx_value())` when the normalised planner provider is `ollama_http`, else `None`. The remote CLIs' windows are not guessed.
- Per planner call: `prompt_chars = len(prompt)`; `context_window_exceeded_estimate = prompt_chars > planner_context_tokens * 4` when a window is known, else `False`; `prompt_overflow_calls` counts such calls and is `None` when no window is known.
- Proposal intent payload gains `prompt_chars`; the proposal artifact gains `prompt_chars`, `planner_context_tokens`, `context_window_exceeded_estimate`. The report gains the four fields above. `_chat_report` renders the overflow sentence only for a positive count.
- Unchanged: prompts, stops, states, `task_success_verified`.

## Acceptance matrix

| Check | Result (2026-09-06, this worktree) |
| --- | --- |
| three new tests without the change | 3 failed (missing report keys) |
| three new tests with the change (a 30,000-character fixture observation is counted once and said) | 3 passed |
| loop, adversarial, history, autonomy, schedule and schedule-autonomy suites | 182 passed (51.2 s) |
| live `computer-loop-measure-11c`: qwen2.5-coder:7b, bounded (`max_steps 16`, `timeout_s 900`), the measure-08 objective against a 394,271-byte page (1,200 paragraphs, same Today list and sentinel) | overflow real: 3 of 4 calls above the estimate (24,984 and 25,643 chars against 24,576), `stalled` after 4 calls, never read, 314.8 s |
| `computer_loop.py` line endings | LF |

## Measured

Live `computer-loop-measure-11c` (2026-09-06 10:22, after two aborted attempts 11/11b that died with session restarts; qwen2.5-coder:7b, native route, `num_ctx` 6144, `max_steps 16`, `timeout_s 900`, the measure-09 objective against `big.html`, 394,271 bytes, the same Today list and sentinel with 1,200 filler paragraphs; other sessions idle, no suite running): call 1 `browser.navigate` at 2,989 prompt characters; the navigate observation carries the page text capped at 20,000 characters by the browser adapter, so call 2 is 24,984 characters and calls 3 and 4 are 25,643, each above the 24,576-character estimate (`context_window_exceeded_estimate: true` on three of four proposal artifacts, `prompt_overflow_calls 3`, `prompt_chars_max 25,643`); the 7B proposed the same one-step plan three times and never read: `stalled` after 4 calls and 1 tool step, 314.8 s (about 78 s per call against 25 to 29 s on the small page). The chat line rendered: "3 Planner-Aufruf(e) überschritten das geschätzte Kontextfenster des lokalen Modells (6144 Token, Schätzung chars/4)". Evidence in `docs/evidence/G1-IKARUS-42_PROMPT_SIZE/` (report, proposals, log, page parameters, retention script; paths scrubbed).

What this establishes: Momus's premise question is answered, overflow is real and reachable with one ordinary page read; a single 20,000-character observation plus the directive and tool schemas already exceeds the local window, so any compaction must bound the per-observation share and not only age out old observations. What it does not establish: that overflow caused the non-finish (G1-IKARUS-34 shows the 7B does not finish on the small page either); the differences here are that it never read at all and that each call took three times as long.

## Migration and rollback

Additive fields; no stored artifact changes shape for older missions. Rollback removes the helper, the bookkeeping and the fields.

## Evidence, expected failures, and review

Evidence: the acceptance matrix; `docs/evidence/G1-IKARUS-42_PROMPT_SIZE/` (measure-11 report, proposals, log, the page generator's parameters; paths scrubbed). Expected failure retained: the 7B is expected not to finish (G1-IKARUS-34); the question here is only whether prompts overflow and whether the report says so. Review: Momus proposed this measurement as the first of three packets (then a renamed finish-summary absence check, then compaction only on measured overflow); no review of the implementation yet. Review question: should the loop refuse to send a prompt the local model provably cannot read in full, and under which execution-limit modes?

Iron Plan: ALIGNED
Iron Gate: 1
Evidence: the acceptance matrix above
