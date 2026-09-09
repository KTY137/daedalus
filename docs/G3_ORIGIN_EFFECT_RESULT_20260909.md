# Result — bm25 and embeddings never look at the non-code planes

> ## REPAIR COMPLETED [MEASURED 2026-09-10]
>
> The defect described in §2 and §4 (bm25 and embeddings scoring 0.00 on
> non-code tasks because they retrieve only the code-only default universe) was
> repaired on 2026-09-10 by packet G3-ARM-PLANE-01. Both arms now pass
> `planes=_RETRIEVABLE_PLANES` to `harness._repo_chunks`. Non-code plane scores
> rose to 1.000 at budgets 4000 and 16000. The measurement in §4 describing the
> 0.00 scores was correct; the behavior described is no longer in effect.
>
> This document records evidence about what was measured on 2026-09-09 and
> remains a valid diagnostic of the defect and its root cause. The repair result
> is in `docs/G3_ARM_PLANE_REPAIR_RESULT_20260910.md`.

> ## RETRACTION, 2026-09-09, same day
>
> **This document was first published under the title "8 of the Gate-3 primary
> tier's 14 tasks are constants". That claim is RETRACTED. It was wrong on both
> halves, and an independent adversarial pass refuted it.**
>
> The original text is kept below, struck through in §2–§3 rather than deleted,
> because a retracted claim that leaves no trace teaches nobody anything.
>
> **What was wrong, and why:**
>
> 1. **The non-code half was my own instrument bug.** The probe reused a helper
>    that hardcoded `label_plane="code"`, so `separate_indices` was handed
>    data/knowledge tasks labelled *code*, searched its code index exactly as it
>    should have, scored 0.00, and was written up as broken. Given the true
>    plane it scores **1.00 on all four** at rungs 4000 and 16000. The arm was
>    never broken; the probe was.
> 2. **The code half did not survive wider measurement either.** I generalized
>    "constant" from 4 arms at 3 budget rungs. Across 10 arms × 7 budgets,
>    **not one of the 8 tasks is constant**. Three *mandatory* Gate-3 baselines
>    I never ran — `alphaevolve_proxy`, `map_elites`, `evaluator_only` — move
>    `sunny_garden` off 1.00, and rungs 10/50 break the ceiling for four more.
>
> What actually survives is narrower and is now this document's title: those
> four arms at those three rungs do give 48/48 perfect on `sunny_garden`, and
> `bm25`/`embeddings` return 0.00 on every non-code task because they never
> search a non-code corpus. That second finding is **confirmed and
> strengthened** — see `G3_ARMS_NEVER_LOOKED_AT_THE_NON_CODE_PLANES_20260909.md`.
>
> The lesson I want to keep: I measured four arms and wrote a sentence about
> the task set. "These arms cannot distinguish these tasks" and "these tasks
> carry no information" are different claims, and only the first was measured.


Status: MEASURED 2026-09-09
Classification: EXPERIMENT (Gate-3 prework; active delivery gate is 1)
Packet: G3-ORIGIN-EFFECT-01
Design: `docs/G3_ORIGIN_EFFECT_PREREGISTRATION_20260909.md`, frozen at `9a8e6a24`,
plus Amendment 1 (three repos, re-scoped question) and Amendment 2 (budget
ladder) — both appended before any measurement.
Instrument: `experiments/g3_origin_effect/run.py`; raw output
`runs/g3_origin_effect/report.json`.

## 1. The frozen verdict

**`REPO_IDENTITY_MATTERS_AT_ALL`**, at the primary rung (4000) and at both
sensitivity rungs. The three rungs agree. Zero trials failed.

| rung | bm25 | code_only_graph | embeddings | separate_indices | aggregate |
| ---: | --- | --- | --- | --- | --- |
| 1000 | **MATTERS** −0.667 `[−0.944, −0.333]` | UNINFORMATIVE −0.222 | **MATTERS** −1.000 `[−1.000, −1.000]` | UNINFORMATIVE −0.056 | MATTERS_AT_ALL |
| **4000** | **MATTERS** −0.333 `[−0.667, −0.056]` | UNINFORMATIVE −0.222 | **MATTERS** −1.000 `[−1.000, −1.000]` | DEGENERATE 0.000 | **MATTERS_AT_ALL** |
| 16000 | UNINFORMATIVE −0.222 | DEGENERATE 0.000 | **MATTERS** −0.833 `[−1.000, −0.611]` | DEGENERATE 0.000 | MATTERS_AT_ALL |

`delta = mean(agent_env) − mean(sunny_garden)`. Every delta is ≤ 0: the fixture
scores at or above the real repository everywhere, which is the direction §7
predicted.

## 2. ~~But the direction was the least of it~~ (RETRACTED — see the box above)

The frozen contrast asked whether repository identity shifts scores. The raw
vectors answer a bigger question that the summary statistic hides:

> **`sunny_garden` scored 1.00 on every task, for every arm, at every rung.
> 48 trials out of 48, perfect.**

That is not "a small corpus is easier". That is a **ceiling**. Those four tasks
return the same value no matter which arm runs them or what budget it gets, so
they cannot distinguish any arm from any other. They are a constant wearing a
task's clothes.

An exploratory follow-up (NOT part of the frozen design; run after the verdict
was read, and reported here as exploratory) put the same four arms over the
primary tier's other fixture repository, `fourfold_wiki_app`, which supplies all
four of its non-code tasks:

| arm | scores on the 4 data/knowledge tasks, all three rungs |
| --- | --- |
| `bm25` | `0.00 0.00 0.00 0.00` |
| `embeddings` | `0.00 0.00 0.00 0.00` |
| `separate_indices` | `0.00 0.00 0.00 0.00` |
| `code_only_graph` | **errors on all 4** (a code-only arm, as designed) |

A second constant, at the opposite rail.

## 3. ~~What the primary tier actually contains~~ (RETRACTED — see the box above)

| group | n | behaviour under these arms |
| --- | ---: | --- |
| `sunny_garden`, code | 4 | constant **1.00** — ceiling |
| `fourfold_wiki_app`, data + knowledge | 4 | constant **0.00** — floor |
| `agent_env`, code | 6 | **the only tasks with any variance** |

**~~Eight of the fourteen primary-tier tasks carry no discriminative
information.~~ RETRACTED — refuted across 10 arms x 7 budgets; not one of the
eight is constant.** A cross-plane comparison at this tier is a constant 1.0 against a
constant 0.0. It cannot separate two arms, cannot be moved by a better method,
and cannot be evidence for or against a plane effect. This is a sharper
statement of the same barrier as complete separation (pre-registration §1), and
it is measured rather than counted.

## 4. Which reading of the 0.00 is right — stated as open

Two explanations survive this data and I cannot separate them here:

- **(a) task-side:** the non-code tasks are unanswerable by these arms.
- **(b) arm-side:** these arms have no non-code retrieval capability, so a 0.00
  is produced by construction rather than earned.

The leading candidate for (b), named with its mechanism so it can be checked:
`bm25` retrieves over `harness._repo_chunks`, a walk of *source* files. If a
CSV, a JSON schema and a Markdown page are not in that document universe, the
arm cannot return them at any budget and the 0.00 is arithmetic, not evidence.
**This is unverified.** It is the obvious next measurement.

Either way the consequence for Gate 3 is identical: **the primary tier and these
arms together cannot support a cross-plane claim.** Under (a) the tasks are
wrong for the arms; under (b) the arms are wrong for the claim.

## 5. Where the verdict is weak — said plainly

- At rung 16000 the aggregate rests on **`embeddings` alone**; `bm25` has fallen
  to UNINFORMATIVE and the other two are DEGENERATE.
- `embeddings` scores **0.00 on nearly every `agent_env` task** at rungs 1000
  and 4000. Its −1.000 delta is as much "this arm fails on the real repository"
  as "the fixture is easy". Its contribution to the verdict is confounded with
  its own weakness, and the verdict should not be leaned on through that arm.
- The verdict's honest load-bearing evidence is **`bm25` at rungs 1000 and
  4000** — an arm that demonstrably works on both corpora and still separates
  them.
- n = 6 vs 4. Every interval here is wide, and none of this is a precise
  estimate of anything.

## 6. What this does not establish

- Not a bound on the origin effect that the cross-plane comparison actually
  suffers from. Amendment 1 already recorded that this is **not identifiable**
  with the present corpus: all non-code tasks live in `fourfold_wiki_app`, which
  appears in neither arm of the frozen contrast. Reasoning from
  `agent_env`-vs-`sunny_garden` to `fourfold_wiki_app` is an **inference, not a
  measurement**.
- Not a Gate-3 baseline result, and not a promotion of anything from quarantine.
- Not evidence about plane-conditioned retrieval. The six existing negatives on
  that question stand untouched. That said, §2's floor result raises a
  *hypothesis* worth testing separately: if non-code tasks score 0.00 for every
  arm, plane-conditioning has nothing to work with by construction. That is a
  hypothesis about those runs, not a re-reading of them.

## 7. A note on the reading table

Row 1, `DEGENERATE`, fired three times — `separate_indices` at 4000 and 16000,
`code_only_graph` at 16000, all of them all-1.00 across both groups. That row
exists because three reading tables I wrote this week failed by offering only
two branches for a space that held a third outcome. Without it, "both groups at
ceiling" would have been reported as a clean null result of exactly 0.000 with a
zero-width interval, which is the most confident-looking way to say nothing at
all.

The first version of the runner also coerced a missing score to `0.0`. That
would have turned `code_only_graph`'s four hard errors on `fourfold_wiki_app`
into four confident zeros. It now records failures and refuses to read any table
when one occurs; the frozen run had zero failures, and that fact is now
measured rather than assumed.

Iron Plan: EXPERIMENT
Iron Gate: 1
Evidence: `runs/g3_origin_effect/report.json`; `experiments/g3_origin_effect/run.py`
