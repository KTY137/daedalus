# G1-UI-20 — Genesis panels touched because `--u5` was never defined

Packet ID: G1-UI-20
Artifact role: primary
Active gate: 1
Classification: ALIGNED
Change class: theme token wiring and glass presentation; no API, policy,
evidence or Genesis behaviour change.
Owner: repository owner ("kannst du den genesis tab ein bissl schöner machen,
beide panels berühren sich", 2026-09-06 08:47)
Base revision: 585b7ea4e141332928ad6c9578b9c9997e55f247
Dependencies: G1-UI-10 (glass recipe in `spatial.css`)
Authority: IKARUS_ARIADNE_MASTER_PLAN.md revision 12.

## Primary acceptance claim

The Genesis intake card and the boundary card are two separate panes with
the theme's spacing between and inside them, in every look, and under glass
they are built from the same material as the composer and the rail.

## Baseline (measured 2026-09-06 08:50, Graphite Atelier, 1440×900)

- `genesis.css` uses `var(--u5)` for the shell gap, the workbench gap and
  the card padding; `ariadne.css` uses `--u5` and `--u7`; `ide.css` uses
  `--u5` for the project dialog and notice. `theme/apply.ts` sets only
  `--u1 … --u4, --u6, --u8`. Every one of those declarations resolved to an
  invalid value, i.e. 0.
- Measured: `.genesis-intro` bottom 321 px = `.genesis-workbench` top 321 px
  (no gap); the two cards shared one edge; card content sat on the border.
- Under glass the cards had a 6 % surface tint with the room render showing
  through the form fields.

## Scope

Owned paths: `apps/web/src/shared/ui/theme/apply.ts` (token list and two
setters), `apps/web/src/app/styles/spatial.css` (appended Genesis glass
block), this packet. Not touched: `genesis.css`, `ariadne.css`, `ide.css`,
Genesis.tsx, tests.

## Contracts and behavior

- `--u5 = unit × 2.5` and `--u7 = unit × 3.5` are defined next to the other
  steps and listed in the applied-token array, so `unit` changes in the
  studio scale them too.
- Glass: `.genesis-card` / `.genesis-result` take the pane recipe (glass
  fill, top edge, blur, pane shadow); the room render behind Genesis is
  dimmed to 14 % like the map's 16 %; intro body text uses `ink2`.

## Acceptance matrix

| Check | Evidence |
| --- | --- |
| Type | `npx tsc --noEmit -p .` exit 0 |
| Bootstrap | `npm run test:app` 527/527 |
| Geometry | intro bottom 321 → workbench top 341 (20 px gap); cards padded; 1440 and 1024 px; zero page errors |
| Side effects | Ariadne view screenshot after: header, boundary and cards spaced; no test references the token list (grep `'--u` in theme.spec.ts, spatial.spec.ts, genesis.spec.ts: none) |
| Not run | `tools/gui_check.py` browser suite |

## Evidence, expected failures and review

The token audit and visual spacing checks are the focused evidence; known
styling limits remain presentation-only and do not change Genesis behavior.

## Migration and rollback

Revert the two files. Nothing is stored.
