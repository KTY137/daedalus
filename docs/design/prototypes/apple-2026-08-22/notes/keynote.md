# P1 · Keynote — notes

## Point of view (three sentences)

The cockpit is an editorial page, not a dashboard: a white ground, one enormous sentence-case
mission title, and the Ikarus conversation set as a column of large type with the six-stage order
timeline and the graph beside it, the way an apple.com product page carries one idea per screenful.
The graph is photographed like a product — a single grey object on white that tilts a few degrees
under the pointer — and everything else is type, hairlines and white space. The page arrives once
(words of the title rise in, the lede resolves out of blur, the two columns and the knowledge
section fade up in sequence) and then it stays completely still.

## React Bits items and their structural role

All ids verified in the `@react-bits` registry via the shadcn MCP before install
(`npx shadcn@latest add @react-bits/<Id>-TS-CSS`). The CLI wrote into a literal `@/components`
folder on Windows; the files were moved to `src/components/`.

| Item | Structural role | Carries real UI |
| --- | --- | --- |
| `SplitText-TS-CSS` | The mission title: the page's H1 arrives word by word (GSAP), the one orchestrated entrance. | yes — text entrance |
| `BlurText-TS-CSS` | The lede "Ikarus proposes. You decide." and the Library H1 resolve out of blur. | yes — text entrance |
| `AnimatedContent-TS-CSS` | Section reveals (`Arrive` wrapper for the Ikarus column, the graph column, the knowledge section, the library tree and stack), the settings sheet sliding in from the right, the palette popping in. | yes — transitions/layout |
| `FadeContent-TS-CSS` | The graph object fades/unblurs into place after the columns. | yes — transition |
| `Dock-TS-CSS` | Primary navigation: macOS dock at the bottom (Cockpit · Library · Command palette · Settings), restyled to white glass, current screen marked. | yes — navigation |
| `Stepper-TS-CSS` | The six-stage order timeline Intent → Plan → Build → Gates → Delivery → Digestion; custom indicators carry the fixture's state per stage, clicking a stage slides in its note. Footer buttons hidden via CSS — the user reads, the stepper does not "run" anything. | yes — data display / control |
| `ScrollStack-TS-CSS` | The Knowledge Library reading pane: the wiki page (with "Linked from" backlinks, provenance, open question), the auto module pages with editable hand notes, and the council card stack as you scroll. | yes — layout |
| `CountUp-TS-CSS` | Token count in the toolbar and the architecture figures (modules / islands / dark). | yes — data display |
| `TiltedCard-TS-CSS` | The graph as an object: the interactive four-plane SVG sits in the card's overlay slot, tilting 4° under the pointer. | yes — the hero's frame |
| `ElasticSlider-TS-CSS` | The spending-ceiling slider in Settings (patched in-app: Chakra/react-icons default icons replaced by plain glyphs, `onChange` prop added so the amount label follows). | yes — control |

Ten items; nine carry real UI. No background item is used — white space is the material.

## Fonts and theme

System stack only: `-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text",
"Segoe UI Variable Display", "Segoe UI", system-ui, sans-serif`; `ui-monospace` for identifiers
and receipts only. Light theme: ground #FFFFFF / #F5F5F7, labels #1D1D1F / #6E6E73, one accent
#0071E3, green/orange only for state (watcher dot, withheld rule). One radius (12 px) everywhere,
indicator circles excepted. 8 pt grid. Provenance M / I / A is a small bordered capital with a
`title` tooltip. `prefers-reduced-motion` renders every surface without the wrappers.

## Deliberately left out

- No Silk / Aurora / any background — the brief allowed 3 % Silk; white was stronger.
- No MagicBento — its registry source ships hard-coded demo cards plus glow/spotlight/particle
  effects; ScrollStack carries the Library instead.
- No metric tile rows, no status pills, no card grid of boxes, no HUD, no glow.
- A project switch does nothing but show the fixture's active project; the fixture carries one.
- The Evidence lens shows proposal scores and marks proposal-bearing nodes dashed; the Cost lens
  sizes nodes by edge count and names the slice numbers — no invented per-node cost.

## Patches to installed registry source (inside this app dir only)

- `BlurText.tsx`: registry code splits on `''` for both modes and joins words with `''`, so
  "Ikarus proposes. You decide." rendered as `Ikarusproposes.You…`; fixed to split on `' '` and
  join with ` `; wrapper changed from `<p>` to `<span>` so it can live inside `<h1>`/`<p>`.
- `ElasticSlider.tsx`: removed `@chakra-ui/react` + `react-icons` imports, added `onChange`.
- `Stepper`, `Dock`, `ScrollStack`, `TiltedCard`: restyled through CSS overrides only.

## Install failures

None. All ten `add` commands succeeded on the first attempt. Unused heavy dependencies the
registry pulled in (`@chakra-ui/react`, `react-icons`, `three`, `@react-three/fiber`) were
uninstalled; React pinned to 18.3.1 (the Vite 8 template scaffolds React 19).

## Screenshot note

`shoot.cjs` uses the bundled Chromium from `apps/web/node_modules/playwright-core`. The
`channel: 'chrome'` launch hung on `page.goto` after the first run (renderer never committed);
bundled Chromium is stable. Headless Chromium does not render `backdrop-filter`, so the sheet and
palette use 0.97 white behind the blur to read correctly in both renderers.
