# UI Handoff — read this first after the restart

Written 2026-07-30 by Athena, immediately before a Claude Code restart that loads the
**shadcn / React Bits MCP server**. The restart loses conversation context; this file is the
context.

## Why the restart happened

React Bits is now the **mandatory default** for all UI work (owner: "das ist nh richtige
goldgrube", "wir müssen das standardmäßig überall verwenden"). Installed:

- `shadcn` MCP server in **`~/.claude.json`** (user scope — every project) and in the repo's
  **`.mcp.json`** (project scope).
- **`components.json`** at the repo root carries the registry
  `"@react-bits": "https://reactbits.dev/r/{name}.json"`, with aliases pointing into
  `apps/web/src/components`.

After the restart: run `/mcp` to confirm the server is alive, then **ask the MCP server to
list components** rather than guessing item names — probing the registry URL directly
returned SPA HTML for every name I tried, so the exact item ids are unknown. The documented
prompt shape is *"Show me all the available backgrounds from the React Bits registry"*.

## Where the design landed (two rejected attempts, then a keeper)

Prototypes are in `docs/design/prototypes/` — open them over a static server, not `file://`:

```
python -m http.server 8801 --bind 127.0.0.1   # run inside docs/design/prototypes
```

| File | What it is | Verdict |
|---|---|---|
| `daedalus-forge.html` | **The keeper.** The 3D forest projection owns centre stage; readings at the rim; three lenses that MORPH the same nodes; hover inspects a node. | Owner: "ja ist gut aber geht noch besser" |
| `daedalus-system.html` | Four surfaces in one language: **The Pass** (the restaurant view — kitchens with their workers), Cockpit, three graph lenses, nested Wiki. | Information architecture is right; the visual layer is superseded |
| `ikarus-hud.html` | First HUD attempt, single screen | Superseded by forge |

**Rejected, do not revive:** a warm-paper/serif "instrument and notebook" direction (it was
AI-slop cluster #1 — cream surface, high-contrast serif, tan accent — I renamed the tokens
and told myself a story; the pixels didn't care), and flat frosted-glass card grids.

### What the owner explicitly liked
> "ich hab gemocht das der graph so 3d in der mitte war"

The rotating 3D graph at centre stage is the signature. Keep it, make it better.

### The three open critiques (verbatim)
> "die panels sehen noch billig aus und der text auch und die status bar oben ist typisch
> claude gui"

1. **Panels look cheap** — corner-bracket frames over a flat fill. Fix with React Bits
   `GlassSurface` (real refraction via SVG `feDisplacementMap`, **zero deps beyond react** —
   source cached in `docs/design/reactbits-refs/GlassSurface.jsx`, 232 lines). Also worth
   evaluating: `SpotlightCard`, `MagicBento`, `ReflectiveCard`, `ElectricBorder`, `BorderGlow`.
2. **Text looks cheap** — static mono. Fix with `CountUp` (101 lines, needs `motion/react`)
   for every number, and `DecryptedText` (384 lines, `motion/react`) for labels that should
   resolve in like instrument telemetry. Sources cached.
3. **Top status bar is "typisch Claude GUI"** — the pill row is the tell. Replace the concept,
   not the styling: `Dock` (143 lines, `motion/react`), `PillNav`, `CardNav`, `LineSidebar`,
   `StaggeredMenu`. Cached: `Dock.jsx`.

### Dependency notes measured from the real sources
- `GlassSurface` — react only. **Cheapest big win; do this first.**
- `Radar` (206 lines) — needs **`ogl`**. A configurable WebGL radar sweep (rings, spokes,
  sweep speed, lobes). Perfect for the instrument ground. Cached.
- `GridScan` (895 lines) — needs `three`, `postprocessing`, **and `face-api.js`**. That last
  dependency is a face-detection library; do not pull it in for a background. Skip or strip.
- `apps/web` already has `framer-motion`, `sigma`, `graphology`,
  `graphology-layout-forceatlas2`, `@xyflow/react`. React Bits imports `motion/react`, which
  is the newer package name for framer-motion — check whether an alias or a version bump is
  needed before adding components.

## The design language, in six lines

1. **Projection, not glass panels.** Line art, corner brackets, hairlines over a lit void.
2. **The forest is the hero.** The rotating 3D graph is centre stage on the operating
   surfaces; furniture goes to the rim.
3. **Lenses morph, they don't swap.** Code / data-structure / knowledge are one object seen
   three ways — animate node positions between them.
4. **Mono for everything measured**, one display face for headlines, **no grotesk body text,
   no third family.**
5. **Light means live.** Amber = hands moving, lime = passed, oxide = failed or unread,
   ice = structure. Nothing glows unless something is happening.
6. **Reading mode is a mode.** On the wiki, motion stops and the measure widens. Known bug in
   the prototype: wiki body copy is still mono — move it to the display face.

Palette: void `#03060A`, ice `#7FD4E8`, amber `#FFB454`, oxide `#FF6B4A`, lime `#8CE8B4`,
hot `#E6F4F8`, warm `#9FBAC4`, cool `#5E7A85`.

## Product shape (the owner's correction: this is a multi-page product)

- **The Pass** — the restaurant overview. Every kitchen (project) with its workers (models) at
  stations (roles), plus a ticket rail of the last six tasks. This is home, because the first
  question is "who is cooking and is anything burning".
- **Cockpit** — one kitchen opened, with Ikarus. Ikarus is *the Jarvis of this product*; that
  is the bar the visual quality is held to.
- **Three graphs** — code, data structure, knowledge as lenses on one forest.
- **Wiki** — nested vaults (global + per-project), backlinks, unlinked mentions, local graph
  at depth 1, `[[code:…]]` links with staleness.

## Also in flight when the restart happened

An 11-agent workflow was implementing the **type-graph foundation** in `daedalus/structcore/`.
It had finished its Baseline phase and Foundation stage 1; `parse.py` and `perfile.py` are
modified and `tests/test_typegraph_parse.py`, `tests/test_typegraph_fixture.py`,
`tests/fixtures/` are new. **Workflow resume is same-session only**, so the orchestration is
gone but the landed code is on disk. To continue, read
`docs/research/TYPE_GRAPH_AND_KNOWLEDGE_SPACE_PLAN.md` — its **NON-GOALS / INVARIANTEN**
section is the contract, and stages 2–4 (resolution → index blocks → forest layers) plus the
three regression thermometers are still outstanding.

Codex is working the same tree in `loop.py`, `provider_router.py`, `providers/ollama.py`,
`kairos/gated_writes.py`, `spine/picker.py` and `apps/web`. Coordinate through
`runs/council/room.md`.
