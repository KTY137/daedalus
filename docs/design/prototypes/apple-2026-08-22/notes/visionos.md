# P2 · visionOS — spatial glass

## Point of view

Three windows of frosted glass float over a room at dusk: Ikarus on the left, the Codebase as the hero in the middle, and Knowledge physically behind it, peeking out on the right and coming forward (with the Codebase receding, dimming and shrinking) whenever something is selected. Chrome lives in two ornaments — a tab bar on the left edge and a project dock below — plus one status strip; nothing has a hard border, depth comes from material, shadow and motion. Type is the system stack in sentence case, one blue accent, semantic colour only for state (watcher, kill switch, withheld).

## Surfaces

- `?screen=cockpit` — the trio, order timeline, lenses, slice state, receipts deck, council verbatim, project dock, status strip, ⌘K reachable (button and Ctrl/⌘-K).
- `?screen=library` — page tree (global / project wiki / module pages), the "Sealed promotion" page with "Linked from", open question, council; the module page with auto stats and hand notes in an editable field.
- `?screen=settings` — the sheet with Routing & rights open; locked write cells render as italic statements ("Codex never writes."), unlocked ones as a segmented control; the three statements from the fixture sit under the matrix.
- `?screen=palette` — ⌘K over the cockpit; seven verbs with hints, arrow keys + return.

## React Bits items and their structural role

| Item | Role |
| --- | --- |
| `GlassSurface-TS-CSS` | The material of every window, the tab ornament, the status strip, the palette and the settings sheet. Layout container, not decoration. |
| `GooeyNav-TS-CSS` | The left tab ornament (Ikarus / Codebase / Knowledge / Settings) — primary navigation, laid out vertically; drives window focus and the settings sheet. |
| `Dock-TS-CSS` | The bottom ornament holding the project tabs (Daedalus / TCT scan planner / Lehrstuhl wiki) with watcher dot and magnification; switches the active project. |
| `AnimatedList-TS-CSS` | Two real lists: the Ikarus conversation (provenance stamps, evidence refs, withheld line) and the ⌘K verb list with keyboard navigation and selection. Patched in place to accept a `renderItem`. |
| `Stack-TS-CSS` | The receipts deck in the Knowledge window — attempts / receipts / withheld as draggable, swipeable cards. |
| `ElasticSlider-TS-CSS` | The spending ceiling in Routing & rights. Patched in place to drop the `@chakra-ui/react` icon import (plain `$0` / `$10` labels instead). |
| `Counter-TS-CSS` | The token count in the status strip (rolling digits, provenance stamp beside it). |
| `DarkVeil-TS-CSS` | The atmosphere — one shader, heavily desaturated and dimmed by CSS filter, behind everything. Substitute for Silk (see failures). |

Eight items; six of them carry real UI (navigation, layout, lists, controls, data display). `GlassSurface` shipped from the registry with malformed `feColorMatrix` values (the CLI flattened the matrix literal to `"0 0\ 1"`); fixed in place inside the app dir.

## Fonts and theme

- `-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Segoe UI Variable Display", "Segoe UI", system-ui, sans-serif`; monospace only for receipts and event refs.
- Dark-neutral dusk: ground `#2a2c31` → `#24262b`, glass `rgba(56,59,66,0.84)` with 28 px backdrop blur, labels `#f4f4f6` / `#aeb1ba` / `#7f828c` (slight blue bias), one accent `#6ea2ff`, green / orange / red only for watcher, kill switch, withheld and destructive.
- Radius scale 24 / 12 / 8. 8 pt grid. All targets ≥ 44 px (dock items 48, nav rows 44, actions 44).
- Motion: one spring entrance (windows rise with a 60 ms stagger), window stacking on a spring, DarkVeil at speed 0.2; `prefers-reduced-motion` zeroes the shader speed and all CSS transitions.

## Deliberately left out

- No metric tile row, no status pills, no all-caps labels, no glow, no HUD rings: provenance is a small-cap letter with a tooltip.
- No "run" button: "Focus the slice" is a lens, "Distill …" is a quick action that changes what the other windows show.
- No cost figures per node: only the two modules that carry a measurement in the fixture are shown with fan-in / churn in the Cost lens; the rest are dimmed and the legend says "2 of 32 nodes carry a measurement".
- Wiki pages other than "Sealed promotion" have no body in the fixture; the page says so instead of inventing one.
- Light theme: the appearance setting exists as a control but only the dusk palette is rendered.
- The spending slider's range (0–10 USD) is a control range, not fixture data; the fixture value 2.00 is the default.

## Install failures (verbatim)

`npx shadcn@latest add @react-bits/Silk-TS-CSS` — attempt 1 ended with:

```
You can also try a previous version to see if that works:
npx shadcn@4.18.0 add @react-bits/Silk-TS-CSS --yes --overwrite
```

attempt 2:

```
Command failed with exit code 1: npm install -- "@react-three/fiber@^9.3.0" "three@^0.180.0"

npm error code ERESOLVE
npm error ERESOLVE unable to resolve dependency tree
npm error
npm error While resolving: visionos@0.0.0
npm error Found: react@18.3.1
npm error node_modules/react
npm error   react@"^18.3.1" from the root project
```

Silk needs `@react-three/fiber@9` (React 19 peer). Substituted `DarkVeil-TS-CSS` (OGL), which installed cleanly.

All other items installed on the first attempt; on Windows the CLI wrote them into a literal `@/components` folder, moved to `src/components`.

## Verification

- `npm run build` exit 0 (tsc + vite, 506 modules).
- Screenshots 1440×900 after 2.5 s with motion running, via `shoot.cjs` (playwright-core from apps/web): `cockpit.png`, `library.png`, `settings.png`, `palette.png`. Console: zero errors after the feColorMatrix fix.
- Interaction probed in the foreground: clicking a graph node brings Knowledge forward and Codebase back; the lens control is then correctly occluded.
