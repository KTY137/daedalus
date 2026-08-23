# Verdict

This is a capable engineering prototype with weak visual judgment. It reads as a generic grey “AI operations cockpit,” not an Apple-grade product. The main failures are the clipped hero conversation, auto-laid-out graph collisions, card-and-pill soup, tiny typography, ambiguous controls, and behavioral claims that exceed the evidence.

## Audit scope

Reviewed the binding [BRIEF.md](C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/c46c7615-e718-4fa6-8756-9c4b7ccdd61b/scratchpad/spike4/BRIEF.md), [NOTES.md](C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/c46c7615-e718-4fa6-8756-9c4b7ccdd61b/scratchpad/spike4/atelier/NOTES.md), relevant source, and the four supplied 1440×900 states.

1. Cockpit at rest — **Poor:** core composition exists, but Ikarus is clipped and visually subordinate to chrome.
2. Node selected — **Poor:** selection model is visible, but labels collide and the inspector is overfilled.
3. Ordered view — **Poor:** four columns are inferable, but the layout lacks headers and editorial cleanup.
4. Command palette — **Poor:** functional skeleton, weak search affordance, hidden breadth, contradictory disabled state.

| Rest | Selected |
|---|---|
| ![Cockpit at rest](C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/c46c7615-e718-4fa6-8756-9c4b7ccdd61b/scratchpad/spike4/atelier/cockpit.png) | ![Cockpit with selection](C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/c46c7615-e718-4fa6-8756-9c4b7ccdd61b/scratchpad/spike4/atelier/cockpit-selected.png) |
| **Ordered** | **Palette** |
| ![Ordered view](C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/c46c7615-e718-4fa6-8756-9c4b7ccdd61b/scratchpad/spike4/atelier/cockpit-ordered.png) | ![Command palette](C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/c46c7615-e718-4fa6-8756-9c4b7ccdd61b/scratchpad/spike4/atelier/palette.png) |

## 1. AI-generated-design tells

- **Everywhere:** monochrome gradient, frosted rounded rectangles, hairline borders, tiny white text, one pale accent. This is the default “futuristic AI dashboard” recipe.
- **Top-left:** a capsule-shaped project switcher containing another white capsule. **Top-right:** unrelated revision, Settings, and Search snippets floating without toolbar structure. They look assembled from separate component generations.
- **Ikarus header:** the six two-line stage cells are exactly the status-tile dashboard pattern the brief forbids. The selected Build tile is yet another card inside glass.
- **Ikarus body:** citation chips, suggestion chips, a large decision card, an outlined textarea, provenance badges, and explanatory footnotes create card/chip soup rather than conversation.
- **Transcript top:** the first visible message begins midway through a faded sentence. NOTES admits this can happen; the gradient mask does not make clipping look intentional.
- **Copy everywhere:** “Canonical Kernel,” “Slice warm,” “Distill,” “Canary,” “Council,” “Doctor,” “Sealed promotion,” and “Kill switch armed” are metaphor accumulation, not a coherent product vocabulary.
- **Left footer and canvas footer:** the UI explains its own implementation and test contract—relations drawn, token accounting, disabled-state mechanics, provenance rules. This reads like generated acceptance criteria pasted into the product.
- **Language:** the clipped German statement inside an English interface reads as fixture residue because its speaker label has scrolled away.
- **Spatial graph:** beveled cubes, diamonds, discs, spheres, nested grids, and crossing lines resemble a Three.js technology demo. Node size and position do not communicate obvious meaning.
- **At rest:** 25 of 38 relations is still a hairball. Most nodes are anonymous while the visible edges provide little usable structure.
- **Selected graph:** the file label, `imports`, two `defines` labels, symbols, and lines collide around the selected node. This is algorithmic placement without an editorial cleanup pass.
- **Ordered graph:** blocks nearly touch, labels cross geometry, one path is ellipsized, and “Receipt” falls below its diamond unlike neighboring labels. The layout visibly exposes its algorithm.
- **Ordered graph:** no column headers or lane containers. A detached shape legend is expected to explain the whole representation.
- **Right edge:** rotated “Knowledge” resembles an axis label and conflicts with Knowledge also being a graph plane.
- **Inspector:** “Knowledge,” “Clear selection,” and “Close” form a crowded header with unclear distinctions. Council content is cut off without a visible continuation cue.
- **Palette:** stock centered glass modal, flat rows, descriptions pushed to the far right, and a tiny syntax footer.
- **Palette:** “Type a command…” resembles a heading more than a focused text field; there is no visible caret, search symbol, or field shape.
- **Palette:** unavailable “Distill” is nevertheless the highlighted active row—a screenshot-first inconsistency.
- **Across states:** repeated phrases and concepts—Attempt 18, Knowledge, Focus the slice, provenance, lane state—create mechanical redundancy.
- **Across states:** nearly every element uses the same four radii and border treatment. There is no crafted iconography or content-specific visual identity.

## 2. Apple/HIG violations

### Typography

- The mission title wraps to two lines despite the binding one-line, 20 px requirement.
- Live information drops to 10.5–11.5 px in the depth key, stage states, group labels, footer legend, and palette categories. The visionOS HIG uses 17 pt as its default and 12 pt as its recommended minimum. [Apple Typography](https://developer.apple.com/design/human-interface-guidelines/typography)
- The primary Ikarus body is `font-weight: 450`, not the requested medium weight.
- Dusk `--lab2` and `--lab3` are both `rgba(255,255,255,.76)`, eliminating the claimed secondary/tertiary vibrancy hierarchy.
- Graph text is technically screen-aligned, but shadows, crossings, and overlapping geometry still make it difficult to read.
- Sentence case largely passes. The actual problem is inconsistent grammar and naming: “Kill-Switch” versus “Kill switch,” stacked fragments such as “Build / Running,” proper-title jargon, nouns, and commands mixed without a consistent voice. Apple recommends consistency by element type. [Apple Writing](https://developer.apple.com/design/human-interface-guidelines/writing)

### Spacing and hierarchy

- Ikarus is called a hero, but header, stage matrix, proposal card, starters, composer help, and provenance legend leave only a shallow strip for conversation.
- Dense left-pane chrome sits opposite large unused canvas areas. The composition is mechanically divided, not balanced.
- The forest ornament uses 2 px gaps inside groups; starters use 6 px. This misses the brief’s 16 px and Apple’s spatial recommendation for regular controls to have centers about 60 pt apart with at least 16 pt separation. [Apple Spatial layout](https://developer.apple.com/design/human-interface-guidelines/spatial-layout/)
- Selected width removes the “Lens” and “Depth” labels, so controls become less understandable precisely when the screen becomes more complex.
- The inspector is externally positioned correctly but internally becomes an uninterrupted wall of facts, relations, prose, buttons, and Council copy.

### Colour, materials, deference, and depth

- The room, windows, cards, inspector, palette, and controls occupy nearly the same grey range. Glass reads as opaque plastic.
- Hierarchy comes mainly from borders and grey fills, not vibrancy or spatial layering.
- Secondary and tertiary colors are identical; active, inactive, and disabled elements consequently look alike.
- At rest, disabled Depth “1” still looks selected.
- The decision card and translucent control fills visually stack another material inside the Ikarus glass, violating the brief’s “nothing stacks on glass” intent.
- The palette produces blurred grey smudges rather than a controlled adaptive material. Apple’s glass guidance prioritizes translucency, legibility, and preserving surrounding context. [Apple Materials](https://developer.apple.com/design/human-interface-guidelines/materials)
- Ordered mode retains strongly shaded 3D geometry even though it is supposed to be the clear 2D alternative.
- Depth does not consistently convey hierarchy: grids recede, but nodes lack coherent occlusion, labels float over everything, and the selected relation cluster becomes flatter rather than clearer. Apple advises that depth add value and that readable text avoid unnecessary depth. [Apple Spatial layout](https://developer.apple.com/design/human-interface-guidelines/spatial-layout/)

### Controls and clarity

- The implementation meets its own 44 px floor, but most spatial controls do not meet the Apple 60×60 pt default target, and their spacing is too tight. [Apple Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility/)
- Spatial/Ordered, lenses, depth, and Reset are fused into one giant capsule. Segment widths are content-driven rather than balanced, contrary to segmented-control guidance. [Apple Segmented controls](https://developer.apple.com/design/human-interface-guidelines/segmented-controls)
- “Attach selection” and “Focus the slice” look like helper labels rather than controls.
- “Clear selection” and “Close” are adjacent, equally styled, and semantically overlapping.
- “Fan-in” combines “23 callers” with “4 calls out”; fan-in and fan-out should be separate facts.
- Relation lines lack direction. “imports of” in the inspector still does not resolve which node imports which.
- Approve receives the only strong primary treatment in what is framed as a neutral governance decision. Unless approval truly is the expected default, this biases a consequential choice.
- Graph nodes rely on invisible hit areas. A target can pass measurement and still fail affordance.
- An Apple-directed capture displaying `Ctrl-K` breaks the platform illusion; use `⌘K` for the Apple presentation or clearly frame the product as cross-platform.
- The palette has no visible dismissal affordance, unavailable options remain keyboard-highlightable, and most actions are below an un-signposted scroll area. Buttons and actions should communicate purpose and availability directly. [Apple Buttons](https://developer.apple.com/design/human-interface-guidelines/buttons)

### Accessibility and adaptability

- Project tabs’ accessible names are “Watcher live/idle,” not the project names, because Dock applies the tooltip string as `aria-label`.
- The depth legend is `aria-hidden`; plane information survives in individual node labels, but the overview itself is unavailable to assistive technology.
- Forest keyboard access requires tabbing through all 32 nodes; NOTES admits there is no roving navigation or neighbor traversal.
- Large Text does not scale graph labels.
- The transcript can snap back to the bottom on unrelated renders, interrupting reading.
- Council and palette content have no strong visible scroll cue.
- The supplied evidence demonstrates neither 1200/1680 reflow nor text-size resilience. Apple expects hierarchy and layouts to survive text and window changes. [Apple Layout](https://developer.apple.com/design/human-interface-guidelines/layout)

## 3. Feature visibility and operability

| Area | What is demonstrated | What is missing or unproven |
|---|---|---|
| Ikarus | Project, mission, stages, provenance, proposal controls, starters, contextual follow-ups, composer | One-line title; consistently visible speakers; citations beside the exact claim; named withheld kinds/locations; decided state, follow-up, Reject result, Undo; streaming |
| Forest | Four planes, depth grid, rest LOD, selection/dimming, relation labels, Spatial/Ordered controls, selected depth 1 | Hover neighborhood; drift pause; drag/orbit/zoom; camera recenter; 600 ms same-node morph; visible 44 px affordance; collision-free layout |
| Ordered | Four x-position groups and all node types | Explicit column headers/lanes; no truncation; consistent row alignment |
| Inspector | Width-yielding panel, facts, provenance, three verified relations, two actions | Wiki body; “Linked from” backlinks; proposed-edge example; empty architecture state; readable full Council section |
| Top/bottom | Full project names, revision, Settings/Search, status sentence, kill-switch state | Watcher word on hover, platform-appropriate shortcut, project-scoping result, confirmation dialog |
| Library/Settings/Appearance | Entry controls only | Library, backlinks, managed notes, settings sections, Day room, accent/motion/text-size states are absent from the supplied four frames |
| Palette | Input, command group, prefixes help, disabled reasons | Visible recents, node/page categories above the fold, per-row shortcuts, scroll cue, fuzzy-match result, every action being reachable |
| Honesty | Printed disabled reasons and labelled provenance | Withheld items contradict the brief: the UI explicitly says their names are withheld instead of naming kind and location |

Operability is not fully established. [verify.cjs](C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/c46c7615-e718-4fa6-8756-9c4b7ccdd61b/scratchpad/spike4/atelier/verify.cjs:1) contains meaningful Playwright assertions, but “every control-table row is asserted” is false. It does not cover, among other examples, project-tab hover, stage navigation, node hover/orbit/wheel, list scrolling, material behavior, or pane transitions. It also serves prebuilt `dist` without rebuilding, so it can pass stale output. I could not rerun it in this read-only environment because Playwright could not create its temporary directory.

## 4. React Bits: structure or garnish

| Component | Verdict | Concrete assessment |
|---|---|---|
| GlassSurface | **Structural** | It genuinely wraps Ikarus, inspector, library, palette, and sheets. However, `saturation` is passed into an unused CSS variable and backdrop blur is hard-coded, so some per-surface tuning is cargo-cult configuration. |
| Dock | **Mixed** | Project selection, roving tab stops, and arrow navigation are structural. The proximity spring is mostly garnish: CSS forces `width:auto`, leaving only a slight 44→50 px lift. The custom tooltip selector is mistyped as `.projdock .projdock .dock-label`, and accessible names expose watcher state instead of project names. |
| Stepper | **Structural, heavily gutted** | It owns selected-step content and transition. The actual buttons, states, ARIA, and keyboard model live in Ikarus, while footer/connectors are removed. This is a bespoke stage shell, not the intact general Stepper NOTES describes. |
| AnimatedList | **Structural for transcript; mixed for palette** | It owns scrolling, row wrappers, entrance motion, and transcript auto-follow. Palette itself owns `aria-activedescendant`, roles, IDs, and visible active styling, contrary to NOTES. Its blunt auto-follow is also what allows the hero transcript to settle mid-turn. |
| FadeContent | **Garnish — fails the binding test** | It is a `<div>` with a 4 px/opacity entrance tween. Parents already perform every pane swap. Remove it and structure, state, semantics, and operability remain; only cosmetic fade disappears. There is no exit orchestration or crossfade. |

Not using React Bits backgrounds, text effects, or orbs is a genuine pass. The failure is role inflation: NOTES describes motion wrappers and partially overridden components as owning more product structure than they do.

## 5. Three strengths to keep

1. Selection uses one accent and dims unrelated nodes, establishing a clear graph-to-inspector relationship.
2. The inspector takes width instead of covering the graph.
3. Plane identity uses shape rather than color, and rest mode limits labels to hubs.

## 6. Five fixes to make first

1. **Rebuild Ikarus as an actual transcript:** one-line mission title, compact stage summary, persistent speaker grouping, citations attached to claims, named withheld items, no clipped turns, and a visually anchored composer.
2. **Art-direct both graph layouts:** fewer rest edges, directional selected relations, explicit Ordered headers/lanes, and zero collisions, inconsistent baselines, or truncation.
3. **Remove the surface soup:** one material per window, fewer borders and pills, real secondary/tertiary vibrancy, 17 px core text, and a coherent standard control family.
4. **Rebuild the palette:** obvious focused search field, genuine recents, categories and shortcuts in rows, visible scroll/dismissal cues, and disabled rows that cannot become active.
5. **Make the evidence honest:** repair Dock accessibility and tooltip behavior, add roving graph navigation and complete text scaling, rebuild before verification, and test every behavior claimed in NOTES.

Want me to plot this out in Figma with the screenshots and notes?

**Score: 3/10 for “the owner would say wow, not AI slop.”** The interaction model has substance, but the visible product is still a generic grey AI cockpit with clipped conversation, auto-layout collisions, component soup, and claims that outrun the evidence.
