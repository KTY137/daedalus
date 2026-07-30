---
name: funnel
description: Point a tiered swarm of DeepSeek agents at a target and bring the JSON back for discussion. Use when the user wants many agents to scan, research, review, or plan over something too large to read at once - a codebase, a document, a diff, a directory of results - or says "funnel", "swarm", "lass agenten drauf", "200 agenten", "let N agents analyse X". Wide tiers observe, narrow tiers synthesise and attack. Advisory only: it promotes nothing and gates nothing.
---

# Funnel

An operator instrument for aiming many cheap external agents at one target and
getting structured JSON back. Not a Daedalus subsystem — it borrows the
advisory fan-out lane and adds no control plane, no store, and no path into the
product.

## Run it

```bash
python tools/funnel.py <name>            # dry run: units, cost, budget verdict
python tools/funnel.py <name> --run      # spend
python tools/funnel.py <name> --run --tier scan --limit 5   # a taste first
python tools/funnel_report.py runs/funnel/<name>            # read it back
```

Always take the taste before the full run. Five units cost cents and prove the
JSON contract holds; a malformed `handoff` discovered on unit 253 costs the
whole tier.

Always dry-run first and **state the projected cost to the user before
spending**. The dry run prints `CAN THIS RUN`, which accounts for what the
period has already committed — a ceiling alone is not a projection.

## Available funnels

- `codebase` — every chunk of tracked source → 50 research → 20 review → 10 plan
- add your own: a directory under `funnels/` with `funnel.json` and one
  markdown system prompt per tier

## Writing a funnel

`funnels/<name>/funnel.json` lists tiers. Each names its source, its system
prompt file, and how many units it splits into.

Source kinds:

| kind | takes | produces |
|---|---|---|
| `code_chunks` | `glob`, `chunk_lines` | one unit per chunk of every tracked file |
| `document_sections` | `path`, `split_on`, `lenses[]`, `whole_document` | one unit per (section × lens) |
| `tier` | `from`, `buckets`, optional `field`, optional `drop_where` | the named tier's `handoff` payloads, dealt round-robin |

`field` pulls one list out of each payload (`hypotheses`, `verdicts`);
`drop_where` filters it — that is how a review tier's refutations actually stop
travelling instead of being laundered into confidence downstream.

## The rules that make it work

These are not style preferences. Each one is a measured failure from
2026-07-30, when a 750-call fan-out over this repo returned 715 answers of
which 713 said "no defect found" — while two focused agents found ten real
defects the same day, same provider, same code.

1. **Every tier ships its own system prompt.** The default one forbids the
   scratchpad ("do not include chain-of-thought"), and every defect worth
   finding is a multi-step comparison. Say `THINK BEFORE YOU ANSWER`.
2. **Never demonstrate the empty answer.** The default report template ends its
   worked example with `"risks": []`; 692 of 736 answers copied that exact
   shape. Populate your example.
3. **Make output length a function of the INPUT.** One row per symbol, per
   claim, per hypothesis. If "nothing found" is the cheapest legal answer, it
   is the answer you will get.
4. **Put the payload in `handoff`.** `coerce_report` rebuilds the report from a
   fixed key set and destroys everything else; `summary` is truncated at 600
   characters. Only `risks`, `todos` and `handoff` are unbounded.
5. **`paths=()` always.** Declaring paths makes the provider re-read and append
   the source a second time, truncated at 24,000 chars under a contradictory
   label. Put the text in the objective once.
6. **Units differ; votes stay at 1.** Corroboration needs temperature > 0, and
   three samples of one prompt at 0.0 are one answer counted three times. Get
   diversity from different questions, not repeated ones.
7. **Bind the task id to tier, unit, and revision**, or resume will serve stale
   answers after you fix the prompt.

## Grounding collapses as the funnel narrows — measured, and the fix

The 253-unit codebase run, reference resolution per tier:

| tier | reads | references that resolve |
|---|---|---|
| scan | the actual code | **92%** |
| research | scan reports | 88% |
| review | hypotheses | 78% |
| plan | verdicts | **15%** |

Seventy-five of eighty-eight file paths in the plan tier did not exist —
`daedalus/core/process.py`, `daedalus/gate_discrimination.py`,
`daedalus/eval/picker.py`. The findings behind them were often real; the paths
were reconstructed from a memory of what a project like this ought to contain.
Every tier below `scan` reasons about *text about code*, and nothing re-reads
the source, so fabrication compounds with distance.

Two fixes, both in the spec:

- `attach_evidence: true` on every tier below research. It resolves each item's
  cited references and pastes the **real source** in, so a reviewer judges the
  code rather than the claim's description of it — and an invented citation
  arrives as `NOT FOUND IN REPOSITORY`, which is a refutation on its own.
- tell the last tier that paths are not negotiable: copy a path only if it
  appears in the input, and answer `UNKNOWN` otherwise. UNKNOWN is correct;
  an invented path only looks actionable.

Then read the grounding rate in the report. A tier with many findings and a
poor grounding rate is generating, not observing.

## What the review tier is for — and how to tell it worked

Same run: 187 hypotheses → 169 verdicts → **85 refuted (50%)**, 39 narrowed,
23 confirmed, 22 needs-evidence. That is the number that separates a funnel
from a megaphone. A review tier returning 5% refuted has not reviewed; check
whether its prompt rewards killing (`you are measured by the bad hypotheses you
stop`) and whether it was given the source to check against.

## One idea that did not survive its own measurement

Merging near-duplicate hypotheses before review, to stop one idea looking like
four votes. Measured on the 187: the highest word-overlap between any two was
**0.32**, and the closest pairs were distinct findings sharing vocabulary — two
undefined variables in two different modules. No threshold merges duplicates
without also merging real findings. The cause is structural: round-robin
dealing gives each research bucket *disjoint* inputs, so there is nothing to
deduplicate. The code remains (`dedupe_on`), off by default, with the
measurement recorded next to it. Turn it on only if you deal overlapping
buckets, and re-measure the overlap curve first.

## Before believing anything it returns

Run the reader and check lane health **before** reading a single finding:

- `distinct objective digests` must equal the answer count — equal digests mean
  two units got the same question and their agreement is not independent
- `distinct answer bodies` near the answer count — a concentrated shape means
  the lane is broken, not that the target is clean
- `answers with status=blocked` — a blocked unit lands in the same array as a
  real one and reads as clean in every aggregate
- finding rate per answer — compare against the 0.0028 that started all this

A report that prints findings before establishing that the answers are
*different* cannot tell "the target is clean" from "the lane is broken".

## Honesty

Model output here is a hypothesis generator. Under the master plan's section 4
it is not evidence, and a majority of agents agreeing is not truth — they share
a prior. Rank by agreement across **different questions**, never by repetition
of the same one. Every finding needs a named check a human can run.
