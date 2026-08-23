# Daedalus — four prototypes, Apple standard (2026-08-22, round 2)

The owner rejected every previous look ("sieht aus wie KI generiert"). Binding instructions from the
owner, verbatim in spirit: **use React Bits properly · do not look AI-generated · orient on Apple
design · be Karl Lagerfeld / Steve Jobs · revamp everything · do NOT use any old version as reference
· construct the UI from the feature list.** This brief is the only reference you get. Do not open
`docs/design/prototypes/*`, `apps/web/src/*`, or any earlier artifact. If you catch yourself building
a dark sci-fi HUD with mono all-caps labels and glowing rings, you have failed — start over.

## What the product is (one paragraph, so you design for a real thing)

Daedalus is a desktop app (Tauri) that SEES a whole codebase, DISTILLS what matters, and ORCHESTRATES
the user's own agents (Claude, Codex, Gemini, local Ollama — the user's own keys and CLIs, BYOK) to
change it — fail-closed, nothing executes without the user's decision, nothing is ever invented on
screen. Ikarus is the assistant inside it: persistent in goals and evidence, it proposes, the user
decides. The audience is one demanding engineer-owner, later university chairs.

## The feature list (everything below must be visible and operable in your prototype)

Per project, a trio:

1. **Ikarus** — the conversation. Streaming chat; every Ikarus claim carries a provenance stamp
   M (measured) / I (inferred) / A (assumed); anything withheld is named, never silent. Inside the
   Ikarus panel lives the **order timeline** of the current mission — six stages
   Intent → Plan → Build → Gates → Delivery → Digestion, with state per stage. Quick actions drive
   the other two panels ("what changed", "hotspots", "distill X"). Ikarus proposes; only the user
   executes.
2. **Codebase** — the hero: the living graph of the project (modules, four planes code / type / data /
   knowledge, cross-plane edges; unverified proposals look different from verified facts). Hover →
   neighbours; click → selection flows into Knowledge. Three lenses (structure / evidence / cost)
   morph the same nodes. A standing distillation state: "slice: warm · refreshed 14:02" and one
   lens-like action **Focus the slice** — never a button that "runs" something.
3. **Knowledge** — what the system knows: selection detail, architecture state (modules / islands /
   dark counts), distillation receipts, and the **Knowledge Library** ("Confluence, but honest"):
   one global library + one wiki per project + one auto page per module with hand notes that survive
   regeneration; page tree, backlinks ("Linked from"), "Show on the atlas" ⇄ "Open its wiki page".
   Council opinions from other vendors are shown **verbatim, never scored**.

Chrome: **project tabs** (each project = its own trio), watcher dot, token/spend count with
provenance, **⌘K / Ctrl-K command palette** (verbs: distill, focus, canary, council, doctor, open
page, find module), a status line with the active lane and a "resolved host" warning when local
traffic could leave the machine.

**Settings** (a sheet, three sections): *Routing & Rights* — preferred route (Auto / Local only /
Claude), "local may leave this machine" toggle, spending ceiling slider, a per-runtime rights matrix
Read / Propose / Write where locked cells are **statements, not controls** ("Codex never writes.",
"Ikarus proposes. You decide.", sensitivity floor always on); *Memory & Privacy* — remember across
sessions, do-not-remember-this-project, retention 30 / 90 / forever, "Delete everything", BYOK stated
("Daedalus never holds a key."); *Appearance* — Light / Dark / Auto, accent, motion Full / Calm / Off,
text size, density.

Data for all of it is in `fixture.json` (same directory). Use it; invent nothing else.

## Apple standard — what it means concretely here

Apple's Human Interface Guidelines in three words: **clarity, deference, depth.** Content first; the
chrome recedes; depth comes from material and motion, not from borders and glow.

- **Type carries the page.** System font stack only:
  `-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Segoe UI Variable Display",
  "Segoe UI", system-ui, sans-serif` (Google Fonts are NOT reachable in the screenshot sandbox — do not
  depend on them). Large titles 34–64 px at weight 600–700 with letter-spacing −0.01 to −0.02 em;
  body 15–17 px; secondary text in a grey with a slight hue bias, never pure mid-grey.
  **Sentence case everywhere.** No all-caps micro-labels. Monospace only for code identifiers and
  receipts, never for UI chrome.
- **Colour.** One accent (Apple blue #0071E3, or one of your own — but ONE), used sparingly. Grounds:
  light #FFFFFF / #F5F5F7 with labels #1D1D1F / #6E6E73, or Apple dark #000000 / #1D1D1F with
  #F5F5F7 / #86868B. Semantic colour (green / orange / red) only for state, never as decoration.
  Provenance M / I / A is typographic (a small capital letter with a tooltip), not a coloured pill.
- **Layout.** 8 pt grid. Generous white space — if it feels empty, it is right. Continuous rounded
  corners (12–20 px) on at most ONE radius scale. Sidebars, toolbars, split views, sheets, segmented
  controls, toggles, sliders — the macOS / visionOS vocabulary. No four-tile metric rows, no status
  pills, no card grids of equal dark boxes, no dashed "islands" rings, no scanlines, no radar.
- **Material.** macOS translucency (backdrop blur) for sidebars and sheets; visionOS glass only where
  something genuinely floats over content.
- **Motion.** Spring physics, short, purposeful. One orchestrated entrance (the page arriving), then
  quiet. Respect `prefers-reduced-motion`.
- **Copy.** Plain, confident, human. "Ikarus proposes. You decide." A control says what happens.
  No jargon in chrome; identifiers only where the user needs the exact name.

## React Bits — as the fabric, not the garnish

React Bits is mandatory and it must be STRUCTURAL. Rule: **at least six registry items, and at least
four of them must carry real UI** — navigation, layout, controls, transitions, data display, text
entrance — not backgrounds or hover sparkle. Decoration-only usage (a glowing border on a button, a
scramble effect on a title) is what the owner rejected last time.

Search the registry before writing anything: load the shadcn MCP via ToolSearch
(`select:mcp__shadcn__search_items_in_registries,mcp__shadcn__view_items_in_registries,mcp__shadcn__get_add_command_for_items`)
and search `["@react-bits"]` by category words — "nav", "menu", "dock", "stepper", "list", "stack",
"card", "slider", "counter", "text", "reveal", "fade", "masonry", "carousel", "folder", "glass",
"silk", "aurora", "particles". Item ids look like `Dock-TS-CSS`, `Stepper-TS-CSS`,
`AnimatedList-TS-CSS`, `ElasticSlider-TS-CSS`, `SplitText-TS-CSS`, `BlurText-TS-CSS`,
`AnimatedContent-TS-CSS`, `FadeContent-TS-CSS`, `GooeyNav-TS-CSS`, `StaggeredMenu-TS-CSS`,
`CardNav-TS-CSS`, `Stack-TS-CSS`, `CardSwap-TS-CSS`, `Folder-TS-CSS`, `Masonry-TS-CSS`,
`ScrollStack-TS-CSS`, `MagicBento-TS-CSS`, `TiltedCard-TS-CSS`, `GlassSurface-TS-CSS`,
`Silk-TS-CSS`, `Aurora-TS-CSS`, `Iridescence-TS-CSS`, `DarkVeil-TS-CSS`, `Counter-TS-CSS`,
`CountUp-TS-CSS` — verify each in the registry, the list is from memory. Install with
`npx shadcn@latest add @react-bits/<Id>` (CSS variants, no Tailwind). On Windows the CLI may write
into a literal `@/components` folder — move the files to `src/components`. `npm i motion` (React Bits
imports `motion/react`). Do NOT use `GridScan` (face-api.js) or `DecryptedText` (scrambles facts).
Never copy React Bits source outside your app dir.

## Deliverables (inside your own dir; touch nothing outside it)

A Vite + React 18 + TypeScript app, `base: './'`, `npm run build` exit 0, with these navigable
surfaces, all reading `fixture.json` from `public/`:

- `cockpit` — the trio for the active project, with project tabs, the order timeline, ⌘K reachable.
- `library` — the Knowledge Library (tree, a page with backlinks, module page with managed notes).
- `settings` — the settings sheet, Routing & Rights section open, locked cells as statements.
- the ⌘K palette open over the cockpit.

Screenshots, 1440×900, 2.5 s settle, motion running, saved in your dir as `cockpit.png`,
`library.png`, `settings.png`, `palette.png`. Use `?screen=cockpit|library|settings|palette` query
routing so the measurement lane can reach each screen by URL. Read your own PNGs and fix what is
broken or empty. Then `NOTES.md`: the design point of view in three sentences, every React Bits item
used and WHAT STRUCTURAL ROLE it plays, fonts, theme, what you deliberately left out, install failures
verbatim. Verify in the foreground; no monitors.

The anti-slop linter (`daedalus/gui/lint.py`) will run on `cockpit`: framed panels ≤ 8, visible
elements ≤ 150, status pills 0, one radius scale, nesting ≤ 2, contrast AA, targets ≥ 44 px.
