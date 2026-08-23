# Atelier — Daedalus v3

## The concept, in three sentences

A quiet dusk-grey room holds one object and one conversation. The object is the
codebase: four depth sheets of nodes, code nearest the eye and knowledge
farthest, drifting until the pointer touches them; the conversation is Ikarus, a
glass window standing beside the object, where every claim ends in how it knows
and every citation is a door into the forest. Everything else is an ornament —
project tabs above, view and lens controls hanging off the bottom edge of the
forest, one status sentence below, and an inspector that takes width from the
forest rather than covering it.

---

## What came from where

| Source app | What was lifted | What changed |
| --- | --- | --- |
| `spike3/sequoia2` (the whole app was copied first, `node_modules` included) | the state model (`state.tsx`), `actions.ts`, the fixture contract in `data.ts`, Palette, Settings, Library, Inspector, the Ikarus thread, the honest empty-project state, `AnimatedList` / `Stepper` / `FadeContent` | recomposed into a room; provenance became a word instead of a letter; citations became labelled deep links; the decision moved into the thread; Settings became a sheet; the palette gained prefixes, categories, a focus trap and lost its silent default target; the status sentence became per-project |
| `spike/scene/src/Forest.tsx` (round 1) | the four depth sheets with `SHEET_Z`, per-lens layouts of the *same* nodes, drei `<Line>` edges rebuilt every frame from live node positions, drei `<Html>` labels, the slow camera sway, the invisible generous hit target | the sway became a ±3° head-on drift that stops on pointer-over; sparkles, additive glow sprites, the emissive rim and the fog were removed; the hit target became a real 44 px DOM button; the layout was rewritten (`forestLayout.ts`) with barycentre sweeps, a sideways fan and a vertical stagger; plane identity moved from colour to shape |
| `spike2/visionos/src/components/GlassSurface.*` | the component, its displacement-map SVG filter, the resize observer, the SVG-vs-fallback split | the material was rewritten (see the measured note below); `light-dark()` was replaced with the room's own tokens |
| `spike2/visionos/src/components/Dock.*` | the ornament panel, the proximity spring, the hover label | became a real `role="tablist"`, carries full project names, the hover label carries the watcher word, Space is `' '` not `''` (upstream typo), arrow keys move between tabs, magnification is off when Motion is off |

Exact versions installed, as the brief required: `three@0.185.1`,
`@react-three/fiber@8.18.0`, `@react-three/drei@9.122.0`, `@types/three@0.185.4`,
on `react@18.3.1`.

### [MEASURED] Why GlassSurface.css was adapted rather than overridden

Upstream `.glass-surface--svg` sets `backdrop-filter: var(--filter-id)
saturate(...)` and `background: light-dark(...)`. Measured in Chromium at
1440×900 against the built app:

- `light-dark()` with no declared `color-scheme` computes to nothing, so
  `background-color` resolved to `rgba(0, 0, 0, 0)` — there was no frost at all.
- With only the SVG displacement in the chain, an 860 px sheet left its backdrop
  **sharp**; the forest and the Ikarus text behind the Settings sheet were fully
  legible through it and the sheet was unreadable.
- Overriding from `styles.css` did not work twice over: `GlassSurface.css` is
  imported after it and wins on order, and when the override was raised to
  `.glass-surface.glass-surface--svg`, lightningcss dropped the unprefixed
  `backdrop-filter` from the emitted rule and only `-webkit-backdrop-filter`
  survived, which lost the cascade to upstream's unprefixed declaration.
  Verified by grepping `dist/assets/*.css` and by reading the computed style off
  the live page.

So the material lives in `src/components/GlassSurface.css`, with the adaptation
written at the top of the file. The displacement stays on as a rim refraction
over a real frost (`blur(20px) saturate(1.5) brightness()`), and
`distortionScale` was reduced from −180 to −48/−40 because at −180 a large pane
threw visible chromatic fringes across its whole edge.

---

## React Bits, and the structural job each one does

Registry ids were confirmed against `@react-bits` through the shadcn MCP
(`search_items_in_registries`); `components.json` points at
`https://reactbits.dev/r/{name}.json`.

| Registry id | Where | Structural role |
| --- | --- | --- |
| `GlassSurface-TS-CSS` | the Ikarus window, the inspector, the library, every sheet, the palette | the window material itself. Without it there are no windows, only rectangles. |
| `Dock-TS-CSS` | the project tabs ornament | the ornament panel and, more importantly, its hover label — which is where the watcher state word lives. The proximity spring is the hover shape visionOS asks every interactive element to have. |
| `Stepper-TS-CSS` | the six mission stages inside the Ikarus header | owns the stage row *and* the one-line detail beneath it: selecting a stage swaps the sentence. `hideFooter` / `hideConnectors` / `stepContainerProps` are additive adaptations. |
| `AnimatedList-TS-CSS` | the Ikarus thread, and the palette list | owns the scroll container, the transcript's follow-to-bottom, the palette's active row, `aria-activedescendant` and row entrance. Adapted so the read-only transcript does not scale on entry (see the audit note). |
| `FadeContent-TS-CSS` | cockpit ↔ library, inspector node ↔ summary, settings section swaps | the pane transition, with a real reduced-motion path: at Motion Off the GSAP timeline is never created. |

No React Bits background, text effect, orb, beam or cursor component is used,
and no React Bits source was written outside this app directory.

---

## The control table

Every row below is an assertion in `verify.cjs`. **84 passed, 0 failed.**
Run it with `npm run verify`.

| Control | What happens | State |
| --- | --- | --- |
| Project tab (Dock) | switches project; forest, thread, inspector, palette rows and the status sentence all change | works |
| Project tab hover | the watcher word appears ("Watcher live" / "Watcher idle") — dot plus label, never colour alone | works |
| Project tab ← → | moves selection and focus together | works |
| `Ctrl-K` / `⌘K` | opens the palette; the same key and Esc dismiss it | works |
| Palette `@` / `#` / `>` | restricts to nodes / pages / commands; categories print inline | works |
| Palette, empty | recents first, then everything | works |
| Palette → Distill | focuses the slice on the chosen module; the slice sentence changes | works |
| Palette → Distill, no target | **disabled**, prints "No module chosen. Select one in the forest, or type its name here." | disabled + printed |
| Palette → Focus | selects and re-centres on that node | works |
| Palette → What changed | rings the 2 modules with recorded churn and says churn is recorded for 2 of 32 | works |
| Palette → Hotspots | switches to the Cost lens and says cost is measured for 2 of 32 | works |
| Palette → Canary | **disabled**, prints "Needs the Daedalus service. Nothing can run from this prototype." | disabled + printed |
| Palette → Council | opens the three vendor opinions verbatim, unscored | works |
| Palette → Doctor | lanes, resolved hosts, and the statement that no key is held | works |
| Palette → Open the knowledge library | replaces the forest area, Ikarus stays | works |
| Palette → Open settings | opens the glass sheet | works |
| Palette → Show the ordered columns / spatial forest | toggles the view | works |
| Palette → Reset the view / Arm / Disarm | resets the camera / opens the kill-switch confirm | works |
| Spatial / Ordered | the same 32 nodes morph between depth sheets and four flat columns over ~600 ms | works |
| Lens Structure / Evidence / Cost | Cost rings measured fan-in and draws unmeasured nodes hollow; any lens change reveals all relations | works |
| Depth 1 · 2 · All | 1 and 2 are the local graph around the selection, All returns the whole forest bright | works |
| Depth, nothing selected | **disabled**, prints "Depth is off until a node is selected — it re-centres the forest on that node's local graph." | disabled + printed |
| Reset view | camera back to head-on, selection cleared | works |
| Focus the slice | re-centres on the distilled module | works |
| Focus the slice, nothing distilled | **disabled**, prints "no module has been distilled yet, so the index does not record which modules the slice holds" | disabled + printed |
| Node click (44 px disc) | selects; unrelated nodes dim to 30 %; relation labels appear; the inspector opens | works |
| Node hover | reveals that node's full relations and its neighbourhood labels | works |
| Drag / wheel on the forest | orbits (clamped ±26°) / zooms (5.6–14) | works |
| Citation hover | lights that node in the forest | works |
| Citation click | selects it and focuses the camera | works |
| Approve | Build → done, Gates → running, a follow-up Ikarus message, the card records the decision | works |
| Reject | the build waits for attempt 19 and says how many are now rejected | works |
| Why | prints what the proposal rests on, stamped measured | works |
| Undo the decision | the proposal comes back | works |
| Composer, empty | Send **disabled**, prints "Send is off until you type a question." | disabled + printed |
| Composer, typed + Enter | appends your turn and an honest system notice, streamed | works |
| Attach selection | adds the selected node's name to your question | works |
| Attach selection, nothing selected | **disabled**, prints "Nothing is selected, so there is nothing to attach." | disabled + printed |
| Use-case starters | two, only under an empty composer with nothing selected | works |
| Follow-ups | only with a selection, and derived from it | works |
| Inspector tab "Knowledge" | opens the panel; the forest yields width, it is never covered | works |
| Open its wiki page | opens that page in the library | works |
| Open its wiki page, no page | **disabled**, prints "No page in the library carries this node's name." | disabled + printed |
| Ask Ikarus about this | seeds the composer with the node and focuses it | works |
| Clear selection / Close | drops the selection / collapses the panel | works |
| Library tree | ↑ ↓ Home End move, → ← expand and collapse a group | works |
| Library page | module pages carry the index paragraph and your notes | works |
| Write it again from the index | rewrites the automatic paragraph, keeps your notes | works |
| Show in the forest | back to the cockpit with that node selected | works |
| Show in the forest, no node | **disabled**, prints "This page has no node in the current index." | disabled + printed |
| Settings tabs | ← → ↑ ↓ move selection *and* focus | works |
| Preferred route / rights per runtime | change and persist | works |
| Locked runtime cells | statements ("Codex never writes."), not controls | by design |
| Local traffic may leave this machine | flips, and the status sentence changes with it | works |
| Spending ceiling | slider, with the spent figure beside it | works |
| Remember / Do not remember / Retention | change and persist | works |
| Delete everything | confirm dialog, clears browser state only, says so | works |
| The room: Dusk / Day room / Auto | repaints room, glass, forest solids and edge colours | works |
| Accent Blue / Amber / Green / Graphite | changes only the interactive-state colour | works |
| Motion Full / Calm / Off | Off stops the drift and the morph, and the forest says so | works |
| Text size Default / Large | scales the interface type | works |
| Run the watcher (unindexed project) | **disabled**, prints "Needs the Daedalus service. This prototype has no backend to start it with." | disabled + printed |
| Kill switch Arm / Disarm | confirm dialog, then the status word changes | works |

Nothing is claimed to be operable that is not. Everything needing the Daedalus
service is disabled and says which service it needs.

---

## The fake-data test

`npm run build` is `tsc -b && vite build && node fakedata.cjs`, so a project
wearing another project's data fails the build. Latest run:

```
fake-data test — projects on screen: Daedalus, TCT scan planner, Lehrstuhl wiki

reference (Daedalus)
  status      : The Claude lane resolves to api.anthropic.com; $0.41 and 12,480 tokens spent today. measured
  palette rows: 32 nodes
  own pages   : 5 — Sealed promotion | Evidence boundary | Gate 0 — what exit means |
                daedalus/policy/enforce.py | daedalus/ledger.py
  global pages: How we review | Reading list — evolution
  PASS  the indexed project does have an index

TCT scan planner
  status      : No lane is running on TCT scan planner and nothing has been spent on it
                today — the watcher is idle and no index has been compiled. measured
  palette rows: 0 nodes (Nothing in TCT scan planner matches “@”.)
  own pages   : 0 — none
  global pages: How we review | Reading list — evolution
  PASS  the status sentence is not Daedalus's
  PASS  the status sentence names this project or says nothing ran
  PASS  the palette offers none of Daedalus's node rows
  PASS  it offers none of Daedalus's own pages
  PASS  no page body under this project equals a Daedalus page body
  PASS  the shared global library is still offered, and labelled as global
  PASS  the tree says plainly that it has no pages

Lehrstuhl wiki
  … the same seven assertions, all PASS

fake-data test: every project is scoped to its own index.
```

**[MEASURED] the test was proved to go red.** Three mutations were applied and
the build re-run: `statusSentence` made to ignore `p.indexed`, `Library` handed
every project `fx.library.project_wiki` and `fx.library.module_pages`, and
`Palette` handed every project `fx.graph.nodes`. Result: **12 assertions failed**
and the build was refused. The mutations were reverted; the current tree passes.

One thing the test deliberately does *not* forbid: the two global library pages
are shared by every project, because they are global and labelled "Read by every
project". The test asserts that they *are* shared and that everything under a
project's own wiki is not. The first version of the test flagged them, which is
how that distinction got made explicit.

---

## Targets and contrast, counted properly

`npm run audit`. Every target is counted — including the 32 invisible 44 px hit
discs the forest draws over its 3D nodes, and anything inside an `<svg>`. The
round-2 audit excluded `el.closest('svg')` and read only the first three numbers
of an `rgba()` colour; both are fixed here, and the contrast pass composites the
text alpha *and* every translucent ancestor background down to an opaque base
before taking the ratio, so a label on glass is scored as it is actually painted.

```
── cockpit            interactive  71  (3D hit discs 32, inside svg 0)
── cockpit-selected   interactive  77  (3D hit discs 32)
── cockpit-ordered    interactive  71  (3D hit discs 32)
── library            interactive  44  (3D hit discs 0)
── settings           interactive  86  (3D hit discs 32)
── palette            interactive 123  (3D hit discs 32)
── dayroom            interactive  71  (3D hit discs 32)

true smallest interactive target : 44px — div[role=tab].dock-item "Watcher live"
targets under 44px               : 0
AA contrast failures             : 0
radii in use                     : 50%×213, 8px×195, 12px×152, 999px×44, 20px×35
```

**The true minimum is 44 px, and that number includes the 3D hit discs.**
The radii census is the concentric set the brief asked for — 20 outer, 8 padding,
12 inner, plus pills and circles for dots and discs; nothing else is in use.

Five real defects the audit found and forced fixes for:

1. `.cite`, `.suggest`, `.linkbtn`, `.twist`, `.seg button`, the switch and the
   slider were all under 44 px. All raised. `.linkbtn` needed `min-width` too —
   "Why" was 44 px tall and **29 px wide**, which is a 29 px target.
2. `AnimatedList` rests its items at `scale: 0.98` until they enter the
   viewport, so every control inside an off-screen transcript item measured 2 %
   under its declared size (43 px, not 44). The read-only list no longer scales.
3. The accent was carrying the word "Running" in the stage row at 4.26:1. The
   accent is now reserved for what the pointer or the keyboard is on, and the
   live stage is marked by weight instead.
4. The tertiary vibrancy tier failed AA in several places (3.67:1 on "4 pages
   link here"). Both themes' tiers were re-tuned until the audit was clean.
5. The compact ornament shrank its depth buttons to 40 px, and "Reset view" was
   clipped off the right edge. Both fixed — and the ornament is now centred by a
   full-width bar, because an absolutely positioned flex box at `left: 50%` only
   gets the space to its right to lay out in and was wrapping at half width.

---

## Screenshots

`npm run shoot`. Chromium is launched with `--no-proxy-server` and
`--proxy-bypass-list=<-loopback>` (a system proxy swallowed loopback traffic in
the last audit) plus SwiftShader for WebGL, against `dist/` served by a Node
http server. Every shot settles 1.4 s + 2.5 s with motion running, in a fresh
browser context.

`cockpit.png` · `cockpit-selected.png` · `cockpit-ordered.png` ·
`cockpit-decision.png` · `library.png` · `settings.png` · `palette.png` ·
`dayroom.png`, all 1440×900, and `cockpit-1200.png` at 1200×800.

All nine were read back and fixed until they were right. The bugs the reading
found, in order: the Dock landed at the bottom of the window instead of the top
(GlassSurface-style cascade problem again — `Dock.css` also loads last); the
Ikarus thread had no height and the decision card was cut in half; four hub
labels stacked on one another because a barycentre sweep aligns connected nodes
across planes and therefore projects them onto each other; the library's page
column did not render at all (the outer grid had one child); the Settings sheet
was transparent; and the day room's forest was near-white on near-white.

---

## The forest, and where it departs from a literal reading of the brief

- **Fanned, not stacked.** Four sheets seen exactly head-on project onto one
  another, and the barycentre sweep that makes cross-plane links run straight
  through the stack makes that worse, not better — connected nodes land on the
  same pixel. The sheets are therefore fanned sideways and staggered vertically
  as they recede (`SHEET_X`, `SHEET_Y`). It is still four depth sheets with code
  nearest; it reads as an exploded view rather than a deck.
- **A screen-space declutter pass** projects every visible label each frame,
  sorts by height and pushes overlapping ones apart. At rest that is four
  labels; on selection it is the neighbourhood.
- **Shape carries the plane**, not colour: box Code, diamond Type, disc Data,
  sphere Knowledge, with a depth key at the top-left of the room. That keeps the
  one accent free for interactive state and stays legible in greyscale.
- **At rest the forest draws 25 of 38 relations** — every verified intra-plane
  edge plus the six strongest cross-plane links — and labels one node per sheet.
  The sentence under the forest says exactly that. Hover, selection or a lens
  change reveals the rest.
- **Drift stops on pointer-over**, not only on selection. Playwright refused to
  click a node because it never stopped moving, which is the same problem a hand
  has.

---

## What is unfinished

1. **Motion Calm and Full differ only in duration.** The drift speed is the same
   in both; only Off stops it.
2. **The Evidence lens changes nothing but visibility.** It reveals all
   relations and shows the two proposed edges as dashed, but there is no
   evidence-specific layout the way round 1 had one. Honest, but thin.
3. **The Cost lens has measured data for 2 of 32 nodes.** The fixture carries
   fan-in for the two module pages only. The interface says so and draws the
   rest hollow rather than guessing, but a project-wide cost lens is not
   demonstrated.
4. **No keyboard traversal inside the forest.** Tab reaches all 32 hit discs in
   DOM order and Enter selects, but there is no "move to the next neighbour" key
   and no roving tabindex, so tabbing through the forest is 32 stops.
5. **Text size Large does not scale the forest labels.** They are fixed at 13 px
   because they are positioned in screen space; only the interface type scales.
6. **The transcript can settle mid-turn.** It follows the newest message, so the
   top of the visible area is often a partial paragraph. A gradient mask makes
   that read as scrolled rather than broken, but it is not art-directed.
7. **Ordered view truncates two long labels** (`.agentenv/tool-allowances.js…`,
   `Master Plan §4 Invariants` at 1200 px). The full name is in the `title`
   attribute and in the inspector.
8. **The Dock's magnification only drives height.** Full names need `width:
   auto`, which overrides the proximity spring's width, so the magnify reads as
   a slight lift rather than macOS-style scaling.
9. **`?screen=` and `?state=` are initial state, not a router.** They set the
   app up once on load; navigating afterwards does not change the URL.
10. **The council opinions appear in two places** — the inspector's empty state
    and its node state — which is one place too many.
11. **No hover-state screenshot.** Hover behaviour is asserted in `verify.cjs`
    but not photographed.
12. **The day room's glass could be stronger.** It passes AA everywhere and the
    forest reads, but the panes sit closer to the wall than they do at dusk.

---

## Running it

```
npm install          # three 0.185 / fiber 8 / drei 9 are already in package.json
npm run build        # tsc -b && vite build && node fakedata.cjs   (exit 0)
npm run verify       # 84 control-table assertions
npm run audit        # targets, contrast, radii, element counts
npm run shoot        # the nine screenshots
npm run dev          # http://localhost:5301
```

Query hooks: `?screen=cockpit|library|settings|palette`,
`?state=selected|ordered|decision`, `?theme=dusk|day`.
