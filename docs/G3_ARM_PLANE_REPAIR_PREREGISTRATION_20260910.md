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

---

## AMENDMENT 1 — the defect is in six arms, not two, and the repository already knew

Appended 2026-09-10, **before** the frozen run's results were read.

### Six, not two

Grepping every caller rather than the four arms I happened to run:

```
best_of_n.py:88          _repo_chunks(task.repo_root)
bm25.py:86               harness._repo_chunks(task.repo_root)
embeddings.py:204        _repo_chunks(task.repo_root)
local_mutation.py:116    _repo_chunks(task.repo_root)
random_search.py:104     _repo_chunks(task.repo_root)
single_llm_loop.py:159   harness._repo_chunks(task.repo_root)
```

**Six of the ten Gate-3 arms** retrieve the code-only default. Not one caller
anywhere in production passes `planes=`; the only uses are in tests. The
previous packet said "two arms" because it measured four.

### Scope of this run, restated honestly

The frozen contrast (§3) still measures `bm25` and `embeddings` only — the two
deterministic ones, where a before/after score comparison is a clean
measurement rather than a seed-variance exercise.

The other four are **stochastic**, and a scored before/after on them at n=14
would mostly measure seeds. They receive the same one-line change, and their
repair is verified structurally instead: by
`test_real_arm_declarations_match_what_they_retrieve`, which runs each arm and
classifies the documents it actually returns. That is a weaker check than a
scored contrast and is labelled as such — it establishes *that they look*, not
*how much it helps*.

### The repository already solved this, in the older layer

`harness._plane_unindexed_reason` / `_plane_unindexed_row` exist precisely for
this situation. When a task's target cannot be reached by the default index,
the product harness **declares the task PLANE-UNINDEXED and does not score it**,
and its docstring calls these "structural properties of the DEFAULT index
rather than measurements of anything."

`harness.py:734` states the intent outright: *"The retrieval extension point
exists (`_repo_chunks(..., planes=...)`); the arm that uses it is Gate-3 work."*

So this is not a subtle oversight anyone could be expected to miss. It is a
lesson the older layer learned, documented, and encoded — and the newer Gate-3
arm layer did not carry forward. Where the harness says *unindexed*, the arms
say **0.00**, and a 0.00 enters a mean while an "unindexed" declaration does
not.

That reframes the consequence for the six existing negatives on
plane-conditioned retrieval, which the previous packet left as an open
question. **They are not artifacts of this defect** — but the reason matters
and my first version of this paragraph gave the wrong one.

*Corrected within the hour, before the run's results were read.* I first wrote
that the negatives were safe because the harness excludes non-code tasks as
plane-unindexed. That is true of the harness, and it is not the reason those
negatives are safe. Checked rather than inferred: the load-bearing row
(`G2-XPLANE-CONFIRM-04`, "12 plane-using retrieval arms, all negative vs pooled
BM25") is recorded as measured on **suffix-partitioned lexical retrieval** over
`black` and `fastapi` — a separate instrument with its own plane-partitioned
corpus, which never calls `_repo_chunks` at all. It is untouched because it
shares no code path with the defect, not because a guard caught it.

The narrower limitation still stands and is worth keeping separate from the
above: those measurements tested plane-partitioned retrieval on external
corpora, not non-code retrieval through this repository's own arm layer.

### Consequence for the acceptance matrix

A7 is added: **no Gate-3 arm may silently score a task its universe cannot
reach.** Either it retrieves the plane, or it reports the task the way the
harness does. An arm that returns 0.00 for a document it never indexed is
producing a number that looks like evidence and is not.

Iron Plan: EXPERIMENT
Iron Gate: 1
