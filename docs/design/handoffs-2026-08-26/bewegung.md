# Handoff: `motion/` → cockpit — Bewegung lane, 2026-08-26

Published early, before polish, per the brief — four lanes were waiting on
this. I will append a short "what actually shipped" section at the bottom
once Part 2/3 of my own work lands; the API below is stable now, read it and
keep going.

## The corrected finding

The brief's `grep -rln "motion/" src/` undercounts. `src/motion/index.ts` is
a barrel, so most importers write `from '../../motion'` — no trailing slash —
and that grep pattern misses every one of them. The accurate command is:

```
grep -rln "from '.*motion'" src/ --include=*.tsx --include=*.ts
```

That list is every file under `src/components/glass/`: `Dock.tsx`,
`SegmentedControl.tsx`, `ChatBubble.tsx`, `Composer.tsx`, `GlassCard.tsx`,
`GlassPanel.tsx`, `GlassSheet.tsx`, `LiveRail.tsx`, plus `LiveDot.tsx`. So the
vocabulary is not undistributed — it is fully wired into the **old** surface
(`components/glass/*`, still live at `?surface=classic`) and not wired into
the **new** cockpit surface (`cockpit/*`, `theme/*`) at all. None of those
files import from `motion` or from `components/glass`. That is the real gap,
and `components/glass/*` is a working, spec-passing reference implementation
for most of what you need — read the file before you invent your own pattern,
several of the four cases below are a rename away from an existing one.

One concrete consequence: `drawerVariants` in `variants.ts` had **zero**
callers anywhere in the tree before today — written, audited by
`motion.spec.ts`, never wired up. I have now wired it into `Settings.tsx` /
`ThemeStudio.tsx` (the two drawers I own). That conversion is a proven,
copyable pattern — see the bottom of this file.

## Import path

```ts
import { transitionFor, bubbleVariants, useReducedMotionPref /* … */ } from '../motion';    // from src/cockpit/* or src/theme/*
import { transitionFor, bubbleVariants, useReducedMotionPref /* … */ } from '../../motion';  // from a components/glass/* file
```
`@/motion` also resolves (`tsconfig.json` and `vite.config.ts` both carry
`@/* → src/*`) if you prefer the alias.

## Non-negotiable while wiring this in

- **Never write a bare `220ms`, `0.22s`, or a bezier tuple** into your
  component or your CSS module. Every duration/easing/spring/distance already
  has a name in `tokens.ts` — go through `transitionFor(tier, reduced)` or a
  ready-made variant factory, not a raw number. This is not a style
  preference — `motion.spec.ts` only audits what runs through these
  functions; a hand-written number is invisible to the test that is supposed
  to keep the two tiers apart.
- **`prefers-reduced-motion` is answered once**, by `useReducedMotionPref()`.
  Call it, pass the result into a variant factory, done. Never read
  `matchMedia` yourself and never add a `@media (prefers-reduced-motion:
  reduce)` rule to your own CSS for anything framer-motion drives — that was
  the actual bug in `settings.css`/`studio.css` (see bottom): a hand-written,
  hard-coded `transform 220ms cubic-bezier(...)` CSS transition, with its own
  local reduced-motion carve-out, duplicating a number that already lives in
  `tokens.ts` and bypassing the centralized reduced-motion contract entirely.

## `data-motion`: who owns transform/opacity on a node

Any node framer-motion writes an inline `transform`/`opacity` onto needs a
`data-motion="<anything>"` attribute (the value doesn't matter, only its
presence). `motion.css` (mine) carries a generic rule that then strips
`transform`/`opacity` out of that node's CSS `transition-property` — so your
own stylesheet can keep a plain CSS transition on `border-color` / `color` /
`box-shadow` for the acknowledgement parts, the generic rule only takes
transform/opacity away from CSS. That covers most new markup with zero extra
work on your side — just add the attribute.

If your component has an actual **cascade conflict** — a `@keyframes …
animation-fill-mode: both` pinning a final frame over an inline style, or two
elements sharing one highlight the way the dock pill / segmented thumb do —
the generic rule is not enough and needs a bespoke override in `motion.css`
(see the `.dockbtn[data-motion][data-motion]` / `.segmented[data-motion]`
rules already there for the shape of it). That file is in my lane: tell me in
a handoff back, or ping in the room, and I'll add the one-line rule — cheaper
than four lanes hand-rolling the same workaround.

## The four things, worked examples

**1. View switch** — a highlight that travels between options it never left
(tier `move`, `SPRING.instrument`):
```tsx
const move = useMemo(() => transitionFor('move', reduced), [reduced]);
{active && <motion.span className="thumb" layoutId="my-switch-thumb" transition={move} />}
// only the ACTIVE option renders the thumb; framer-motion measures old vs new position
```
Reduced motion drops `layoutId` entirely (shared-layout IS travel by
definition) and cross-fades a static thumb at the `ack` tier instead — that
branch is already built in `components/glass/SegmentedControl.tsx` and
`Dock.tsx`/`DockItem.tsx`. If a same-width N-option control fits your layout,
import `SegmentedControl` directly rather than re-deriving this; otherwise
copy its ~15-line `active && (reduced ? <fade/> : <motion.span layoutId/>)`
shape onto your own markup.

**2. Modal palette opening** — scrim + panel (tier `enter`/`exit`,
`SPRING.surface` in, timed depart out):
```tsx
const sheet = useMemo(() => surfaceVariants(reduced), [reduced]);
const scrim = useMemo(() => scrimVariants(reduced), [reduced]);
<motion.div data-motion="scrim" variants={scrim} initial={false} animate={open ? 'open' : 'closed'} />
<motion.div data-motion="sheet" variants={sheet} initial={false} animate={open ? 'open' : 'closed'} />
```
`surfaceVariants` rises 24px and settles from 98.5% scale on open, and departs
in 220ms accelerating on close (arrival is deliberate, dismissal is fast — do
not make the two symmetric). `components/glass/GlassSheet.tsx` is the full
reference including the scrim, if the palette's chrome ends up close enough
to reuse wholesale rather than hand-rolling scrim+panel again.

**3. A message arriving in a transcript** — enters from its own side of the
spine (tier `move`, `SPRING.instrument`):
```tsx
const v = useMemo(() => bubbleVariants(reduced, t.role === 'you' ? 'right' : 'left'), [reduced, t.role]);
<motion.article data-motion="bubble" variants={v} initial="hidden" animate="visible" exit="hidden">
```
Rises 12px, settles from 98.5%, nudges 6px from its own side. The variant
already declares `exit` — wrapping the turn list in `<AnimatePresence>` is
the only thing needed to also animate a turn being removed (e.g. a
regenerated answer), no new prop. `components/glass/ChatBubble.tsx` is the
identical pattern already wired for the `.msg` class; this is the same thing
for `.turn`.

**4. Node selection changing on a map** — a highlight that travels between
nodes it never left, same family as #1:
```tsx
const move = useMemo(() => transitionFor('move', reduced), [reduced]);
{selected === p.id && <motion.circle className="sel-ring" layoutId="stage-selection" transition={move} r={ringRadius} />}
```
framer-motion drives SVG shape attributes the same way it drives a `div`'s
transform. One `layoutId` shared by every glyph's selection indicator means
the ring itself slides from the previously selected node to the newly
selected one instead of blinking off one and on the other. If the spatial
graph and the four-plane column layout share this `layoutId` across their
toggle, the same ring can visibly travel **across** the representation
switch, which is exactly the "selection carried across the toggle" the brief
asks for — worth trying before building a separate mechanism for that
handoff between the two views. Reduced motion: drop `layoutId`, cross-fade a
static ring at the `ack` tier instead (same branch shape as #1/#3).

## What actually shipped in my two drawers (verification, not a promise)

`Settings.tsx` / `ThemeStudio.tsx` both converted from a hand-coded
`transform: translateX(102%); transition: transform 220ms cubic-bezier(0.32,
0.72, 0, 1);` CSS rule (with its own local `@media (prefers-reduced-motion:
reduce)` carve-out) to `drawerVariants(reduced)` driven by
`useReducedMotionPref()` — the exact conversion pattern above, generalized:
`motion.aside` + `data-motion="drawer"` + `variants={drawerVariants(reduced)}`
+ `initial={false}` + `animate={open ? 'open' : 'closed'}`. `pointer-events`
stays a plain CSS class toggle (`.settings.open`/`.studio.open`), since that
property is not one `drawerVariants` animates. `motion.css` gained
`.settings[data-motion], .studio[data-motion] { transition: none; }`,
mirroring the existing `.sheet[data-motion], .scrim[data-motion]` rule.
`npx tsc --noEmit` and `npm run test:motion` both pass after the change;
Playwright-driven mid-transition sampling confirmed the panel now
opacity-fades (0→1) while it travels the last 32px into place, on the
`surface` spring, rather than the previous instant-opacity/pure-translate
CSS transition. Full detail in the session report to the foreman.
