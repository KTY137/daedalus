# Aurora — iteration brief (2026-08-23)

The owner's verdict on the last build: **"das ist viel viel zu loaded — da war die vorherige 3D-Szene
besser."** Then: iterate four times on that, with a critical Apple-designer review between each
round; be creative, be awesome, be beautiful.

So this is not a feature round. It is an **art-direction round with a subtraction budget.**

## The starting point

`…/scratchpad/spike/scene` (round 1, "C · 3D-Szene") — the quietest thing we ever built:
**43 visible DOM elements, one framed panel**, rim readings as bare sentences in the corners, the
four planes as literal depth sheets. The jury called its rim "the most Jobs-like piece of typography
in the whole spike" and the depth sheets "the one genuinely new spatial idea".

Its measured failures, all fixable and all forbidden to repeat: no node labels (32 anonymous blobs);
body text on CSS3D-skewed planes; LightRays + Sparkles + fog + glow sprites stacked; an Orb mascot;
the top third empty while panels crowd the bottom; a 1.25 MB three/r3f/drei bundle.

The thing to beat, and to strip: `…/scratchpad/spike4/atelier` — correct behaviour, wrong density
(384 elements, six permanent explanation sentences, pills, cards on glass, a grey diorama).
**Take its logic, throw away its surface.**

## The law of this round

> One room. One object. One voice. Everything else appears when asked.

**Element budget at rest: ≤ 70 visible DOM elements on the main screen.** This is measured with
`daedalus/gui/probe.js` and it is the hard gate of the round — a beautiful screen that measures 200
has failed. Every element must earn its place by being read in the first ten seconds or by being the
one thing the user's pointer is on.

Concretely, at rest the screen carries: the conversation (as type, not as a panel), the object, one
line of state per corner, and nothing else. No headers, no section titles, no cards, no chips, no
pills, no capsules, no permanent explanation sentences, no legends that repeat what the picture says,
no toolbars. Controls fade in on hover over the region they act on; ⌘K, inspector, library and
settings arrive on demand and leave completely.

## Art direction

**The room.** Not black, not grey-flat: a room with a light source. A deep, slightly cool ground
(#07090C–#0E1116 range) that is *lit* — a soft falloff behind the object, darker at the frame edges,
so the object sits in space rather than on a background. No shader backgrounds, no rays, no
particles, no orbs, no vignette clichés. If you add atmosphere, it must be physically motivated by
the object (its own glow spilling onto the ground).

**The object.** The four planes as depth sheets, but the forest must look like a made thing:
- material, not primitives: nodes with real shading — a warm-neutral base, slight specularity,
  ambient occlusion where sheets overlap, and *emissive* only where meaning demands it (the node
  the conversation is about, the live attempt);
- colour with meaning and restraint: the planes differ by value and temperature, not by four hues;
  one accent for what the pointer or the conversation is on;
- silhouette: node size from fan-in across a wide enough range that the graph has rhythm; hubs read
  as hubs from across the room;
- depth cues: a faint ground shadow per sheet, near/far contrast, mild depth of field on the far
  sheet only (never on text);
- edges: at rest only the backbone, drawn as light that *travels* slowly along the live path (one
  subtle motion, the room's heartbeat) — everything else on hover/selection;
- labels: 6–8 at rest, screen-aligned, set in the same type as the conversation, never colliding
  (measured: zero overlaps), the rest on approach.

**The voice.** The conversation is typography in the room, not a window: no frame, no card, no
avatar, no name badge repeated per message — the owner's words in a lighter weight, Ikarus in the
brighter one, generous leading, ~60 characters per line, large enough to read as prose (17–19 px).
Provenance is a small typographic mark at the end of the sentence it belongs to, with a tooltip.
Citations are the file name set inline in the sentence, underlined, and hovering one lights its node
in the forest. The composer is a single line of type with a hairline under it — no box, no button
until there is something to send.

**The decision.** When an attempt waits, the room says so once, in the voice: a short paragraph and
two words to act on. It is the only place where a filled control is allowed.

**Motion.** One ambient behaviour (a slow drift or the travelling light), one transition family
(spring, short, same curve everywhere), and stillness otherwise. Motion Off must actually still the
room. If motion draws attention to itself, it is wrong.

## What must still be true (from the earlier rounds — non-negotiable)

- Per-project isolation, enforced by the fake-data gate in the build (keep `fakedata.cjs`).
- Every control works against `fixture.json` or is disabled — but the reason now lives in a tooltip
  and in the one contextual line that appears only when the user tries or hovers that control.
- Withheld items are named with kind and place. Citations point at real fixture nodes.
- Targets ≥ 44 px including 3D hit discs; AA contrast on every text; keyboard: arrows move in the
  forest, Enter selects, Esc clears; visible focus; ⌘K opens and dismisses on one key.
- The Ordered view stays as an alternative representation of the same nodes (owner's request):
  reachable, same selection, morphing — but it is a *state*, not a permanently visible toolbar.
- No React Bits background components or text effects. React Bits only where it carries structure
  (list, sheet, nav) and only if it makes the screen quieter, not louder.

## Deliverables per iteration

App under `…/spike5/aurora`. `npm run build` exit 0 with the fake-data gate. Screenshots at
1440×900, motion running, 2.5 s settle, each READ and corrected: `rest.png`, `selected.png`,
`decision.png`, `ordered.png`, `palette.png`, plus `elements.json` from the probe with the visible
element count at rest. `NOTES.md`: what changed this iteration, the element count, the label-overlap
count, what you removed, and what you refuse to remove and why.

The round is judged by a critic playing an Apple designer — avant-garde, allergic to templates,
reading the current web on what gives interfaces life. Beauty is the deliverable; the numbers are
the floor, not the goal.
