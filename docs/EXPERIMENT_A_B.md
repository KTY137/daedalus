# The A/B: does Daedalus earn its cost?

Status: **designed, not run.** Pre-registered — this document is written before
any measurement so the criteria cannot be chosen after seeing the numbers.

Owner decision required before running: the feature (§2) and the go/no-go on the
blockers (§6).

## 1. The question

One large, well-specified feature, implemented twice:

- **Arm A — crew only.** Claude subagents, no Daedalus machinery. Plain file
  edits, the model's own judgment, whatever tests it chooses to write.
- **Arm B — full Daedalus.** Distilled context, TaskAttempt in an isolated
  worktree, gates, cross-vendor council review, human promotion.

Both arms get the same objective text, the same repo state, and the same
acceptance criteria. Neither is told which arm it is.

The question is NOT "which produces code". It is: **does the machinery pay for
itself?** A slower, more expensive arm that produces something correct and
maintainable has won. A cheap arm that produces something that fails on contact
has not.

## 2. The feature

Must satisfy four properties, or the result is uninterpretable:

1. **Large enough that process matters.** A one-file change is decided by the
   model, not by the harness around it. Target: something that touches 5+ files
   and needs a decision the spec does not make for you.
2. **Specified, not invented.** Both arms must be building the same thing, or we
   are comparing interpretations rather than methods.
3. **Verifiable without a human.** There must be a gate that runs: a build, a
   test suite, a rendered screenshot compared to a reference. If "is it good"
   can only be answered by opinion, the quantitative half of this experiment
   does not exist.
4. **Greenfield or near-greenfield**, so neither arm benefits from code the
   other wrote.

Candidate: a slice from `PnP_App/design/06-giga-product-architecture.md` — it has
a route inventory, a shared object/view-recipe model, and named delivery slices
with validation gates. `design/visual-lab/` already proves the stack builds
(React 19 + Vite, TypeScript and production build pass), so `npm run build` is a
real gate on day one.

**Not yet chosen. Kaya picks the slice.**

## 3. What gets measured

Recorded per arm, mechanically, into a JSON receipt:

| Axis | How |
|---|---|
| Tokens in / out | Per agent call, summed. Every vendor, including local. |
| USD | Tokens × the rate for the model that actually ran. Local model = 0 but wall-clock still counts. |
| Wall clock | Start to promotable artifact. |
| Human interventions | Every time a person had to answer, unblock, or correct. Count and total human minutes. |
| Gate outcome | Build passes / test suite / whatever §2.3 defines. Pass or fail, not "mostly". |
| Rework | Attempts that were discarded before one was accepted. |

**The headline number is tokens per ACCEPTED outcome**, not tokens. An arm that
burns 3× the tokens and lands on the first try may be cheaper than an arm that is
frugal per attempt and needs four.

Runtime quality, measured on the artifact itself: build time, bundle size,
lighthouse or equivalent if it is a UI, and any perf assertion the spec makes.

## 4. The qualitative half — and why it must be blind

A human-or-model judgment of "which code is better" is worth having. It is also
the easiest thing in this experiment to corrupt, because the obvious judge (the
Claude session that built Arm B) has an interest.

Protocol:

1. Both artifacts are copied to `X/` and `Y/` by a script that assigns the
   mapping **randomly** and writes it to a sealed file nobody opens yet.
2. Identifying traces are stripped: commit messages, receipts, branch names,
   agent-authored comments naming the process, anything that says which arm.
   (A `daedalus-attempt-*` branch name or a council receipt gives it away
   instantly.)
3. Judges write their verdict **independently, before seeing each other**:
   - the live Claude session,
   - Codex (different vendor),
   - Opus 4.6 (different model),
   - Kaya.
4. Each verdict answers a fixed rubric — not "which is nicer": correctness under
   the spec, failure handling, naming and structure, test quality, what it would
   cost to change, and what each one gets *wrong*.
5. Only then is the mapping opened.

A judge who guesses the arm correctly and says so is more informative than one
who pretends not to know. Record the guess.

## 5. The traps this design exists to avoid

- **Order effects.** If the same model runs both arms in sequence, the second
  benefits. Use independent sessions with no shared context, and counterbalance
  if the experiment is ever repeated.
- **Criteria chosen after the fact.** Everything in §3 and §4 is fixed before
  the run. If a new axis looks interesting mid-run, record it and mark it
  exploratory — it does not decide the outcome.
- **N = 1.** One feature is an anecdote. State it as one. A second and third
  feature is what turns it into evidence, and the first run should be treated as
  a pilot that mostly tests whether the harness for measuring even works.
- **Measuring a broken arm.** See §6.
- **Silent human help.** If a person nudges either arm, it counts as an
  intervention, even if it felt trivial. Especially if it felt trivial.

## 6. Blockers — Arm B cannot run today

1. **Open CRITICAL in `cleanup_worktree`.** An independent review reproduced
   deletion of the primary repository against the *patched* code. TaskAttempt is
   the centre of Arm B; running it now measures a system that is being repaired.
2. **`daedalus improve --once` is inert** while the security fix sits
   uncommitted.
3. **The index returns 0 files on `PnP_App`.** Measured: a fresh `build_index`
   on that repo yields nothing, with 25 source and 137 markdown files present.
   Arm B's whole advantage is context; if the context layer sees nothing on the
   target repo, the experiment measures nothing.

None of these are reasons to abandon the experiment. They are the definition of
"ready to run".

## 7. What would falsify Arm B

Stated up front, so a loss is legible as a loss:

- Arm B costs more tokens **and** more wall-clock **and** more human
  interventions, and the blind judges do not prefer its output.
- Or: the gate outcome is the same for both, and the extra machinery bought only
  process.

If that is the result, it is the most valuable thing this project could learn,
and it must be written down as plainly as a win would be.
