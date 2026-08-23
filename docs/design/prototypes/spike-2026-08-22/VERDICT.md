# Cockpit look spike — verdict (2026-08-22)

Question: glassmorphism, skeuomorphism, or a 3D scene for the Daedalus cockpit?
Method: the same scene (trio IA, same `fixture.json`) built three ways in isolated throwaway
Vite apps with React Bits fetched from the registry, measured with `daedalus/gui/probe.js` +
`lint.py` against the approved forge keeper, judged by three lenses (owner taste, measurement,
product/feasibility). 7 agents, 35 min, 575k subagent tokens. All three built; no blank shots.

Everything built is THROWAWAY and lives outside the repo. Retained here: canonical screenshots
(`shots/`), metrics (`metrics.md`/`.json`), the builders' notes (`notes/`), brief and fixture.
No React Bits source was copied into the repo (MIT + Commons Clause).

## Rankings (split on order, unanimous on substance)

| Lens | 1st | 2nd | 3rd |
|---|---|---|---|
| owner's eye / restraint | scene | instrument | glass |
| measurement | glass | scene | instrument |
| product / feasibility | glass | instrument | scene |

Unanimous findings [3/3 jurors]:

- **None of the three beats the forge keeper as built.** Forge still wins on restraint and on
  the one thing that matters: one hero, one stamped sentence in a human voice, readings at the rim.
- **Instrument is the rejected flat dark card grid wearing a radar** (13 framed panels
  [MEASURED], three bordered columns, ElectricBorder on the kill switch, a knob duplicating
  three buttons). Skeuomorphism as a *layout* is dead for this product.
- **DecryptedText is a self-inflicted wound**: two of three canonical frames show scrambled
  titles (`NPZnw*RgEmy@_@O@`, `Sealeh i!Dh#Skug`) at the agreed 2.5 s settle. A fact garbled for
  effect is the opposite of honesty grammar. Drop it everywhere.
- **Every variant pulled Ikarus's voice out of the centre into a chat-transcript sidebar.**
  The forge's single hero sentence was the warmth; none kept it.
- **The one genuinely new idea is scene's four planes as four depth sheets** (code nearest,
  knowledge farthest, z = plane fixed across lenses). It makes the Project Twin legible *as a
  twin* — and it is drowned by spotlights, sparkles, fog, glow sprites and skewed text.
- **Glass's graph is not a graph** (four node lists with spaghetti), its Threads aurora is the
  2024 AI-dashboard tell, and it breaches the element budget 2.2× [334 vs ≤150 MEASURED] —
  but its honesty grammar, dashed-amber proposals, and hover-dimming are the best of the three.

## Answer to the owner's question

**3D for the data, glass as a material, skeuo nothing.** Depth belongs in the graph (the four
planes as z), not in the chrome. Glass is allowed for exactly two panes as plain backdrop
blur. Skeuomorphic instrument bodies, radar dressing, knobs and electric borders are out.

## The one hybrid to build (three jurors converged; this is the union)

Identity: **forge** — dark ground, the forest owns the centre, readings at the rim, mono
everywhere except Ikarus's voice.

Borrow exactly:

- from **scene**: the four planes as depth sheets, camera fixed head-on with ±2° parallax on
  the NODES only; text never leaves screen space; the frameless rim typography (corner
  statements, no boxes, no bars, no tiles); the kill switch as a sentence
  ("armed · enforced at the effect boundary"); stamps spelled out on first use (M MEASURED).
- from **instrument**: the source line under every rim reading ("M · ledger.json"); the
  single machined square as the M/I/A stamp; the scope caption as a legend sentence
  ("32 nodes · 34 edges · 3 unverified proposals, dashed amber"); labelled text detents
  STRUCTURE / EVIDENCE / COST instead of an icon dock.
- from **glass**: dashed amber with dashed endpoint halos for `verified:false`; hover dims to
  the neighbourhood with a two-line reading beside the node; the humanist face (Source Sans 3)
  confined to Ikarus; at most two glass panes (Ikarus left, Knowledge right), plain
  `backdrop-filter`, no SVG refraction.
- from **forge**: the hero sentence — the latest stamped Ikarus statement in the bottom band
  with stamp, evidence locator and withheld line; the transcript is a drawer, not a panel.

Drop entirely: Threads/aurora, LightRays, Sparkles, fog, glow sprites, Orb, GlassSurface
refraction, Dock, ElectricBorder, SpotlightCard, rotary knob, Radar sweep and spokes,
DecryptedText, Space Grotesk, CSS3D-transformed text, the "persistent in goals and evidence"
tagline, the three-card layout.

Budget for the build (hard, linter-enforced): ≤ 5 framed panels · ≤ 120–150 visible elements
(graph on canvas, labels in DOM only for hovered/selected + top-3 per plane) · 1 radius ·
0 contrast failures · 0 small targets · console_errors ≤ 1 (shared baseline) · 3 hue families
(ice/amber/oxide; lime only on signed/passed) · canonical shot settles within 2.5 s.

Feasibility in `apps/web` (Vite + React 18 + sigma/graphology, Tauri target): the hybrid does
not rewrite the graph layer. Depth sheets = sigma with per-plane parallax offset (2D canvas) or
a bounded three.js node layer; lenses = graphology layouts per lens + `animateNodes`; the one
real cost is a custom dashed-edge program for `verified:false`. React Bits stays registry-fetched
(`CountUp`, maybe `Dock`-free panes); `motion` added alongside framer-motion. Scene's
three/r3f/drei stack (1.25 MB) is not carried over.

If that frame does not make the owner say wow, the problem is the graph's data density, not
the chrome — fix it with node sizing and edge weighting, never with more effects.

## Where the linter was wrong (feed back into `lint.py`)

- `banned_faces` flags Space Grotesk, which the brief allowed — ban list wider than the rubric.
- `largest_equal_tile_row` counts full-viewport stacked background layers (7/7/8 for
  forge/glass/scene) — it only meant something for instrument (4 = a real tile row).
- `visible_elements` cannot see a WebGL canvas: scene's 43 is an artefact of the hero living in
  three.js, not restraint. A canvas-aware count (or a node-count from the app) is needed.
- All three variants fixed forge's baseline accessibility defects (14 contrast failures, 6 small
  targets → 0/0, 0/4, 0/0) — the one place the spike measurably beat the keeper.

Provenance: rankings and quotes from the jury transcripts (workflow `wf_d8d81edc-bd0`);
numbers [MEASURED] from `metrics.md`; the synthesis is Athena's.
