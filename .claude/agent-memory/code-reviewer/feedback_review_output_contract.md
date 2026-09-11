---
name: feedback-review-output-contract
description: How the Daedalus owner wants code reviews delivered — severity-ranked, file:line, verified vs suspected labelled, repo's own scripts run with raw tails, "nothing serious" allowed
metadata:
  type: feedback
---

Deliver reviews as: findings ranked by severity, each with `file:line` and a concrete
failure input; an explicit **verified (traced/ran)** vs **suspected (could not confirm)**
label on every claim; the repository's own scripts actually run with their raw tail
quoted; and a plain short "it is sound" when it is. No report `.md` files — the answer
is the message.

**Why:** the owner's global constitution (`~/.claude/CLAUDE.md` §8) treats an unrun check
as failed, not "probably okay", and `AGENTS.md` lists "unverifiable claims" as a
release-blocking defect. A review that blurs traced-and-confirmed into plausible-sounding
is worse than no review here.

**How to apply:** when handed a commit to review, run `apps/web` scripts / `uv run --frozen`
suites yourself rather than repeating the author's numbers; separate "the mechanism is in
the code" from "I saw it fire". If a suite cannot run (needs a build artifact, a live API,
a toolchain absent from the host), say UNVERIFIED and name what would run it. See
[[project-daedalus-lane-hazards]].

**Repair tasks carry two extra obligations** (2026-09-11, PR #370, stated by the owner and
worth pre-empting next time):

1. **Mutation-prove every new guard.** Disable the code each guard protects, one at a time,
   run the suite, quote the raw tail, restore. A guard that passes with the fix removed is
   not evidence — and the owner asks for this explicitly rather than trusting a green run.
2. **When handed numbered options, pick and justify.** "The reviewer named three options;
   pick deliberately and say which and why" — a silent choice reads as not having noticed
   the others.

Also: name defects you were told NOT to fix in the commit message as known-and-deferred, so
the record does not imply a clean file.
