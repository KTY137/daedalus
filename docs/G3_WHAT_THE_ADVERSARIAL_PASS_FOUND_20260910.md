# What the adversarial pass found, and what happened to each finding

Status: MEASURED 2026-09-10
Classification: EXPERIMENT (Gate-3 prework; active delivery gate is 1)

On 2026-09-10 I promoted 35 tasks out of quarantine into the Gate-3 primary
tier — the tier that feeds go/no-go numbers — on the strength of a promotion
witness I had written an hour earlier. I then sent it to an independent
adversarial pass, aimed at the weakest link.

It refuted the promotion. This is the disposition of every finding, kept in one
place because the pattern across them is more useful than any one of them.

## The findings

| # | Finding | Verdict | Disposition |
| --- | --- | --- | --- |
| S1 | "file added ⇒ T1/T2 impossible" is false — git calls a byte-identical **copy** an add | REFUTED my claim | Promotion reverted; `--find-copies-harder` added |
| S2 | The audit inspected the **anchor**, which by design supplies **none** of the gold labels | STRUCTURAL | Re-pointed at the label sources |
| S3 | The scored corpus contained **its own answer key** | LEAK | `minted_tasks.json` excluded from the retrieval universe |
| S4 | My headline numbers do not reproduce, and no instrument existed | UNVERIFIABLE CLAIM | Retracted; retained instrument built |
| S5 | 7 of the 35 **are** constants | REFUTED my claim | Retracted |
| S6 | The "frozen" digest ignored task content | INSTRUMENT DEFECT | `content_digest` added |
| S7 | One mutant survived: verdict ordering in the main aggregation | GAP | Pinned |
| S8 | "Complete separation is broken" — arithmetic exact, conclusion overreached | NARROWED | Restated |

## The three that matter most

**S1 — the copy.** `git` reports a byte-identical copy of an existing file as
an add unless copy detection is on. My audit concluded from "added" that
nothing existed to rename, while the file sat in the parent tree under another
name. One promoted task was a **pure packaging move**: 56 of its 57
label-supplying files were `C100`, and 19 of its 25 gold labels were
recoverable from those copies' pre-images. It is threat T2 exactly as
`MINT_CONFIRM_THRESHOLD`'s own comment words it — *"a rename that round-trips
to byte-identical source under a new name"* — at file granularity instead of
symbol granularity, and my audit gave it the strongest verdict in its
vocabulary.

Two rival explanations were tested and killed: merge parents (0 of 32) and
delete-then-restore (0 of 32). The route was specifically copy/vendor.

**S2 — the wrong file.** Both mint paths exclude the anchor from `must_include`
on purpose. My audit read `task["target"]` — the anchor. So it was a correct
statement about the one file in the commit that supplied no labels at all,
harmless 31 times out of 32. Auditing the label sources instead changed the
verdicts on **20 of the 35**.

**S3 — the answer key.** `daedalus/eval/minted_tasks.json` is a tracked `.json`
under `daedalus/eval/`, so the data-plane extension rule swept the evaluator's
own store into the retrieval universe: one 76,439-character chunk holding every
gold label of every minted task, from which **29 of 35 reach recall 1.0 on that
chunk alone**. For six, part of the gold answer exists *only* there.

It was inert while every minted task was quarantined and became scoreable the
moment they were promoted. The exclusion list's own comment already stated the
principle for `fourfold.json` in as many words — *"Retrieving it would hand a
retrieval arm the answer key"* — and the store simply was not on the list.

## What the corrected audit says

| verdict | before (buggy) | after |
| --- | ---: | ---: |
| clean | 35 | **15** |
| undecided | 11 | 21 |
| unverifiable provenance | 2 | 2 |
| **fired** | 0 | **10** |

Twelve tasks flipped clean → fired, eight clean → undecided. Ten of the 48 are
demonstrably noise by the threshold's own named threats — the first time that
gate has caught anything at all, since the recurrence witness has never fired
once in 400 commits.

## The pattern, which is the point of this document

Four of the eight findings are the same mistake in different clothes: **I
checked a proxy and reported it as the thing itself.**

- the anchor stood in for the label sources (S2)
- "added" stood in for "new content" (S1)
- ids and a census stood in for the corpus (S6)
- a mean over the tier stood in for the tasks in it (S4, S5)

Each proxy was reasonable. Each was wrong in a way that only showed up when
someone measured the thing directly. The tests did not catch any of them,
because I wrote the tests from the same misconception as the code — every
fixture in `test_mint_noise_audit.py` used one file as both anchor and label
source, which is why 13 tests stayed green while the audit read the wrong file.

The one defence that worked was an outside instrument checking the claim
against reality, and the reason S4 is on this list is that in that one place I
had not built one.

## What is true now

- **Nothing is promoted.** All 48 minted tasks are quarantined.
- The audits are retained on every task, including the ten `fired` ones: they
  are evidence of what was claimed and refuted.
- Complete separation is **not** broken. It was, for about an hour, on a
  promotion that no longer stands.
- Re-promotion is gated on a retained instrument
  (`experiments/g3_task_answerability/measure.py`) producing a receipt, because
  the absence of exactly that is what let an unreproducible number justify the
  first attempt.

Iron Plan: EXPERIMENT
Iron Gate: 1
Evidence: commits reverting the promotion, repairing the audit, closing the leak,
and adding `content_digest`; `tests/eval/test_mint_noise_audit.py` (19 tests)
