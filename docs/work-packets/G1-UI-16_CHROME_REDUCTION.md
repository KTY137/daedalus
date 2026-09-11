# G1-UI-16 — Less in the bar, nothing over an empty stage

Packet ID: G1-UI-16
Artifact role: primary
Active gate: 1
Classification: ALIGNED
Change class: presentation only; chat stays an interface, with no orchestration,
policy, API or evidence change.
Owner: repository owner (owner loop of 2026-09-06, "GUI besser, aber nicht
überladen", four iterations with artifacts)
Base revision: 585b7ea4e141332928ad6c9578b9c9997e55f247
Dependencies: G1-UI-14 (workspace pane), G1-UI-15 (rooms)
Authority: IKARUS_ARIADNE_MASTER_PLAN.md revision 12.

## Primary acceptance claim

Iteration 1 of the loop. With the Graphite Atelier default, the chrome bar
carries one hierarchy: brand, project scope, five destinations, four quiet
tools. The theme trigger is no longer the loudest control on the screen, the
marketing caption is gone, and an empty map shows no mode switch.

## Baseline (measured 2026-09-06 02:10, dev server on 127.0.0.1:5173)

- The bar's most saturated element was "Themes": accent-tinted pill with a
  visible label while Suchen / Neu lesen / Einstellungen collapsed to icons
  at ≤1500 px. The least task-relevant control had the highest visual rank.
- Under the brand sat "YOUR IDEAS, IN MOTION" in tracked caps. A tagline is
  landing-page vocabulary; the owner rejected that register on 2026-09-05.
- Without a project the map showed the Modulumfeld / Fourfold switch as a
  floating pane over "Kein erreichbarer Checkout ausgewählt." — a control
  with nothing to control.

Screenshots (before and after, 1440×900 and 1024×720) are retained in the
loop's published artifact "Daedalus GUI Iterationen".

## Scope

Owned paths: `apps/web/src/app/Cockpit.tsx` (brand markup, chrome tools,
the map render site), `apps/web/src/app/styles/spatial.css` (glass rules
for `.theme-trigger` and `.workspace-brand-caption`), this packet.
Not touched: kernel, API, tests' accessible names ("Themes" stays the
button's name; tests keep resolving it).

## Contracts and behavior

- Brand: caption removed; `aria-label="Daedalus"`; the two caption rules in
  `spatial.css` deleted with it.
- Theme trigger: label carries `.tool-label` like its siblings; the accent
  pill rules and every `:not(.theme-trigger)` exception are deleted, so the
  four tools share one width and one weight at every breakpoint.
- Map: `{project && graphModeSwitch}` — the switch renders only when there
  is a project to switch between.

## Acceptance matrix

| Check | Evidence |
| --- | --- |
| Type | `npx tsc --noEmit -p .` exit 0 (2026-09-06 02:14) |
| Bootstrap | `npm run test:app` 527/527 |
| Names | `getByRole('button', {name: 'Themes'})` still resolves: the label is clipped, not removed (cockpit.spec, spatial.spec, interactive-rooms.spec use it) |
| Visual | After-screenshots at 1440×900 and 1024×720: four equal icon tools, no caption, no switch on the empty stage; zero console errors in the after-run |
| Not run | `tools/gui_check.py` browser suite (needs the real server harness); named as residual |

## Evidence, expected failures and review

The acceptance matrix and retained room screenshots are the focused evidence;
no runtime-health or promotion claim is added by this presentation packet.

## Migration and rollback

Revert the two files; no data, storage or contract changes.
