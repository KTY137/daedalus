# Material — handoff, 2026-08-26

New tokens are live on every theme. Nothing existing was renamed or removed —
`--shadow`, `--font-display`, `--font-body`, etc. are byte-identical to before.
Everything below is additive.

## New CSS custom properties (set by `theme/apply.ts` on `<html>`)

| Token | What it is | Notes |
| --- | --- | --- |
| `--warn` | Alert/blocker tone, distinct hue from `--accent` AND `--bad` in every theme | Was needed because two of the seven presets had `bad === accent` or `bad === live` outright — fixed in the same pass |
| `--warn-ink` | Text/glyph colour on top of `--warn` | |
| `--heat-1` … `--heat-5` | Sequential ramp, low → high magnitude (fan_in, loc, hot-list score) | One hue per theme, checked distinct from that theme's `--accent` hue (see "Kartograph fix" below) — Nachtfenster is the deliberate exception, a two-hue thermal-camera arc |
| `--plane-1` … `--plane-4` | Categorical set, FIXED ORDER [Code, Type, Data, Knowledge] | Not yet consumed anywhere — Kartograph confirmed the map is code-only right now and declined it on purpose. Available when a node/edge carries real plane data |
| `--font-voice` | Humanist face, Ikarus's own words only | "Cold glass, warm voice" — every other face in a theme is instrument-cold on purpose |
| `--voice-weight`, `--label-weight`, `--label-tracking`, `--datum-weight`, `--datum-tracking` | Type ROLES, not just sizes | label = eyebrows/field names/captions; datum = a number read as a number (tabular). Neither existed before — the scale only had `--fs-xs`…`--fs-2xl` |
| `--shadow-pane`, `--shadow-drawer`, `--shadow-modal` | Elevation as a 4-step scale | `--shadow` (the base/card level) is unchanged. Pane < drawer < modal, per theme |
| `--stage-parallax`, `--stage-depth-fog`, `--stage-depth-blur` | Spatial-map depth | Kartograph is already consuming all three (see their handoff to you) |

All of these degrade gracefully: every value is written by `applyTheme()` on
every theme switch (same "synchronous and total" contract the file already
had), so nothing is ever left unset.

## Where they live in the TypeScript contract (matters if you read `types.ts`)

`warn`, `warnInk`, `heat`, `plane` sit on **`ThemeSpec` directly** (`theme.warn`,
not `theme.colors.warn`), not inside `ThemeColors`. This was a mid-round
correction — putting them in `ThemeColors` broke `theme/store.ts`'s generic
repair loop and `ThemeStudio.tsx`'s `Record<keyof ThemeColors, string>`
swatch list, both of which assume `ThemeColors` is a closed, uniformly-typed
bag. They're optional there for the same reason (a theme saved before today
still opens). `heat`/`plane` are **comma-joined hex strings**
(`'#a,#b,#c,#d,#e'`), not arrays — same reasoning, plus `store.ts`'s loop
assumes every `ThemeColors`-shaped value is a plain string. If you ever need
the array form in JS (not CSS), the five/four `--heat-N`/`--plane-N` custom
properties are already split for you; there's no exported `splitRamp` outside
`apply.ts` today, say so if you need one.

The six `type.*` role fields, three `form.elevation*` fields, and three
`stage.*` depth fields are optional on their interfaces for the same
store.ts-compatibility reason, with fallbacks in `apply.ts` (voice→body,
label/datum weight→displayWeight, elevation\*→elevation, parallax/fog/blur→0).
Every one of the seven BUILT_INS sets all of them explicitly — the optionality
is a migration seam for old stored themes, not a hint that a new preset can
skip them.

## Fix made for Kartograph mid-round

Kartograph's stage draws the one focus node in `--accent` and every other
node from the `--heat-*` ramp. My first pass put three themes' heat ramps too
close to their own accent hue (Kammer 13°, Sternkarte 11°, Leitstand ~3°/same
family) — a hot node would have read as the selected one. Revised all three
to hues 27–159° from their accent (Kammer: crimson `hue 345`; Sternkarte:
bronze/gold `hue 40` instead of reusing the room's own blue; Leitstand: amber
`hue 45` instead of the accent's own rust). Depesche's heat ramp stays in the
accent's red family deliberately — a broadsheet has one ink colour to spend,
by the theme's own concept — but the hot end (`#770d13`) is materially darker
than the accent (`#A3161F`), not the same swatch.

Also: Kartograph asked for a call on `backboneOnly` for Leitstand and
Werkstatt (currently `false` on both, meaning every edge draws at rest, not
just the backbone). Leaving both `false` deliberately — Werkstatt's own
concept is a pinboard where every pinned card and connecting thread is
visible at once, and Leitstand's is a **Schaltplan** (circuit diagram), which
isn't a schematic if it hides half its wiring. Both themes' `backboneOnly`
choice is the theme being honest about what it's imitating, not an oversight.

## Palette changes (half two — the aesthetic pass)

- **Fixed real bugs found while designing `warn`**: Depesche had `bad`
  literally equal to `accent` (`#A3161F` both); Leitstand had `bad` equal to
  `live` (`#8A2E05` both). A blocker, a failure and a highlight were three
  names for one colour. `bad`/`live`/`accent` values are untouched — only
  `warn` was added as the missing fourth tone, now distinct from all three
  everywhere.
- **Typography**: verified via Playwright canvas-width detection (not
  `document.fonts.check()` — it returns `true` for every local font name on
  this Chromium regardless of whether it's installed, so it's not a real
  signal) which faces this Windows box actually has. Result: **Referenz was
  already fine** (Segoe UI Variable Display/Text are genuinely two different
  faces here). **Werkstatt's `Seravek` is not installed** and was silently
  resolving to Segoe UI — the exact "seven themes share one voice" bug the
  brief named — replaced with Gill Sans MT (installed, humanist, real
  workshop-typography heritage). Sternkarte and Depesche both resolved to
  Georgia — gave Sternkarte its own transitional serif (Constantia) plus
  Bahnschrift for body (an installed engineering/drafting grotesk).
  Nachtfenster and Leitstand get their own instrument faces too (Bahnschrift,
  Franklin Gothic) instead of defaulting to Segoe UI Bold. Full reasoning is
  in the per-theme comments in `presets.ts`.
- **"Cold glass, warm voice"**: every theme now has a `type.voice` distinct
  from `type.body`/`type.display` — mostly the Sitka family (a real humanist
  serif installed on this box, with optical sizes built for on-screen text).
  Depesche is the one deliberate exception: `voice === body` there, because
  the whole theme already IS Ikarus's words as a masthead — documented in
  its comment.
- **Glass restricted to two surfaces** (`materials.css`): the `:root[data-material='glass']`
  blur rule used to hit `.panel, .convo, .decision, .palette, .hotlist` — five
  surfaces, including the entire conversation transcript and the hot-module
  list. Now only `.decision` and `.palette` blur (a status strip and the
  command-palette dialog — genuine floating overlays). `.panel`/`.convo`/`.hotlist`
  still get the theme's surface colour (translucent in a glass theme), just
  not the backdrop-filter. This is a real behavior change, not cosmetic —
  screenshot it if you're touching those classes.

## Small fix outside the four owned files (coordinator exception)

`cockpit/cockpit.css`'s header comment claimed `data-decision` was one of the
attributes `theme/apply.ts` sets on `<html>`. It never was — Instrumente
confirmed decision state is expressed via classes on `.decision` itself, not
a document-level switch. Corrected the comment (one line, no cascade impact).
If a theme ever needs to affect decision-card composition for real, that's a
new `composition.decision` field through `types.ts`/`apply.ts`, not yet done.

## Verification

- `npx tsc --noEmit` on the whole `apps/web` tree: clean (the one error seen
  mid-session, `Cockpit.tsx`/`Decision.tsx`, is Rahmen/Instrumente's own
  in-flight code, not mine).
- Screenshot + contrast audit run across all six non-default themes; see my
  final report to the coordinator for paths and raw output.
