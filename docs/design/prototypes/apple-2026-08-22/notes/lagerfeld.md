# P4 · Lagerfeld — monochrome couture

## Point of view

Black ink on white paper, nothing else: the one accent is a single 3 px red dot on the live watcher, and every other state is carried by weight, size and a hairline. The page is held by one giant thin display word (the project name, 140 px at weight 100–300 that firms up under the pointer) against 12–15 px precise text on an asymmetric 384 / fluid / 352 grid with deliberate emptiness. The graph is drawn as ink — dots, solid verified strokes, dashed grey proposals with their score — on one canvas, so it reads like a plate from a book, not a dashboard.

## React Bits items (all verified in the @react-bits registry before install; CSS variants)

| Item | Role | Structural? |
| --- | --- | --- |
| `TextPressure-TS-CSS` | The hero title of the Codebase panel — the only display-scale type on the screen; weight axis driven by pointer distance on "Segoe UI Variable Display" (a real variable font), `fontUrl=""` so no Google Fonts dependency, `text-transform` overridden to sentence case. | yes — primary text entrance / hero |
| `Stepper-TS-CSS` | The mission order timeline Intent → Plan → Build → Gates → Delivery → Digestion. Custom `renderStepIndicator` renders stage names with done / live / waiting state; the step content shows the stage note; footer buttons hidden, indicators are the navigation. | yes — navigation + data display |
| `Stack-TS-CSS` | Receipts as a deck of white cards (signed receipts, evidence packets, attempts, withheld) — drag or click to send to back. | yes — data display |
| `ElasticSlider-TS-CSS` | The spending ceiling control in Settings › Routing & Rights (0–10 $, stepped 0.5, starts at the fixture's 2.0). | yes — control |
| `AnimatedContent-TS-CSS` | The one orchestrated entrance: every column block arrives with a staggered 16 px rise; disabled when motion is "Off". | yes — transition |
| `AnimatedList-TS-CSS` | The ⌘K command palette result list (arrow navigation, selection, enter). | yes — navigation / control |
| `LineSidebar-TS-CSS` | The Knowledge Library page tree (global library / project wiki / module pages) with the proximity marker. | yes — navigation |
| `ChromaGrid-TS-CSS` | The library shelf: the page grid, greyscale by construction (typographic plates rendered as SVG from each page's initial; its overlay/fade removed so it is ink on paper). | yes — layout / data display |
| `Magnet-TS-CSS` | On the few real controls: the three quick actions and "Focus the slice". | decoration-adjacent (interaction feel) |
| `LiquidChrome-TS-CSS` | The only material: a greyscale chrome field at 3.5 % opacity, masked to the title block, behind the display title. | material (background) |

Eight of ten carry real UI.

## Fonts

System stack only: `-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Segoe UI Variable Display", "Segoe UI", system-ui, sans-serif`. Display title uses the Segoe UI Variable weight axis (SF Pro Display on macOS). Monospace (`ui-monospace, SF Mono, Menlo, Consolas`) only for paths, hosts, receipt ids and evidence locators.

## Theme

Light by default: paper #FFFFFF / #F5F5F7, ink #000000 / #1D1D1F, secondary #6E6E73 (slight cool bias), hairlines at 14 % / 6 % black. Dark inverts the same tokens (#000000 / #1D1D1F, #F5F5F7 / #86868B); Settings › Appearance › Light / Dark / Auto switches live. One radius scale (12 px cards, 20 px sheet, 8 px segmented control). 8 pt grid throughout. Provenance M / I / A as a small superscript letter with a tooltip.

## Deliberately left out

Colour of any kind beyond the one red dot; icons (the only glyphs are ⌘K and ↑); filled buttons outside the segmented control; status pills, tile rows, borders around panels (columns are separated by one hairline); glow, glass, scanlines; the Stepper's own "Back / Continue" footer; ChromaGrid's spotlight and colour-reveal overlay (the grid is greyscale content, not a greyscale filter); a tabbed settings nav with icons. Backdrop-filter was replaced by a real blur + desaturation on the page under sheets, because the headless screenshot renderer did not apply `backdrop-filter` consistently.

## Install failures (verbatim)

`Silk-TS-CSS` — attempted twice, failed twice (peer dependency: React 18 pinned per brief, Silk pulls `@react-three/fiber@^9.3.0` which requires React 19):

```
npm error   @react-three/fiber@"^9.3.0" from the root project
npm error
npm error Fix the upstream dependency conflict, or retry this command with --force or --legacy-peer-deps to accept an incorrect (and potentially broken) dependency resolution.
...
Could not resolve dependency:
peer react@">=19 <19.3" from @react-three/fiber@9.7.0
node_modules/@react-three/fiber
  @react-three/fiber@"^9.3.0" from the root project
```

Substituted with `LiquidChrome-TS-CSS` (ogl, no peer conflict) for the material role. `FlyingPosters` was not attempted — it is a scroll-driven WebGL poster carousel and needs raster images; `ChromaGrid` took the library role instead. `ScrollVelocity` / `ShinyText` were not needed once `TextPressure` worked with the system variable font.

## Verification

`npm run build` exit 0 (tsc -b + vite). Served `dist` on 127.0.0.1:5194 and captured the four 1440×900 screenshots with playwright-core after a 2.5 s settle with motion on; each PNG was read and fixed through four iterations (chat overflow, graph label collisions, CSS cascade order against component styles, a `--r` variable collision with ChromaGrid that turned cards into ovals, veil stacking, palette list height). No console errors on any screen.
