# The quarantine gate cannot open, and the threats it guards are already absent

Status: MEASURED 2026-09-10
Classification: EXPERIMENT (Gate-3 prework; active delivery gate is 1)
Instrument: `experiments/g3_mint_threats/probe.py` (read-only)

Gate 3's primary tier still draws its non-code labels from a six-file fixture.
48 repository-derived tasks exist and every one is quarantined. This document
measures *why the gate never opens*, and finds that the specific dangers it was
built to hold back are, on this corpus, already ruled out.

## 1. The threshold's own rationale contains a prediction, and it is false

`MINT_CONFIRM_THRESHOLD = 3`. Its comment names exactly three failure modes a
single mint could be:

> **T1** a reformat-only touch that happens to shift a docstring
> **T2** a rename that round-trips to byte-identical source under a new name
> **T3** a generated-file regen

and then predicts:

> "…while staying low enough to actually accumulate from real (comparatively
> infrequent) commit/offload activity **instead of never firing**."

**Measured: zero confirmations, across 400 first-parent commits and all 48
stored tasks.** Not one label set recurred. The comment named the exact failure
mode it would suffer and asserted it would not happen; it happens.

A gate that never opens is not a strict gate. It is an absent one — it never
admits a task, so it never validates a task either.

## 2. The three threats are directly decidable, and none fires

The threshold treats recurrence as a *proxy* for "these three threats are
absent". They can be checked directly instead. Measured over all 48 tasks:

| T1 decidability | n | T1 result |
| --- | ---: | --- |
| `FILE_ADDED` — the anchor did not exist at the parent commit | **32** | **impossible by construction**: there was nothing to reformat |
| `YES` — before/after both parse; compared by AST with docstrings dropped | **3** | **not cosmetic** |
| `NON_PY` — Markdown/JSON, needs a text normalizer | 11 | undecided today |
| `TARGET_ABSENT_AT_MINT` | 2 | see §3 |

**T1 fires on 0 of the 35 decidable tasks. T3 (generated path) fires on 0 of
48.**

So 35 of 48 tasks have had the named threats ruled out *by measurement*, and
remain quarantined anyway — waiting for a coincidence that 400 commits did not
produce.

Two counting errors of my own, both corrected before this was written:

- The first run reported 35 tasks as `NO_BLOBS`. That was a `text=True`
  subprocess decoding blobs with the console codepage and dying on the first
  non-UTF-8 byte — a measurement of my decode bug, not of the corpus.
- The second still lumped 34 together. `git show parent:file` failing usually
  means the file was **added** by that commit, which does not make T1 unknown —
  it makes T1 *impossible*. Separating the cases moved 32 tasks from "unknown"
  to "decided".

## 3. Two tasks whose provenance cannot be verified

`mint-commit-1a1436dee948` (target `daedalus/orchestration/ikarus/shell.py`) and
`mint-commit-b1e7bf80890a` (target `daedalus/orchestration/verifier.py`) name
targets that **did not exist at their own `minted_at_sha`**. Both paths are
post-relocation; both mint SHAs predate the commits that created them
(`e6b8bc26`, `7aa3348e`), and this is consistent with the 2026-09-03 history
rewrite.

Their labels may well be fine. The point is narrower and worth keeping: **their
provenance cannot be checked**, and a corpus entry whose provenance cannot be
checked should say so rather than sit indistinguishable from 46 that can.

## 4. What follows — and what deliberately does not

The measurement supports replacing a coincidence-based proxy with direct
detection of the three named threats: a task whose T1/T2/T3 have each been
checked and found absent has had *its stated dangers ruled out by evidence*,
which is strictly more than three unrelated commits colliding by luck.

Stated as sharply as it deserves, because it is the limit of the argument:
**direct detection covers the three NAMED threats only.** Recurrence, in
principle, guards against unnamed ones too. In practice it fires never, so it
guards nothing — but "covers the named threats" is a smaller claim than "is
safe", and a replacement must carry the smaller one.

Therefore any such route must be a **second, separately named witness**, with
the witness kind recorded on the task, so a consumer can filter to one kind.
Silently redefining what `confirmations` means would make every historical
count ambiguous.

**Not done in this document:** the change itself. This measures the case for it.

## 5. What this does not claim

- Not that the 48 tasks are correct. Threat-absence is not label-correctness.
- Not that promoting them would fix Gate 3's primary tier. Complete separation
  (`G3_ORIGIN_EFFECT_PREREGISTRATION` §1) is a separate barrier.
- Not a promotion. Nothing here moves a task out of quarantine.

Iron Plan: EXPERIMENT
Iron Gate: 1
Evidence: `experiments/g3_mint_threats/probe.py` output, reproduced above
