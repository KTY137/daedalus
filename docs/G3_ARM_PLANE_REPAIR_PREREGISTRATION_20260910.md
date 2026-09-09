# Pre-registration — repairing the two arms that never look

Status: FROZEN before measurement, 2026-09-10
Classification: EXPERIMENT (Gate-3 prework; active delivery gate is 1)
Packet: G3-ARM-PLANE-01
Depends on: `docs/G3_ARMS_NEVER_LOOKED_AT_THE_NON_CODE_PLANES_20260909.md`, which
established and independently verified that `bm25` and `embeddings` call
`harness._repo_chunks(root)` with no `planes` argument, retrieve the code-only
default universe, and therefore score 0.00 on every non-code task by arithmetic.

This is the repair that diagnostic packet deliberately did not perform, because
plan §10 puts a change to a frozen baseline's measured behaviour in its own
packet with before/after evidence.

## 1. The design question this run exists to settle

There are two defensible repairs and they are not equivalent.

**Variant A — one general index.** Request
`planes=("code", "data", "knowledge")`: every document the harness can retrieve,
ranked together, the arm choosing for itself. This is what a "BM25 over the
repository" baseline is normally understood to be.

**Variant B — plane-hinted.** Request `planes=("code", task.label_plane)`,
which is the information `separate_indices` already consumes.

**B carries an information asymmetry that must not be introduced silently.**
`task.label_plane` is derived from where the gold labels live. Handing it to a
retriever tells it which plane the answer is in. It is inside the current
contract — `protocols.Task` declares `label_plane` and `separate_indices` uses
it — so it is not a sealed-evaluator breach. But an arm that is told the answer's
plane and an arm that is not are not doing the same task, and the s08 lesson in
this repository is precisely that an arrangement can decide a comparison before
any method does.

So **Variant A is the primary repair.** B is measured as sensitivity, and the
A→B gap becomes the measured value of the plane hint — a number that any future
comparison against `separate_indices` has to declare rather than absorb.

## 2. Measured before freezing (universe sizes, so cost is not a surprise)

| repo | code-only | all three planes | growth |
| --- | ---: | ---: | ---: |
| `fourfold_wiki_app` | 10 | 27 | 2.70× |
| `sunny_garden` | 6 | 6 | **1.00×** |
| `agent_env` | 27,335 | 37,818 | 1.38× |

`sunny_garden` holds no non-code documents at all, so its four code tasks are an
untouched control: Variant A cannot change them, and if their scores move,
something other than the universe changed.

`_repo_chunks` knows three planes and **refuses** `type` rather than falling
back to code — so "all planes" here means three, and that is a property of the
harness, not a choice of this packet.

## 3. What is measured

For each arm in {`bm25`, `embeddings`}, each rung in {1000, 4000, 16000}, each
of the 14 primary-tier tasks: the sealed evaluator's score, BEFORE (code-only),
AFTER-A (all planes), AFTER-B (code + label plane).

Reported as per-arm × per-plane × per-rung, never as a single mean. A mean over
a tier holding both a saturated fixture and a large repository is the statistic
that hid this defect for as long as it was hidden.

## 4. Reading table — frozen

Evaluated per arm; the first matching row wins.

| # | Condition | Reads |
| --- | --- | --- |
| 1 | any trial errors, or the run cannot complete | **BLOCKED** — no verdict is read, exactly as in the origin-effect run |
| 2 | non-code scores rise under A **and** no code-plane score falls | **REPAIRED_CLEAN** |
| 3 | non-code scores rise under A **and** at least one code-plane score falls | **REPAIRED_WITH_REGRESSION** — a real trade, reported as one. A larger corpus at a fixed token budget can push a code answer out of the window; that is a cost of generality, not a rounding error |
| 4 | non-code scores do not rise under A, but do under B | **NEEDS_THE_HINT** — retrieval at this budget cannot surface non-code documents from a mixed index. The plane hint is doing real work and becomes a declared asymmetry in every comparison against `separate_indices` |
| 5 | non-code scores rise under neither | **CAUSAL_STORY_INCOMPLETE** — the diagnosis in the previous packet is not the whole cause, and the repair does not ship |

Row 3 exists because it is the outcome most likely to be reported as a clean
win. Rows 1 and 5 exist because a repair that is assumed to work is how a
baseline silently acquires a defect.

## 5. Acceptance matrix

| id | check | passes when |
| --- | --- | --- |
| A1 | `bm25`/`embeddings` retrieve non-code documents on the four-plane fixture | at least one data and one knowledge document returned |
| A2 | the four `sunny_garden` code tasks are unchanged | byte-identical scores before/after (it has no non-code files) |
| A3 | no trial errors at any rung | zero errors |
| A4 | `coverage.py` declarations updated to match measured behaviour | `test_real_arm_declarations_match_what_they_retrieve` passes, and fails under a mutation that over-declares |
| A5 | the arms' docstrings stop asserting a code-only universe | the stated corpus matches the code |
| A6 | full affected suite green with everything staged | `tests/eval/ tests/test_eval_mint.py tests/contracts/` 0 failed |

## 6. What this packet does not claim

- Not a Gate-3 baseline result. Nothing here is sealed evidence.
- Not a re-reading of the six existing negatives on plane-conditioned retrieval.
  Whether any of them scored a non-code plane through a code-only universe is a
  separate question this packet does not answer.
- Not a promotion of anything out of quarantine.

Iron Plan: EXPERIMENT
Iron Gate: 1
