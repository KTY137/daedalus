# Handoff: conversation → other lanes — Ikarus lane, 2026-08-26

Everything below is something I could not fix from inside
`cockpit/Conversation.tsx`, `cockpit/ContextPlan.tsx`, `cockpit/conversation.css`.
Each item says what I did instead so the page works today either way.

## → Rahmen (`cockpit/shell.css`)

**1. `.cockpit-body.talk { align-content: start }` leaves a band of empty page
under the row, and no rule in my lane can reach it.**

Measured at 1440×900, nachtfenster, empty conversation:
`.cockpit-body` is `y=75 … 816`, padded content area `99 … 792` (693px).
The talk grid has one row, sized to `max(.talk-main, .talk-side)` content, so
with `align-content: start` the row ended at `y=661` and left **131px** of
page below it that nothing can claim.

`align-content: stretch` on `.cockpit-body.talk` would hand the row the full
height, and then `.convo`'s `flex: 1 1 auto` (which I added) fills it exactly,
at any viewport height and with or without a decision card above it.

Until then I approximate it with `min-height: min(70vh, 680px)` on
`:root .cockpit-body.talk .convo`. That is a magic number and I know it — it
lands within ~10px at 900px tall and drifts at other heights. Delete it the
moment `align-content: stretch` lands; the `flex: 1 1 auto` next to it is the
part that should survive.

**2. I override two of your rules.** Both are later in the cascade
(`conversation.css` follows `shell.css` in `cockpit.css`), same specificity,
so they win by source order. Named here so neither looks like an accident:

- `.cockpit-body.talk .convo-scroll { overflow: visible }` → back to `auto`.
  With `visible` the transcript grows the page, which walks the composer off
  the bottom of the screen on a long thread — and it also makes the
  follow-the-stream pinning in `Conversation.tsx` inert, because the element
  it scrolls (`scroller.current`) has nothing to scroll: `scrollHeight ===
  clientHeight`. That auto-follow has therefore never worked on the talk page.
- `.cockpit-body.talk .composer button { min-width: 52px; min-height: 52px }`
  → `min-width: 0; min-height: 44px`, with 52px restored for
  `.composer-send` specifically. The composer is now a well that also contains
  the context rail's controls ("Einfügen", "Was würde gelesen?"), so that rule
  had started sizing two text controls as if they were the send button.

**3. `.cockpit-body.talk .convo-empty { font-size: var(--fs-lg); max-width:
60ch }` is now dead.** The empty state is `.convo-open` / `.convo-open-line` /
`.convo-open-note` (a composed invitation, two type sizes), and the resuming
line is `.convo-reading`. Yours can go whenever you are next in the file.

## → Bewegung (`motion/`)

**The CSS half of the motion system does not exist on the cockpit surface.**

`--dur-fast`, `--dur`, `--dur-slow` and `--ease` are declared in
`src/styles.css`, and `main.tsx` loads `styles.css` **only** for
`?surface=classic` — deliberately, and the comment there explains why. So on
the cockpit those four custom properties are undefined, and any CSS
transition written against them silently does not run. Two consequences:

- No cockpit lane can write an acknowledgement transition the way your
  handoff describes, without hand-writing a number — which your handoff
  correctly forbids. I therefore wrote **zero** CSS transitions in
  `conversation.css` and drove the one acknowledgement that needed motion
  (the picker's caret flipping over) from JS via `transitionFor('ack',
  reduced)` instead.
- `motion/motion.css:157` already uses `var(--ease)` for
  `animation: motion-dot-ring 2.4s var(--ease) infinite`. On the cockpit
  surface that easing is invalid, so that animation is running on the
  browser's default easing wherever it applies there.

The cheap fix is on your side: `motion.css` is loaded by `motion/index.ts`,
which the cockpit now imports (from this file), so publishing the four
properties on `:root` from `motion.css` — generated from `tokens.ts`, which is
where they already live — would give every cockpit lane the CSS half back
without anyone writing a number. `useMotion.ts`'s parity check already skips
empty values (`if (!raw) continue`), so it does not currently warn about this.

Wired in this lane, all through your vocabulary, all with `data-motion`:
`bubbleVariants` on `.turn` (side by role), `revealVariants` on the provenance
receipt, the offer card and the picker menu, `armVariants` + `pressProps` on
the send button, `useReducedMotionPref` once. A turn animates only if its
index is `>= freshFrom.current` — a resumed thread of twenty turns starts at
rest rather than staging a page load.

## → Material (`theme/*`)

**1. Blocking, and not design feedback: `theme/apply.ts` is crashing the whole
app right now.** `splitRamp(c.heat, 5)` at `apply.ts:135` throws
`TypeError: csv.split is not a function` inside `applyTheme`, which takes
`<ThemeProvider>` down and renders a blank page — measured at 12:28 today
against `http://127.0.0.1:5173/?view=chat&theme=nachtfenster`, six console
errors, `document.querySelector('.cockpit-body')` returns null. `colors.heat`
is undefined for the theme being applied. Presumably the preset half of your
change had not landed yet when I looked; flagging it because every lane's
screenshots go blank while it is in that state.

**2. Two tokens I wanted and did not have.** I used the nearest existing one
and noted it here rather than inventing a value:

- *A focus-ring colour.* The composer well rings on `:focus-within` and I
  built it as `0 0 0 3px color-mix(in srgb, var(--accent) 20%, transparent)`.
  Derived from a token, so not a hard-coded colour, but a real `--ring` (or an
  `--accent-soft`) would let a theme tune ring weight independently of the
  accent — a 20% mix of a pale accent on a pale surface is nearly invisible in
  `leitstand`, and the same mix of a saturated accent is loud in `kammer`.
  Same for `color-mix(… var(--accent) 60% …)` on the user turn's rule.
- *A recessed-well surface.* The composer sits on `--surface2`, the same token
  as the recessed panel fill. It works, but the well is now the most important
  object on the page and it would earn its own step if your elevation scale
  grows one.

If your published type roles (label / datum / voice) land, the mapping here is:
`.brain-opt-note`, `.stamp`, `.cite`, `.ctxplan-score` are **datum** (all
`--font-mono` today); `.brain-off-head`, `.offer-eyebrow`, `.turn-nudge` are
**label**; `.turn.ikarus .turn-text` and `.convo-open-line` are **voice**.

## → nobody: `api.ts` / `types.ts` need no change

`RuntimeRow` already carries `mode`, `version`, `selected_model`,
`auth_status` and `available`, which is everything the rebuilt picker shows.
Nothing was needed from the read-only files.

---

# Round 2 — conversation, 2026-08-26 (second Ikarus session)

The first session's handoff above stands. This section is what the second
session found, changed, and could not fix from inside the three owned files.

## → Rahmen (`cockpit/shell.css`) — one rule of yours I now override, declared

`align-content: stretch` fixed the EMPTY page exactly as you intended. It
cannot fix the opposite case: `stretch` only ever GROWS a track, so with a
transcript taller than the viewport the single auto row sizes to its content
and nothing inside can scroll.

Measured at 1440×900 on a four-exchange thread, before the fix:

    .cockpit-body   clientH 741  scrollH 1323   (the page scrolls)
    .talk-main      height 1275  min-height auto
    .convo-scroll   scrollHeight 1023 === clientHeight 1023
    last .turn      y 734 … 1236, sticky .composer y 666 … 788

So `overflow: auto` on `.convo-scroll` never engaged, the follow-the-stream
pinning in `Conversation.tsx` was still inert (your item from round 1 was only
half-fixed), and 448px of the last answer printed behind and below the sticky
composer, with a sliver of it visible under the well.

`conversation.css` now carries, deliberately and with a comment saying it is
yours:

    .cockpit-body.talk { grid-auto-rows: minmax(0, 1fr); }
    .cockpit-body.talk .talk-main { min-height: 0; }

`minmax(0, 1fr)` is what `stretch` was reaching for in the form that also
shrinks. It is a no-op on the empty page (the row was already full height) and
it is what makes the transcript scroll inside itself. **If you would rather own
this, move both lines into `shell.css` and delete them from mine** — they are
one behaviour, and it is your grid.

Residual risk I did not chase: `.talk-side` is now height-bounded by the same
row. Its content (focus card + hot list) is ~560px at 1440×900, so it fits, but
at a short viewport it will overflow rather than scroll. `.talk-side` is yours.

`.cockpit-body.talk .convo-empty` (dead since round 1) is still dead.

## → Material (`theme/*`) — the type roles are cashed, and one is missing

Consumed on this page: `--font-voice` + `--voice-weight` on
`.turn.ikarus .turn-text` and nowhere else, which is the point — the first time
the reader meets the humanist face is the first time Ikarus speaks rather than
the interface. `--label-weight`/`--label-tracking` on `.stamp`,
`.brain-btn-role`, `.composer-stage-label`, `.convo-thread-role`,
`.brain-legend`, `.brain-off-head`. `--datum-weight`/`--datum-tracking` on
every measured number and identifier. `--shadow-drawer` on the route menu.

Still wanted, and still worked around: **a focus-ring token**. The composer
well rings on `:focus-within` as `0 0 0 3px color-mix(in srgb, var(--accent)
20%, transparent)`. Derived from a token, but a 20% mix of a pale accent on a
pale surface is nearly invisible in `leitstand` and loud in `kammer`.

## → nobody yet: three things the backend says that the UI cannot fix

1. **`/api/runtimes/status` takes 16.6s warm** (measured in the page) against
   the 20s ceiling `request()` gives it, because it waits out an unreachable
   Ollama endpoint's connect timeout. Under load it does not answer at all, and
   the route picker then degrades to "only the automatic route is certain" —
   honest, and the whole control is gone. This lane now retries once and offers
   an explicit "Erneut prüfen" inside the menu, and a runtime that has no name
   yet is drawn as an identifier rather than typeset as a name. The real fix is
   a shorter probe or a cached answer, on the backend.
2. **The deterministic route's canned answer says "Pick a model in the header"**
   (`daedalus/ikarus_os.py`). There is no model picker in the header any more —
   it is on the composer's rail. Backend copy, not mine.
3. **`/api/context/plan` is lexical over identifiers.** Measured: `picker
   attempt lease` → 22 seeds in 244ms; `wo wird der Kontextplan gebaut` → 0
   seeds. The panel says "0 Kandidaten gerankt · gezeigt 0", which is true and
   is the honest thing to print, but a German sentence is what a German
   interface invites, so most real presses will show an empty plan.

## → Bewegung — the CSS half is still missing, and it now costs something

`--dur-*` / `--ease` are still undefined on the cockpit surface, so this lane
still writes zero CSS transitions and drives every acknowledgement from JS.
Newly wired this round: `revealVariants` on the thread bar, which now appears
when a thread comes into existence.

One raw duration does live in `conversation.css`: `animation: blink 1.05s
steps(2, start)` on `.caret`, inherited from before this round. `run-spec.mjs`
scans `.tsx` only, so no guard sees it. Publishing the four properties from
`motion.css` would let it become a token.
