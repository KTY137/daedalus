# GEPA: reflective prompt evolution, read against Ariadne

Status: **read-only critique of an external system**, per master plan §1. Nothing
here changes the plan, and the transfer proposed at the end would be an
`EXPERIMENT` with a frozen spec, not a production path.

Read from source, not from the paper's abstract: `gepa 0.0.27`, installed into
`.venv-dspy` as a dependency of `dspy 3.2.1` on 2026-07-30. File references
below point into that package.

---

## 1. What it actually does

GEPA optimises the *text* of a system's prompts by evolution. Three mechanisms
matter, and only the first two are novel enough to be worth our attention.

### 1.1 The mutation signal is language, not a number

`strategies/instruction_proposal.py` builds a proposer prompt containing
`<inputs_outputs_feedback>`: the task inputs, what the system answered, **and
textual feedback on how each answer could have been better**. Its instruction
to the proposer is explicit:

> "Read all the assistant responses and the corresponding feedback. Identify
> all niche and domain specific factual information about the task and include
> it in the instruction, as a lot of it may not be available to the assistant
> in the future. The assistant may have utilized a generalizable strategy to
> solve the task, if so, include that in the instruction as well."

So a failure is not compressed to a scalar before it is used. The proposer
reads *why* the attempt failed and writes the lesson into the next candidate.
That is the whole idea, and it is the part worth stealing.

### 1.2 Selection keeps whatever wins on anything

`gepa_utils.select_program_candidate_from_pareto_front` builds a Pareto front
**per test case**, drops dominated programs, then samples a parent weighted by
*how many fronts it appears on*. A candidate that is best on exactly one
instance survives; a candidate that is mediocre everywhere does not, even if
its aggregate score is respectable.

Aggregate-score selection cannot do this. It collapses a population toward one
lineage, which is precisely the failure our own preconditions worried about:
the population must be diverse and the diversity must be measured, or a ranking
over candidates carries no information.

Alternatives ship beside it (`CurrentBestCandidateSelector`,
`EpsilonGreedyCandidateSelector` in `strategies/candidate_selector.py`), so the
selector is a swappable axis rather than a belief.

### 1.3 The loop is factored into named, swappable strategies

`strategies/` contains `candidate_selector`, `component_selector`,
`batch_sampler`, `eval_policy`, `instruction_proposal`; `proposer/` contains
reflective mutation and a separate `merge.py` (crossover between candidates).

This is the same factorisation the master plan demands of campaigns in §8 --
change one major axis at a time -- arrived at independently by a different
project. That is weak evidence that the factorisation is right, and it is also
a ready-made vocabulary if we ever want to compare our axes to theirs.

---

## 2. Why this is interesting for Ariadne specifically

Ariadne today mutates code with a model and scores the result with a gate that
answers pass or fail. Meanwhile the evaluator produces pytest output,
tracebacks, and failing assertions -- several kilobytes of precise, mechanical
explanation of *what went wrong* -- and all of it is discarded in favour of one
bit.

GEPA's claim, applied to us: **that discarded text is the gradient.** A repair
operator that sees `AssertionError: expected 3 fields, got 2 at row 17` can
write a different candidate than one that sees `False`.

This is aligned with the evidence boundary rather than in tension with it. The
model *proposes* using the feedback; the evaluator still *decides*. §6 permits
exactly that division and forbids only the reverse.

Second transfer: Pareto-per-task selection is a concrete, cheap answer to the
diversity precondition. It needs no embedding, no descriptor design, and no
new store -- only per-task scores, which any evaluation cascade already
produces.

---

## 3. The objection that must be answered first

§13 lists what must not leak into a candidate. **"evaluator paths or outputs"**
is on that list, by name.

GEPA's central mechanism is feeding evaluator outputs back into the proposer.
Adopted naively, it is the leakage the plan forbids -- and worse, it is the
kind that improves your numbers, which is how it survives review.

The distinction that makes it safe is the split, not the mechanism:

- feedback from the **train/public** split may reach the proposer; that is
  ordinary supervised signal, and a developer reading a test failure is doing
  the same thing;
- feedback from the **held-out** split may never reach it, in any form, at any
  remove -- not as text, not as a score, not as a selection pressure.

If a candidate can be selected using held-out feedback, the held-out set has
become a training set and every number computed on it afterwards is void. Any
experiment here needs that firewall built before the first run, not bolted on
after a promising result.

A second, smaller objection: the reflection step reads execution traces, and
traces from this repository can contain paths, environment, and occasionally
secrets. The same secret floor that guards every other lane has to guard this
one, and it is not obviously the same code path.

---

## 4. What is NOT established

- **Prompts are cheap; code is not.** GEPA's sample-efficiency claims are for
  prompt search, where a candidate costs one inference and evaluation is a
  scored answer. An Ariadne candidate costs a worktree, a build and a test
  suite. The mechanism may transfer; the economics do not, and any claim that
  it "needs fewer rollouts" has to be re-measured on our cost model.
- **Pareto fronts need instances.** With five tasks, nearly every candidate is
  on some front and the selector degenerates to random choice. The mechanism
  presupposes a task set we do not yet have.
- **Reflection quality is a model capability.** The proposer must read a
  traceback and infer a general lesson. Whether a cheap model can do that on
  our traces is an open question with a cheap answer: try it on twenty real
  failures and count.

---

## 5. The experiment, if we run one

Frozen, bounded, isolated, measured -- per §1. One axis only.

**Hypothesis.** A repair operator whose mutation step receives the evaluator's
textual output produces a valid candidate in fewer attempts than the same
operator receiving only pass/fail, at equal token budget.

**Control.** Identical operator, identical model, identical temperature and
seeds, identical task set; the only difference is whether the failure text is
in the prompt.

**Primary metric.** Evaluator calls until the first candidate that passes the
full gate. Secondary: tokens spent, and the fraction of candidates that fail
for the *same* reason twice (a reflective loop that keeps making one mistake
is not reflecting).

**Kill criterion.** If feedback-conditioned repair does not beat pass/fail
repair at equal budget on a pre-registered task set, the mechanism does not
transfer to code and the track stops. Record the negative result; do not
retune the prompt and re-run.

**Firewall, built first.** Train/held-out split enforced mechanically, with a
test that fails if held-out feedback can reach the proposer by any path.

**Cost.** Small. This needs no GEPA dependency at all -- the mechanism is a
prompt change and a selector change, both of which we can implement in our own
loop and measure with the evidence we already collect. Installing GEPA would
buy us their engine and their control plane, which we do not want; reading
their source bought us the idea, which is what we came for.

---

## 6. One line

Feed the evaluator's words back into the mutation, select on per-task fronts
instead of an average, and keep the held-out set out of both -- and the rest of
GEPA is machinery we already have or deliberately do not want.
