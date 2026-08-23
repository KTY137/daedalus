# Atelier — Daedalus v3 brief (2026-08-23)

The owner's ruling, verbatim in spirit: the trio IA is lifted, design freely. Keep the 3D graph
"wie früher" (the spatial forest from round 1, NOT the column grid); the rest of Sequoia v2 "sah gut
aus"; visionOS was the favourite look — build a 3D scene around the graph; combine the old proposals
with what we have now; be more creative and use common-sense UI practice from the internet;
**Ikarus is a main interface — the chat is the hero together with the graph**; and the ORDERED
four-plane column layout stays as an alternative representation of the same nodes.

Three source apps you may lift from (copy code, keep attributions in NOTES):
- 3D forest: `…/scratchpad/spike/scene/src/Forest.tsx` (three / @react-three/fiber 8 / drei 9, React 18).
- Glass material: `…/scratchpad/spike2/visionos/src/components/GlassSurface.*` (feColorMatrix already repaired there).
- Everything behavioural + the ordered atlas: `…/scratchpad/spike3/sequoia2/src/*` (state, actions, Palette, Settings, Library, Ikarus, Inspector, Atlas.tsx = the ordered view).
Scratchpad root: `C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/c46c7615-e718-4fa6-8756-9c4b7ccdd61b/scratchpad`.
Data: `fixture.json` in this directory (same as round 2). Reviews to honour: `…/spike3/review/sequoia2.md`
(Codex full review of v2) and `…/spike3/review/sequoia2-delta.md` (three levers). Do NOT open
`docs/design/prototypes/spike-2026-08-22` (retired HUD direction) or `apps/web`.

## The concept

**A room, an object, and a conversation.** The scene is a quiet dusk-grey room (not black, not indigo;
no shaders, orbs, beams, sparkles, fog, or glow). The codebase is the object in the room: a 3D forest
of nodes on four depth sheets (code nearest, knowledge farthest), drifting slowly until touched.
Ikarus is a glass window standing beside the object — the conversation is the reasoning trail, the
forest is the product (the chat-plus-canvas relation). Everything else is an ornament: project tabs
above, view/lens controls under the forest, one status sentence below, an inspector that slides in
from the right edge when something is selected. Nothing stacks on glass; nothing announces doctrine.

## Composition at 1440×900 (must also survive 1200 and 1680 wide)

- **Ikarus window, left, ~500 px, full height between ornaments.** Glass (GlassSurface). Inside:
  - header: project name, mission title (one line, 20 px medium), and the six stages as six words
    with state (Intent · Plan · Build · Gates · Delivery · Digestion) — compact, inside Ikarus, not a band.
  - thread: messages grouped by speaker; body 17 px; Ikarus text in white/primary vibrancy, owner text
    secondary; **provenance as an inline annotation at the end of the claim** ("measured", "inferred",
    "assumed" as a small labelled mark with a tooltip; a legend line once in the footer) — never a
    stray capital letter; **citations next to the claim, labelled with the file/symbol name, deep-linked:
    hover highlights that node in the forest, click focuses the camera on it**; withheld items named
    with kind and where, never silent.
  - **the decision is a message**: the current proposal (attempt 18) appears in the thread as a card
    with Approve / Reject / Why; approving or rejecting changes state visibly (stage word, status
    sentence, a follow-up Ikarus message) and is undoable.
  - suggestions: only contextual follow-ups beneath the last answer, derived from the current
    selection / mission state (e.g. after selecting enforce.py: "What calls enforce.write_root()?",
    "Distill around enforce.py"); none when nothing is selected except two use-case starters under an
    empty composer. Never generic chips.
  - composer at the bottom with labelled controls (Send, attach selection), the verify note near the
    input ("Ikarus cites what it measured; check the citation before you decide."), Enter sends,
    streaming replies short and scannable.
- **The forest, right, ≥ 60 % of the width, full height.** r3f canvas. Planes as four depth sheets with
  a faint reference grid (depth cue), camera head-on with slow ±3° drift that pauses on interaction,
  orbit by drag, zoom by wheel, Reset view. **Level of detail at rest**: labels only on hubs
  (top fan-in per plane) and on the hovered neighbourhood; only backbone edges at rest (top-k by
  degree or the spanning structure), full relations on hover / selection / lens change. **Labels are
  screen-aligned HTML (drei Html), 13–14 px, never perspective-distorted.** Selection: dim unrelated to
  ~30 %, the selected subgraph in accent with relation labels, and a **local-graph mode** — a depth
  selector (1 · 2 · all) in the ornament re-centres the forest on the selected node. Hit targets ≥ 44
  px via invisible hit discs (and count them in your audit — SVG/3D included).
  - **Bottom ornament of the forest** (visionOS: floats over the bottom edge, overlapping by 20 px,
    borderless buttons, ≥ 44 px targets, 16 px between buttons): view toggle **Spatial / Ordered**,
    lenses Structure / Evidence / Cost, depth 1 · 2 · all, Reset view. Ordered = Sequoia v2's
    four-plane columns drawn in the same canvas space (2D layout), **same nodes, same selection,
    positions morph (lerp ~600 ms)** between the two views.
  - legend as one sentence under the ornament; the slice state as one sentence ("Slice warm, refreshed
    at 14:02 — 8,120 of 112,400 tokens, 2 paths withheld" with its provenance mark) and "Focus the
    slice" with its disabled reason printed when disabled.
- **Inspector ornament, right edge.** Collapsed: a slim vertical tab "Knowledge". Expanded on selection
  (or click): a glass panel beside the forest (the forest yields width; never overlaps it) with: node
  facts (plane, kind, fan-in/out with provenance, churn), its edges (verified / proposed), the wiki
  page with backlinks ("Linked from"), "Open its wiki page", "Ask Ikarus about this" (seeds the
  composer with the node), council opinions verbatim and unscored beneath the page. Empty (nothing
  selected) = architecture sentence for the project with provenance.
- **Top ornament**: project tabs with FULL names and a watcher state word on hover (dot + label, never
  colour alone); ⌘K / Ctrl-K. **Bottom**: one status sentence — lane, resolved host, spend with
  provenance, kill switch as a real control with a confirm dialog. No other status lines anywhere.
- **Library**: a second window that replaces the forest area (Ikarus stays): tree (≤ 2 levels, ≥ 225 px),
  page, backlinks, module pages with managed notes, "Show in the forest".
- **Settings**: a glass **sheet** over the scene (not a page): Routing & rights (locked cells as
  statements), Memory & privacy, Appearance (Dusk / Day room / Auto; accent; motion Full / Calm / Off;
  text size). Day room = a light-grey room with the same glass rules.
- **⌘K**: one palette, fuzzy, recents on empty, categories and shortcuts inline, prefixes (`@` node,
  `#` page, `>` command), every action reachable; no settings inside it.

## Rules from the research (binding; sources in RESEARCH.md beside this brief)

- Chat: citations beside the claim with meaningful labels and deep links; no fake chain-of-thought;
  neutral non-anthropomorphic language; verify note near the input; suggestions only contextual.
- Graph: overview first, zoom and filter, details on demand; labels above a zoom threshold only;
  one accent reserved for interactive state; no global hairball; local graph around the current node
  is what people actually use; 3D only with rotation, depth cues, screen-aligned labels, tooltips.
- Spatial (Apple WWDC 10076): windows are glass — no solid-colour windows, no glass stacked on glass;
  text on glass is white-ish, heavier weights (body medium, titles bold), slightly wider tracking,
  system fonts, vibrancy tiers, never custom low-contrast colours; ornaments float outside the
  window; every interactive element has a hover shape; 60 px hover targets where possible, 44 px
  minimum, 16 px between stacked buttons; concentric continuous corners (outer 20 / padding 8 / inner
  12); hierarchy by layering not colour; keep the important content centred; wider beats taller.
- Desktop: sidebar 225–400 px, ≤ 2 levels; macOS uses sidebar + toolbar + inspector, never tab
  bars; controls grouped by proximity and named functionally.
- Tells to avoid: Inter, purple gradients, three-card triptychs, badge-above-headline, coloured
  left-border cards, 1-2-3 steps, neon glows, glass on everything, floating orbs, thin generic line
  icons, weightless copy, dashboards of status tiles, "Source" as a label, stray provenance letters.

## Honesty (binding, tested)

- Per-project scoping is real: switching projects changes forest, thread, inspector, palette rows and
  the status sentence, or shows "No index yet" — **write a fake-data test**: for each project, the
  status sentence, the palette's node rows and any wiki page must differ from Daedalus's or be
  explicitly empty; fail the build if not.
- Every control works against the fixture or is disabled with its reason **printed** (not only a
  tooltip). Send when empty: disabled with "Type a question first" beneath.
- Count ALL targets, including SVG and 3D hit discs; report the real minimum.
- React Bits must be structural: GlassSurface (window material), AnimatedList (thread), Stepper or an
  equivalent compact stage row, Dock or GooeyNav for the project tabs ornament (verify ids in the
  registry via the shadcn MCP), FadeContent for pane transitions. No backgrounds, no text effects.

## Deliverables (in this directory's `atelier/` app; touch nothing outside it)

Vite + React 18 + TS, base './', `npm run build` exit 0, `?screen=cockpit|library|settings|palette`
and `?state=selected|ordered|decision` query hooks. Real 1440×900 screenshots (2.5 s settle,
motion running): `cockpit.png`, `cockpit-selected.png` (node selected, inspector open, local depth 1),
`cockpit-ordered.png`, `cockpit-decision.png` (proposal card in the thread), `library.png`,
`settings.png`, `palette.png`, `dayroom.png`. Read each and fix what is wrong. `NOTES.md`: concept in
three sentences, what came from which source app, React Bits items and their structural role, the
control table (control → what happens → works / disabled + printed reason), the fake-data test
output, the real target minimum including 3D, and what is unfinished. Foreground verification only.
