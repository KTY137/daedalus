# Spike 2 measurements [MEASURED] 2026-08-22

Probe: daedalus/gui/probe.js (motion frozen) + lint.py, screen=cockpit, 1440x900. DOM probe cannot see canvas/WebGL content.

| metric | keynote | visionos | sequoia | lagerfeld |
|---|---|---|---|---|
| horizontal_overflow | 0 | 0 | 0 | 0 |
| contrast_failures | 0 | 11 | 15 | 3 |
| small_targets | 6 | 10 | 39 | 2 |
| banned_faces | 0 | 0 | 0 | 0 |
| console_errors | 1 | 1 | 1 | 1 |
| visible_elements | 145 | 369 | 288 | 172 |
| framed_panels | 4 | 0 | 7 | 19 |
| distinct_radii | 1 | 0 | 1 | 1 |
| panel_nesting_depth | 1 | 0 | 1 | 2 |
| allcaps_text_share | 0.0 | 0.0 | 0.0 | 0.0 |
| status_pills_visible | 10 | 0 | 3 | 0 |
| largest_equal_tile_row | 4 | 5 | 4 | 6 |
| accent_hue_families | 1 | 3 | 3 | 0 |
| identifier_leaks | 0 | 0 | 0 | 0 |

## Breaches vs brief
- keynote: status_pills_visible=10 (brief == 0)
- keynote: small_targets=6 (brief == 0)
- visionos: visible_elements=369 (brief <= 150)
- visionos: contrast_failures=11 (brief == 0)
- visionos: small_targets=10 (brief == 0)
- sequoia: visible_elements=288 (brief <= 150)
- sequoia: status_pills_visible=3 (brief == 0)
- sequoia: contrast_failures=15 (brief == 0)
- sequoia: small_targets=39 (brief == 0)
- lagerfeld: framed_panels=19 (brief <= 8)
- lagerfeld: visible_elements=172 (brief <= 150)
- lagerfeld: contrast_failures=3 (brief == 0)
- lagerfeld: small_targets=2 (brief == 0)