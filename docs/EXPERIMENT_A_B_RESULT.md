# A/B result — the machinery did not pay for itself on this task

Run 2026-07-28/29. Pre-registration: `docs/EXPERIMENT_A_B.md`. Spec, hidden
suite, runner, scorer and blinding were committed **before** any result existed
(`2bf36ae`, `6476cdf`).

## The headline, stated as plainly as a win would be

**Both arms produced functionally indistinguishable work. Arm B spent 23% more
billable tokens and 52% more wall-clock to get there.**

Pre-registration §7 named two falsification conditions for Arm B. The second one
is met:

> *"Or: the gate outcome is the same for both, and the extra machinery bought
> only process."*

Gate outcome identical, hidden-conformance score identical, per-test failures
identical, rework identical, forbidden-file compliance identical. **On this task,
the machinery bought process and nothing measurable else.**

The first condition (more tokens **and** more wall-clock **and** more human
interventions) is **not** met: human interventions were zero in both arms, so
"more" is false. It was equal, not worse.

## What was actually compared — read this before quoting the result

**This was NOT "full Daedalus", and calling it that would be the most
misleading sentence available.** Codex made this correction during design review
and it is right. Pre-registered Arm B is *distilled context + TaskAttempt in an
isolated worktree + gates + cross-vendor council review + human promotion*. What
ran was:

| | Arm A | Arm B |
|---|---|---|
| Model | `sonnet` | `sonnet` (same) |
| Spec | `runs/ab/SPEC.md` | identical bytes |
| Base state | PnP_App @ `f894b3f`, own git worktree | identical |
| Tools | full | full |
| Context | free rein over the repo, incl. the 3592-line architecture doc | **DSS-distilled bundle, 7623/8000 tokens, 5 files** |
| Gate | told to run it itself | **run for it, failures handed back (≤2 repair rounds)** |

So the honest label is **"DSS + enforced gate feedback versus self-directed
Claude"**. TaskAttempt, council review and human promotion were not in the loop.

Why not: a plan-only `daedalus offload` on this objective returned
`provider: claude_cli`, `eligible: false`, `action: "senior"` — for a high-risk
greenfield write, the router **escalates to the senior instead of executing**.
"Arm B = `daedalus offload --live`" would therefore have measured a system
declining to run. That routing decision has a large side benefit: both arms ran
the same model, so this measures **process, not model**. Had Arm B run on
qwen2.5-coder:7b against Arm A's Claude, nothing here would have been
interpretable.

## Numbers

| Axis | Arm A (self-directed) | Arm B (DSS + gate feedback) | Δ |
|---|---|---|---|
| Gate (`tsc --noEmit && vite build`) | **pass**, first try | **pass**, first try | — |
| Hidden conformance | **21/23** | **21/23** | — |
| …excluding contested tests | 20/21 | 20/21 | — |
| Per-module | scope 4/4, objectRef 4/4, viewRecipe 4/4, visibility 6/6, deepLink 3/5 | identical | — |
| Failing tests | the same two | the same two | — |
| Output tokens | 33,845 | 39,194 | **+15.8%** |
| Billable tokens | 99,971 | 122,592 | **+22.6%** |
| Cache reads | 1,755,377 | 2,480,149 | +41.3% |
| USD | $1.4335 | $1.8451 | **+28.7%** |
| Wall clock | 358s | 545s | **+52.2%** |
| Turns | 1 | 1 | — |
| Rework | 0 | 0 | — |
| Human interventions | 0 | 0 | — |
| Forbidden-file edits | none | none | — |
| Tests written | **none** | **none** | — |

**Tokens per accepted outcome** — the pre-registered headline metric — is
99,971 for Arm A and 122,592 for Arm B, both denominators being 1. Arm A wins it.

## The caveat that matters most

**Arm B's central mechanism never fired.** Both arms passed the gate on the
first pass, so the repair loop — the thing that was supposed to make Arm B worth
its cost — had nothing to repair. This run therefore measures Arm B's *overhead*
in full and its *benefit* not at all.

That is not a defence of Arm B. It is a statement about what this experiment can
and cannot support: it is evidence that the machinery costs ~23% on a task that
goes right the first time. It is **not** evidence about a task that goes wrong,
which is the case the machinery exists for. A second feature chosen to be
harder — one where a first pass plausibly fails — is the obvious next run, and
until it exists this result should not be generalised.

## Blind judging

Protocol per §4: artifacts copied to `X/` and `Y/` under a random mapping sealed
before anyone read them, process-naming traces stripped, verdicts written
independently. **Mapping: X = Arm B, Y = Arm A.**

**Missing voices, named rather than papered over:** Opus 4.6 and Kaya did not
judge. The pre-registration wanted four judges; two verdicts exist. "Two judges
split" is a much weaker sentence than "the judges agreed", and it is the true one.

### Claude (built Arm B's machinery — the conflicted judge)

Preferred **Y**, narrowly, on engineering: full `ObjectRef` identity survives a
round trip, strict trailing-segment rejection, an explicit header stating the
judgment call and its cost. Guessed **X = A, Y = B**.

**The guess was wrong.** And the interesting part is the direction: I preferred
the artifact I *believed* was Arm B, and it turned out to be Arm A. My conflict
of interest would have pushed me toward Arm B, I followed that pull, and the
blinding sent it to the wrong arm. That is the blinding working exactly as
designed on the judge most likely to need it.

### Codex (OpenAI, different vendor)

Preferred **X**, narrowly — which is Arm B.

**Codex disqualified its own guess, unprompted:** it contaminated the blind while
locating the files (receipt metadata named the arms) and said so, refusing to
present hindsight as prediction. That is the correct call and it is worth
recording as a process win. But the contamination taints its *qualitative*
verdict too, not only its guess: a judge who knows which artifact came from the
system under test cannot be scored as a blind preference for it.

**So the only uncontaminated qualitative verdict in this experiment preferred
Arm A.**

## What blind review found that 23 mechanical tests could not

This is the part worth keeping regardless of the cost numbers.

1. **Arm B (X) corrupts stable identity in deep links.** It builds links from
   `slug ?? id` and reparses the path form with a hardcoded placeholder type,
   so a parsed ref can never satisfy `sameObject` against the real one — in a
   module whose entire spec rule is *"IDs remain stable across renames"*.
   Invisible to a suite whose round-trip fixtures carry no slug.
2. **Arm A (Y) widens the canonical form.** `formatObjectRef` emits
   `type:id@revision`, where the brief says the canonical form is built from
   type and id **only**. My test compared two refs at the *same* revision, so
   the extra field never showed. My instrument's blind spot, not its cleverness.
3. **Both violate "export exactly these names"** — X exports `RECIPE_IDS`, Y
   exports `RECIPE_IDS` and `SLUG_PATTERN`. No test checked the export surface.
4. **Arm B promotes the first unrecognised query parameter into an object**, a
   collision waiting to happen. Nothing tested unspecified query keys.
5. **Divergent slug grammars** (X lowercase/hyphen only; Y also uppercase and
   underscore) with no authority in the brief to settle it.

Five real findings, none of which the 23 tests could see. This is the strongest
argument in the whole run for cross-vendor review existing at all — and it is an
argument for *review*, not for Arm B's machinery.

## Defects in the instrument, disclosed

- **The hidden suite initially scored `deepLink` 0/5 for BOTH arms.** Cause: both
  arms wrote `from "./scope"`, idiomatic TypeScript that `tsc` and Vite resolve
  and that both gates accepted; Node's native type-stripping loader demands an
  explicit extension. I was grading them in a configuration the product never
  runs — §5's "measuring a broken arm", and the same defect class this repo has
  catalogued repeatedly. Fixed by a mechanical, arm-neutral import rewrite
  applied identically to both (`runs/ab/score.py: materialise`). Scores moved
  18/23 → 21/23 for both; the tie was unaffected.
- **Two tests are not fairly derived from the brief**, per Codex's design review,
  and are excluded from `excluding_contested`: one asserts `place + tisch → null`
  from a mapping list the brief calls *required* rather than exhaustive; the
  other requires the document's `recipe=tactical` URL to parse while `tactical`
  is not a `RecipeId` and alias semantics are undefined. **Both arms fail the
  second one identically** — which is evidence the ambiguity is in my brief.
- **23 tests are not 23 equal requirements** (ten recipe mappings share one
  test), so `runs/ab/receipts/conformance.json` reports per-test and per-module
  results and the ratio should not be quoted alone.
- **`rework` is not comparable across arms.** The pre-registration defines it as
  discarded attempts; the runner counts Arm B's harness-driven repair turns and
  cannot observe Arm A's internal iterations. Both were 0 here, so nothing turns
  on it, but the axis is process-specific and should not be compared.

## The finding I did not expect, and the one I would act on first

**Neither arm wrote a single test.** Both were told the gate was
`tsc --noEmit && vite build`, and both optimised precisely for it.

That is not a fact about the models. It is a fact about my brief: **I specified a
gate that cannot fail for a wrong-but-compiling implementation, and I received
two wrong-but-compiling implementations with no tests.** Both arms answered the
question actually asked.

It is also the same lesson this repo learned three times in one day on its own
safety code — a green gate is not evidence — arriving from the opposite
direction. The fix is not more machinery around the model. It is a gate that can
fail for the right reason.

## Status

**N = 1. This is an anecdote, and it is recorded as one.** A pilot whose main
achievement is proving the measuring harness works — and finding two defects in
that harness while doing it. §5 said to expect exactly that.

What it does support: on a spec-dense greenfield task that goes right the first
time, DSS distillation plus enforced gate feedback cost ~23% more tokens and
~52% more wall-clock, and produced work no measurement in this experiment could
distinguish from a self-directed run.

What it does not support: any claim about Daedalus as a whole. TaskAttempt,
council review and promotion were never exercised, and neither was the repair
loop.
