# P3 · Sequoia — notes

## Point of view
Sequoia is the macOS app Apple would ship for Daedalus: a translucent sidebar carrying the project tabs and the library tree, a toolbar with the lenses and the slice state, a split view with the living codebase atlas in the content area and the Knowledge inspector on the right, and Settings as a System-Settings sheet. Type carries every surface — one blue, sentence case, system font, hairlines instead of frames — and depth comes from material and a single orchestrated entrance rather than borders or glow. The one deliberate risk is the Routing & Rights matrix: locked cells are sentences in the body face ("Codex never writes."), not greyed controls or lock icons.

## Surfaces (`?screen=`)
- `cockpit` — trio: Ikarus (chat with M/I/A provenance, withheld named, order timeline, quick actions) · Codebase (canvas atlas, four plane columns, verified solid / proposed dashed, hover neighbours, click → inspector, three lenses morph the same nodes, "Focus the slice") · Knowledge (selection, architecture counts, distillation receipts, council verbatim).
- `library` — Masonry overview of global library + project wiki + module pages, page "Sealed promotion" with provenance, open question, Linked from, Show on the atlas; module page (auto stats regenerated, hand notes that survive) in the inspector.
- `settings` — sheet, Routing & Rights open: route segmented control, "Local may leave this machine" switch (drives the status-line warning), spending ceiling ElasticSlider, rights matrix with statements. Memory & Privacy and Appearance are operable; Appearance → Dark switches the whole app (data-theme on root; Auto follows the OS).
- `palette` — ⌘K / Ctrl-K over the cockpit; arrow keys + return; every verb routes back to a decision.

## React Bits items (all `-TS-CSS`, installed via `npx shadcn@latest add @react-bits/<Id>-TS-CSS`, verified in the registry first)
| Item | Structural role |
| --- | --- |
| `StaggeredMenu` | The app's "Go" drawer (top of sidebar): navigation between the four surfaces plus the project list. Real navigation, restyled to sentence case. |
| `AnimatedList` | Carries the Ikarus chat transcript (rows are the messages with provenance meta) and the command palette list with arrow-key navigation. Generalised in-app from `string[]` to `ReactNode[]`. |
| `Stepper` | The order timeline Intent → Plan → Build → Gates → Delivery → Digestion; custom indicators carry the per-stage state, the step content shows the stage note. Footer buttons hidden by CSS. |
| `ElasticSlider` | The spending ceiling control in Routing & Rights (0–$10, stepped, reports value). Chakra/react-icons imports replaced by plain spans in-app; `onChange` added. |
| `Folder` | Distillation receipts in the Knowledge inspector; the three papers carry receipt / event / packet identifiers from the fixture. |
| `Counter` | Live token count in the toolbar spend readout. |
| `FadeContent` | Inspector selection transition (keyed on the selected node) and settings section transition. |
| `AnimatedContent` | Page entrance for inspector sections and the library page. |
| `Masonry` | The library overview grid (global / wiki / module pages). Generalised in-app to accept `content` nodes and an `onSelect` instead of images + `window.open`. |

Nine items; six carry real UI (menu, lists, stepper, slider, folder, masonry), two are transitions, one is data display.

## Fonts & theme
System stack only: `-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Segoe UI Variable Display", "Segoe UI", system-ui, sans-serif`; `ui-monospace` only for identifiers and receipts. Light by default (#F5F5F7 / #FFFFFF, labels #1D1D1F / #6E6E73), dark (#000 / #1D1D1F, #F5F5F7 / #86868B) via Appearance. One accent #0071E3 (#2997FF in dark). Radii: 12 px containers, 8 px controls. 8 pt grid. Semantic colour only for state (live dot, proposed edges, withheld, delete). `prefers-reduced-motion` and Motion = Off stop the transitions and the atlas spring.

## The atlas
Drawn on one `<canvas>` (keeps the cockpit DOM small for the linter): four plane columns, nodes stack with labels beside them, cross-plane edges as beziers, unverified proposals dashed in orange with their score shown when focused. Hover lifts the neighbourhood; click selects and the selection flows into the inspector. Lenses: structure (kind-sized), evidence (size = verified-edge count, proposals emphasised), cost (compacted by degree with an honest note: no per-node cost is measured; only the slice totals are).

## Deliberately left out
- No background component, no glass over content — the only material is the translucent sidebar and the sheets.
- No provenance pills, no status pills, no metric tile rows, no icons for locks, no all-caps chrome.
- No chat scrolling state persisted; chat is an interface, not the workflow.
- No invented body for the library pages whose body is not in the fixture ("How we review", etc. show the path and say so).
- Accent picker offers one swatch only — one accent is the rule.
- Page tree lives once, in the sidebar; the library inspector is the module page, not a second tree.

## Install failures
None. All nine items installed on the first attempt into `src/components` (aliases from `components.json`). Only in-app edits: `ElasticSlider` (dropped `@chakra-ui/react` and `react-icons`, added `onChange`/`showValue`), `AnimatedList` (ReactNode rows, softer entrance, margin moved to a class), `Masonry` (content nodes, `onSelect`, optional images), `Folder` (unused-parameter rename for strict TS), `StaggeredMenu` ("Socials" → "Projects").

## Build / screenshots
`npm run build` exit 0 (Vite 8, React 18.3, TS strict). Screenshots 1440×900 after 2.5 s with motion running via `shoot.cjs` (playwright-core from apps/web): `cockpit.png`, `library.png`, `settings.png`, `palette.png`. Dark theme, node selection, palette run and lens switch were exercised in a throwaway Playwright pass with zero page errors.
