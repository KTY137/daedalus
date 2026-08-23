# Sequoia v2 — build notes

Sequoia rebuilt against the Codex review of round 2. The rule for this pass: **every visible
affordance is truthful.** It either changes state against `fixture.json`, or it is rendered
disabled with the reason written next to it. Nothing on screen looks operable and is not.

Vite + React 18 + TypeScript, `base: './'`, `npm run build` exit 0, preview on port 5201.
No backend, no network, no fonts beyond the system stack.

---

## 1. Codex's fix-first list, item by item

### Fix 1 — "Make the product loop truthful"

| Codex defect | What was done | Where |
|---|---|---|
| "Cockpit deliberately reads `projects.find(p => p.active)`, so graph, mission, chat and architecture remain Daedalus" | The whole app is keyed on `projectId`. Per-project state (selection, lens, chat, stage tab, decision, highlight, distill target, atlas view) lives in a map in the store. The fixture carries a compiled index for exactly one project, so the other two get an honest empty state instead of Daedalus data under another name. TCT: "The watcher has counted 62 modules, 2 islands and 3 dark modules … but it has not compiled an index." Lehrstuhl: "Nothing has been indexed … yet." Both carry a disabled **Run the watcher** with its reason, and the topbar says "Not indexed yet". | `src/state.tsx` (`pmap`), `src/data.ts` (`projectViews`, `indexed`), `src/Cockpit.tsx` (`EmptyProject`) |
| "The composer only edits local text. There is no streaming state, submission handler, Send action" | Enter or **Send** appends the owner turn and then streams a reply word by word (55 ms per word on Full, 26 ms on Calm, instant on Off). The reply is the honest one: *"I can answer that once the Ikarus service is connected. Nothing in this prototype reaches a model, so I will not guess at an answer about your project."* It carries **no provenance stamp**, and a line underneath says why. | `src/Ikarus.tsx`, `src/state.tsx` (`ask`, stream effect) |
| "no proposal object, approval or execution decision" | The Build stage detail is a proposal with two real controls. **Approve** flips Build to Done, Gates to Running, the status line to 18 attempts done, writes a decision record with **Undo**, and appends an Ikarus turn. **Reject** marks the attempt rejected, the status line to 5 rejected, and the note "the build waits for attempt 19". Both records say plainly: recorded in this prototype only, nothing ran. | `src/Cockpit.tsx` (`BuildDetail`, `useStages`) |
| "'Hotspots' and 'Distill enforce.py' both select `c5`; no distillation occurs" | Three distinct outcomes. **What changed** rings the two modules with recorded churn and dims the other 30, with the coverage stated in the caption. **Hotspots** switches to the cost lens, sizes the measured nodes by fan-in, draws the unmeasured ones hollow, and says "Cost is measured for 2 of 32 nodes". **Distill enforce.py** focuses the slice on that node, rewrites the slice line to "Slice focused on daedalus/policy/enforce.py …" and enables **Focus the slice**. | `src/actions.ts`, `src/Atlas.tsx` |
| "The button merely resets Structure and selects `c5`; it does not meaningfully focus or frame the slice" | **Focus the slice** frames the atlas on the distilled module at 1.6× and centres it. Until a module is distilled it is disabled, with the reason in its tooltip: "the fixture does not record which modules are in the slice." | `src/actions.ts` (`focusSlice`), `src/Atlas.tsx` (`focusReq` effect) |
| "It cannot find actual modules. Canary, Council and Doctor simply close" | The palette searches all 32 graph nodes and all 7 library pages. Every verb lands somewhere real: Distill → slice focus; Focus → selection; **Council** → a pane with the three vendor opinions verbatim; **Doctor** → a pane with the lanes, resolved hosts and the key statement; Open page → the library; Find module → a module-only search mode. **Canary** is the one disabled row: "Needs the Daedalus service. Nothing can run from this prototype." | `src/Palette.tsx`, `src/App.tsx` (`Dialogs`) |
| "Delete everything explicitly deletes nothing … changes are not persisted" | All preferences, lane write rights and hand notes persist to `localStorage`. **Delete everything** opens a confirm dialog and really clears the store back to the fixture defaults, saying honestly that it cannot touch anything on disk. | `src/state.tsx` (`setPrefs`, `resetPrefs`), `src/Settings.tsx`, `src/App.tsx` |
| "Notes live only in component state and disappear when Library unmounts" | Notes are in the persisted store. **Regenerate from the index** really rewrites the automatic paragraph from the fixture and stamps the time; the note is untouched, and the page says so. | `src/Library.tsx` |

### Fix 2 — "Recompose the cockpit around the atlas"

- The full library tree and the `StaggeredMenu` are gone from the cockpit. The sidebar is Projects
  and Views only; the tree lives on the library screen.
- All six stages are named and each shows its own state word, not just the selected one.
  The current stage detail sits beneath.
- The atlas pane is **800 px of the 1440 px window — 55.6 %** [MEASURED, `probe.cjs`].
- Labels are 12 px and **never truncated**: they are wrapped on path separators with the real font
  measured through a canvas context, up to three lines, and the canvas is sized to fit the pane at
  scale 1 so zoom is for comfort, not for legibility.
- Zoom (wheel, around the pointer, 0.6×–3×), pan (drag) and a **Reset view** control.
- Progressive emphasis, borrowed from Lagerfeld: on selection or hover everything outside the
  subgraph drops to 35 %, unrelated edges to 6 %, and the incident edges are drawn in the accent
  with their relation label on top.
- Keyboard: the atlas is a `role="listbox"` with `aria-activedescendant`; arrows move, Enter
  selects, Escape clears. The keyboard cursor ring only appears while the atlas has focus.
- A legend row: four plane shapes and colours, solid verified, dashed proposed.
- The Knowledge inspector has no dead state. With nothing selected it shows the architecture
  sentence, the slice, the receipts list, the council link and the line "Select a node to inspect
  it." With a selection it shows the node, plane, kind, fan-in and churn where measured, its edges
  with relations and proposal scores, and **Open its wiki page** — or, when there is none, a
  disabled "No wiki page for this node yet".

### Fix 3 — "One visual specification"

- Body 16 px. Exactly two text colours: `#1D1D1F` and `#6E6E73` (4.66:1 on `#F5F5F7`, 5.07:1 on
  white). No tertiary grey anywhere. **0 contrast failures on all four screens** [MEASURED,
  `audit.cjs`, WCAG AA with the 18.66 px bold / 24 px large-text rule].
- **One radius: 8 px.** [MEASURED] `cockpit {8px, 50%}`, `library {8px, 50%}`, `settings {8px, 50%}`,
  `palette {8px, 50%}` — the only round shapes are the state dots and the switch track and knob.
- 8 pt spacing scale, enforced through tokens `--s1…--s6`; nothing off-scale.
- One blue action per context. The cockpit's only accent-coloured action is **Approve**; Send is a
  neutral button, and every text link is label-coloured with an underline. The library and the
  atlas have no blue action at all.
- Sentence case everywhere, including the values the fixture writes lower case: lane write rights
  ("Within a mission", "Ask every time"), retention and the palette hints are capitalised on read.
  **0 all-caps strings** [MEASURED].
- No interpunct prose. The stage notes, the architecture counts and the slice state are sentences:
  "Slice warm, refreshed at 14:02: 8,120 of 112,400 tokens, 2 paths withheld."
- Every doctrine line is gone from the chrome — "Ikarus proposes. You decide.", "Nothing runs
  without you", "verbatim, never scored", "named above, not hidden". Grep of the built bundle:
  0 hits. The behaviour carries the meaning instead: Approve/Reject is the decision, the council
  pane is unscored, the withheld count is named in the transcript.
- The three fake traffic lights were never rebuilt.
- The metric strip is a sentence: "Daedalus holds 149 modules in 4 islands, and 11 of them are dark
  — nothing in the index reaches them. M". Receipts are a plain list.
- The kill switch is a status-line entry with a real control and a confirm dialog, and the resolved
  host line changes when "local traffic may leave this machine" is switched on.

### Fix 4 — "Rebuild accessibility and controls"

- `role="tablist"` with `aria-selected` and arrow keys: project tabs (vertical), mission stages,
  settings sections. `role="tree"`/`role="group"`/`role="treeitem"` with `aria-expanded` and
  `aria-selected` in the library. `role="combobox"` + `role="listbox"` + `role="option"` +
  `aria-activedescendant` in the palette. `role="radiogroup"`/`role="radio"` for lenses, route,
  write rights, appearance. `<button role="switch" aria-checked>` for the toggles.
- The spending ceiling is a real `<input type="range">` with `aria-valuetext`, a visible thumb and
  native keyboard handling. `ElasticSlider` was deleted.
- Dialogs are `role="dialog" aria-modal="true"` with a focus trap, Escape, and focus restored to
  the control that opened them.
- Visible focus rings on everything (`:focus-visible`, 2 px accent, 2 px offset).
- **0 targets under 44 px on all four screens** [MEASURED, `audit.cjs`]. The switch is a 51×44
  target around the 51×31 macOS visual.
- Reduced motion is genuine. `motionOn` is threaded into GSAP (`FadeContent` never creates a
  timeline and never leaves the element hidden) and into Motion (`AnimatedList`, `Stepper` render
  at their resting values with zero duration), and the streaming interval collapses to instant.
  Calm is a real 45 % of every duration, not a synonym for Full. `prefers-reduced-motion: reduce`
  overrides the setting to Off. Verified: with motion off, **0 elements are left
  `visibility: hidden`** [MEASURED, `verify.cjs`].

### Fix 5 — "Remove requirement-shaped garnish"

Deleted from the tree: `Folder`, `Counter`, `Masonry`, `AnimatedContent`, `StaggeredMenu`,
`ElasticSlider` (and the vite-template `hero.png` and `icons.svg`). The library's bento grid is
gone; the tree is the navigation. Settings is a full preferences screen in the Views list, not an
application architecture squeezed into a modal — translucency is reserved for what genuinely
floats, the ⌘K palette and the dialogs.

---

## 2. React Bits — four items, all structural

Installed from `@react-bits` into this app dir only. Each adaptation is additive and marked in the
file header; nothing was gutted the way `ElasticSlider` was last round.

| Item | Structural role | Adaptation |
|---|---|---|
| `Stepper-TS-CSS` | **The order timeline.** It owns the six-stage indicator row and the animated detail panel below it. All six stages are named with their own state; the panel is the current stage's detail, including the Approve/Reject proposal. | `hideFooter` (mission state is not advanced by a wizard button), `hideConnectors`, `stepContainerProps` so the indicator row is a real `role="tablist"`, and `motionOn`/`durMs` so the Motion setting stops it. Restyled onto the design tokens. |
| `AnimatedList-TS-CSS` | **The Ikarus transcript and the ⌘K result list.** In the transcript it is the scroll container that follows the newest turn; in the palette it is the listbox. | `interactive={false}` for the transcript (no pointer cursor, no hover selection, no global key listener — Codex's complaint), `controlledIndex` so the palette owns the active row, `itemProps` so each row gets its real ARIA role and id, `autoScrollBottom`, `motionOn`. |
| `FadeContent` (GSAP) | **Pane transitions only.** Screen and project changes, the inspector switching between summary and selection, the library page, the settings section. | `motionOn` — with motion off the timeline is never created and nothing is left hidden (this was the reduced-motion bug); `immediate` play on mount instead of a ScrollTrigger, because these panes are swapped in place, not scrolled into view. |
| `LineSidebar-TS-CSS` | **The Views navigation** (Cockpit / Knowledge library / Settings) with its proximity marker as the active indicator. | Each row is a real `<button aria-current="page">` at 44 px instead of a clickable `<li>`; `activeIndex` is controlled by the app router; `motionOn` stops the rAF proximity loop. |

The four planes' node shapes, the atlas, the split view, the mission band and the status line are
ordinary CSS grid and SVG. That is deliberate: React Bits owns navigation, timeline, list and
transition, and nothing else is dressed up to raise the count.

---

## 3. Every control on the cockpit

| Control | What happens | Fixture or disabled |
|---|---|---|
| Project tab — Daedalus | Switches every pane to the Daedalus index: atlas, mission, transcript, inspector, library wiki, counts | Works against fixture |
| Project tab — TCT scan planner | Whole content area becomes "No index yet — run the watcher", with the 62 / 2 / 3 counts the watcher did record | Works against fixture |
| Project tab — Lehrstuhl wiki | Same, with "Nothing has been indexed in Lehrstuhl wiki yet" | Works against fixture |
| Run the watcher (empty state) | — | **Honestly disabled**: "Needs the Daedalus service. This prototype has no backend." Reason printed under the button, not only in the tooltip |
| Views — Cockpit / Knowledge library / Settings | Switches screen; the marker and `aria-current` follow | Works |
| Search (Ctrl K) | Opens the command palette | Works |
| Stage tabs ×6 | Shows that stage's detail; arrow keys move; each tab shows its own state word. Inspecting a stage never edits mission state | Works against fixture |
| Approve (Build) | Build → Done, Gates → Running, status line → 18 attempts done, decision record with Undo, Ikarus turn appended | Works; the record says the decision is stored in this prototype only |
| Reject (Build) | Attempt 18 marked rejected, status line → 5 rejected, "the build waits for attempt 19", Ikarus turn appended | Works, same honesty note |
| Undo (after a decision) | Restores the proposal state and the counts | Works |
| Lens — structure | Plain typed graph; edges at rest | Works against fixture |
| Lens — evidence | Verified edges lifted, the 3 unverified ones drawn dashed in the warning colour with their score, and their nodes ringed | Works against fixture |
| Lens — cost | Node ring sized by fan-in where the index measured it; the other 30 nodes drawn hollow rather than guessed | Works, with coverage stated |
| Focus the slice | Frames the atlas on the distilled module at 1.6× | **Disabled until a module is distilled**: "the fixture does not record which modules are in the slice" |
| Reset view | Returns the atlas to scale 1 and no pan | Works |
| Atlas — click a node | Selects it; unrelated nodes drop to 35 %, unrelated edges to 6 %, the subgraph is drawn in the accent with relation labels; the inspector fills | Works against fixture |
| Atlas — hover a node | Same emphasis, transient | Works |
| Atlas — arrows / Enter / Escape | Move the cursor between nodes, select, clear | Works |
| Atlas — wheel / drag | Zoom around the pointer 0.6×–3×, pan | Works |
| What changed | Rings the 2 modules with recorded churn, dims the other 30, caption names the coverage, Ikarus reports it with an M stamp | Works against fixture |
| Hotspots | Switches to the cost lens, dims the unmeasured, caption "Cost is measured for 2 of 32 nodes", Ikarus reports the fan-in figures | Works against fixture |
| Distill enforce.py | Focuses the slice on that module, selects it, rewrites the slice line, enables Focus the slice, Ikarus reports the slice state | Works against fixture |
| Composer + Enter / Send | Appends the owner turn, streams the reply word by word | Works. The reply itself is the honest disabled state: it says it cannot answer without the service and carries no provenance stamp |
| Clear selection | Empties the selection, inspector returns to the architecture summary | Works |
| Open its wiki page | Opens the library at the matching page | Works when the node has a page; otherwise the control reads "No wiki page for this node yet" and is disabled |
| Read the 3 council opinions | Opens a dialog with the three vendor opinions verbatim, unscored | Works against fixture |
| Kill switch — Disarm / Arm | Confirm dialog, then the status line changes state | Works; the dialog says no lane is connected to stop |
| Status line provenance letters | Tooltip explains M / I / A | Works |
| ⌘K — Distill *module* | Focuses the slice on the typed or selected module (falls back to the most called-into module in the index) | Works |
| ⌘K — Focus *module* | Selects it in the atlas and returns to the cockpit | Works |
| ⌘K — Canary | — | **Honestly disabled**: "Needs the Daedalus service. Nothing can run from this prototype." |
| ⌘K — Council | Opens the council pane | Works |
| ⌘K — Doctor | Opens a pane with the lanes, resolved hosts and the key statement | Works |
| ⌘K — Open page | Goes to the library | Works |
| ⌘K — Find module | Switches the palette to a module-only search over all 32 nodes | Works |
| ⌘K — any module or page row | Selects the node in the atlas, or opens the page | Works |

Off the cockpit: the library tree, the backlinks (each with a real destination), **Show on the
atlas**, **Regenerate from the index**, the notes field, and every settings control (route, local
egress switch, ceiling slider, per-runtime write rights, memory switches, retention, theme, accent,
motion, text size, density, Delete everything) all change visible state and persist. The locked
matrix cells are statements, not controls, exactly as the fixture writes them.

---

## 4. Measurements

`npm run build` exit 0. Screenshots at 1440×900, 2.5 s settle, motion running, real Chromium via
`playwright-core`.

`node verify.cjs` — 62 assertions driving the real UI: **62 passed, 0 failed** [MEASURED].
It covers per-project switching, chat submit and streaming, all three quick actions, approve /
reject / undo and their counts, palette filtering and every verb's destination, the atlas keyboard,
zoom and pan, settings effect and persistence across a reload, delete-everything, the kill switch,
note survival, and `prefers-reduced-motion`.

`node audit.cjs` [MEASURED]:

| | cockpit | library | settings | palette |
|---|---|---|---|---|
| contrast failures (AA) | 0 | 0 | 0 | 0 |
| targets under 44 px | 0 | 0 | 0 | 0 |
| radii | 8px, 50% | 8px, 50% | 8px, 50% | 8px, 50% |
| all-caps strings | 0 | 0 | 0 | 0 |
| framed panels | 0 | 0 | 0 | 1 (the floating palette) |
| visible elements | 384 | 110 | 116 | 667 |

Font sizes on the cockpit: 12 px (atlas node labels only, the floor the brief allows), 13 px (the
four plane band labels), 15 px (secondary, all AA), 16 px (body), 17 px (window title), 21 px
(mission title). Library adds 19 px and 40 px for the article; settings adds 34 px for the title.

---

## 5. What I could not do, and what I chose not to

- **The old anti-slop budget of ≤ 150 visible elements is missed on the cockpit (384).** The atlas
  alone is 32 labelled, selectable nodes and 38 edges. Cutting to 150 would mean hiding the graph,
  which is the opposite of "the graph is the hero". Library and settings are at 110 and 116.
- **Tab does not step between atlas nodes.** The brief asked for "Tab/arrows move between nodes",
  but Tab-per-node makes the graph a keyboard trap with 32 stops. I used the standard roving
  tabindex instead: Tab reaches the atlas, arrows move, Enter selects, Escape clears, Tab leaves.
  This is a deliberate deviation.
- **The cost lens is only 2/32 measured.** The fixture records fan-in and churn for two module
  pages and nothing else. Rather than invent a cost per node, unmeasured nodes are drawn hollow and
  the caption states the coverage. The same is true of "What changed".
- **Two wiki pages and both global pages have no body in the fixture.** They render as index
  entries with the sentence "This page is in the library index, but the fixture does not carry its
  text", instead of a written-out page.
- **Containment edges are derived.** The fixture models a file defining a member twice — once as an
  explicit `defines` edge (c1→c2) and once as a `parent` field (c5→c6, c5→c7, c8→c9, c10→c11).
  I derive the four missing edges so the atlas does not emphasise members with no visible link.
  This is stated in `data.ts`; it adds no relation the fixture does not already assert.
- **Stage notes are rendered as sentences.** The fixture writes them as interpunct fragments
  ("attempt 18 of 20 · Claude lane"). The numbers and lane names are the fixture's; only the
  punctuation and casing are the interface's.
- **No install failures.** `npx shadcn@latest add @react-bits/LineSidebar-TS-CSS` wrote
  `src/components/LineSidebar.{tsx,css}` directly, no `@/components` folder on this run.
- Nothing here reaches a network, a model, or the repository. Every "needs the service" state says
  so where the control is, not in a footnote.
