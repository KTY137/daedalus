---
title: Night shift 2026-07-30
type: finding
status: verified
updated: 2026-07-30
---

# Night shift 2026-07-30

Overnight run: 170 external DeepSeek agents against this repository through the
harness's own external lane, under the egress fence. 244 reports, 1,226 claims,
1,056 clusters. One critical defect found by *building*, not reviewing.

## What was run

| Wave | Agents | Model | Rights | Outcome |
|---|---|---|---|---|
| Scan + research | 40 | deepseek-chat | read | 40/40 completed |
| Audit + cross-module | 100 | deepseek-v4-pro | read | 100/100 completed |
| Lab experiments | 10 | deepseek-v4-pro | read+write | 5 new, 5 modified, **3 destroyed** |
| Verification cascade | 50 | deepseek-v4-pro | read | 50/50 completed |
| Synthesis | 25 | deepseek-v4-pro | read | 25/25 completed |
| Implementation + refutation | 20 | deepseek-v4-pro | read+write | run with fixed write path |

## The defect: content substitution in rewrites

Three modules silently destroyed. Agents were asked to rewrite one file; they
returned another. A `daedalus/shift.py` rewrite request returned a test module.
Both guards were blind: truncation (test module was **39% larger**), and
elision-marker (nothing was omitted, just the wrong file).

Fixed in `daedalus/providers/deepseek.py`: bind output to path in the request
itself, and refuse rewrites where fewer than half of the original top-level
definitions survive. Validated: 5 of 5 against the failure corpus, 235 existing
tests still pass.

## Two more holes in the same gate

**Invented APIs.** With substitution fixed, twenty agents wrote seven test
modules against source they had been given. **0 of 26 tests passed**; three
files would not even import, naming `daedalus.linting`, `ShiftManager` and
`daedalus.wiki_vault` — none of which exist. `compileall` passed them all,
because a syntax gate cannot distinguish code from plausible-looking code.
Fixed with static first-party import resolution: 4 of 7 files now refused,
**0 false positives across 336 real repository files**.

**`writable=True` removes the reporting channel.** Eight agents were told to
review and not edit. All eight rewrote their subject and **all eight returned
zero findings**. Not disobedience: `_run_rewrite` hard-codes `"risks": []` and
`"todos": []` and parses the reply only for `{"content": ...}`, so a writable
agent has no way to report anything. The flag is a mode switch, not an added
capability, and the caller is not told. The wave was worthless and the error was
mine for not reading the flag.

The one control that *did* hold was a capability: `budget.py` was refused to an
external lane as a `high_risk_path`, while the prose brief did nothing.

## Retracted: the "concurrency bug" that was mine

I reported that budget accounting stops under concurrency — forty concurrent
calls, zero ledger entries. The observation was real; the diagnosis was wrong.
Measured: without `install_process_guard()` 76→76 entries, with it 76→78. The
guard patches `urlopen` process-wide and is installed at the product entry
points; the fan-out scripts constructed the provider directly and never
installed it. Roughly 170 unpriced API calls before anyone noticed.

A plausible pattern is not a mechanism. Kept in the record rather than deleted.

## What this settles about the external lane

Five substantive new modules that import and expose real APIs — and zero working
tests. **Use it to draft; never to verify.**

## Corroboration: agreement was unavailable

Largest group of agents saying the same thing: **two agents**. The fan-out
(nearly every agent got different code) meant almost no opportunity for two to
agree. Confidence has to come from *checking* findings, not counting them.

## Cascade verdict

When round 2 was given source and asked to refute, it did:

| Verdict | Count |
|---|---|
| CONFIRMED | 74 |
| REFUTED | 21 |
| UNDECIDABLE | 264 |

Of 95 checkable claims, **22% were false** — including "budget raises NameError"
and "containment leaks handles". REFUTED is the verdict that justified the
cascade cost.

## Related

**Picking this up in a new session? Start here:**
[docs/HANDOFF_2026-07-30_NIGHT.md](../HANDOFF_2026-07-30_NIGHT.md) — what can be
lost, what order to do things in, and the list of claims that were checked and
found false so nobody re-schedules them.

Full detail: [docs/research/NIGHT_SHIFT_2026-07-30.md](../research/NIGHT_SHIFT_2026-07-30.md)

[[Feature backlog]] — the harvest from 29–30 July.
[[Graph delta as fitness]] — the concurrent measurement that ran the same night.
