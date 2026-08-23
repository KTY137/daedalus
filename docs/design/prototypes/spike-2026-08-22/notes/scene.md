# Variant C · 3D Scene (Jarvis room) — NOTES

## The ONE design law
The cockpit is a room; the codebase is the object in it. Everything else stands around that object.
The four planes are four depth sheets (code nearest, knowledge farthest) in a real three.js scene;
chat and knowledge are glass surfaces STANDING in the room (drei `<Html transform>`), so the slow
camera sway moves them like furniture, not like a HUD. Only the rim readings are screen-space.

## React Bits items (exact registry names)
- `@react-bits/LightRays-TS-CSS` — scene atmospherics, top-center rays, pulsating, not following the mouse.
- `@react-bits/Orb-TS-CSS` — the Ikarus presence in the chat surface header (hue 195, forced hover state).
  Honest note: at 56 px inside a CSS3D-transformed surface it reads as a thin ring; it earns its place barely.
- `@react-bits/CountUp-TS-CSS` — the budget readings (tokens, USD).
- `@react-bits/DecryptedText-TS-CSS` — the knowledge page title settling in.
Scene itself: `three` + `@react-three/fiber@8` + `@react-three/drei@9` (Html, Line, Sparkles).
Install note: shadcn wrote the files to a literal `@/components` folder (no path alias existed yet);
moved them to `src/components` and added the `@` alias in tsconfig + vite. No item failed to install.

## Fonts
- JetBrains Mono — micro labels, provenance stamps, owner lines, evidence locators.
- Space Grotesk — readings and knowledge body (display/cold).
- Alegreya Sans — Ikarus's voice ONLY (humanist/warm). No Inter, Roboto, or serif anywhere.

## What the scene does
- Hero graph: 32 nodes on four depth sheets; 34 edges rebuilt every frame from live node positions.
  Cross-plane edges are brighter than intra-plane; `verified:false` edges are AMBER and DASHED (proposal, not fact).
- Three lenses morph the SAME nodes (lerp in 3D on their own sheet; z = plane never changes):
  structure (parents on a row, children hang beneath), evidence (verified weight pulls to the sheet
  centre, unverified pushes to the rim, ≥3 verified edges tints lime), cost (sorted by cost left→right,
  size by cost, the most expensive tinted amber).
- Hubs (degree ≥ 4) carry an additive glow sprite (the "near-field bloom"; no postprocessing pass).
- Depth fog + 50 slow sparkles for dust; camera sways ±7° around the room (full orbit would turn the standing surfaces away).
- Hover: glow + edges light up + an in-scene tag; the bottom-centre focus line restates plane · kind · label.
- Chat: every Ikarus message carries its M/I/A stamp spelled out (measured/inferred/assumed), evidence
  locators, and the withheld line in amber.
- Knowledge: title, body, provenance, four backlinks, the open question.
- Rim readings are statements: "12 480 of 40 000 tokens spent", "24 of 24 receipts signed", "armed · enforced at the effect boundary".

## Anti-slop self-check
framed_panels = 2 (chat, knowledge surfaces) + hover tag · one radius (3px) · no pills · nesting ≤ 2 ·
no raw ids rendered (only labels; revision hash shown as the fixture gives it) · lens buttons 44px min.

## Deliberately left out
- No postprocessing bloom (EffectComposer) — a sprite does it for 34 nodes at a fraction of the cost.
- No full 360° orbit; no mouse-follow on the rays; no tooltips with edge scores (would crowd the room).
- No ModelViewer (no GLB), no Beams (LightRays alone is already "genug going on").
- No typed chat input; the "ask Ikarus" line is a caret, not a form.

## Failures
None at install. Build warning only: single chunk 1.25 MB (three) — irrelevant for a spike.
Three logs "THREE.Clock deprecated" in the console (r3f 8 internals), cosmetic.

## Verify
`npm run build` → exit 0. `node shot.cjs` serves dist on 127.0.0.1:5183, shoots 1440×900 after 2.5 s with
motion running (swiftshader GL), then closes the server. shot.png is that frame.
