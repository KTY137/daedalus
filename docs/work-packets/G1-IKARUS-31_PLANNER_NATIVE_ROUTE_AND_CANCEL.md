# G1-IKARUS-31 — The computer planner takes Ollama's native route and can be abandoned

Packet ID: G1-IKARUS-31

Artifact role: primary

Classification: `ALIGNED`

Active gate: Gate 1

Owner: repository owner

Base revision: cfe8d34b8ef1438156e6fa3e6982f5a30d91696f

Working-tree context: isolated worktree `.claude/worktrees/stage3-failed-receipt`, branch `loop/stage3-failed-receipt`, stacked on the stage-14 integration (7ea37c20)

Dependencies: `G1-IKARUS-26` (the live measurement), `G1-IKARUS-29` (plan budget, pre-effect timeout), `G1-KERNEL-02` (`run_cancellable`, `ProviderCancelled`)

Stage: 15 of the owner-directed 2026-09-05 loop; design agreed with Codex in the room (question 21:55, answer 21:56: option B, three additions) and with review session 6e (21:00: explicit transport discriminator, Codex's additions, the transport-switch reload measured as a residual).

## Primary acceptance claim

A schema-constrained Ollama call from the Ikarus shell (the general computer planner is the measured case) is sent to Ollama's native `/api/chat` with the schema as `format`, `keep_alive` from `keep_alive_value()`, `options.num_ctx` from `num_ctx_value()` and the effort output cap as `num_predict` (absent when the token axis is disabled), without the separate warm-up request; schema-less calls keep the `/v1` route byte for byte. The computer loop hands the default planner a non-raising probe over the mission cancellation and the service stop, so an in-flight planner call is abandoned through `run_cancellable` and `ProviderCancelled` reaches the loop, where the existing checkpoint maps a user cancellation to exactly `cancelled` and a kill-switch stop to its own state. Ten tests pin it (seven fail without the change; three guard the state mapping the loop already had).

## Measured

Why: stage 13 measured about 74 s per planner call with the model evicted between calls; lane 2 (G1-KERNEL-02 evidence `ollama_v1_keep_alive.log.txt`) measured on Ollama 0.33.3 that `/v1/chat/completions` ignores `keep_alive` (`expires_at` +5m00s), pins `context_length` 4096 and evicts a natively warmed instance, while `/api/generate` with the same TTL and `num_ctx` 6144 keeps +30m00s and 6144. Review session 6e measured that `warm_model()` (the shell's pre-call warm-up, keep_alive 30m) returns False after its 60 s timeout on this host because the cold load takes longer, so the pin never took effect for the planner.

Live re-measurement after the change: mission `computer-loop-measure-06`, 4 planner calls in 102.1 s (25.5 s per call) against 125 s per call one hour earlier on the `/v1` route with the same policy; evidence `measure-06_*` in the G1-IKARUS-26 directory.

## Council record

Room, Codex 21:56 (static review at 7ea37c20, no live run): supports option B, ALIGNED, Gate 1; keep `num_ctx_value()` (default 6144 plus `OLLAMA_NUM_CTX` exist, a smaller planner constant would need its own measurement); carry the existing output limit as `num_predict` from `_effort_cap()`, `None` when the token axis is disabled; remove the extra `warm_model_async()` in the native branch (one request, so the cancellation test covers the only request); pass `ProviderCancelled` through explicitly (`_ollama` swallowed every exception as `None`); add a barrier test that a call cancelled before dispatch sends zero requests (Codex noted `run_cancellable` checks the probe on the caller only before the thread starts, a static gap in G1-KERNEL-02, not reproduced); user cancellation must map to exactly `cancelled`. All five adopted. Advisory only.

## Scope

In scope: `daedalus/orchestration/ikarus/shell.py` (`_llm` gains `cancelled`; `_ollama` branches on `response_schema`; new `_ollama_native_schema`), `daedalus/orchestration/ikarus/computer_loop.py` (`_cancel_probe`, `_model_proposal(..., cancelled=)`, the default `propose` binding), new `tests/test_ikarus_shell_ollama_native.py`, three tests in `tests/test_ikarus_computer_loop.py`. Out of scope: `_openai_compat.py` and `_ollama_native.py` (unchanged), the `/v1` route for schema-less voices, `chat_stream`, other providers, the registry (no door changes).

## Contracts and behavior

- `shell._llm(..., cancelled=None, transport=None)`: the probe and the transport are forwarded to the Ollama HTTP route only; other providers ignore them.
- `transport` is an explicit caller decision (review session 6e): `"native"` or `"v1"`; any other value is a `ValueError`. Left unset, a schema-constrained call derives `"native"` (Codex, option B) and a schema-less call keeps `"v1"`. The computer planner names `transport="native"` explicitly; `--transport native` without a schema sends a plain native chat (no `format`).
- `shell._ollama(..., response_schema=None, cancelled=None)`: with a schema, `_ollama_native_schema` posts one native request `{model, messages:[system,user], stream:false, format:<schema>, keep_alive, options:{num_ctx, temperature 0.3[, num_predict]}}`; `timeout_s` reaches `native_chat` unchanged, `None` included; with a probe the call runs through `run_cancellable` and `ProviderCancelled` is raised through; any other failure still returns `None` as before. Without a schema the `/v1` branch is untouched, warm-up included.
- `computer_loop._cancel_probe(cancelled, service)`: `True` when the mission probe fires or `service.check_cancelled()` raises; never raises itself. The loop's `checkpoint()` after a failed planner call keeps the typed attribution: `_ComputerCancelled` -> `cancelled`, `LoopHalted`/operator stop -> `blocked` with the stop's own message. An injected `propose` keeps its four-argument contract.
- A cancelled planner call is abandoned, not retried (G1-KERNEL-02 contract); the proposal intent is marked failed by the existing handler.

## Acceptance matrix

| Check | Result (2026-09-05, worktree) |
| --- | --- |
| ten new tests without the change | 7 failed, 4 passed (the three loop guards and the `/v1` route test) |
| twelve new tests with the change (ten plus the explicit-transport pair), plus the loop and adversarial files | 58 passed (6.5 s) |
| broad verification of the integrated branch (22 suites) | 672 passed, 7 xfailed, 1 failed: the import census pins moved with the lanes' ten new modules (473 to 483 modules, 1905 to 1923 edges), re-measured in this commit; 3 passed |
| wider suites touching the Ollama route (stream, egress lane, os boundary, desktop runtime, dynamic, room wiring, shells, autonomy, schedule, provider cancellation, CLI boundary, registry doors) | 452 passed, 34 subtests, 120.3 s |
| transport-switch reloads over a mixed session (`measure-07`, 6e's condition 3): chat `/v1`, planner native, chat `/v1`, planner native, planner native | 3 reloads in 4 switches: every `/v1` call reloads at `context_length` 4096 (19.4 s, 16.7 s for one token) and every native call after it reloads at 6144 (15.7 s, 14.0 s); two consecutive native calls stay warm (0.6 s). The number is not zero, so option A (the native route for schema-less voices too, after a memory measurement on this host) is the follow-up packet. |
| live `computer-loop-measure-06` on the native route (same objective, tools, bounded policy and stall rule as measure-05) | plan, plan, `browser.navigate` (ok, page observed), plan x3 identical: `stalled` after 4 planner calls in 102.1 s, about 25.5 s per call, against 749 s for 6 calls (about 125 s per call) in measure-05 on the `/v1` route and about 74 s per call in measure-03; the model stayed loaded between calls. Planner behaviour otherwise unchanged: the 7B still never proposes `browser.read` after navigating. |

## Migration and rollback

No stored artifact changes shape. Rollback drops the native branch (schema calls return to `/v1`), the `cancelled` keywords and the probe binding; retained missions are unaffected. Callers that pass a schema and depend on the `/v1` shim's silent 4096 context now get `num_ctx_value()`; on a memory-constrained host the value is tunable through `OLLAMA_NUM_CTX` as before.

## Evidence, expected failures, and review

Evidence: the stage-13 and G1-KERNEL-02 evidence directories carry the measurements this packet acts on; the measure-06 run is retained under `docs/evidence/G1-IKARUS-26_COMPUTER_LOOP_LIVE/` next to measure-02..05. Residual, measured: a mixed session still reloads the model on every transport switch (`measure-07`, 3 of 4); option A closes it and is the follow-up packet once the native path's memory behaviour on this host is measured. Review questions: option A's num_ctx on a 16 GB host? Should `run_cancellable` re-check the probe on the worker before `work()` (Codex's static gap in G1-KERNEL-02)? Neither decided here.

Iron Plan: **ALIGNED**

Iron Gate: **1**

Automatic merge/promotion: **forbidden**
