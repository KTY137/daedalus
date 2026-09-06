# G1-UI-17 — The Theme Studio speaks like a tool

Packet ID: G1-UI-17
Artifact role: primary
Active gate: 1
Classification: ALIGNED
Change class: presentation and copy only; no theme schema, storage, API or
policy change.
Owner: repository owner (owner loop of 2026-09-06, iteration 2 of four)
Base revision: 585b7ea4e141332928ad6c9578b9c9997e55f247
Dependencies: G1-UI-16 (iteration 1)
Authority: IKARUS_ARIADNE_MASTER_PLAN.md revision 12.

## Primary acceptance claim

The Theme Studio panel uses the interface's own register: headings name
what a section contains, the type preview shows the faces in the words the
product actually sets, and no line in the panel is a slogan.

## Baseline (measured 2026-09-06 02:20, Graphite Atelier, 1440×900)

- Panel eyebrow "DEIN WORKSPACE. DEIN LOOK." (9 px tracked caps) over
  "Theme Studio." with an accent-coloured full stop that encodes nothing.
- Looks heading "Eine neue Perspektive. / Ein Klick verändert die
  Atmosphäre." and custom-looks heading "Von dir gestaltet. / Deine Looks,
  automatisch gespeichert." — slogans where a label belongs.
- Type preview sample "Raum für große Ideen." over "DAEDALUS · DEIN
  WORKSPACE" in 8 px tracked caps: the sample never appears in the product,
  so it demonstrates nothing about how the chosen faces will read.

## Scope

Owned paths: `apps/web/src/shared/ui/theme/ThemeStudio.tsx` (four copy
sites), `apps/web/src/shared/ui/theme/studio.css` (eyebrow rule, h2 span
rule, type-preview small rule), this packet. Not touched: tab names, the
"Alle Looks" button, "Themes" trigger, "Fertig", save notices — every string
the browser specs resolve.

## Contracts and behavior

- Header: `<h2>Theme Studio</h2>`; eyebrow and accent-dot rules deleted.
- Looks: "Eingebaute Looks — Ein Klick wechselt sofort; das Original bleibt
  erhalten." and "Deine Looks — Kopien, die du bearbeitet hast; automatisch
  gespeichert." The count on the right stays.
- Type preview: sample line is the empty-thread headline "Woran arbeiten
  wir?", the small line is the composer placeholder, set in the body face at
  the small step instead of 8 px tracked caps.

## Acceptance matrix

| Check | Evidence |
| --- | --- |
| Type | `npx tsc --noEmit -p .` exit 0 (02:24) |
| Bootstrap | `npm run test:app` 527/527 |
| Pinned names | grep over `tests/*.ts` and `theme.spec.ts`: none of the changed strings is referenced |
| Visual | Panel screenshots before/after, Looks and Schrift tabs, retained in the artifact "Daedalus GUI Iterationen" |
| Not run | `tools/gui_check.py` browser suite (real-server harness) |

## Evidence, expected failures and review

The focused copy assertions and retained browser capture are the evidence;
known presentation limits remain named and no policy claim is implied.

## Migration and rollback

Revert the two files; no stored theme is affected.
