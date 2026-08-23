## Verdict

Reject this round. It avoids the forbidden sci-fi aesthetic, but it still looks like an AI assembled a macOS-flavoured component gallery from a feature checklist. Worse, several prominent controls are façades: the prototype says “you decide,” yet there is no decision workflow.

## 1. AI-generated-design tells

### Everywhere

- The three grey “traffic lights” at the top-left are decorative imitation window chrome. They are neither native nor functional.
- “Menu +” is a stock animated-menu demo grafted over a sidebar that already contains the same navigation. The plus sign conventionally means Add, not Menu.
- The entire window is a dashboard template: permanent sidebar, packed toolbar, three columns, inspector, KPI strip, bottom status ticker. Every region advertises a feature; nothing is edited down.
- Interpunct abuse is everywhere: “proposes · you decide,” “32 nodes · 34 edges · 3 proposed,” “slice: warm · refreshed,” “concept · knowledge plane,” “Done · esc.” This is classic AI microcopy styling.
- Rounded-rectangle proliferation: selected sidebar rows, chat bubbles, quick-action chips, search field, segmented controls, backlinks, cards, sheets and palette rows.
- The interface dumps nearly every fixture number simultaneously—149, 4, 11, 32, 34, 3, 24/24, 12,480, $0.41—creating a staged “look how much data I have” demo rather than a product hierarchy.
- Product doctrine is repeated as interface decoration: “Ikarus proposes. You decide,” “Nothing runs without you,” “verbatim, never scored,” “named above, not hidden.” One clear policy explanation is useful; repetition becomes branding filler.

### Cockpit

- The Ikarus column is the generic AI-chat recipe: blue user bubble, grey assistant bubbles, chip actions and a rounded composer.
- The order timeline is a stock six-circle stepper. Hiding five stage names makes it look cleaner in a screenshot while removing the feature’s meaning.
- “Architecture” is the familiar three-number dashboard-stat strip.
- The oversized bright-blue folder is visibly a third-party demo component. Its skeuomorphic shape and paper animation belong to a different design system from the atlas and split view.
- The atlas resembles a graph-library showcase: spaghetti curves, tiny nodes, clipped labels and explanatory legend text. “Hover for neighbours · click to inspect” reads like prototype instructions left in the product.
- Labels such as “Master Plan §4 Inva…,” “fixtures/adapters/*…” and “artifacts/ (content-…)” are knowingly truncated without a zoom, pan or disclosure strategy.
- The lower half of the atlas is mostly unused while its meaningful labels are crushed into four narrow columns.
- The empty inspector starts with “Nothing selected,” making a third of the product’s right side look unfinished in the hero screenshot.

### Library

- The alleged Masonry layout is seven equal cards in a 4+3 “bento” grid. Every item has the same height, so Masonry has no reason to exist.
- Those cards repeat navigation already visible in the sidebar. They are there to fill the top of the page and demonstrate a component.
- The right inspector shows `enforce.py` while the actual page is “Sealed promotion.” This unrelated persistent context is a strong generated-dashboard tell.
- Backlinks become another row of rounded chips, followed by a separate blue rounded action.
- “The section above is regenerated…” and “Hand notes survive regeneration” are explanatory annotations standing in for trustworthy behaviour.

### Settings

- This is the standard Dribbble/web interpretation of macOS Settings: large centred rounded modal, nested sidebar, blur and shadow.
- A full application-preferences architecture is squeezed into something called a sheet. It is not a small, context-bound decision.
- The custom slider has no visible thumb. It reads as a progress bar beside `$2.00`.
- The matrix mixes sentences, values and custom segmented controls in the same column. It looks engineered to demonstrate the brief rather than designed around a user’s decision.
- “Done · esc” at the bottom-left is an awkward hybrid of action and keyboard instruction.

### Palette

- It is a near-default Spotlight/Linear command palette clone: oversized placeholder, solid-blue first result and a tiny keyboard-help footer.
- “Type a command or a module name” promises module search, but the list only contains seven canned verbs.
- The doctrine footer—“Nothing runs without you. Every verb ends in a decision.”—is false in implementation and visually reads as manifesto copy.

## 2. HIG and binding-brief violations

Apple’s current guidance emphasizes readable/adaptable content, sufficient contrast and non-colour cues; coherent segmented controls; sidebars with meaningful hierarchy and disclosure; and sheets for scoped contextual tasks. [Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility), [sidebars](https://developer.apple.com/design/human-interface-guidelines/sidebars), [segmented controls](https://developer.apple.com/design/human-interface-guidelines/segmented-controls), [sheets](https://developer.apple.com/design/human-interface-guidelines/sheets).

### Typography and contrast

- The brief requires 15–17px body text. Most of the cockpit, sidebar, inspector, settings descriptions and palette hints are 12–14px; receipt metadata is 11px and the folder papers are 8px.
- Only the library page gets a meaningful large title at 40px. Cockpit titles are 20px, Settings is 28px and the project title is 17px. Type does not carry those surfaces.
- `#A1A1A6` tertiary text on `#F5F5F7` is approximately 2.3:1—well below AA for normal text. It is used for mission IDs, composer policy text, card metadata, keyboard hints and notes.
- Atlas labels and edges are deliberately faint despite being the core content.
- The Text size preference mostly changes inherited body text; explicit 11, 12, 13 and 14px declarations remain fixed.
- Critical codebase labels are truncated instead of reflowing, expanding or offering a readable alternative.

### Spacing and geometry

- The claimed 8pt system is not visually enforced. Heights and offsets mix 28, 31, 32, 36, 40, 44, 52 and 56px.
- The claimed single radius scale is false: visible radii include 6, 8, 12, 16 and 20px, plus fully circular controls.
- The 56px toolbar holds lenses, slice state, a primary action, faux search and spending data with inadequate separation.
- The bottom 28px status bar crams eight unrelated status groups into 12px text.
- The sidebar permanently exposes project navigation, view navigation and the entire library hierarchy, leaving no deference to the active task.
- The brief’s stricter 44px target is missed by the 28px stage controls, 28px inspector links and numerous 32/36px buttons. These may exceed Apple’s macOS minimum, but they still fail the binding brief.

### Hierarchy, deference and depth

- The Codebase is nominally the hero, but receives only about 41% of the total window width. Persistent navigation, chat and inspector consume the majority.
- Two full-width blue sidebar selections compete with the blue chat bubble, blue Focus action, blue palette row and blue folder. Accent no longer signals one clear priority.
- The library card grid competes with the actual page title and body.
- The active page is not highlighted in the library tree.
- The sidebar is translucent in CSS but visually behaves as an anchored grey column with a separator. Content does not extend beneath it, so the material provides little depth.
- Depth is reserved for oversized web modals and card shadows rather than representing navigation and content layers.
- Settings places a second sidebar over the first sidebar, producing nested navigation rather than a clear modal task.

### Controls and accessibility

- The faux search field is a button. It looks editable but cannot accept text until a separate overlay opens.
- Lens buttons have `role="tablist"` on the container but no tab roles or `aria-selected` state.
- The spending slider is a pointer-driven `div`, with no `role="slider"`, keyboard handling, focus target or `aria-valuenow`.
- The atlas is a pointer-only canvas with no semantic fallback, keyboard navigation or VoiceOver representation.
- Masonry page cards are clickable `div`s without button/link semantics or keyboard activation.
- Palette results are clickable `div`s, not a listbox/options model, and selection isn’t exposed accessibly.
- Dialogs lack `aria-modal`, focus trapping and reliable focus restoration.
- The folder’s keyboard handler accepts Enter but checks an empty string instead of the Space key.
- Most focus treatment is browser-default or absent. Composer and textarea remove outlines and replace them with faint border changes.
- Reduced motion is not genuinely respected. The media query alters CSS durations, but GSAP and Motion animations continue; only the atlas receives the calculated motion flag.
- “Calm” behaves essentially like “Full”; “Off” does not stop all JavaScript-driven motion.

### Colour and state communication

- The active live watcher turns white inside the blue project row, so its semantic green “live” state disappears.
- Node shapes and grey shades distinguish planes without a legend; this becomes especially weak for Data versus Knowledge.
- Timeline state is mostly conveyed by blue/grey treatment. Only the currently selected stage exposes a written state.
- Orange is appropriately reserved for proposed edges and withheld data, but the extremely small orange text weakens the warning.

### Sentence case and copy

Visible violations of the brief’s “sentence case everywhere” include:

- “slice: warm”
- “proposes · you decide”
- “verified” and “proposed, not yet verified”
- “verbatim, never scored”
- “concept · knowledge plane”
- “auto page · hand notes”
- “never,” “ask every time” and “within a mission”
- “return,” “return to run” and “esc to close”
- Every command hint beginning with lowercase text

Clarity also suffers from unlabeled project counts, jargon-heavy status chrome, the ambiguous `M` beside spend, duplicate “Show on the atlas” actions and the unrelated module inspector on a concept page.

## 3. Feature-list audit

| Feature area | Verdict |
|---|---|
| Ikarus conversation | Transcript and M/I/A stamps are visible; withheld outputs are named. There is no streaming state, submission handler, Send action, proposal object, approval or execution decision. The composer only edits local text. |
| Six-stage order timeline | Six dots exist, but only the selected stage name and state are visible. Clicking a past/future stage changes the explanatory note, making mission state look editable. |
| Quick actions | Visible, but they only select fixed node IDs. “Hotspots” and “Distill enforce.py” both select `c5`; no distillation proposal occurs. |
| Per-project trio | Missing. Project rows change the outer title, but Cockpit deliberately reads `projects.find(p => p.active)`, so graph, mission, chat and architecture remain Daedalus. These are not project tabs and each project does not get its own trio. |
| Living Codebase graph | Four planes, verified/proposed edges, pointer hover/click and lens morphs exist. It lacks keyboard access, zoom/pan, readable label handling and a useful cost view. |
| Focus the slice | The button merely resets Structure and selects `c5`; it does not meaningfully focus or frame the slice. |
| Knowledge inspector | Selection, neighbours, architecture counts, receipt summary and council opinions exist. Initial empty state wastes the hero screenshot. |
| Knowledge Library | Global/wiki/module groups, backlinks and atlas links exist. The “tree” is an always-expanded flat list without disclosure or active-page state. Selecting another project only renames the wiki group; it does not supply that project’s wiki. |
| Module pages and hand notes | Module stats and editable notes exist. Notes live only in component state and disappear when Library unmounts, so “survive regeneration” is unsupported. |
| Project tabs and watcher | Missing as specified. There are sidebar buttons and ambiguous dots, not tabs; live loses its green state when selected. |
| Token/spend provenance | Visible, although the animated count is static fixture data and the isolated `M` depends on hover for meaning. |
| Command palette | Opens with ⌘K/Ctrl-K and filters seven commands. It cannot find actual modules. Canary, Council and Doctor simply close; Distill, Focus and Find module all perform essentially the same fixed selection. |
| Status line | Lane, resolved host, attempts, withholding and receipts are visible. The local-egress warning does respond to its toggle. |
| Routing & Rights | Route, toggle, matrix and locked statements are present. The slider is pointer-only; write choices reset when Settings closes; changes are not persisted or enforced. |
| Memory & Privacy | Controls and BYOK copy exist behind navigation. Delete everything explicitly deletes nothing. |
| Appearance | Theme works. Accent has one inert swatch; Text size and Density affect only portions of the UI; Calm doesn’t implement its claimed behaviour; Off/reduced motion misses JS animations. |

The most important source-confirmed stubs are the inert composer in [Cockpit.tsx](C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/c46c7615-e718-4fa6-8756-9c4b7ccdd61b/scratchpad/spike2/sequoia/src/Cockpit.tsx:91), canned command routing in [App.tsx](C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/c46c7615-e718-4fa6-8756-9c4b7ccdd61b/scratchpad/spike2/sequoia/src/App.tsx:209), local-only notes in [Library.tsx](C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/c46c7615-e718-4fa6-8756-9c4b7ccdd61b/scratchpad/spike2/sequoia/src/Library.tsx:14) and pointer-only slider in [ElasticSlider.tsx](C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/c46c7615-e718-4fa6-8756-9c4b7ccdd61b/scratchpad/spike2/sequoia/src/components/ElasticSlider.tsx:158).

## 4. React Bits: structure or garnish

| Item claimed in NOTES.md | Actual role |
|---|---|
| `StaggeredMenu` | Technically structural navigation, but redundant with the permanent sidebar. Its project links all open the same cockpit in a new tab and don’t select a project. Misapplied structure. |
| `AnimatedList` | Structural in the palette. In chat it is mainly an entrance wrapper around a static transcript; every inert message receives a pointer cursor. Mixed. |
| `Stepper` | Structural and correctly tied to the timeline concept, but the generic wizard model hides stage names and makes historical state look selectable. |
| `ElasticSlider` | A real control, but the React Bits adaptation removed the thumb and never added native slider semantics or keyboard support. Structural failure. |
| `Folder` | Garnish. Receipt data is already duplicated beside it, and the actual papers use 8px text. |
| `Counter` | Carries real data, but the digit animation is ornamental and the value is not live. Minor structural value. |
| `FadeContent` | Useful keyed transition for inspector and settings-section changes. This is the most defensible transition use. |
| `AnimatedContent` | Garnish. It repeatedly animates static inspector sections and the library page despite the claim of one quiet entrance. |
| `Masonry` | Structural navigation in code, but every tile has identical height, so it produces a conventional equal-card grid. The component choice is requirement-driven, not content-driven. |

The numerical registry requirement is met. “React Bits as the fabric” is not. The main application structure—the trio, library split, toolbar, sidebar and Settings layout—is ordinary CSS Grid/Flexbox; React Bits appears as conspicuous widgets inside it. NOTES.md accurately lists the imports, but overstates their design coherence.

## 5. Three strengths to keep

1. The four-plane atlas model is the right conceptual centre, and verified solid versus proposed dashed edges are immediately understandable.
2. Provenance, named withholding and unscored council opinions preserve the product’s evidence discipline without inventing scores.
3. The restrained light ground, system font stack and hairline split-view foundation are viable; the large library article title is the only surface where the intended typographic hierarchy is demonstrated.

## 6. Five fixes to make first

1. Make the product loop truthful: real per-project trios, chat submit/streaming, explicit proposal and owner-decision states, distinct quick-action outcomes, real module search and real command destinations.
2. Recompose the cockpit around the atlas. Remove the full library tree and duplicate animated menu from this surface, show all six named timeline stages, and give graph labels enough space plus zoom/pan/focus.
3. Establish one visual specification: 16px body, AA secondary text, one radius system, one prominent blue action per context, consistent sentence case and no decorative interpunct prose.
4. Rebuild accessibility and controls: semantic tabs/tree/listbox/slider, keyboard atlas alternative, visible focus, proper dialogs and genuine reduced-motion behaviour across GSAP and Motion.
5. Remove requirement-shaped garnish. Delete the folder, static rolling counter and fake Masonry grid; use React Bits only where it owns a necessary navigation, state, control or transition. Present Settings as an honest preferences surface with standard controls and persistent state.

**Score: 3/10 — the atlas has a credible product idea, but the result still reads as a polished component-demo dashboard and its central “Ikarus proposes, you decide” workflow does not function.**
