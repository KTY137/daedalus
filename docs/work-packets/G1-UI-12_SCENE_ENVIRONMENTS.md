# G1-UI-12 — Rendered rooms behind the glass

Packet ID: G1-UI-12
Artifact role: primary
Active gate: 1
Classification: ALIGNED
Owner: repository owner (request 2026-09-05: work the UI in parallel with the Codex UI session)
Base revision: 61cd1f3e8eca1d02cd9ddeb734f4c112c69c29a0
Dependencies: G1-UI-10 (Theme Studio, ThemeProvider, scene controls), G1-UI-11 (Blender scene renders)
Authority: IKARUS_ARIADNE_MASTER_PLAN.md revision 12, SHA-256
`126594137ebf1854458e625b64831c431c64b4a9f3dd8ca2b03c7867e0e8d8fb`.
Presentation only: no kernel, runtime, API, policy, ledger, graph identity or
promotion change. Chat and theme state stay interface state (plan §7, §13).

## Primary acceptance claim

The owner can put any of the six Blender-rendered rooms from G1-UI-11 behind
the glass workspace from the Theme Studio, live, per look, with the choice
persisted and round-tripped through the existing theme JSON. Existing looks are
unchanged until the owner picks a room: the negative visual verdict on G1-UI-10
(owner, 2026-09-05 07:43) is retained and the art-direction choice stays with
the owner; this packet makes the three directions comparable inside the app
instead of on static images.

## Baseline

- G1-UI-11's README states that integration of the scenes into the Theme
  Studio is not part of that packet. Nothing in the app referenced the renders.
- `ThemeScene` carried `enabled`, `intensity`, `speed`; the only ambient layer
  was the WebGL sculpture (`SpatialScene`).
- `npm.cmd run test:app`: **509/509 passed, 29.1 s** (measured before any change).
- Final renders present under `docs/design/blender-scenes/renders/` for all six
  scenes (1600×1000, Blender 4.5.13 LTS, 64 samples, seed 20260905).

## Scope

Owned paths:

- `apps/web/src/shared/ui/scene/environments.ts` — registry (ids, names, notes, light/dark base) plus provenance read from the manifest; pure data, no images.
- `apps/web/src/shared/ui/scene/environmentImages.ts`, `vite-env.d.ts` — Vite `import.meta.glob` over the WebP files; empty outside Vite (spec runner, SSR) instead of crashing.
- `apps/web/src/shared/ui/scene/environments/` — generated WebP (full 1600 px + 480 px thumbnail) and `manifest.json` with source path, source SHA-256, output SHA-256, Blender version, samples, resolution, quality (`final`/`draft`).
- `apps/web/src/shared/ui/scene/SceneEnvironment.tsx|css` — the backdrop layer: full-bleed picture, veil in the theme's own room colours driven by the existing "Intensität", vignette, pointer parallax scaled by "Bewegung", off under reduced motion.
- `tools/build_scene_environments.py` — deterministic PNG→WebP build with a
  lock-backed `daedalus[design-build]` encoder and a stdlib-only `--check`.
  Registered effectful door `tools.scene_environments_build` in
  `daedalus/spine/effect_boundary.py` (`_PORTABLE_TOOL_ROWS`: FILESYSTEM_WRITE,
  `budget.process_guard`, CENTRAL, GuardAnchor on `main`); `main()` calls
  `begin_effect` before argument parsing, like the other portable tool rows.
  The registry digest therefore moved from `a22bf297…` to `5b1feaf1…`; the 27
  test pins on that digest were re-measured (see evidence). Evidence documents
  that recorded the earlier digest are historical measurements and were left
  untouched.
- Edits: `theme/types.ts` (`ThemeScene.environment?`), `theme/store.ts` (validated, reported, never repaired from a base), `theme/apply.ts` (`data-environment`), `theme/ThemeStudio.tsx` + `studio.css` (room picker in the Szene tab), `app/Cockpit.tsx` (one mount line), `theme/theme.spec.ts`, `tests/spatial.spec.ts`.

Forbidden and untouched: kernel, runtimes, HTTP API, policy, ledger, plan,
`daedalus/ariadne`, `features/ariadne`, Genesis, packaged `dist`/`web_dist`,
built-in look palettes and their scene defaults.

## Contracts and behavior

- `environment` is optional. Absent means what every look meant before: no room.
- Store repair does not borrow an environment from the origin built-in. An id
  the registry does not know is dropped and reported in `problems` as
  `scene.environment`; it never reaches CSS or an `<img>`.
- The registry and the manifest must agree in both directions; the app spec
  fails on a scene registered without provenance or a manifest entry without a
  registry row.
- Images enter the bundle only through Vite's glob, hashed like every other
  asset. The esbuild-based hierarchy spec (which bundles `main.tsx` without
  binary loaders) therefore keeps passing.
- The picker is a roving radiogroup with the Studio's existing keyboard rules;
  "Kein Raum" is the first, real option. A room whose picture is missing is
  shown as not rendered and cannot be chosen.
- The veil is never opaque: at full intensity the room shows almost bare, at
  low intensity it recedes behind the palette. A light look over a dark room
  (or the reverse) is flagged in the Studio, not corrected silently.

## Acceptance matrix

| Check | Evidence |
| --- | --- |
| Round trip | Chosen room survives export/import with the sculpture off; unknown id dropped and reported (theme.spec) |
| Defaults | No built-in look carries a room (theme.spec) |
| Provenance | Every registered room has manifest provenance with 64-hex digests; manifest names no unknown room (theme.spec) |
| Tooling | `tools/build_scene_environments.py --check` verifies output and source digests |
| Type/architecture | `tsc --noEmit`; hierarchy and single-root checks in `test:app` |
| Browser | Choose room → `data-environment`, 1600 px picture loaded, provenance line visible, keyboard arrow moves selection, reload persists, "Kein Raum" removes, corrupted stored id renders nothing (spatial.spec) |
| Regression | Existing spatial, cockpit and app specs stay green |
| Build | Production build to a temporary outDir; tracked packaged assets not overwritten |

## Migration and rollback

Additive field on the existing scene record; stored themes without it load
unchanged. Rollback removes the scene directory, the tool and the small edits;
saved user themes keep working and an orphaned `environment` field is dropped
with a visible problem by the pre-existing repair path.

## Evidence, expected failures and review

Measured 2026-09-05, 10:36–10:49, Windows 11, Node 24.18, while the machine
was under load from parallel Codex test runs:

- `python tools/build_scene_environments.py`: six finals consumed
  (Blender 4.5.13 LTS, 64 samples, 1600×1000, seed 20260905); WebP sizes
  16.5–109.9 kB full, 2.8–16.4 kB thumbnails. Regeneration is pinned to
  Pillow 10.4.0/libwebp 1.4.0; `--check` needs no Pillow and reports six
  entries, zero problems after source-metadata sanitation.
- Red first: `npm.cmd run test:app` failed at esbuild on the missing
  `../scene/environments` module before the implementation existed.
- `npm.cmd run test:app`: **516/516 passed** (509 baseline + 7 new), 33.2 s.
  Includes the hierarchy check that bundles `main.tsx` with esbuild, which
  proves the image glob never becomes a static binary import.
- `npx.cmd tsc --noEmit -p .`: exit 0 (one overload-signature error found and
  fixed on the first run).
- `npm.cmd run build -- --outDir <temp>`: TypeScript and Vite passed in 1 m 47 s;
  `assets/` carries the six hashed full-size WebPs and the thumbnails above 4 kB
  (porcelain/daylight/studio thumbnails are inlined by Vite's asset limit).
  Tracked `apps/web/dist` and `daedalus/resources/web_dist` were not touched.
  Main chunk 810.62 kB minified (was 785.52 kB in G1-UI-10); the chunk-size
  warning predates this packet.
- `DAEDALUS_GUI_BASE_URL=http://127.0.0.1:5173 npx.cmd playwright test tests/spatial.spec.ts`:
  **5/5 passed**, 1 m 31 s against the running Vite dev server with offline
  API fixtures. The new test covers: seven radios with "Kein Raum" checked by
  default; choosing Graphite Atelier sets `data-environment`, loads the 1600 px
  picture and shows the provenance line; ArrowRight moves to Spatial Daylight;
  reload persists; "Kein Raum" removes the layer; a stored `environment:
  "lava-lamp"` renders nothing and no page error occurs.
- Visual inspection (screenshots retained in the session scratchpad
  `shots/`): Liquid Glass + Graphite Atelier in conversation and map views,
  Frost + Porcelain at 1440×900 and 390×844, Studio picker open. The glass
  chrome, composer and suggestion cards frost the render through their
  existing backdrop-filter; the map view attenuates the room to 65 % weight.
- Live backend on port 8765 was down throughout (HTTP 500 through the proxy);
  no provider or mission execution is claimed.

Addendum (2026-09-05, 13:16–13:27) — effect-boundary registration:

- Independent review (Claude session daedalus-84) measured
  `tests/test_registry_new_doors.py` + `tests/test_effect_boundary.py` at
  5 failed / 118 passed: `tools/build_scene_environments.py:main` was an
  `entrypoint.unregistered` conformance blocker. Reproduced here before
  changing anything.
- Fix: registry row `tools.scene_environments_build` (FILESYSTEM_WRITE only,
  `budget.process_guard`, CENTRAL, anchor `begin_effect` on `main`) and the
  boundary-first `begin_effect` call in the tool. `--check` still runs
  (6 entries, 0 problems) and now passes through the boundary.
- `tests/test_registry_new_doors.py tests/test_effect_boundary.py`:
  **44 passed, 0 failed**, 167 s under load.
- `registry_sha256()` moved to `5b1feaf1127f72bc4c6fb457993805ceb2311c88cb0a1c47bbd6d077a8d116da`;
  26 test files re-pinned from `a22bf297…` (one, `test_work_packet_index.py`,
  already carried the new value). All 27 pinning files plus
  `tests/contracts/test_import_scc_hierarchy.py`: **235 passed, 5 subtests
  passed**, 26 s. `docs/evidence/ikarus-autonomy-validation.json` and
  `docs/work-packets/G1-IKARUS-COMPUTER-01.md` still record the earlier
  digest as the measurement of their time and were not rewritten.
- 13:44, reported by the Ariadne session (daedalus-84): the registry gained
  `cli.council` and `registry_sha256()` moved on to
  `7a8fc9442be4d1fff8f576fa951036788ef146c779c5c1145bce21f471f3c605`; that
  session re-measured the 27 pins with the same three commands (27 pins + SCC
  census 234 passed, registry/CLI boundary suites 66 passed). The
  `5b1feaf1…` value above is therefore the digest as of this packet's own
  measurement, not the current one.

Negative results and residuals:

- The tool shipped for ~2.5 hours without its registry row; the gap was
  found by a peer's run of the governance suites, not by this packet's own
  acceptance matrix, which listed `test:app`, `tsc`, build and browser checks
  only. Python-side governance suites now belong in the matrix of any packet
  that adds a script under `tools/`.
- First veil formula left "Verstehe dein Projekt …" borderline over the
  brightest glass block of Graphite Atelier; the floor was raised
  (`.84 − .62·weight`) and the map view attenuated. Contrast against a bright
  room at intensity 100 % still depends on the owner's look; the Studio flags
  a light/dark mismatch rather than correcting it.
- IDE diagnostics flagged `user-select` without the `-webkit-` prefix; fixed
  in both new CSS blocks (the desktop shell is WebKit on macOS). The remaining
  diagnostics in `studio.css` predate this packet.
- Pre-existing and not fixed here: the compact sculpture in the conversation
  empty state is clipped at viewport heights ≤ 800 px (negative margins in
  `spatial.css`); with a room chosen it also competes visually. Left with
  G1-UI-10's owner; the sculpture can be switched off in the same tab.
- Independent review of the picker's copy, the veil values and the manifest
  contract is outstanding; no release, merge or promotion is claimed.
