# Blind verdict — Claude (the session that built Arm B's machinery)

Written after reading `blind/X` and `blind/Y` and BEFORE reading Codex's verdict
or opening the sealed mapping. My conflict of interest is on the record: I built
the thing Arm B is testing, so treat this verdict as the most suspect of the two.

## 1. Correctness under the spec

Both implement all five modules with the required exports and both pass the
project gate. Both fail the same two hidden tests, for the same reasons, and
neither failure separates them.

**One real spec deviation, and the hidden suite could not see it.**
`SPEC.md` says the canonical text form "is built from `type` and `id` only".

- **X** — `formatObjectRef` returns `` `${type}:${id}` ``. Complies literally.
- **Y** — returns `` `${type}:${id}@${revision}` ``. Revision is always emitted.

Y is deviating from the word "only". My test compared two refs that differed
only in `slug` **at the same revision**, so the extra field was invisible to it.
That is my instrument's blind spot, not Y's cleverness — and it is exactly the
class of defect this project keeps cataloguing: a test that pins the property it
was thinking about rather than the property it stated.

The deviation is not free either way. X pays for compliance by losing `revision`
through every deep link (it round-trips to 0). Y pays for fidelity by widening
the canonical form the spec called minimal. **I judge Y's the better engineering
and the worse compliance**, and I would want that argued rather than silently
merged.

## 2. Failure handling

Both honour "returns null, never throws" everywhere it is demanded, both wrap
`new URL` in try/catch, and both validate `recipe` against the real `RecipeId`
union rather than accepting any string.

Both fail my `malformed input` test on exactly one input: `"u/eron/c/x"`, with no
leading slash. `new URL(url, base)` resolves it to `/u/eron/c/x` and both then
parse it happily. Whether a scheme-relative path is "malformed" is a judgment
the brief never makes. Identical behaviour, so it separates nothing.

Y is stricter in one place that matters: `if (idx !== segments.length) return null`
rejects trailing unrecognised segments outright. X only rejects them in the
object branch, so some trailing shapes slip through.

## 3. Naming and structure

Both keep the brief's module boundary exactly; neither invented one. Both
factored a private scope-prefix parser out of `parseDeepLink` with an almost
identical comment explaining why `parseScope` could not be reused — genuinely
convergent, not copied.

One blemish in X: `deepLink.ts` mixes `from "./scope"` and
`from "./objectRef.ts"` in adjacent lines. Cosmetic, but it is the kind of
inconsistency that survives forever.

## 4. Test quality

**Neither wrote a single test.** Both were told the gate was
`tsc --noEmit && vite build`, and both optimised for exactly that. One of them
wrote a scratch `_smoke.ts`, exercised it, and deleted it before finishing —
tidy, but it left no regression behind either.

This is the sharpest thing the run has taught me and it is about my brief, not
about them: **I specified a gate that cannot fail for a wrong-but-compiling
implementation, and I got two implementations with no tests.** Both arms
answered the question I actually asked.

## 5. Cost to change

Y, clearly. `RECIPE_ID_SET` is a `Set` built once from `RECIPE_IDS`;
`SEGMENT_TO_WORKSPACE`/`WORKSPACE_TO_SEGMENT` are paired `Record`s; a fifth
workspace is two entries and nothing else. X needs the same two entries **plus**
a revisit of `shouldUseObjectPath`, whose condition hard-codes `welt`.

Y's unified object encoding is also the cheaper long-term shape: one path form
to maintain instead of a pretty form and a query form whose object key is the
object's own type.

## 6. What each gets wrong that the other gets right

- **X gets right:** literal fidelity to the document's two URL shapes, and a
  canonical `ObjectRef` form that matches the brief's word "only".
- **X gets wrong:** loses object `type` on the path form (hard-codes the
  placeholder `"object"`), so a parsed ref can never satisfy `sameObject`
  against the real one; loses `revision` through every link; mixed import
  extensions; `shouldUseObjectPath` couples URL shape to one workspace.
- **Y gets right:** full `ObjectRef` identity survives a round trip; strict
  trailing-segment rejection; a header comment that states the judgment call and
  its cost instead of leaving it to be discovered.
- **Y gets wrong:** widens the canonical form beyond what the brief said, and
  does it silently enough that my own suite missed it.

**Overall: Y, narrowly, on engineering. Not on compliance.** If I had to merge
one it would be Y with the `formatObjectRef` question reopened.

## 7. My guess

**X = Arm A, Y = Arm B. Confidence: moderate, ~60%.**

The tell: X preserves the architecture document's two URL shapes *literally*,
including the query-keyed-by-object-type form that only appears in one
illustrative example. That reads like something written with the 3592-line
document open. Y explicitly notes the doc's shapes "neither survives a generic
round trip on its own" and unifies them — the move of something reasoning from a
brief rather than from the source corpus.

The counter-argument I cannot dismiss: Y's greater thoroughness could just as
easily be the free-rein arm having more room, and I may be pattern-matching Y's
carefulness onto the arm I want to have won.

## 8. Is there a difference the conformance suite could not see?

**Yes, and it cuts against Arm B if Y is Arm B.** The `formatObjectRef`
deviation in §1 is a real divergence from the brief that scored 21/23 either
way. A mechanical tie hid a genuine disagreement about what the canonical form
is — which is an argument for blind review existing at all, and simultaneously
an argument that my suite is weaker than its number suggests.

The other invisible difference is `shouldUseObjectPath` hard-coding `welt`. No
test in the suite builds a link for an object in `vorbereiten`, so a real
coupling defect sat there unmeasured.

**And the honest headline: on everything I actually measured, the two arms are
indistinguishable.** Same gate result, same 21/23, same module breakdown, same
two failures, same zero tests, no forbidden edits either side. Arm B spent 23%
more billable tokens and 52% more wall-clock to arrive there.
