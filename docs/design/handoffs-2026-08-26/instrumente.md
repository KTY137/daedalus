# Instrumente — handoff notes, 2026-08-26

Everything below is out of my lane (`Decision.tsx`, `StatusLine.tsx`,
`instruments.css` only). Recorded here instead of touched.

## 1. To Rahmen / Ikarus — the decision card's hero slot

I shrank the quiet states (`!loaded`, `!current`) to a single borderless line
(`.decision.quiet`, now `role="status"`, flex row, ~one text-line tall instead
of a padded bordered card with its own eyebrow). That's the ceiling of what I
can do from inside `Decision.tsx` — the card still *mounts* in `talk-main`'s
top slot in `Cockpit.tsx` (~line 360, 527) and its layout comes from
`shell.css`'s `.talk-main { display:flex; flex-direction:column; gap:var(--u4); }`
(~line 172), both outside my lane.

Measured live: `/api/drafts` takes ~12–14s to resolve on this machine (confirmed
again this session — the existing code comment on line ~158 already knew this).
For that whole window, and for however long there happen to be zero pending
drafts, the quiet line still occupies a real row above the conversation, with
a `gap: var(--u4)` reserved below it either way.

Recommendation, for whichever of you owns that call: the quiet states should
not need a slot in `talk-main` at all — either render `<Decision/>` inside
`.talk-side` unconditionally (it already reads fine as a compact line next to
"Auf der Karte") and only hero-promote it into `talk-main` when `current` is
set, or have `Cockpit.tsx` skip the gap/slot entirely while `Decision` is
quiet. I did not make this change myself since it means moving where the
component mounts, and that's `Cockpit.tsx` composition, not this file.

## 2. To Ikarus — `Conversation.tsx` threw during this session's verification

Observed via Playwright console while testing the neighbouring `Decision`
card (unrelated to anything I touched):

```
ReferenceError: pressProps is not defined
    at Conversation (.../src/cockpit/Conversation.tsx:860:25)
ReferenceError: SendGlyph is not defined
    at Conversation (.../src/cockpit/Conversation.tsx:868:49)
```

Both cleared on a full reload and recurred on the next HMR cycle a few
minutes later, so this reads as an in-progress edit rather than a landed
regression — flagging in case it's still open when you read this. One
concrete visual side-effect I caught in a screenshot: the composer's input
area rendered as a narrow native stepper control instead of the text field,
while a real pending decision was showing fine beside it.

## 3. To Rahmen — floor audit, at this session's HEAD

`node tools/audit.mjs --base http://127.0.0.1:5173 --widths 1440,1280,1024,900 --themes leitstand,nachtfenster,kammer`
reported 24 theme/page/width combinations below the floor. Every failure was
in classes that live in `Cockpit.tsx` / `shell.css` (`span.scope-eyebrow`,
`span.viewswitch-label`, `button "Karte"`/`"Gespräch"` at 46–71×38px,
`kbd.chrome-kbd`) — none in `.decision-*`, `.status-*`, or `.dot*`. Re-running
scoped to just those selectors turned up nothing, so this is not something my
files are contributing to; noting it since it means the shared floor is
currently red and someone should re-check before the round closes. (A second
full audit run stalled entirely — `page.waitForSelector('.stage-node')`
timed out after 180s on the map page, most likely a concurrent edit in
flight on the stage; re-run once things settle.)

## 4. To Material — `data-decision` is documented but not wired

`cockpit.css`'s own header comment (line 9–10) lists `data-decision` among the
attributes that switch composition on `<html>`, alongside `data-chrome`,
`data-chat`, `data-material`, `data-stage`. `theme/apply.ts` sets all of those
*except* `data-decision` — grepped the whole tree, it's written nowhere. I
didn't need it: both decision-card shapes in this round style themselves off
the component's own state (`.decision` vs `.decision.quiet`), not off a theme
switch, so nothing here depends on it. Flagging only because a comment
promising a lever that doesn't exist is exactly the kind of prose-without-an-edge
this codebase has been bitten by before — either wire a real
`composition.decision` field through `types.ts`/`apply.ts` if a theme is meant
to affect the card's composition, or trim the comment.

## 5. Observation, not acted on — `/api/drafts` is not project-scoped

`getDrafts()` in `api.ts` calls plain `/api/drafts` with no `project` param,
and the backend returns every draft across every project regardless (checked
directly against :8765). Live in this session, `Decision.tsx`'s "427 offen"
count and its top card are drawn from the *global* draft pool, not from the
`agent_env` project the rest of the page is scoped to — confirmed against the
raw API response, several dozen of those pending rows belong to a `scribe`/
`helper-dev` fixture project, not this repo. That's a real product-correctness
question (should a project's decision queue really include another project's
drafts?) but it's a backend/`api.ts` contract question, both outside my lane
and outside a design pass — recording it here rather than guessing at a fix.
