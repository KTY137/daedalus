# Cockpit round, 2026-08-26 — the shared brief

Iron Plan: ALIGNED · Iron Gate: 0 (the cockpit is a read surface over the
canonical kernel; nothing in this round adds an effectful entrypoint).

Six lanes work on `apps/web` at the same time. This file is the part of the
brief they share. Read it before touching a file.

## Where this starts

The floor is already met and was re-measured at the start of this round:

    node tools/audit.mjs --base http://127.0.0.1:8765 --widths 1440,1024 \
      --themes leitstand,nachtfenster,kammer
    → 0 theme/page/width combinations below the floor
      (contrast, 44px targets incl. SVG, 11px type, no sideways scroll)

So this round is **not** about the floor. Nothing below is a bug report; it is
a design brief. Contrast, target size, type floor and overflow must still pass
when you are done — they are the price of entry, not the work.

Before-shots of the two pages in two themes:
`docs/design/prototypes/cockpit-2026-08-26/before/`.

## What is actually wrong, measured from those shots

**The map page.** The upper-left third of a 1440×900 canvas is empty while the
graph sits centred below it. Fifteen node cards are drawn at one weight, one
size, one border, one type size — while the payload behind each carries
`fan_in`, `loc` and a heat score spanning 134…256 in the hot list alone. Edges
are identical hairlines with elbow routing that pass behind the cards and
carry neither direction nor weight. There is no depth of any kind. The zoom
control is three unlabelled boxes with a percentage floating outside them.

**The conversation page.** The invitation, the thread bar, the context line and
the composer stack against the top edge and leave roughly 60 % of the page
empty below the send button. The thread bar puts an unstyled native `<select>`,
a bare "Neuer Verlauf" label and a right-flushed "Neuer Chat" button on one
line with 350 px of nothing between them. "Was würde gelesen?" and "Auf der
Bühne: …" float as bare grey text. The decision card takes the top slot on the
page to say "Entwürfe werden gelesen …". Vertical gaps between the stacked
blocks measure 30, 40, 25 and 30 px — four values, no rhythm.

**Motion.** `src/motion/` is a complete, documented, tested vocabulary — two
tiers, a spec that asserts the tier boundary — and **the cockpit imports none
of it.** The only importer in the tree is a classic-surface component. A view
switch, a palette, two drawers and an arriving message all cut instantly.

## The direction, from the owner's standing rulings

- Chat and graph are the joint hero. The trio IA is lifted; Knowledge is an
  inspector, not a standing panel.
- The graph is spatial — planes as depth, parallax on nodes, camera calm —
  with the ordered four-plane column layout kept as an alternative
  representation of the same nodes, selection carried across the toggle.
- Glass is a material for at most two surfaces. Skeuomorphism never.
- Every value comes from a theme token. A hard-coded colour, radius or type
  size is a value one of the six designs cannot reach, and it is a defect.
- React Bits (`shadcn` MCP, `@react-bits` registry) is the default source for
  a structural component — one that carries navigation, a control, a list or a
  transition the product needs. Backgrounds and text effects on facts are
  garnish and read as AI-generated. Never vendor React Bits source into this
  repository (MIT + Commons Clause).
- Reviewers have rejected four rounds for the same tells: fake affordances,
  doctrine pasted into chrome, demo components as garnish, metric strips in
  disguise, type too small, sentence case broken.

## What "professional" means in this round

An affordance that does nothing is worse than an absent one. A control that
reports a state must report the state it actually has, including "unknown".
Data the payload already carries should be visible in the drawing rather than
in a caption. One idea per element. The bold move goes in one place per lane
and everything around it stays quiet.

## Lanes and file ownership

`apps/web/src/cockpit/cockpit.css` is now seven modules and the index that
orders them. **The order in `cockpit.css` IS the cascade** — several rules tie
on specificity and are decided by position. Do not reorder the imports.

| Lane | Owns |
| --- | --- |
| Kartograph (opus) | `cockpit/Stage.tsx`, `cockpit/layout.ts`, `cockpit/stage.css`, new files under `cockpit/stage/` |
| Ikarus (opus) | `cockpit/Conversation.tsx`, `cockpit/ContextPlan.tsx`, `cockpit/conversation.css` |
| Rahmen (sonnet) | `cockpit/Cockpit.tsx`, `cockpit/shell.css`, `cockpit/overlays.css`, `cockpit/responsive.css` |
| Instrumente (sonnet) | `cockpit/Decision.tsx`, `cockpit/StatusLine.tsx`, `cockpit/instruments.css` |
| Material (sonnet) | `theme/presets.ts`, `theme/apply.ts`, `theme/types.ts`, `cockpit/materials.css` |
| Bewegung (sonnet) | `motion/*`, `cockpit/Settings.tsx`, `cockpit/settings.css`, `theme/ThemeStudio.tsx`, `theme/studio.css` |

Shared, and therefore **read-only for every lane**: `cockpit/cockpit.css`,
`cockpit/graph.ts` (additive only — the four exported functions keep their
signatures), `api.ts`, `types.ts`, `main.tsx`, `App.tsx` and everything under
`components/`. Need a change in someone else's file? Write it to
`docs/design/handoffs-2026-08-26/<yourlane>.md` and keep going.

## House rules

1. **Do not commit and do not stage anything.** Several agents share one index;
   a commit here takes someone else's half-finished file with it. The
   coordinator commits at the end, by pathspec.
2. **Do not run `npm run build`.** It writes a shared `dist/`. Typecheck with
   `npx tsc --noEmit` (read-only) as often as you like.
3. One dev server serves everyone at **http://127.0.0.1:5173** (proxying the
   API on 8765). Point Playwright at it. Do not start another.
4. Verify what you changed by looking at it. `node tools/shoot.mjs --base
   http://127.0.0.1:5173 --out <your own folder> --themes <two>` and read the
   PNG. A claim about how something looks that was not looked at is not
   evidence.
5. Scratch files go in the session scratchpad **prefixed with your lane name**.
   Parallel lanes have swapped files through generic names before.
6. Writing files from Python on Windows: pass `newline=''` or use `write_bytes`,
   or a 19-line change lands as a 4000-line CRLF diff.
7. German is the interface language of this app. Match the existing voice:
   plain, declarative, sentence case, no exclamation, never chirpy. The copy in
   this codebase is unusually good — read a neighbouring string before writing
   a new one.

## Errata: what the instruments in this round could not see

Recorded as they were found, so a later round does not read a green run as a
guarantee it never was.

**`tools/audit.mjs` measures contrast against ANCESTORS only.** Its `backdrop()`
walks `parentElement` compositing every translucent background onto the one
below. A fill painted by a *sibling* — an absolutely positioned pill behind a
label, say — is invisible to it, so text over that fill is scored against
whatever is behind them both. Found on 2026-08-26 when the Rahmen lane's new
view-switch pill put the accent fill on a sibling of the label: the audit
reported the run as failing (it saw the wrong, darker backdrop) and the lane
fixed the markup so the pill wraps the label instead. That is the right fix for
the markup, and the tool's blind spot is unchanged: **the same shape could just
as easily produce a false PASS.** The instrument can currently only be trusted
where the paint is an ancestor of the ink.

**The drafts count was not measured by anything.** `/api/drafts` returned every
project's drafts and the cockpit displayed the total under whichever project
was selected — 427 pending shown under `agent_env`, which owns none. No test,
audit, or shot caught it in four review rounds; a lane found it by reading the
data flow. `tests/cockpit.spec.ts` already checks drawn nodes, palette offers
and the status line against `/api/structure`, but the decision card was outside
what it compares. Fixed at the source with three tests in `tests/test_drafts.py`;
the gap it points at is that a per-project honesty check has to name every
surface that shows a count, not only the ones someone thought of.

## Blockers this round measured but did not fix

**`/api/structure` emits one plane, so the four-plane view cannot be built.**
`StructureGraphNode` carries `id`, `fan_in`, `loc`, `score`. No node or edge
says which of Code/Type/Data/Knowledge it belongs to, and every drawable node
is a Python module. The owner's ruling asks for the ordered four-plane column
layout as an alternative representation; what shipped is an ordered view over
the code plane, whose columns are *relation to the focus* (Importeure, Fokus,
Importe, Zweite Ebene) sorted by heat — and the interface says so in words,
under the toggle, so it cannot be mistaken for the four-plane view. Material's
`--plane-1..4` tokens exist and have no consumer until the endpoint emits a
plane. The blocker is upstream.

**`/api/runtimes/status` costs more than its own client timeout.**
Measured 2026-08-26: 16.6s with the box under load, **28.0s with the box
quiet**, against `request()`'s 20s default. It probes the installed runtimes
by launching each CLI to ask its version, so it is slow by construction. Two
surfaces silently lost content: the settings reachability list rendered zero
rows (`tests/cockpit.spec.ts` "settings names the brain …" fails on it), and
the conversation's runtime picker had nothing to offer. Fixed on the client by
giving that one call a 45s ceiling that matches the measurement. **Making the
probe cheap is a backend change and is not done** — a version probe that costs
half a minute is the actual defect.

It also DEGRADES with use. Measured the same evening on an otherwise quiet
box: **28.0s before the Playwright suite ran, 36.1s after it**, while
`/api/projects` stayed at 1.1s throughout. So the cost is specific to the
probe (it launches each CLI) and grows with the number of times it has been
called. That is why two tests in `tests/cockpit.spec.ts` pass in isolation and
fail inside the full run — "the thread survives a reload" clears 60s by about
a second when run alone — and it is a product characteristic, not test flake.

Raising the client ceiling again would be chasing a moving number with a
constant. The obvious backend fix, caching the probe, is NOT obviously correct
either: a cached reachability reading that reports "erreichbar" for a CLI that
broke a minute ago is exactly the lie this codebase forbids. If it is cached it
must carry when it was measured, and the surface must show that. That is a
design decision, not a patch.

**`/api/context/plan` returns 0 seeds for a German sentence** and 22 for
`picker attempt lease`. The panel reports it honestly rather than hiding it.
The fix is backend.

**The assistant speaks English inside a German interface.** The deterministic
route's answers ("I can queue this on the free local bench …") come from the
backend and were not translated in this round. The client's own five error
strings in `api.ts` were, because they arrive at the moment something fails and
sat two elements away from German text saying the same thing. The backend voice
is a larger, separate decision.
