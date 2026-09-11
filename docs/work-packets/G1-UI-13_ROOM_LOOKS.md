# G1-UI-13 — One look per rendered room, and a room by default

Packet ID: G1-UI-13
Artifact role: primary
Active gate: 1
Classification: ALIGNED
Owner: repository owner (2026-09-05: "der codex chat hat aufgehört du kannst weiter machen")
Base revision: 61cd1f3e8eca1d02cd9ddeb734f4c112c69c29a0
Integration context: uncommitted tree on top of G1-UI-12
Dependencies: G1-UI-12 (room environments), G1-UI-11 (renders), G1-UI-10 (Theme Studio)
Authority: IKARUS_ARIADNE_MASTER_PLAN.md revision 12, SHA-256
`126594137ebf1854458e625b64831c431c64b4a9f3dd8ca2b03c7867e0e8d8fb`.
Presentation only: presets, their tests and this packet. No kernel, runtime,
API, policy, ledger, graph identity or promotion change.

## Primary acceptance claim

Each of the six rendered rooms has a built-in look whose palette is read off
its render, whose sculpture is off, and which puts the room behind the glass
without any Studio step. A fresh installation opens in Graphite Atelier. Saved
selections are not overridden, and every older look — including the rejected
Liquid Glass — remains selectable and roomless.

## Why this and not a redesign

The owner rejected G1-UI-10 visually and was asked by Codex to choose between
three still images (Porcelain, Graphite Atelier, Spatial). Instead they asked
for the scenes as Blender projects. G1-UI-12 made rooms selectable; this packet
makes the three directions switchable looks so the comparison happens in the
running product. Codex's own diagnosis of the rejection ("the 3D form
dominates", "glass feels heavy") is answered inside the new looks: sculpture
off, panel alpha 0.58 and blur 26 instead of 0.62/28. The composition issues
("three windows", "landing page") are a separate axis, G1-UI-14.

## Scope

Owned paths: `apps/web/src/shared/ui/theme/presets.ts`,
`apps/web/src/shared/ui/theme/theme.spec.ts`, `apps/web/tests/spatial.spec.ts`,
this packet. Nothing else.

## Contracts and behavior

- Ids `room-porcelain`, `room-graphite`, `room-daylight`, `room-dusk`,
  `room-studio`, `room-forest`; origin `rooms-2026-09-05`. Codex's earlier
  `dusk` look keeps its id; the room look is `room-dusk`.
- Light rooms fork Frost's light-adjusted status/heat/plane colours; dark rooms
  fork Liquid Glass. Room, surface, ink, line, accent and map colours are set
  per render from measured anchors (mean, darkest and brightest tenth of a
  160×100 downsample): Porcelain `#e1e3e2`, Graphite `#333f4b`/`#0b1219`,
  Daylight `#a5a7a4`/`#697d8b`, Dusk `#614b4a`/`#39292e`, Studio `#c0c4c6`,
  Techno Forest `#446773`/`#153037`.
- `scene: { enabled: false, intensity: .85, speed: .35, environment }` per look.
- `DEFAULT_THEME_ID = 'room-graphite'`. `theme/store.ts` reads the stored id
  first, so an existing installation keeps its selection.

## Acceptance matrix

| Check | Evidence |
| --- | --- |
| Collection | Six room looks, one per registered environment, sculpture off, base matches the room (theme.spec) |
| Isolation | Every non-room look still carries no environment (theme.spec) |
| Default | Default id is `room-graphite` with the graphite room; Liquid Glass still exists (theme.spec) |
| Round trip | All sixteen built-ins survive JSON export/import unchanged (existing loop in theme.spec) |
| Browser | Fresh load: theme id `room-graphite`, `data-environment` graphite, picture present, no sculpture; Liquid Glass selectable and its sculpture draws; existing sculpture/reduced-motion tests pinned to Liquid Glass (spatial.spec) |
| Regression | `test:app`, `tsc`, existing spatial tests |

## Migration and rollback

Additive presets. A stored fork of a room look carries its own environment in
JSON; a fork made before this packet is unaffected. Rollback deletes the
collection and restores `DEFAULT_THEME_ID = 'liquid'`; a stored
`room-*` selection then falls back to the default through the existing
`builtIn(id) || builtIn(DEFAULT_THEME_ID)` path.

## Evidence, expected failures, and review

Measured 2026-09-05, 11:50–11:54:

- `npx.cmd tsc --noEmit -p .`: exit 0.
- `npm.cmd run test:app`: **524/524 passed** (516 after G1-UI-12 + 8 new or
  rewritten checks), 39.5 s. The export/import loop now covers sixteen
  built-ins including the six room looks.
- `DAEDALUS_GUI_BASE_URL=http://127.0.0.1:5173 npx.cmd playwright test tests/spatial.spec.ts`:
  **5/5 passed**, 51 s. Fresh load asserts `data-theme-id="room-graphite"`,
  `data-environment="graphite"`, one room picture and zero sculptures; the
  Liquid Glass reference is selected from the gallery and its sculpture still
  draws; the reduced-motion/WebGL-loss test is pinned to Liquid Glass; the room
  test now starts from the default room, forks on choosing Porcelain, shows the
  light-room-behind-dark-look hint and walks the radiogroup with ArrowRight.
- Browser inspection after clearing storage (1440×900): theme id
  `room-graphite`, environment `graphite`, `data-scene="off"`, 0 sculptures,
  1 room, 16 looks in the gallery. Screenshot retained in the session
  scratchpad (`d5-default-graphite-look.png`).

Negative results and residuals:

- Palettes are derived from render statistics and eyeballed once each; they
  have not been reviewed against WCAG contrast per look. The light rooms
  inherit Frost's darker status colours for that reason.
- Over the brightest module of Graphite Atelier the invitation body text is
  still borderline at intensity 85 %. That is a composition problem of the
  empty state (text on bare room), addressed in G1-UI-14, not by darkening the
  room further.
- No release, merge or promotion is claimed; independent review outstanding.
