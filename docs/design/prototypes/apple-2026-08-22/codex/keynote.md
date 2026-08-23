## Verdict

This is polished AI slop, not Apple-standard product design. It reproduces the ingredients associated with Apple—large type, pale gray, blur, rounded rectangles—but not the discipline: the codebase is not the hero, navigation is non-native, important information is microscopic, and many apparently operable controls are fake.

I checked the screenshots, [BRIEF.md](/C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/c46c7615-e718-4fa6-8756-9c4b7ccdd61b/scratchpad/spike2/BRIEF.md), [NOTES.md](/C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/c46c7615-e718-4fa6-8756-9c4b7ccdd61b/scratchpad/spike2/keynote/NOTES.md), and the implementation to verify operability.

## 1. AI-generated-design tells

### Across all screens

- The design is “Apple by prompt keywords”: giant bold headline, white ground, gray capsules, blur, floating glass, count-up numbers and spring motion. There is no convincing native desktop information architecture underneath.
- The 12 px radius is applied indiscriminately to tabs, chips, cards, provenance stamps, switches, dialogs, tooltips and the Dock. A token has replaced judgment about control geometry.
- “Ikarus proposes. You decide.”, “Confluence, but honest.”, “named here, not hidden”, “verbatim, never scored” and “nothing executes without you” repeatedly announce product values instead of letting the interface demonstrate them.
- The vocabulary is metaphor soup: cockpit, atlas, wiki, library, slice, lane, mission, council, canary, doctor and digestion. An expert tool can have domain language; it still needs one coherent spatial model.
- The fixed floating Dock is the most obvious generated-design flourish. It copies the macOS Dock inside an app window, duplicates top-level navigation, hides labels until hover and overlays content.
- The composition is tuned to produce an attractive 1440×900 screenshot, not to survive resizing. The CSS has fixed two-column grids, a 720 px drawer and a 640 px palette with no responsive layout rules.

### Cockpit

- The large marketing H1 occupies the strongest position while the “hero” code graph is compressed into a 644×311 gray rectangle. That reverses the binding product hierarchy.
- The graph resembles a decorative network wallpaper: dozens of labels rendered around 10–12 SVG px, crossing hairlines, no visible legend and tiny click targets.
- NOTES explicitly calls the graph “photographed like a product” and tilts it 4°. Technical topology should remain spatially stable; tilting it is React-demo behavior.
- The left transcript, right timeline and graph are arranged as two editorial columns because it looks balanced, not because it supports investigation. There is no durable selection/detail region.
- The provenance letters are decorative outlined circles. The brief explicitly asked for typographic M/I/A, not a badge treatment.
- The project selector looks like a generic SaaS pill strip. Inactive projects look disabled, and they actually are nonfunctional.
- The quick actions are generic gray chips. Nothing distinguishes “change my view” from “propose work” from “execute work.”
- The bottom status line is nearly invisible while “kill switch armed” is safety-critical. That is visual theater instead of operational hierarchy.

### Library

- “Confluence, but honest.” is a launch-page headline sitting above a working document browser. It wastes vertical space and competes with the selected document title.
- The ScrollStack converts documents into oversized floating cards. This is a component-demo structure, not a reading environment.
- Selecting “Sealed promotion” still stacks module pages and Council below it. A page selection should produce one stable detail view, not a promotional feed.
- The module page contains the explicitly prohibited four-metric strip: `23 / 4 / 11 / B`.
- The 64 px gulf between tree and document, large card padding and redundant borders make sparse fixture data appear artificially premium.
- The floating Dock covers the editable note area at the bottom of the screenshot. The layout visibly loses a fight with its own garnish.

### Settings

- This is neither a macOS settings window nor a macOS sheet. It is a web-app right drawer occupying exactly half the viewport with a modal scrim.
- The same pale capsule treatment is used for section navigation, preferred route and per-runtime write rights, flattening three different levels of control.
- The ElasticSlider is playful motion applied to a spending safety limit. That is precisely where predictability should beat personality.
- “Rights per runtime” looks configurable, but Read and Propose are static text and the visible Write selectors do nothing.
- The large declarative statements at the bottom read like a generated manifesto inserted to fill space.

### Palette

- It is a generic Command-K clone: oversized white rectangle, one saturated blue row, right-aligned explanations and a tiny keyboard legend.
- There is no scope, result type, parameter entry, preview or confirmation. “Distill,” “Focus” and “Canary” are materially different operations but receive identical rows.
- “Canary — run the cheap smoke” conflicts with the fail-closed promise unless the next state is explicitly a proposal or confirmation.
- The selected row implies immediate operability, but six of seven commands only close the palette and return to the cockpit.

## 2. HIG violations

### Typography and language

- Graph labels and proposal scores are too small for sustained desktop use. The exact text may technically contrast, but it is not comfortably perceivable.
- The palette’s selected hint uses 80% white over `#0071E3`, about 3.56:1 contrast at 15 px—below Apple’s cited 4.5:1 guidance for small text. Apple also recommends supporting larger text and auditing interface accessibility. [Apple Accessibility HIG](https://developer.apple.com/design/human-interface-guidelines/accessibility/)
- Sentence case is inconsistent:

  - “Routing & Rights” should be “Routing & rights.”
  - “Memory & Privacy” should be “Memory & privacy.”
  - “Knowledge Library” should be “Knowledge library.”
  - “within a mission” and “ask every time” should begin with capitals as control labels.
  - “esc close”, “lane Claude” and “kill switch armed” are fragments rather than polished status copy.
  - Palette descriptions should begin with capitals.

- “Focus the slice” does not describe what happens—the implementation merely activates the Cost lens.
- “⇄ this page” beside “Show on the atlas” is cryptic and appears noninteractive.
- Apple recommends active, clear labels and consistency over clever language. [Apple Writing HIG](https://developer.apple.com/design/human-interface-guidelines/writing)

### Layout and hierarchy

- A macOS toolbar belongs at the top of the window; primary app navigation does not belong in an internal imitation of the system Dock. [Apple Toolbars HIG](https://developer.apple.com/design/human-interface-guidelines/toolbars)
- The fixed Dock and status line overlay content instead of reserving a safe area. The library note editor is visibly obscured.
- The main project areas are switched using a segmented control, while Apple recommends a tab view for switching the main window area. The project segments also have visibly unequal widths. [Apple Segmented Controls HIG](https://developer.apple.com/design/human-interface-guidelines/segmented-controls)
- The library should be a proper sidebar/split view. It has the shape of one, but no disclosure hierarchy, hide/show mechanism or material distinction. [Apple Sidebars HIG](https://developer.apple.com/design/human-interface-guidelines/sidebars)
- The settings right drawer is presented as a sheet, but a macOS sheet is a targeted modal task attached to its parent context. App-wide preferences generally need a stable settings surface. [Apple Sheets HIG](https://developer.apple.com/design/human-interface-guidelines/sheets)
- The graph is supposed to be the hero, yet it receives less visual weight than the marketing title and chat transcript.
- The implementation does not adapt to window resizing, contrary to basic macOS expectations. [Apple Designing for macOS](https://developer.apple.com/design/human-interface-guidelines/designing-for-macos)

### Colour and controls

- Accent blue means both “clickable” and “noninteractive metadata”: the cockpit eyebrow is blue despite not being a link. Apple warns against assigning the same color to different meanings. [Apple Color HIG](https://developer.apple.com/design/human-interface-guidelines/color)
- Inactive project tabs use pale text and gray dots that resemble disabled controls.
- The graph uses dashed lines to distinguish proposals but provides no legend. Essential state must not rely on subtle stroke styling alone.
- Many bare text actions and graph nodes do not meet the brief’s stricter 44 px target requirement.
- Graph nodes are pointer-only SVG groups: no keyboard focus, button semantics or accessible names per node.
- The M/I/A explanations depend on an unfocusable `title` tooltip.
- The settings and palette dialogs do not trap focus, declare `aria-modal`, or restore focus.
- The command palette’s listbox semantics are incomplete: selection changes visually, but the input does not announce an active descendant.

### Clarity, deference and depth

- Clarity fails because the graph is unreadable, the three product areas do not have stable regions, and controls frequently lie about what they do.
- Deference fails because the marketing H1, Dock, card stack, count-ups and entrance effects compete with project evidence.
- Depth is mostly borders, shadows and scrims. The `0.97` opaque sheet and palette barely read as material; the library sidebar has no material separation at all.
- Apple’s current guidance emphasizes hierarchy, harmony and consistency between content and elevated controls. This prototype instead creates several unrelated floating layers. [Apple HIG overview](https://developer.apple.com/design/human-interface-guidelines)

## 3. Feature-list coverage

| Requirement | Verdict |
|---|---|
| Streaming Ikarus chat | Transcript only. Send has no handler; no streaming behavior exists. |
| M/I/A provenance | Visible on Ikarus claims, but styled as badges and tooltip access is poor. |
| Named withheld output | Present and clear. |
| Six-stage order timeline | Present and clickable; stage notes change. |
| Quick actions | Present; they only change graph lens/selection. |
| Project graph, four planes and cross-plane edges | Present, but illegible at this scale. |
| Verified versus proposed facts | Dashed styling exists; no legend and differentiation is too subtle. |
| Hover neighbours and click selection | Works with a pointer; not keyboard-operable. |
| Selection flows into Knowledge | Missing. Selection changes only the graph heading. |
| Structure/evidence/cost lenses | Present and interactive. |
| Slice status | Present. |
| Focus the slice | Incorrect: it simply switches to Cost. |
| Architecture state and receipts | Implemented below the initial cockpit viewport, not visible in the supplied frame. |
| Global library/project wiki/module pages | Present. |
| Notes survive regeneration | False. Notes exist only in component state and disappear when Library unmounts or the app reloads. |
| Backlinks | Visible, but backlink clicks explicitly prevent navigation. |
| Atlas ↔ wiki linkage | Partial. “Show on the atlas” returns to the cockpit; code-node lookup often falls back to the first wiki page. |
| Council opinions verbatim | Present below the visible area; not scored. |
| Project tabs | Visible but deliberately no-op at [App.tsx:101](/C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/c46c7615-e718-4fa6-8756-9c4b7ccdd61b/scratchpad/spike2/keynote/src/App.tsx:101). |
| Token/spend provenance | Token count has M; spend does not. |
| Command palette | Opens by keyboard and lists all verbs; only Open page performs meaningful navigation. |
| Active lane/resolved host | Present in the status line. |
| Resolved-host warning | Conditional behavior exists, but changing the local-traffic setting does not update it. |
| Routing and spending controls | Change temporary local state only. |
| Rights matrix | Locked statements are correct; unlocked Write controls are no-ops, and Read/Propose are not configurable. |
| Memory and privacy | Section exists; Delete everything has no handler or confirmation. |
| Appearance | Controls change hidden state but do not alter theme, motion, text size or density. Accent is a one-option fake selector. |

The largest missing pieces are real streaming/send, functional project switching, graph-to-Knowledge selection, correct node-to-page routing, persistent notes, working backlinks, actual slice focusing, functional palette verbs, spend provenance, functional rights/settings, deletion confirmation and applied appearance preferences.

## 4. React Bits: structure or garnish?

| Item claimed in NOTES | Judgment |
|---|---|
| `SplitText` | Formally carries text entrance; product-wise it is garnish on the H1. |
| `BlurText` | Garnish. Blurring a slogan and Library headline adds no structure or state. |
| `AnimatedContent` | Legitimate transition infrastructure for the sheet and palette; generic reveal wrappers elsewhere add little. |
| `FadeContent` | Pure garnish around the graph. |
| `Dock` | Genuinely structural navigation, but it is the wrong structure for macOS and obscures content. |
| `Stepper` | Proper structural use. It carries mission state and stage-note selection. Keep it. |
| `ScrollStack` | Structural, but destructive. It forces the Library into stacked presentation cards instead of a stable split-view reader. |
| `CountUp` | Carries data, but animating known ledger values implies live mutation and feels like dashboard theater. |
| `TiltedCard` | Garnish and actively harmful. It wraps a transparent 1×1 image while the real graph sits in the overlay at [App.tsx:183](/C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/c46c7615-e718-4fa6-8756-9c4b7ccdd61b/scratchpad/spike2/keynote/src/App.tsx:183). |
| `ElasticSlider` | A real control, but inappropriate motion for a spending ceiling and not connected to persisted settings. |

The numerical requirement is arguably met by Dock, Stepper, ScrollStack, ElasticSlider and modal transitions. The spirit is not: the most recognizable React Bits effects are demo garnish, while two genuinely structural components—Dock and ScrollStack—make the product less native and less usable.

## 5. Three strengths to keep

1. The measured/inferred provenance, evidence references and named withholding communicate the product’s honesty better than the surrounding chrome.
2. The six-stage timeline distinguishes done, live and waiting states through shape, text and color, and reveals useful stage detail.
3. The base palette and system font stack are restrained: one blue accent, green/orange used for state, and monospace mostly limited to identifiers.

## 6. Five fixes to make first

1. Replace the marketing-page composition with a resizable native split view: project/sidebar navigation, a large stable graph canvas as the center hero, and persistent Ikarus/Knowledge inspectors.
2. Remove every fake control. Wire Send, project switching, palette verbs, Focus, backlinks, correct wiki routing, rights, settings, persistence and confirmation—or render them honestly disabled.
3. Rebuild the graph for investigation: readable labels, zoom/pan, legend, keyboard navigation, stable geometry, neighbour emphasis and a real selection-detail pane synced to Knowledge.
4. Delete TiltedCard, ScrollStack, CountUp motion, repeated blur/split entrances and the internal Dock. Retain Stepper and restrained modal transitions; use React Bits only where state or navigation materially benefits.
5. Normalize the native system: top toolbar, proper sidebar/settings surface, platform-sensitive `⌘K`/`Ctrl-K`, sentence case, unobscured safe areas, 44 px targets per brief and accessible dialog/focus behavior.

**Score: 3/10 — the owner will recognize a competent generated Apple imitation, but the fake interactions, component-showcase motion and non-native information architecture still make “AI slop” the immediate read.**
