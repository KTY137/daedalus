# G1-UI-10 — Spatial glass and live theme editing

Packet ID: G1-UI-10

Artifact role: primary

Classification: ALIGNED

Active gate: 1

Owner: repository owner

Base revision: 61cd1f3e8eca1d02cd9ddeb734f4c112c69c29a0

Dependencies: G1-UI-05, G1-IKARUS-09

Authority: IKARUS_ARIADNE_MASTER_PLAN.md revision 11; one existing UI/provider,
no backend effects, policy changes, evidence changes or promotion.
The workspace advanced independently to revision 12 during implementation.
Its general-assistance amendment was rechecked; presentation-only scope stays
ALIGNED. Final plan SHA-256:
`126594137ebf1854458e625b64831c431c64b4a9f3dd8ca2b03c7867e0e8d8fb`.

## Primary acceptance claim

Improve the existing cockpit shell and conversation invitation; add an optional
decorative WebGL sculpture and three recoverable built-in themes. Extend the
existing Theme Studio and ThemeProvider rather than add a theme store.

## Scope

Allowed: apps/web/src/app/Cockpit.tsx and styles, conversation presentation,
shared/ui/theme, shared/ui/scene, focused UI tests, this evidence packet.
Forbidden: kernel, runtime, APIs, graph data/identity, policy, ledger and plan.

## Contracts and behavior

Acceptance: TypeScript/build and existing app/motion specs pass; live theme
selection, editing, persistence, JSON round-trip, keyboard access and narrow
layout work. Decorative canvas has no effect controls or project assertions;
it stops when hidden or reduced motion is enabled, has bounded resolution,
and degrades gracefully when WebGL is unavailable. Existing saved theme choices
remain selected. New installations start with Liquid Glass.

## Baseline and isolation

Existing cockpit used a compact text toolbar and flat reading surfaces.
Theme Studio already had a canonical persistence provider and seven presets.
Initial worktree contained extensive owner changes, including uncommitted
conversation, Genesis, Ariadne, graph and desktop work. Those changes are kept;
this patch remains reviewable in the current working tree. The isolated-worktree
step of the plan is not completed: it would omit the current integration state.
No merge or promotion is performed.

## Acceptance matrix

Theme Studio implementation was separately reviewed and exercised with 19
browser checks: persistence, fork/copy/rename/reset/delete, file and clipboard
round trips, malformed imports, keyboard controls and 390px mobile bounds.
Final integration results are appended after local verification.

### Final local verification (2026-09-05)

- `npm.cmd run test:app`: 498/498 passed, including 15 new round-trip and
  legacy-theme assertions. Optional voice, depth, elevation, ramps and scene
  settings now survive the existing import/reload path.
- `npm.cmd run test:motion`: 143/143 passed.
- `npm.cmd run build -- --outDir <local-temporary-directory>/daedalus-spatial-build`:
  TypeScript and Vite passed. Tracked packaged assets were not overwritten.
  Vite still warns that the main chunk exceeds 500 kB (785.52 kB minified;
  245.08 kB gzip). No dependencies were added.
- `DAEDALUS_GUI_BASE_URL=http://127.0.0.1:5173 npx.cmd playwright test tests/spatial.spec.ts`:
  4/4 passed, 28.5 seconds. Covers live controls and persistence, 390px layout,
  module evidence across light/dark theme changes, reduced-motion frame counts
  and real WebGL context-loss fallback. Backend requests use isolated offline
  fixtures; no live provider/mission execution is claimed.
- Desktop, editor, narrow chat and both map palettes visually inspected.
- `git diff --check`: passed; only existing Windows line-ending advisories.

Reports and screenshots are retained under the local temporary directory:
`daedalus-spatial-final-report.json`, `daedalus-spatial-final-artifacts`,
`daedalus-spatial-app-tests.log`, `daedalus-spatial-{desktop,editor,mobile}.png`.

## Evidence, expected failures, and review

Negative evidence: the first narrow layout clipped its invitation and overlapped
the composer with the rail; it was corrected with a scrolling empty-state
layout. Initial browser fixture matching accidentally intercepted Vite's
`src/shared/api` module URLs; the match now requires `/api/` at the pathname
start. A measurement taken during drawer entry animation and an incorrect
extensionless expected module label were corrected in the harness. Earlier
failure artifacts remain in `daedalus-gui-artifacts`; final artifacts use a
separate directory. Headless screenshot capture emitted driver ReadPixels
performance warnings, with no shader compile failure or page exception.

The preview's live backend at port 8765 is unavailable and reports HTTP 500
through the Vite proxy. Its error remains visible. Full connected-runtime
verification, isolated-worktree integration and independent review of the final
shell/renderer are outstanding release-chain steps; no release is claimed.

## Migration and rollback

Rollback: revert only this packet's scoped patch; retain all pre-existing edits
and saved user themes. Earlier reference presets remain available in the editor.
