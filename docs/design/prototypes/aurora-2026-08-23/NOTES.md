# Aurora — iteration 2, "Orrery"

Iteration 1 was refused: *"das sieht scheiße aus, ich wollte sowas wie eine
3D-Kugel, der Ikarus-Chat fehlt auch, das ist nh dead page"*. Three things were
wrong and all three are replaced, not patched.

| what was wrong | what it is now |
| --- | --- |
| depth sheets — a misread of the brief | **four bodies of nodes**, spheres with volume, each turning about its own axis |
| the chat was quoted text with no field | **Ikarus is a real chat**: visible field, blinking caret, Send, word-by-word answers out of the index |
| everything on hover — the page read as dead | **controls are there at rest**, the bodies turn, the caret blinks, two follow-ups invite the first question |

The frame is now the synthesis the owner named: **Sequoia's composition**
(sidebar, Ikarus column, hero in the middle, inspector taking width, one slim
toolbar, one status line), **visionOS material** (glass panels floating over
the room, an ornament under the stage overlapping its edge, concentric radii,
depth from layering), **Keynote's calm** (generous type, sentence case, one
clear title, the six stages as one compact line).

## The numbers

| | measured |
| --- | --- |
| **visible DOM elements at rest** | **85** (budget 90) |
| visible elements in the ordered view | 117 — it is a state, not the screen at rest, and its job is to carry all 32 names |
| **overlapping text boxes** | **0** (`overlap-check.json`) |
| **text boxes crossing a body silhouette** | **0** (`overlap-check.json`) |
| labels in the room at rest | 4 plane names; 1 callout under the pointer |
| ordered view | **36 labels** = 32 full node names + 4 group heads, 0 overlaps, none truncated |
| smallest 3D pointer disc | 46.2 px |
| AA contrast failures | 0 (rest and ordered) |
| targets | primary ≥ 44 px, chrome ≥ 36 px, both measured |
| `npm run build` | exit 0 with the fake-data gate |

## What the object is now

Four spheres of nodes hanging in one lit room:

- **code** nearest and largest (R 0.79, 12 nodes), **type** and **data**
  offset between, **knowledge** furthest and smallest (R 0.46). Size and depth
  agree, so the reading order is the same from any angle.
- nodes sit on the shell on a **golden-angle lattice** with a deterministic
  breath in and out of the surface — a body with volume, not a ring seen
  edge-on. Busiest nodes are walked out from the equator, where the shell is
  widest and a hub reads as a hub.
- each body turns about **its own tilted axis at its own rate** (0.050 to
  0.085 rad/s — a full turn between 74 and 126 seconds). Visible, never
  distracting; that is the frequency rule.
- a relation **inside** a plane is a chord through its body; a relation
  **across** planes is an arc that leaves one body and lands on another. At
  rest only the spine, drawn as fine threads, plus the live attempt's path
  `Mission.compile() → Attempt.run() → Ledger.charge() → runs/budget/ledger.json`
  with **one light travelling it** over nine seconds. Every hop is an edge the
  fixture actually carries.
- material and light are unchanged from iteration 1 and are the part that
  worked: warm-neutral bases, one warm key that is the only light casting,
  a cool fill and a cool rim from behind, a painted contact shadow under every
  node and every body, a painted lit back wall exempt from the fog, aerial haze
  instead of a depth-of-field pass. Emissive is the only saturated colour and
  it only ever means *this is what we are talking about* or *this is running*.

## Text discipline — the hard rule, and how it is kept

**No text ever lies across a body.** Placement is a search, not an offset:

1. every obstacle is collected first — the four projected silhouettes, and the
   rectangle of every glass panel, the toolbar, the ornament and the status bar;
2. each name is tried at a ring of candidate positions (16 angles × 5 radii)
   around its anchor, starting in the direction away from the constellation's
   centre;
3. a candidate is accepted only if its box misses every silhouette, every
   panel, every name already placed, and the frame edges;
4. a name that finds no clear position is **dropped**, never laid over the
   object.

So at rest the room carries four plane names standing in the gaps of the
constellation, and nothing else. The node under the pointer gets **exactly one
callout**, parked clear of every body with a hairline leader line back to it —
the leader is what lets a name sit off the object and still belong to it.
Selection details go to the inspector column, which has its own width in the
grid and therefore never covers anything.

`overlap-check.json` records both numbers, at rest, with the callout up, and in
the ordered view. Panel text over a body is counted and reported separately and
is **not** gated: a panel is glass with its own opaque fallback and its own
measured contrast, while a name in the room has nothing between it and the
object it would otherwise be lying on.

## The silhouette test

`silhouette-16pct.png` — `rest.png` at 16 % and blown back up. **Pass.** The
four bodies read as four separate clusters of different size with the live
arc running between two of them; the panel skeleton reads as a cockpit with a
clear hero in the middle. What does not survive at that size is which
individual node is which, which is correct — that is what the callout is for.

## Ikarus is a chat

- **A visible field** with a real caret, focused on load, and a Send that
  lights up when there is something to send.
- **Typing and Enter work.** The answer is assembled from the compiled index —
  name a module, a schema, a store or a page, or ask about spend, attempts,
  what was withheld, or the gate — and it arrives **word by word**, with a
  blinking caret while it streams. When the question is outside the index the
  answer is the honest sentence saying so, as a system notice carrying **no**
  provenance mark, because no model produced it.
- **Two follow-ups** derived from the thread, both of which the index can
  genuinely answer. They are the first thing a reader can click, which is what
  the dead-page complaint was really about.
- The thread scrolls to the last whole turn and runs off its top edge under a
  mask rather than being cut.
- A project with no compiled index answers nothing and says exactly that.

## Codex's objections to the glass, treated as a specification

| objection | what was built |
| --- | --- |
| placeholder glyphs | full project names, full view names, no icon dock at all |
| a second navigation system | one sidebar. The ornament carries stage state (Spatial/Ordered, Depth, Reset); the lenses live in the toolbar; nothing is duplicated |
| things cut off | nothing truncated at 1440×900; the ordered column carries every full node name |
| text on glass too thin / low contrast | 400–500 weights, primary `#F2ECE2`, secondary `#BDB4A7`, tertiary `#948C81`; every visible sentence is contrast-measured in `verify.cjs` |
| atmosphere instead of hierarchy | hierarchy is layering and value: room → glass → ornament, three surfaces, concentric radii (20 px containers, 10 px controls) |

## Everything from iteration 1 that stayed

Per-project isolation with the fake-data gate wired into `npm run build`; every
control works against `fixture.json` or is disabled with its reason in the
tooltip plus one contextual line when it is reached; withheld items named by
kind and by place; citations inline in the sentence that hovering lights in the
room; provenance as one typographic mark; the ordered view as a state; arrows,
Enter and Esc in the room; visible focus; ⌘K; warm-neutral palette; emissive
only for state; no second accent.

## Unfinished, and named

1. **The bundle is still 1.08 MB** (three + r3f + drei). Untouched from round 1.
2. **No real depth-of-field**; aerial haze stands in for it, because a post
   pass may silently not render under software GL.
3. **The conversation is German and the chrome is English.** That is the
   fixture's own text rendered verbatim; Ikarus's own answers follow the
   language of the question. A single-language product is an owner decision.
4. **The knowledge body is faint** at rest — it is the smallest and furthest,
   which is correct, but it is close to the floor of legibility.
5. **The stage's lower third is empty room** below the constellation.
6. **The ordered view has no camera choreography**; the nodes fly, the camera
   cuts to its named flat position.
7. **Library and Settings are still full-screen overlays**, not the fifth and
   sixth places in the Sequoia grid.

## Deliverables

`rest.png` · `selected.png` · `decision.png` · `ordered.png` · `palette.png` ·
`hover.png` (the callout and its leader line) · `library.png` · `settings.png`
— all 1440×900, motion running, 2.5 s settle, each one read and corrected.
`overlap-check.json` · `elements.json` · `verify.json` ·
`silhouette-16pct.png`.

## How to check it

```
npm run build         # tsc + vite + the fake-data gate; exit 0
node verify.cjs       # elements, overlaps, silhouette crossings, contrast,
                      # targets, keyboard, the callout and its leader line,
                      # Ikarus answering a typed question, Motion Off
node probe.cjs        # writes elements.json
node shoot.cjs        # rest / selected / decision / ordered / palette /
                      # library / settings / hover, 1440×900, 2.5 s settle
```
