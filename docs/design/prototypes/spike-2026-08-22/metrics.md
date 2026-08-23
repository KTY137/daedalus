# Spike measurement — 1440x900, dark, deterministic probe [MEASURED]

Probe: daedalus/gui/probe.js (motion frozen). Linter: daedalus/gui/lint.py. Canonical LOOK screenshots (motion running, 2.5 s settle): forge.png, glass.png, instrument.png, scene.png — all four confirmed non-blank.

| metric (unit) | forge | glass | instrument | scene |
|---|---|---|---|---|
| horizontal_overflow (px) | 0 | 0 | 0 | 0 |
| contrast_failures (elements) | 14 | 0 | 0 | 0 |
| small_targets (elements) | 6 | 0 | 4 | 0 |
| banned_faces (families) | 0 | 1 | 0 | 1 |
| console_errors (errors) | 1 | 7 | 1 | 1 |
| visible_elements (elements) | 115 | 334 | 262 | 43 |
| framed_panels (panels) | 15 | 2 | 13 | 1 |
| distinct_radii (values) | 0 | 1 | 1 | 0 |
| panel_nesting_depth (levels) | 2 | 1 | 2 | 1 |
| allcaps_text_share (% of chars) | 32.1 | 6.0 | 10.7 | 50.0 |
| status_pills_visible (pills) | 0 | 0 | 0 | 0 |
| largest_equal_tile_row (tiles) | 7 | 7 | 4 | 8 |
| accent_hue_families (hues) | 4 | 4 | 3 | 0 |
| identifier_leaks (strings) | 0 | 0 | 0 | 0 |
| probe elements kept/raw | 115/117 | 334/384 | 262/302 | 43/43 |

## Breaches (BRIEF.md thresholds: framed_panels<=15, visible_elements<=~150, status_pills_visible=0, distinct_radii<=1, panel_nesting_depth<=2, identifier_leaks=0, contrast_failures<=14 and small_targets<=6 relative to forge)

- glass.visible_elements = 334 (threshold <= 150) [MEASURED]
- instrument.visible_elements = 262 (threshold <= 150) [MEASURED]

## Other measured deviations from forge (not in the brief's threshold list)

- glass.banned_faces = 1 ('space grotesk'; forge 0) [MEASURED]
- scene.banned_faces = 1 ('space grotesk'; forge 0) [MEASURED]
- glass.console_errors = 7 (forge 1) [MEASURED]

## Console errors (verbatim)

- all four: `pageerror: Cannot read properties of null (reading 'appendChild')` (forge baseline shows the same one)
- glass additionally x6: `Error: <feColorMatrix> attribute values: Expected number, "0 0\
  1".`

Note: the linter's `largest_equal_tile_row` counts full-viewport 1440x900 stacked layers (backgrounds), not metric tiles, for forge/glass/scene.
