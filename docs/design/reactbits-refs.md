# React Bits — reference notes, NOT vendored source

React Bits is **MIT + Commons Clause**: free to use in a product, commercially, but
> "you may not sell, sublicense, or redistribute the components themselves — whether alone,
> in a bundle, or as a ported version."

So this repo must **never** carry React Bits source. Six component sources were briefly
copied here during design work on 2026-07-30 and removed the same session — if they
reappear in git history, that is the reason to strip them.

The sanctioned path is per-project resolution through the registry
(`@react-bits` → `https://reactbits.dev/r/{name}.json`) via the shadcn CLI / MCP server.
Daedalus's GUI lane must fetch, never bundle.

## What was measured from the real sources (facts, safe to keep)

| Component | Size | Dependencies | Note |
|---|---|---|---|
| `GlassSurface` | 232 lines | **react only** | Real refraction via SVG `feDisplacementMap`. Cheapest large win for "panels look cheap". |
| `Radar` | 206 lines | `ogl` | Configurable WebGL radar sweep: rings, spokes, sweep speed, width, lobes, falloff. The instrument ground. |
| `CountUp` | 101 lines | `motion/react` | Every number on an operating surface should arrive through this. |
| `DecryptedText` | 384 lines | `motion/react` | Labels that resolve in like telemetry — fixes "text looks cheap". |
| `Dock` | 143 lines | `motion/react` | Replaces the pill status bar that reads as "typisch Claude GUI". |
| `GridScan` | 895 lines | `three`, `postprocessing`, **`face-api.js`** | Do NOT adopt: it pulls a face-detection library in for a background. |

`apps/web` already has `framer-motion`, `sigma`, `graphology`, `graphology-layout-forceatlas2`,
`@xyflow/react`. React Bits imports `motion/react` (the newer framer-motion package name) —
resolve that alias or bump before adding components.

Other candidates worth evaluating, by the critique they answer:
- panels: `SpotlightCard`, `MagicBento`, `ReflectiveCard`, `ElectricBorder`, `BorderGlow`, `FluidGlass`
- backgrounds: `DotField`, `Threads`, `Beams`, `LightRays`, `Prism`, `LiquidEther`, `Dither`, `FaultyTerminal`
- nav: `PillNav`, `CardNav`, `LineSidebar`, `StaggeredMenu`
- 3D: `ModelViewer`, `Orb`, `Ballpit`
