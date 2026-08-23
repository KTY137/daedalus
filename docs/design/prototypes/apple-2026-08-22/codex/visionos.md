The prototype fails the owner’s central test. It is a technically competent glassmorphism demo, but it still reads immediately as AI-generated “futuristic control room” UI—not as an Apple-standard engineering product.

## 1. AI-generated-design tells

- **Entire cockpit:** the dim shader, theatrical light beams, frosted floating cards, large radii, inner highlights, and deep shadows are the default “premium AI dashboard” recipe. The brief explicitly warned against a dark sci-fi HUD; this is one.
- **Every screen:** nearly every object is glass. When panels, navigation, status, dialogs, and the background all compete to demonstrate material, none of them establishes hierarchy.
- **Top-right status capsule:** a detached pill containing lane, host, tokens, spend, provenance, kill switch, and ⌘K looks composed for a concept render rather than everyday use.
- **Left navigation plus bottom dock:** two ornamental navigation systems remain visible even though the three cockpit panels are already permanently present. This is visual theater, not a coherent information architecture.
- **Bottom project dock:** `D`, `T`, and `L` are placeholder-grade glyphs. Project names exist only in hover labels; the tiny status dots and selected dot are ambiguous.
- **Cockpit graph:** four perfectly spaced columns, uniformly distributed nodes, hairline Bézier curves, and aggressive truncation resemble an architecture-diagram generator. The lower half is largely empty while the upper rows become spaghetti.
- **Ikarus timeline:** all six notes are reduced to fragments such as “compil…”, “2 work…”, and “eviden…”. It satisfies a checklist while communicating almost nothing.
- **Quick actions:** “What changed” and “Hotspots” occupy one line while “Distill enforce.py” drops to another. It looks like uncontrolled flex wrapping.
- **Knowledge window:** deliberately placing important content behind the Codebase and lowering its contrast turns “spatial depth” into obstruction.
- **Library:** “Sealed promotion” and `enforce.py` are both highlighted simultaneously. That is the classic generated-dashboard mistake of showing multiple plausible selections without defining the selection model.
- **Library:** “Show on the atlas” appears twice, once for the article and once for the unrelated module sidebar.
- **Settings:** the rights matrix uses repeated miniature segmented controls where a native pop-up/menu or a single policy editor would be clearer.
- **Palette:** an oversized glass dialog, long tutorial placeholder, evenly spaced command rows, and no command-specific symbols or shortcuts make it look like a component-library showcase.
- **Acceptance criteria pasted into UI:** “verbatim, never scored,” “survive regeneration,” “named, never silent,” and “nothing runs until you press return” repeatedly expose internal product requirements as explanatory chrome.
- **Receipts stack:** draggable stacked cards are a demo interaction that conceals two-thirds of the information. It optimizes for animation, not comprehension.
- **Overall:** the interface has almost no distinctive iconography or product-specific visual language—mostly text, dots, generic segmented pills, and glass rectangles.

## 2. Apple/HIG and binding-brief violations

### Typography

- Cockpit titles are approximately 22 px/500; Settings is about 28 px/400; the Library title is 36 px/400. The brief calls for 34–64 px titles at 600–700.
- Most operational text is 12–14 px rather than the required 15–17 px body size.
- Low-contrast microtext dominates the timeline, graph, status line, metadata, Council, and sidebars.
- Standalone labels are not consistently sentence case: `code`, `type`, `data`, `knowledge`, `slice: warm`, `cross-plane, verified`, `never`, `ask every time`, and `within a mission`.
- The graph truncates identifiers precisely where exact identifiers matter.
- Italic locked statements in Settings look disabled rather than authoritative.

### Spacing and controls

- The supposed 8-point grid contains many arbitrary 2, 3, 4, 6, 10, 12, 14, 18, and 20 px values.
- The promised single radius scale is absent. The implementation uses 8, 10, 12, 13, 14, 16, 18, 20, and 24 px radii.
- Several targets are below the required 44 px: Library rows are 40 px, links 32 px, ⌘K 36 px, rights segments 34 px, the toggle 32 px high, and graph rows 30 px.
- Text fields remove their focus outline without supplying a visible replacement.
- Graph nodes are mouse-only SVG groups: no keyboard focus, role, or activation.
- The spending “slider” has no visible thumb or current-value indicator. It reads as a progress bar.
- The Ikarus composer has no Send control and no visible keyboard instruction.
- “Done” is stranded at the bottom-left of the Settings sidebar, far from the changed settings and unlike a normal macOS Settings window.

### Hierarchy, colour, clarity, deference, and depth

- The secondary grey used throughout is below comfortable contrast; the receded Knowledge pane becomes substantially worse.
- Chrome does not defer. The shader, glass, status capsule, dock magnification, overlapping windows, and shadows are more visually assertive than the project data.
- Codebase is nominally the hero, but it receives only a 592×400 graph within a 1440×900 canvas.
- The floating-window overlap hides content rather than revealing relationships. That is depth without clarity.
- The graph legend explains blue cross-plane edges and dashed proposals but not solid grey intra-plane edges, selected nodes, dim nodes, or measured nodes in the default state.
- Blue simultaneously means selection, cross-plane relationship, action, link, and timeline activity.
- The cockpit has no single obvious primary action or focal reading order.
- The Library is closer to a native split view, but keeping the external nav, project dock, and floating status strip prevents it from feeling like one coherent application window.
- The custom grey grounds do not follow the specified Apple dark palette, while the DarkVeil shader introduces decorative colour and luminance variation.
- Glass is used even for ordinary content panes; genuine floating material should be limited to transient or spatially elevated surfaces.

## 3. Feature coverage and operability

### Present and substantially working

- Four graph planes and cross-plane edges.
- Dashed treatment for unverified proposals.
- Mouse hover neighbour highlighting.
- Mouse selection bringing Knowledge forward.
- Structure/evidence/cost lens selection and node rearrangement.
- Six-stage mission timeline, although its detail is illegible.
- Three Ikarus quick actions.
- Knowledge Library tree, backlinks, Council quotations, module metrics, and editable-looking notes.
- ⌘/Ctrl-K opening, filtering, arrow navigation, and Return selection.
- Settings section navigation, toggles, segmented controls, and locked write statements.
- Token/spend display, watcher dots, host, and kill-switch state.

### Missing, misleading, or non-operable

- **Chat is not operable:** the input has no submit or Enter handler, and there is no streaming state.
- **Palette commands are mostly fake:** only “Open page” performs an action. Distill, Focus, Canary, Council, Doctor, and Find module merely close the palette.
- **Focus the slice is mislabeled:** it only selects the Evidence lens; it does not focus the selected node or alter the slice.
- **Project switching is misleading:** it changes the project name and aggregate counts, but reuses the Daedalus graph, mission, chat, Knowledge page, lane, and status. There is not actually one trio per project.
- **Project tabs are not visibly named:** only `D`, `T`, and `L` appear until hover.
- **The Library is hardcoded to the first project’s wiki.**
- **Cockpit-to-Library selection is lost:** “Open its wiki page” always opens the default Sealed promotion page.
- **Library-to-atlas selection is lost:** both “Show on the atlas” actions return to the default graph selection rather than the current page or module.
- **Most backlinks are no-op buttons:** only backlink names matching another project-wiki title navigate.
- **Hand notes do not survive anything:** they exist only in component state, with no save, persistence, or regeneration behavior.
- **The slider is disconnected:** it receives a default value but has no change handler and does not update the displayed ceiling.
- **Settings do not affect the application:** route, rights, memory, theme, accent, motion, text size, and density are transient local state.
- **Delete everything does nothing.**
- **Appearance is largely fictitious:** Accent, Text size, and Density each provide only one option; Light/Dark/Auto and motion choices are not applied.
- **Resolved-host warning behavior is absent:** changing the local-egress control cannot update the status strip.
- **Receipts and Council are not visible in the supplied cockpit frame:** they are below an undiscoverable scrollbar inside the receded Knowledge window.
- **Only the M provenance state is visible in the supplied frame.** I and A are not demonstrated.
- **The second withheld message is clipped behind the chat fade.**
- **There is no explicit proposal/review/execute transaction**, despite the core promise that Ikarus proposes and the user decides.

## 4. React Bits: structure versus garnish

| Item claimed in NOTES.md | Verdict |
|---|---|
| `GlassSurface` | **Skin/garnish.** Custom `.window`, `.sheet-body`, and grid CSS provide the real structure. GlassSurface is nested inside already styled glass hosts and adds another material effect. |
| `GooeyNav` | **Structural, but brittle.** It carries primary navigation, although actions are wired through parent `onClickCapture` and DOM child indexes rather than the component’s own semantic API. |
| `Dock` | **Partly structural.** It switches a project index, but the underlying project content does not switch. Its magnification and initials mainly operate as ornament. |
| `AnimatedList` | **Structural.** It carries the chat and palette results. However, hidden chat scrolling damages discoverability, and six palette selections have no behavior. |
| `Stack` | **Real data in a garnish interaction.** It contains receipts, but stacking and dragging hide information that should be directly scannable. |
| `ElasticSlider` | **Component-demo garnish.** It looks interactive but is not connected to settings state and suppresses its value indicator. |
| `Counter` | **Garnish.** It animates one number; the status strip’s data structure is entirely custom. Rolling digits add no useful behavior. |
| `DarkVeil` | **Pure decoration and directly harmful.** It creates the forbidden dark sci-fi atmosphere and competes with the content. |

The source meets the numerical import count. It does not convincingly meet the substantive requirement that four React Bits items carry complete, meaningful UI. GooeyNav and AnimatedList do; Dock is incomplete, while Stack and ElasticSlider prioritize their demo behavior over the product task.

## 5. Three strengths worth keeping

1. Keep the four-plane atlas and the distinction between verified and proposed relationships. That is the clearest product-specific idea here.
2. Keep the trust semantics: provenance letters, named withheld material, explicit locked write statements, and verbatim Council positions.
3. Keep the Library’s basic three-part model—tree, readable page, module notes—but make it one selection system rather than two simultaneous pages.

## 6. Five fixes to make first

1. **Replace the floating cockpit with one native application window.** Use a project sidebar or visible project tabs, a restrained toolbar/status area, a large Codebase canvas, and stable Ikarus/Knowledge inspectors. Remove DarkVeil, the project dock, redundant left ornament, and most shadows.
2. **Rebuild the type and contrast hierarchy.** Use 34 px/600 page titles, 20–22 px/600 section titles, 15–17 px body text, AA secondary text, sentence case, visible focus rings, and no essential clipped copy.
3. **Make every named operation truthful.** Implement chat submission/streaming, all seven palette verbs, actual slice focusing, preserved atlas/wiki selection, persistent notes/settings, resolved-host warnings, and a confirmed Delete flow.
4. **Fix project and Library state.** Show full project names; never display Daedalus data under another project; make module pages open as actual pages; use one active tree selection; make every backlink and atlas link preserve its subject.
5. **Use React Bits only where its behavior improves the task.** Keep the animated list for live results, simplify or replace the nav, connect the slider properly, expose receipts as a readable list, and remove Counter/DarkVeil motion. Then audit every control for 44 px targets and keyboard access.

**Score: 3/10 — the product model is visible underneath, but the dominant impression is still generic AI glassmorphism with ornamental motion, low-contrast microtype, and too many controls that only pretend to work.**
