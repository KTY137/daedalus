# Cockpit — 2026-08-25

**These are not mockups.** Every image in this folder is a screenshot of the
running application at `apps/web`, taken from the built bundle served by
`python -m daedalus.cli web`, against the live local API. `manifest.json`
records what was on screen for each one: the theme, the composition attributes,
the number of nodes drawn, and the module in the middle.

## What changed

The gallery round of 2026-08-24 was left as "the live decision": six designs,
pick one, throw five away. The owner asked a different question — *"können wir
ein theme editor haben mit multiple themes?"* — and this round is the answer.

Every design is now a **theme**. A theme here is not a palette: the gallery
round asked for divergence in COMPOSITION, so a theme carries where the
conversation sits, what the chrome is and how the stage draws, alongside colour,
type and material. All six are built in, all six are editable, and a seventh
does not need another design round.

| theme | chrome | conversation | decision | stage |
| --- | --- | --- | --- | --- |
| Kammer | bar | card over the stage | floating | node forest, pearls |
| Werkstatt | bar | drawer below | with the conversation | cards |
| Sternkarte | bar | drawer below | floating | star chart |
| Depesche | masthead | in the text flow | with the conversation | arc figure |
| Nachtfenster | bar | column beside | with the conversation | node forest, discs |
| Leitstand | bar | column beside | own bar | cards |

## What is real

- the map: `/api/structure` — 349 nodes, 848 edges drawn, 1840 leading off the
  map, and the surface says all three numbers.
- the conversation: `/api/ikarus/stream`, with a provenance stamp that names
  what produced the answer (the local index, or the model by name).
- the decision: `/api/drafts` — Annehmen and Ablehnen are the real apply and
  dismiss endpoints, and "Warum" fetches the draft's own report.
- the state line: `/api/health` (five states, none of which collapse into
  green), `/api/governance`, and the live event stream.

There is no fixture path in `src/cockpit/`.

## What is not drawn, and where it says so

A module with 161 importers has no readable ring. Past the layout's budget the
remainder becomes ONE glyph carrying its own count (`+66 weitere`), the header
states how many direct and how many distant neighbours were left out, and
pressing either lists exactly those modules. The stage never quietly draws 14 of
80.

## The test that came out of round three

`apps/web/tests/cockpit.spec.ts` is the per-project fake-data test round three
asked for: no drawn node, no palette entry and no line of the status bar may
name anything belonging to a project other than the selected one, and switching
project must CLEAR the map rather than relabel it. That last check found a real
defect on its first run, and was mutation-checked — disabling the guard turns it
red.

## Open

- Depesche's arc figure is the least finished of the six; the axis takes what
  fits at 96px per name and hands the rest to the aggregate glyph.
- The cockpit does not yet reach `/api/topology`, `/api/capabilities` or
  `/api/context/plan`. Those endpoints still have no client anywhere.
