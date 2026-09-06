# G1-UI-19 — Muted text reaches 4.5:1 on the rendered glass in every room

Packet ID: G1-UI-19
Artifact role: primary
Active gate: 1
Classification: ALIGNED
Change class: palette values of six built-in looks; no schema, storage, API or
policy change.
Owner: repository owner (owner loop of 2026-09-06, iteration 4 of four)
Base revision: 585b7ea4e141332928ad6c9578b9c9997e55f247
Dependencies: G1-UI-13 (room looks), G1-UI-14 (pane), G1-UI-18
Authority: IKARUS_ARIADNE_MASTER_PLAN.md revision 12.

## Primary acceptance claim

In each of the six room looks, the muted text step `ink3` (eyebrow, composer
role words, status line, secondary notes) reaches WCAG 2.2 AA 4.5:1 against
the pane it is actually drawn on: the glass composited over the room image,
sampled in the browser, not the flat token colour.

## Baseline (measured 2026-09-06 02:48, Playwright, 1440×900, empty thread)

Contrast of `ink3` against the rendered `.convo-open` pane (average of the
text-free left padding strip; "worst" = the least favourable sampled pixel):

| Look | ink3 | avg | worst |
| --- | --- | --- | --- |
| Porcelain | #5d687c | 4.33 | 4.09 |
| Graphite Atelier | #8d9bb0 | 3.55 | 2.94 |
| Spatial Daylight | #5f6b7b | 3.70 | 3.59 |
| Spatial Dusk | #a8968c | 4.09 | 3.97 |
| Spatial Studio | #5f6970 | 3.84 | 3.65 |
| Techno Forest | #87a4aa | 4.30 | 4.11 |

`ink2` (body notes, suggestions) was already ≥ 4.85 everywhere; headlines
≥ 8.9. Only the muted step failed, in all six rooms.

## Scope

Owned paths: `apps/web/src/shared/ui/theme/presets.ts` (the six `ink3`
values; Graphite's `ink2` one step lighter), this packet, the measurement
scripts in the loop scratchpad (not part of the tree). Not touched: Liquid
Glass / Frost references, flat and paper looks, any CSS.

## Method

For each room, walk from the old `ink3` toward that room's `ink2` in 1 %
steps and stop at the first colour whose worst sampled ratio is ≥ 4.5 and
whose average ratio is ≥ 4.7. Hue is preserved because the walk is a linear
mix of two same-family colours. Graphite's pane has the widest luminance
spread (its render has bright reflections behind the glass), so its `ink3`
lands at 85 % of the way to `ink2`; `ink2` moves from #bcc7d6 to #c4cedc so
the three text steps stay distinguishable.

## Contracts and behavior

| Look | ink3 before | ink3 after | mix toward ink2 |
| --- | --- | --- | --- |
| Porcelain | #5d687c | #566176 | 33 % |
| Graphite Atelier | #8d9bb0 | #b5c0d0 | 85 % (ink2 → #c4cedc) |
| Spatial Daylight | #5f6b7b | #4f5b6c | 78 % |
| Spatial Dusk | #a8968c | #b4a297 | 26 % |
| Spatial Studio | #5f6970 | #515b63 | 65 % |
| Techno Forest | #87a4aa | #90acb2 | 18 % |

## Acceptance matrix

| Check | Evidence |
| --- | --- |
| Type | `npx tsc --noEmit -p .` exit 0 |
| Bootstrap | `npm run test:app` (result appended below) |
| Rendered contrast after | re-measured with the same script; table appended below |
| Pinned values | no test references a room `ink3` hex or the `rooms-2026-09-05` palettes (grep over tests/ and theme.spec.ts) |
| Visual | pane crops before/after for Graphite and Daylight in the artifact "Daedalus GUI Iterationen" |
| Not run | `tools/gui_check.py` browser suite |

## Measured after (2026-09-06 02:55, same script, same viewport)

`npm run test:app`: 527/527. `ink3` against the rendered pane:

| Look | avg | worst |
| --- | --- | --- |
| Porcelain | 4.80 | 4.54 |
| Graphite Atelier | 5.45 | 4.51 |
| Spatial Daylight | 4.71 | 4.57 |
| Spatial Dusk | 4.72 | 4.59 |
| Spatial Studio | 4.74 | 4.51 |
| Techno Forest | 4.74 | 4.53 |

Graphite `ink2` (notes, suggestions) rose from 5.86 to 6.30; headlines
unchanged. No look moved below any of its previous values.

## Evidence, expected failures and review

The measurement samples one pane on one viewport. Text over the bare room
image (outside any pane) is not covered; with G1-UI-14 no body text sits
there in glass looks, but the map's empty state headline does — it measured
≥ 8.9 and is not muted.

## Migration and rollback

Revert `presets.ts`; stored themes are copies and keep their own values.
