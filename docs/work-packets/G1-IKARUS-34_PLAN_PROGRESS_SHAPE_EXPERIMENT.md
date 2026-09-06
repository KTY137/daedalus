# G1-IKARUS-34 — Does the shape of plan_progress change whether the local planner finishes?

Packet ID: G1-IKARUS-34

Artifact role: primary

Classification: `EXPERIMENT`

Active gate: Gate 1

Owner: repository owner

Base revision: ef9ff1c47617e428ab04b1fe88aa6615e1963167

Working-tree context: base ef9ff1c4 is branch `loop/lane11-planner-progress` (G1-IKARUS-32/33); same worktree and interpreter recipe as G1-IKARUS-32; the loop source is not edited while the runs execute (one process, one `source_sha256`)

Dependencies: `G1-IKARUS-32` (the payload under test and its Momus review), `G1-IKARUS-26` (fixture page and measurement recipe)

Stage: owner loop of 2026-09-06, third tick, session daedalus-9d. Pre-registered here before the first run started (03:12).

## Primary acceptance claim

Hypothesis (Momus, G1-IKARUS-32 review, rated minor): the committed `plan_progress` payload ships one counter in six views, and a small planner fixates on the plan text; a single representation (the plan repeated with a per-step `executed` flag) would let the 7B conclude. Outcome variable, fixed in advance: whether the mission's terminal state is `completed` (the planner proposed `finish`). Secondary: planner calls, tool steps, terminal state, elapsed time. Decision rule, fixed in advance: V2 is adopted into the loop (with tests) only if it finishes in strictly more runs than V1 out of five; a tie or a V1 lead retains V1 and records V2 as negative evidence. No other change ships from this packet.

## Scope

Frozen specification: `docs/evidence/G1-IKARUS-34_PLAN_PROGRESS_SHAPE/experiment_payload_shape.py` (retained verbatim). Two variants, five runs each, alternating v1, v2, v1, ... in one process. V1 = the committed `_plan_progress`. V2 = `{"steps": [{"index", "text", "executed"}], "next_step"}`, installed by monkeypatching `computer_loop._plan_progress` in the experiment process only; the directive text is identical for both (it names `next_step`, which both shapes carry). Same page (`fixture_notes.html` on a loopback `http.server`), objective, tools (`browser.navigate`, `browser.read`), planner (`qwen2.5-coder:7b`, native route, local only), bounded policy `max_steps 16`, `timeout_s 900` as measure-10, kill switch armed. Budget: at most 10 x 16 planner calls and 10 x 900 s; no money (local inference). Evaluator: the loop's own deterministic terminal state, never the planner's text. Expiry: the runs of 2026-09-06; not to be re-run with a different objective and still counted here.

Out of scope: any production code change, the directive text, other planners, other objectives, the plan budget and stall rules.

## Contracts and behavior

Nothing in the tree changes behaviour. If the decision rule adopts V2, that is a separate ALIGNED commit with tests, referencing this packet; `_prompt`'s directive would be updated in the same commit.

## Acceptance matrix

| Check | Result |
| --- | --- |
| pre-registration written before the first run | this file, committed with the results |
| V1 finished / 5 | RESULT_V1 |
| V2 finished / 5 | RESULT_V2 |
| decision per the rule above | RESULT_DECISION |

## Measured

MEASURED_PLACEHOLDER

## Migration and rollback

None: no behaviour change ships from this packet.

## Evidence, expected failures, and review

Evidence: `docs/evidence/G1-IKARUS-34_PLAN_PROGRESS_SHAPE/` (script, log, results JSON with every proposal verbatim, paths scrubbed). Expected failures: a 7B on CPU under shared load may time out (`timeout`) or stall; both count as "not finished" and are retained. Known confounder, stated: the box runs other sessions' test and Vite load; it affects elapsed time, not the terminal state, but a wall-time timeout would. Review: Momus proposed the variant; no independent review of the result yet.

Iron Plan: EXPERIMENT
Iron Gate: 1
Evidence: see above
