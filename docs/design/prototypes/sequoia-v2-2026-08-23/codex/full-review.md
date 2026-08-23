I treated [BRIEF.md](<C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/c46c7615-e718-4fa6-8756-9c4b7ccdd61b/scratchpad/spike3/BRIEF.md>) as binding and checked [NOTES.md](<C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/c46c7615-e718-4fa6-8756-9c4b7ccdd61b/scratchpad/spike3/sequoia2/NOTES.md>) against the implementation.

The verdict: this is engineered more carefully than it is designed. It still looks like a requirements-shaped enterprise dashboard generated from a checklist, not an authored Apple-standard product.

## 1. AI-generated-design tells

- **Every screen:** the universal top bar + left navigation + hairline-separated content + permanent bottom status bar is the default AI SaaS shell. Nothing about this composition feels specific to a codebase-seeing desktop product.

- **Every screen:** active selection is rendered identically at every hierarchy: white row plus a 3 px blue stripe. In the library, Daedalus, Knowledge library, and Sealed promotion all display the same motif simultaneously. That mechanical repetition is a strong generated-template tell.

- **Cockpit, atlas:** 32 labelled nodes and nearly every edge are exposed at once. The result is a spreadsheet-shaped hairball, not a “living graph.” The notes admit 384 visible elements against the binding limit of 150; the palette reaches 667 with the cockpit behind it.

- **Cockpit, atlas:** equal columns, equal rows, horizontal plane bands, tiny coloured geometric markers, and a legend explaining all of them make this look like a requirements diagram. The graph is documenting that four planes were implemented rather than helping the owner understand the codebase.

- **Cockpit, right rail:** every action is the same outlined rectangle. “What changed,” “Hotspots,” “Distill enforce.py,” Send, Focus, Reset, Reject, and Search share almost the same visual language regardless of importance or reversibility.

- **Cockpit, transcript:** the conversation is visibly clipped/scrolled into an awkward starting position. The owner’s final question appears without a clean turn boundary, while the Ikarus label and response dominate. It looks like a component auto-scrolled to the last item without anyone art-directing the settled screenshot.

- **Cockpit, bottom bar:** attempts, lane resolution, spend, tokens, provenance, kill-switch state, and Disarm are packed into one sentence-strip. This is “put every remaining requirement in the footer” design.

- **Library:** the triple-column documentation template is generic. The right sidebar repeats the selected page title, then mechanically appends “— show on the atlas” to several underlined backlinks, then repeats “Show on the atlas” again below.

- **Library:** the page has generous empty space, but it is residual rather than composed. Three rigid navigation/metadata columns consume the width while the short article floats at the top of the remaining slot.

- **Settings:** it resembles a component gallery: segmented control, switch, slider, another segmented control inside a table. The enormous blank right half and a switch placed hundreds of pixels from its label reveal a layout container, not a considered preferences experience.

- **Palette:** verbs, modes, files, methods, and pages are dumped into one undifferentiated list. “Find module” appears while module results are already present. “Distill” and “Focus” silently default to the busiest module, so pressing Enter can act on a target the user never chose.

- **Across screens:** raw Unicode triangles, coloured dots, primitive graph shapes, and no coherent icon language make the prototype feel like styled HTML rather than a desktop product.

- **Copy:** phrases such as “A locked cell is a statement about the runtime,” “the fixture does not record,” and “this prototype has no backend” repeatedly explain implementation constraints. Truthfulness is correct; making internal prototype mechanics the dominant product voice is not.

- **Language:** German conversation inside entirely English chrome may be legitimate data, but the unmediated mixture reinforces the impression that fixture strings were dropped into a generic shell.

## 2. HIG and binding Apple-standard violations

### Typography

- The cockpit’s actual page title is only 21 px. Ikarus and Knowledge headings are 16 px. The binding range for large titles is 34–64 px; only Library and Settings approach it.

- Atlas labels are 12 px despite being primary interactive content. They fail the requested 15–17 px body range and are difficult to scan through the edge noise.

- Code identifiers use the same sans-serif voice as navigation and prose. `enforce.egress()`, file paths, receipts, and methods need a controlled monospace treatment so identifiers are distinguishable without colour.

- The typography has too few hierarchy levels. Using exactly two text colours has flattened headings, metadata, state, captions, evidence, and disabled explanations into a uniform grey field.

### Sentence case and copy

- The lens labels are visibly lowercase: “structure,” “evidence,” and “cost.” They should be “Structure,” “Evidence,” and “Cost.”

- “Ctrl K” does not match the stipulated “Ctrl-K,” nor does it read like a platform keycap.

- “Canonical Kernel” in metadata is unexplained title case.

- “Where a mission goes first. Daedalus falls back only downwards, never outwards” is cryptic system topology, not plain user language.

- The interface is over-explanatory where controls should be self-evident and under-explanatory where meaning matters: watcher dots and the kill-switch state have weak visual explanation, while locked table cells get a paragraph describing the concept of a locked cell.

### Spacing and geometry

- The declared 8 pt grid is not actually followed: the CSS uses 2 px, 4 px, and 6 px gaps repeatedly in mission stages, transcript labels, graph labels, and lists.

- The single 8 px radius directly violates the requested 12–20 px continuous radius range. The palette in particular looks like a flat web modal, not a carefully surfaced floating material.

- The right-rail content is compressed while Settings and Library leave large unstructured voids. This is not generous whitespace; it is inflexible column sizing.

- In Settings, the “Local traffic may leave this machine” switch sits around 600 px from its label. The control and explanation no longer read as one setting.

### Hierarchy and deference

- The order timeline is outside Ikarus even though the brief explicitly places it inside the Ikarus panel. It consequently dominates the entire cockpit and pushes the graph downward.

- The atlas occupies 55.6% of the total window only by measurement. Visually, it competes with the mission band, toolbar, legend, slice bar, sidebar, inspector, transcript, and status line. The hero does not win.

- The armed kill switch is low-contrast footer prose, while the visually strongest control is Approve. A critical safety state deserves unmistakable but restrained semantic treatment.

- The permanent chrome does not recede. Borders define virtually every region and row, creating an administrative grid around the content.

### Colour

- The blue accent is repeated as project marker, view marker, page marker, stage line, selection wash, focus ring, and primary action. Individually valid, collectively noisy.

- Grey watcher dots communicate state without a label or stable nearby key. Colour alone is carrying meaning.

- The exact same secondary grey is used for useful evidence, instructions, disabled content, metadata, and incidental status. Passing AA does not produce good perceptual hierarchy.

### Controls and accessibility

- Settings is a full page. The binding brief requires a sheet.

- Disabled “Focus the slice” provides its explanation only through a native tooltip. This contradicts NOTES’ opening promise that disabled reasons are written next to controls and fails clarity for touch and keyboard users.

- The palette is modal in ARIA only. Unlike the other dialogs, it has no focus trap; Tab can leave it, and Escape handling is attached to the input rather than the modal.

- The library declares a tree but implements no tree keyboard model: no Up/Down, Home/End, Left/Right navigation, or managed focus.

- Settings arrow keys change the selected tab but do not move focus to the newly selected tab.

- The atlas’s visible node marks are roughly 10–14 px. Default SVG node groups contain only the marker and text, with no permanent 44 px hit rectangle. The claimed “0 targets under 44 px” audit is evidently not measuring these SVG options meaningfully.

- Navigation, mode selection, and value selection all use nearly identical segmented or selected-row styling. The control vocabulary lacks enough visual distinction.

### Clarity, deference, and depth

- **Clarity:** the initial atlas is unreadable without interaction; unrelated edges should not all be present at rest.

- **Deference:** implementation status and fixture limitations repeatedly interrupt the product content.

- **Depth:** almost all depth comes from one-pixel borders. The sidebars are opaque, Settings is not a floating sheet, and only the palette uses blur and shadow. This misses the brief’s material requirement.

## 3. Feature visibility and operability

The behavior table is not fabricated wholesale: most listed actions do change local state. But the complete feature list is not both visible and operable.

### Ikarus

Present: transcript, composer, simulated streaming, M/I provenance on fixture turns, evidence lines, quick actions, and user-controlled Approve/Reject.

Missing or wrong:

- The six-stage order timeline is not inside Ikarus.

- The service-unavailable Ikarus reply intentionally has no provenance. That directly violates “every Ikarus claim carries M/I/A.” It should be an M-stamped claim or a separate system notice.

- Withheld content is counted and categorised as “secret-bearing paths,” but the paths or outputs are not named. “Anything withheld is named” is not satisfied.

- “Ikarus proposes. You decide.” exists in the fixture but is omitted from the interface.

### Codebase

Present and wired: four planes, three lenses, verified/proposed edge distinction, selection, hover emphasis, keyboard navigation, pan/zoom, Reset, slice status, quick-action highlighting, and Focus after distillation.

Defects:

- “Focus the slice” starts disabled without a visible inline reason.

- The cost lens has data for only 2 of 32 nodes. The prototype is honest about that, but it cannot credibly present a project-wide cost lens.

- The initial graph exceeds the binding visible-element budget and is not useful at rest.

### Knowledge

Present and wired: architecture summary, counts, receipts, library groups, wiki pages, backlinks, atlas navigation, module pages, persisted notes, and regeneration that preserves notes.

Missing from the delivered views:

- The module notes and regeneration experience are not demonstrated in the supplied Library screenshot.

- Council content is hidden behind another interaction; only its palette entry is visible.

- Two global and two project pages have no body. The honest empty state is preferable to invented text, but the claimed “Confluence” library is visibly skeletal.

### Chrome and settings

Present: project switching, watcher dots, spend/tokens with provenance, lane/host status, command palette, route, egress switch, spending slider, rights matrix, memory, privacy, appearance, motion, density, and retention state.

Missing or non-operable:

- Canary is disabled.

- Run the watcher is disabled for the other projects, so they do not actually have the required per-project trio.

- Delete everything clears browser prototype state only; it is not the product-level operation its label suggests.

- Settings is not a sheet.

- The locked statement “Ikarus proposes. You decide.” is missing.

- The binding anti-slop limit of 150 visible elements is knowingly failed.

## 4. React Bits: structure or garnish

The binding rule is at least six registry items, with at least four carrying real UI. NOTES explicitly declares only four. That alone is noncompliance.

| Item | Verdict | Critique |
|---|---|---|
| `Stepper-TS-CSS` | Structural | It owns real stage navigation and detail transitions. However, connectors, footer, and native indicators were removed or replaced, and it was installed in the wrong product location. Still counts as one structural item. |
| `AnimatedList-TS-CSS` | Structural in palette; borderline in chat | The palette depends on its list rendering, active row, scrolling, and item entrances. In chat it is mostly an animation/autoscroll wrapper. Using it twice still counts as one registry item. |
| `FadeContent` | Structural transition, visually garnish-like | Transitions are allowed by the brief, and reduced-motion handling is real. But fading otherwise complete panes by 4 px does not affect the information architecture; its visible contribution is garnish. |
| `LineSidebar-TS-CSS` | Borderline | It renders working navigation, but its distinctive proximity shift and colour interpolation are decorative. The routing would work identically as three ordinary buttons. |

At best this is three clearly structural items plus one borderline navigation skin. It is two items short of the absolute registry minimum.

## 5. Three strengths worth keeping

- The proposal hierarchy is correct: Approve is primary, Reject is neutral, and neither pretends that a backend executed.

- The Library article is the strongest composition. The 40 px title, readable measure, restrained prose, and refusal to invent missing page bodies should survive the redesign.

- Measured, inferred, proposed, and unmeasured information is generally distinguished honestly. The hollow cost nodes and dashed proposed edges are conceptually sound; the presentation needs reduction.

## 6. Five fixes to make first

1. **Recompose the cockpit.** Move the six-stage timeline into Ikarus, remove the global mission slab, and give the atlas a clean dominant canvas. Treat the inspector as contextual rather than permanently equal-weight.

2. **Redesign the atlas’s resting state.** Show the verified structural spine and islands first; reveal cross-plane and proposed edges through lenses, selection, or hover. Raise labels to at least 14–15 px, use monospace for identifiers, and add real 44 px hit regions.

3. **Replace the web-admin visual system.** Use 34 px or larger page titles, 12–16 px continuous radii, fewer borders, translucent sidebars, a genuine Settings sheet, and spacing that groups content instead of merely satisfying numeric tokens.

4. **Close the binding feature gaps.** Stamp or reclassify the service reply, explicitly disclose that withheld identities are unavailable, surface “Ikarus proposes. You decide.,” place disabled reasons inline, and stop claiming everything is operable while Canary and watcher execution are unavailable.

5. **Rebuild the palette and React Bits integration together.** Remove the arbitrary busiest-module default, group commands/modules/pages, add focus containment and shortcuts, and add at least two registry components that genuinely own library or settings structure—not background effects.

**Score: 3/10 — the owner would see a careful AI-generated admin prototype with good state wiring, not a singular Apple-standard product worth saying “wow” about.**
