# Variant A · Spatial Glass — NOTES

## The one design law
**Few panes, real refraction, the graph lives BEHIND the glass.** Three glass panes only
(rim strip, Ikarus, Knowledge); the four-plane Project Twin is drawn full-bleed on a lit
canvas underneath and the panes refract it (SVG feDisplacementMap via GlassSurface).
Lenses are a Dock at the bottom edge; switching a lens morphs the same nodes (CSS transform
transition on each node group), never swaps the picture.

## React Bits items (exact registry names, all installed via `npx shadcn@latest add`)
- `@react-bits/GlassSurface-TS-CSS` — the three panes (load-bearing: real refraction, chromatic rim)
- `@react-bits/Dock-TS-CSS` — the three lenses (structure / evidence / cost)
- `@react-bits/CountUp-TS-CSS` — rim numbers
- `@react-bits/DecryptedText-TS-CSS` — knowledge title + project ident resolving in
- `@react-bits/Threads-TS-CSS` — the living ground (ogl), rendered at half resolution and CSS-scaled 2x, opacity .55

Note: the shadcn CLI wrote the files to a literal `@/components` folder (alias not resolved
on Windows); they were moved to `src/components/` unchanged. The registry components pull in
`motion` and `ogl`.

Not used: FluidGlass (three.js + GLTF models; did not add depth the SVG refraction lacks),
LiquidEther (heavier than Threads; "nicht zu viel going on").

## Fonts (Google Fonts, loaded in index.html)
- JetBrains Mono — everything structural: labels, rim statements, backlinks, owner lines
- Space Grotesk — display: knowledge title, body, project ident
- Source Sans 3 — Ikarus's voice ONLY (the single humanist face: cold glass, warm voice)

## Scene coverage
- Hero graph: all 31 nodes, 35 edges; unverified cross-plane edges are dashed amber with a
  flowing dash offset and a dashed amber halo on their endpoints (proposal, not fact);
  verified intra-plane edges are plane-hued, cross-plane curve upward. Hover dims everything
  off the node's neighbourhood and prints a two-line reading beside it (label · plane · kind ·
  lens-specific figure). Structure = staggered plane columns (code top-left, knowledge
  bottom-right, panes in the opposite corners); evidence = rings by verified degree, proposals
  flung to the outer ring; cost = rank spectrum per plane band, radius = tokens touched
  (pseudo-cost from the fixture, deterministic), only the three dearest per plane labelled.
- Ikarus: all five messages; M/I stamps (lime/amber; A = oxide) as a letter with an underline,
  evidence lines, and the withheld line ("withheld 2 · secret-bearing paths").
- Knowledge: title, provenance, body, four backlinks, open question in amber.
- Rim readings: statements with an M stamp, units, and hue (amber live, oxide rejected, lime
  signed); kill switch armed at the far end. No tiles.
- Radii: one (14px) — Dock CSS overridden to the same token; GlassSurface borderRadius=14.
- Framed panels: 3 panes + dock = 4. Status pills: 0. No raw node ids in the DOM text.

## Deliberately left out
- No suggestion chips, no input field chrome (a single "Frag Ikarus" affordance line).
- No plane legend; the plane tags sit in the graph itself.
- No "d" path morphing for edges (Chrome can't transition the attribute) — edges snap,
  nodes glide. Acceptable for a look spike.
- No fifth element competing with the graph: the ident sits bottom-right as text, not a pane.

## Failures / caveats
- No install failures.
- Console: React Bits GlassSurface emits "<feColorMatrix> attribute values: Expected number"
  (its own template string formatting) — cosmetic, the filter renders.
- Headless Chromium here is software-rendered (3–8 fps measured: Threads + three SVG
  backdrop-filters + SVG graph). Consequence: in `shot.png` (2.5 s, motion running) the rim
  counters are still settling (12.152 of 12.480; 23/24). On a GPU they finish in ~0.5 s.
  Real Chrome (`channel: 'chrome'`) could not reach 127.0.0.1 from this sandbox, so the
  screenshot uses the Playwright headless shell with swiftshader.
- Also shot: `shot-evidence.png`, `shot-cost.png` (other two lenses, 4 s settle).
- `shot.cjs` serves dist on 5181 with a tiny node http server; server stops when done.
