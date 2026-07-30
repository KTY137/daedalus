# Ceiling: does a shared latent representation buy anything the brief cannot?

Written 2026-07-30. **Not yet run** — it must not run concurrently with
`tools/gate_discrimination.py`; see §5.

## 0. The question, stated so it can be answered wrong

Lane A2 measured a co-change ceiling of **2.3%** (`daedalus/eval/ceiling.py`,
clean ceiling at `min_count=2` = 1/43) and was closed on that basis. Reopening is
gated on a ceiling run, which is the right rule.

That number does **not** transfer to the proposal on the table, because it was
measured for a different consumer:

| | consumer | question it answers |
|---|---|---|
| lane A2 | the **router / picker** | which file should I look at next? |
| this run | **N working groups sharing one representation** | does group 7 know what group 3 already established? |

Same machinery, different question. Quoting 2.3% at the second one would be
inheriting a number, which this repo treats as no number at all.

## 1. What is actually being proposed

Two hundred generation agents in groups of ten, each group spiking one problem
from a different angle, then a review panel. Every group gets the threefold graph
(imports / symbols / documents) — that part is built and landed today as
`daedalus.lanes.graph_brief`.

The *addition* under test is: project the graph into a latent space so groups
share a representation rather than each receiving the same deterministic text.

## 2. The ceiling, and why it needs no embeddings

A ceiling run measures **headroom**, not performance. So the correct experiment
is a classification over a corpus of failures we have already measured, asking of
each one:

- **(a) already covered** — the information needed to prevent it is present in
  the deterministic brief. Latent buys **zero** here by construction.
- **(b) present but not expressible** — the information is in the repo, but not
  as a symbol, an import edge or a doc link. It needs similarity, analogy or
  "something like this already exists under another name". This is the **only**
  bucket a latent representation can claim.
- **(c) absent** — the information is not in the repo at all (a wrong assumption
  about runtime behaviour, an intent only the requester knows). Nothing retrieval
  -shaped buys this; only execution does, per the tier table in
  HANDOFF §2.

**Ceiling = |b| / (|a| + |b| + |c|).**

If that is 2–3%, the answer is the same as lane A2's and the infrastructure is
not built. If it is 30–40%, it is the most valuable open lane in the project.
Either way the run costs a classification pass, not a vector store.

## 3. The corpus, which already exists

Every item below was measured on 29/30 July and is on disk. No new failures need
to be provoked.

| source | n | what it is |
|---|---|---|
| write-lane substitutions | 3 | a module replaced by another file's content |
| invented first-party imports | 3 | `daedalus.linting`, `ShiftManager`, `daedalus.wiki_vault` |
| wrong-assumption test failures | 4 | agent-written tests that parsed, imported, and asserted false things |
| UNWIRED false positives | 147 of 154 | the cheap model's 95.5% false-positive tag |
| fan-out claims with no corroboration | 1,226 | largest agreement cluster: two |

The first three rows are the sharp corpus (10 items, each with a known root
cause). The last two are the volume corpus and are what makes the denominator
honest — a ceiling computed only over failures somebody already diagnosed is
a ceiling over the easy half.

## 4. Predicted result, recorded BEFORE the run

Recording a prediction is the cheapest available guard against reading the
outcome as confirmation of whatever we hoped.

- The 3 invented imports are **(a)** — `graph_brief` demonstrably lists `Shift`,
  `daedalus/gui/lint.py` and `daedalus/wiki/vault.py`. Latent buys nothing.
- The 3 substitutions are **(a)** — caught deterministically, 3/3, µs.
- The 4 wrong-assumption failures are **(c)** — only execution catches them.
- The 147 false UNWIRED tags are the interesting ones and I do not know which
  bucket they land in. If "this symbol is referenced somewhere I cannot see"
  turns out to need similarity rather than an edge, they are **(b)** and the
  ceiling is high. If they are simply the function-body import edges the index
  already has, they are **(a)** and the ceiling collapses.

So: **the ceiling is roughly the fraction of the UNWIRED corpus that is (b)**,
and the honest expectation before measuring is that most of it is (a), because
the 38% invisible-edge finding says the graph already knows.

That prediction is falsifiable, which is the point of writing it down.

## 5. Sequencing — do not run this against a busy box

`eval/ceiling.py`-shaped work shells out to git (`_parents_of`, 10 s timeout per
call) and builds the structcore index. `tools/gate_discrimination.py` runs the
whole suite once per mutation, twelve times.

MEASURED 29/30 July: the suite takes ~105 s idle and **exceeded the 900 s
`DEFAULT_TIMEOUT_S` under concurrent agents**, and the gate reported that as
`baseline_red` — a red baseline that was never a failing test. Hours were spent
on it.

So this run waits for the receipt. It is not a resource question, it is a
correctness one: two measurements sharing eight cores produce two numbers with no
provenance.

## 6. What a positive result would and would not license

A high ceiling licenses **one** thing: an experiment where the latent layer is
the only variable, judged by the existing fitness function
(`eval/graph_delta.py --held-out`, 95.3% / 286 of 300, reproducible).

It does not license a global embedding infrastructure, because "project
everything into a latent space" is the single most common architecture in this
product category and having it is not evidence that it works here. The ceiling is
what turns it from an architecture into a claim.
