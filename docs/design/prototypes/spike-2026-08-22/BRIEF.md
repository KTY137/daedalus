# Daedalus cockpit spike — shared brief (2026-08-22)

THROWAWAY. The output of this spike is a recommendation, not code we keep.

## The scene (identical for all three variants)

One screen, 1440×900, dark scheme. The Daedalus cockpit for ONE project. Locked IA (trio):

1. **Codebase graph — THE HERO.** The four-plane Project Twin (code / type / data / knowledge)
   from `fixture.json`. Cross-plane edges with `verified:false` must look different
   (proposal, not fact). Three lenses (structure / evidence / cost) that MORPH the same nodes,
   never swap pictures. Hover/selection shows one node.
2. **Ikarus chat** — the Jarvis voice. Messages from `fixture.chat`. Every Ikarus message
   carries its provenance stamp **M** (measured) / **I** (inferred) / **A** (assumed) and
   names what was withheld. Ikarus's voice is the ONLY place a humanist/warm typeface is
   allowed ("cold glass, warm voice").
3. **Knowledge** — `fixture.knowledge_page` with backlinks and the open question.

Plus the rim readings from `fixture.rim` (budget, attempts, evidence, withheld, kill switch).
Readings are statements, not widgets: a number with its unit and its provenance, no tiles.

## Owner's taste (stated repeatedly — this is the jury's rubric)

- WOW, but not AI-ish. "Sophisticated and clean", Jobs-level restraint. Competence as the aesthetic.
- Real depth and animation — "wie Jarvis". An animated background for depth, but
  "nicht zu viel going on".
- Glassmorphism, minimalism, skeuomorphism/spatial UI are all welcome vocabularies.
- REJECTED, do not revive: warm-paper/serif, flat dark card grids, flat frosted-glass CARD
  GRIDS, four-tile metric rows, suggestion chips, status pills, Inter/Roboto template faces.
- The keeper so far: `docs/design/prototypes/daedalus-forge.html` in the agent_env repo
  ("ja ist gut aber geht noch besser") — the forest owns the centre, readings live at the rim,
  lenses morph the same nodes. Read it once before you start; do not copy it.

## Measured anti-slop thresholds (from the forge keeper; `lint.py` will be run on you)

framed_panels ≤ 15 · visible_elements ≤ ~150 · status_pills_visible = 0 · distinct_radii ≤ 1 ·
panel_nesting_depth ≤ 2 · identifier_leaks = 0 · contrast AA everywhere · targets ≥ 44×44.
All-caps mono micro-labels are FINE (that rule was falsified by the data). Semantic hues are
fine and expected: ice = structure, amber = live, oxide = failed, lime = passed.

## Toolchain — MANDATORY

- React Bits via the registry. Never hand-roll an effect the registry already ships.
  Fetch with `npx shadcn@latest add @react-bits/<Name>-TS-CSS` (CSS variants; no Tailwind).
  A `components.json` with `"registries": {"@react-bits": "https://reactbits.dev/r/{name}.json"}`
  and sensible aliases must exist in your app dir. React Bits imports `motion/react` → `npm i motion`.
  If an item's name is unknown, search the registry with the shadcn MCP
  (`mcp__shadcn__search_items_in_registries`, registries `["@react-bits"]`) — load it via ToolSearch.
- Do NOT use `GridScan` (it pulls face-api.js).
- Fonts: no Inter, no Roboto, no serif. Cascadia Mono / Segoe UI Variable / Bahnschrift exist on
  this Windows box; Google Fonts are allowed (JetBrains Mono, Geist, Space Grotesk, IBM Plex…).
- Stack: Vite + React 18 + TypeScript. `base: './'` in `vite.config.ts` so `dist/` serves statically.
- The graph may be drawn with whatever the variant needs (SVG, canvas, three). Keep it ≤ 200 lines
  of your own code; this is a look spike, not a graph engine.

## Deliverables per variant (inside your own dir; touch nothing outside it)

- `dist/` that renders the full scene from `fixture.json` (copy it into `public/` and fetch it).
- `NOTES.md`: React Bits items used (exact registry names), fonts, the ONE design law of the
  variant, what you deliberately left out, and anything that failed to install (with the error).
- `shot.png` at 1440×900 after the scene settled (2.5 s), motion RUNNING (the look matters).

Verify in the foreground: `npm run build` must exit 0; then serve `dist/` and take a real
screenshot. Do not arm a monitor and wait on it — check state yourself.
