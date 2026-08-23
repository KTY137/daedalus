# Variant B · Instrument (skeuomorphic flight deck)

THROWAWAY spike. Vite + React 18 + TS, `base: './'`, `dist/` serves statically.

## The one design law

**A machined object, not a webpage.** One material family (brushed graphite deck,
bevelled bezels with a single top-left light source), one radius token (`--r: 6px`,
the scope is a circle by `clip-path`, not by border-radius), lit readouts instead of
tiles. The Project Twin is a scope in the centre: a WebGL radar sweep is the ground,
the four planes are concentric traces (code innermost, knowledge at the rim). The
three lenses are a rotary with three detents; the needle turns, the same nodes morph
(spring-animated) onto new positions. Nothing glows except the armed kill switch.

## React Bits items (exact registry names)

- `@react-bits/Radar-TS-CSS` — the scope ground (ogl WebGL sweep), low brightness, mouse off
- `@react-bits/SpotlightCard-TS-CSS` — the two instrument bodies (Ikarus, Knowledge); radius/background overridden to the bezel material
- `@react-bits/CountUp-TS-CSS` — rim readings (tokens, attempts, packets, receipts)
- `@react-bits/DecryptedText-TS-CSS` — bezel labels and the project name
- `@react-bits/ElectricBorder-TS-CSS` — ONLY on the armed kill switch (amber)

Not used: Dither/DotField (the Radar already owns the animated ground; a second
animated surface would be "too much going on"), SpecularButton (the lens buttons
needed a pressed/detent state, done with a plain `<button role="radio">` + CSS).
Nothing failed to install. Note: the shadcn CLI wrote the files into a literal
`@/components/` folder (no Tailwind, alias not resolved); moved into `src/components/`.

## Fonts

- Readouts/labels/body: JetBrains Mono (Google) → fallback Cascadia Mono / Consolas
- Ikarus voice only: Nunito Sans (Google) → fallback Segoe UI Variable Text
- The screenshot was taken in a sandboxed headless Chromium with no egress, so `shot.png`
  shows the local fallbacks (Cascadia Mono + Segoe UI). In a normal browser the Google faces load.

## The scene

- Hero scope: all 32 nodes, 34 edges. Intra-plane edges grey, verified cross-plane edges
  ice, unverified cross-plane proposals dashed amber. Hover a node: neighbourhood stays
  lit, rest dims, readout line under the glass names plane · kind. Lenses: structure
  (one ring per plane), evidence (verified-edge weight pulls to centre, proposals drift
  to the rim), cost (plane sectors, degree = depth). Graph code: `src/Scope.tsx`, 101 lines.
- Ikarus: provenance stamp M/I/A as a machined square, evidence refs under each
  message, the withheld line in amber.
- Knowledge: page, provenance, backlinks, open question in amber.
- Rim readings: four statements along the bottom edge separated by machined seams,
  number + unit + provenance; no tiles.

## Anti-slop self-count

framed panels: 5 (top strip, Ikarus, scope housing, knowledge, kill switch) ·
status pills: 0 · radii: 1 token (6px) + the circular scope via clip-path ·
nesting depth: 2 (deck > bezel > content) · targets: lens buttons 92×44 ·
identifier leaks: none (labels are fixture labels).

## Deliberately left out

Second animated surface, particle fields, per-node tooltips, chat input box,
any radial-gauge widget for the budget (it is a sentence), glass blur.
