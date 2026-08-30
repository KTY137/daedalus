// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-License-Identifier: Apache-2.0

import type { ThemeSpec } from './types';

/**
 * The six built-in themes.
 *
 * Each one is a reading of one design from the gallery round of 2026-08-24
 * (docs/design/prototypes/gallery-2026-08-24). The palettes are lifted from
 * those files rather than re-invented, so a theme here and its prototype are
 * the same design, not two designs with the same name.
 *
 * They are read-only. Editing one in the Theme Studio forks it into a stored
 * copy; the built-in stays where it is, so a bad afternoon of tweaking never
 * destroys the reference.
 */

export const BUILT_INS: ThemeSpec[] = [
  {
    id: 'referenz',
    name: 'Referenz',
    note: 'Aus gemessenen Oberflächen gebaut: fast schwarzer Grund, Flächen als Prozente von Weiß, ein Ring statt Schatten.',
    base: 'dark',
    origin: 'measured-2026-08-25',
    /**
     * NOT A TASTE. Every value below was read off a shipped interface with
     * tools/reference.mjs on 2026-08-25 and is quoted here with its source:
     *
     *   linear.app     bg rgb(8,9,10); text f7f8f8 / d0d6e0 / 8a8f98 / 62666d;
     *                  surfaces rgba(255,255,255,.02–.05); radius 6px dominant;
     *                  shadow `rgba(0,0,0,.2) 0 0 0 1px` — a ring; sizes
     *                  12/13/15/11/14; weights 510/400/590; tracking -0.13 to
     *                  -0.18px at body size; gap 8px dominant.
     *   raycast.com    bg rgb(7,8,10); radius 11px dominant; layered shadow
     *                  with an inset white highlight.
     *   graphite.dev   bg lab(2.75) ~ #070707; text hierarchy by ALPHA;
     *                  radius 10/8/4; gap 8/16/4.
     *
     * The accent is Apple's system blue (#0A84FF), which measures 5.46:1 on
     * this background — above the floor, and not a colour this project chose
     * because it looked nice.
     */
    colors: {
      room: '#111417',
      room2: '#08090A',
      surface: 'rgba(255,255,255,.035)',
      surface2: 'rgba(255,255,255,.06)',
      ink: '#F7F8F8',
      ink2: '#D0D6E0',
      ink3: '#8A8F98',
      line: 'rgba(255,255,255,.09)',
      line2: 'rgba(255,255,255,.055)',
      accent: '#0A84FF',
      // Dark ON the blue, not white. Apple's system blue is bright enough to
      // be readable AS text on this background (5.46:1) and too bright to
      // carry white text at 11-13px (3.43:1, measured). Something has to give,
      // and it is not the blue.
      accentInk: '#031627',
      live: '#E9A23B',
      bad: '#F0616D',
      ok: '#4CC38A',
      node: '#E7E9EE',
      node2: '#6C727E',
      edge: 'rgba(255,255,255,.10)',
      edgeHot: '#0A84FF'
    },
    // warn: gold, hue 50 — clears live's amber (35) and bad's coral (355) by
    // >=15deg; 12.0:1 on room, so it reads as text as well as a badge.
    warn: '#ead053',
    warnInk: '#302803',
    // heat: one hue (amber-ember, ~32), anchor flipped for dark — low sits
    // near room and climbs to a light, saturated high. 134..256 in the hot
    // list reads as "barely there" to "glowing", not five ticks of one grey.
    heat: '#3e2f1e, #79552d, #bd7c33, #e0a159, #f3c591',
    // plane: Code / Type / Data / Knowledge, fixed order, four hues 90deg
    // apart so no CVD confusion between adjacent planes.
    plane: '#dd9988, #a2dd88, #88ccdd, #c388dd',
    type: {
      display: '"SF Pro Display", -apple-system, "Segoe UI Variable Display", "Segoe UI", system-ui, sans-serif',
      body: '"SF Pro Text", -apple-system, "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif',
      mono: 'ui-monospace, "SF Mono", "Cascadia Mono", Consolas, monospace',
      // Ikarus's voice only — Sitka is a real humanist serif with an optical
      // size built for on-screen text (Sitka Text), the one warm face against
      // this theme's cold measured-instrument grotesk.
      voice: '"Sitka Text", Constantia, Georgia, serif',
      voiceWeight: 400,
      labelWeight: 590,
      labelTracking: 0.02,
      datumWeight: 510,
      datumTracking: -0.005,
      // 13 at 1.15 gives 11 / 11.3 / 13 / 15 / 17 / 20 — the measured range.
      size: 13,
      scale: 1.15,
      displayWeight: 600,
      displayTracking: -0.014,
      displaySerif: false
    },
    form: {
      radius: 8, border: 1, unit: 8, elevation: 1, elevationPane: 1, elevationDrawer: 2, elevationModal: 3,
      material: 'glass', blur: 20, alpha: 0.035
    },
    stage: {
      layout: 'cards', glyph: 'card', backboneOnly: true, curve: 0, sizeByFanIn: 0.8, glow: 0.12,
      parallax: 0.15, depthFog: 0.25, depthBlur: 1.5
    },
    composition: { chrome: 'bar', chat: 'column' }
  },

  {
    id: 'kammer',
    name: 'Kammer',
    note: 'Ein warm ausgeleuchteter Raum aus Perlknoten; die Oberfläche schwebt als Glas darin.',
    base: 'dark',
    origin: 'gallery-2026-08-24',
    colors: {
      room: '#33220f',
      room2: '#0d0805',
      surface: 'rgba(255,255,255,.11)',
      surface2: 'rgba(255,255,255,.06)',
      ink: '#f4ecdf',
      ink2: 'rgba(244,236,223,.68)',
      ink3: 'rgba(244,236,223,.62)',
      line: 'rgba(255,255,255,.28)',
      line2: 'rgba(255,255,255,.12)',
      accent: '#ffb85c',
      accentInk: '#2b1804',
      live: '#ffb85c',
      bad: '#e2705c',
      ok: '#8fc08a',
      node: '#f0e3cd',
      node2: '#8a7458',
      edge: 'rgba(244,236,223,.22)',
      edgeHot: '#e89b3e'
    },
    // warn: gold, hue 52 — clear of the room's own orange accent (33) and
    // its terracotta bad (8) by >=19deg.
    warn: '#ead653',
    warnInk: '#302a03',
    // heat: crimson ember (hue ~345), 49deg from the accent's 33 — Kartograph
    // draws the stage's one focus node in --accent and every other node from
    // this ramp, so a hot node that reads as "selected" is a real bug, not a
    // style nit. (Revised 2026-08-26: the first pass used hue ~20, only
    // 13-14deg from accent — too close once lightness/saturation moved
    // together at the hot end.)
    heat: '#351d23, #682737, #a32947, #d92653, #e4446c',
    plane: '#c8dd88, #88ddc8, #9d88dd, #dd889d',
    type: {
      // Candara: a rounder humanist grotesk, warmer curves than Segoe UI —
      // a chosen face for the "warm lit room," not the Windows default.
      display: 'Candara, Corbel, "Segoe UI", system-ui, sans-serif',
      body: 'Candara, Corbel, "Segoe UI", system-ui, sans-serif',
      mono: 'ui-monospace, "Cascadia Mono", Consolas, "SF Mono", monospace',
      voice: '"Sitka Small", Constantia, Georgia, serif',
      voiceWeight: 400,
      labelWeight: 600,
      labelTracking: 0.03,
      datumWeight: 600,
      datumTracking: -0.005,
      size: 14,
      scale: 1.22,
      displayWeight: 600,
      displayTracking: -0.01,
      displaySerif: false
    },
    form: {
      radius: 24, border: 1, unit: 8, elevation: 2, elevationPane: 2, elevationDrawer: 3, elevationModal: 4,
      material: 'glass', blur: 26, alpha: 0.11
    },
    stage: {
      layout: 'forest', glyph: 'pearl', backboneOnly: true, curve: 0, sizeByFanIn: 0.75, glow: 0.85,
      parallax: 0.35, depthFog: 0.45, depthBlur: 3
    },
    composition: { chrome: 'bar', chat: 'column' }
  },

  {
    id: 'werkstatt',
    name: 'Werkstatt',
    note: 'Der Graph als Werkbankbrett: Symbole als angeheftete Karten, das Gespräch als Schublade darunter.',
    base: 'light',
    origin: 'gallery-2026-08-24',
    colors: {
      room: '#F5F3ED',
      room2: '#EFEDE8',
      surface: '#FBFAF7',
      surface2: '#EAEDE3',
      ink: '#26251F',
      ink2: '#55524A',
      ink3: '#6B675C',
      line: '#D8D4C8',
      line2: '#E6E3DA',
      accent: '#55663F',
      accentInk: '#FBFAF7',
      live: '#6F5417',
      bad: '#98352B',
      ok: '#475633',
      node: '#FBFAF7',
      node2: '#EFEDE8',
      edge: '#BFBAA9',
      edgeHot: '#55663F'
    },
    // warn: olive-gold, hue 58 — the theme's whole palette is earthy, so
    // caution stays in that family while clearing the olive accent (95)
    // and the brick bad (5).
    warn: '#6f6c0b',
    warnInk: '#fefdec',
    // heat: brick-clay hue (~24) — a workbench idiom (scorch/rust), and the
    // one warm note against the theme's cool olive accent.
    heat: '#e8dfd9, #d4b39e, #cb8658, #b05c24, #77380d',
    plane: '#758e29, #298e75, #43298e, #8e2943',
    type: {
      // Seravek is not installed on Windows and silently fell through to
      // Segoe UI — the exact "seven themes, one voice" bug this round is
      // about. Gill Sans MT is: installed, humanist, and carries real
      // workshop/instrument-label heritage the fallback didn't.
      display: '"Gill Sans MT", Corbel, "Segoe UI", sans-serif',
      body: '"Gill Sans MT", Corbel, "Segoe UI", sans-serif',
      mono: '"Cascadia Code", Consolas, "SF Mono", ui-monospace, Menlo, monospace',
      voice: '"Sitka Text", "Palatino Linotype", Georgia, serif',
      voiceWeight: 400,
      labelWeight: 600,
      labelTracking: 0.02,
      datumWeight: 600,
      datumTracking: 0,
      size: 14,
      scale: 1.2,
      displayWeight: 600,
      displayTracking: -0.005,
      displaySerif: false
    },
    form: {
      radius: 6, border: 1, unit: 8, elevation: 1, elevationPane: 1, elevationDrawer: 2, elevationModal: 3,
      material: 'flat', blur: 0, alpha: 1
    },
    stage: {
      layout: 'cards', glyph: 'card', backboneOnly: false, curve: 0, sizeByFanIn: 0, glow: 0,
      parallax: 0.1, depthFog: 0.15, depthBlur: 1
    },
    composition: { chrome: 'bar', chat: 'column' }
  },

  {
    id: 'sternkarte',
    name: 'Sternkarte',
    note: 'Messung als Kartografie: die Nachbarschaft als Sternatlas, das Gespräch als Schublade.',
    base: 'dark',
    origin: 'gallery-2026-08-24',
    colors: {
      room: '#0A1120',
      room2: '#060A12',
      surface: 'rgba(9,14,23,.94)',
      surface2: 'rgba(20,29,44,.9)',
      ink: '#E7EEF7',
      ink2: '#9FB0C4',
      ink3: '#7C8DA3',
      line: '#2E3F55',
      line2: '#1B2634',
      accent: '#A9DBF2',
      accentInk: '#07202E',
      live: '#A9DBF2',
      bad: '#E4796B',
      ok: '#7FC3A0',
      node: '#E7EEF7',
      node2: '#5E7188',
      edge: 'rgba(169,219,242,.2)',
      edgeHot: '#A9DBF2'
    },
    warn: '#eac653',
    warnInk: '#302503',
    // heat: bronze-to-gold ember (hue ~40), 159deg from the accent's pale
    // cyan (~199) — deliberately NOT the room's own blue. Kartograph draws
    // the stage's one focus node in --accent and every other node from this
    // ramp; a first pass reused the room's blue for heat and landed only
    // 11deg from accent, so "selected" and "hot" read as the same star.
    // Star temperature runs the other way in life (hotter = bluer), but a
    // warm-reads-as-more idiom is the one every reader already has, and
    // that legibility wins over the astrophysics footnote.
    heat: '#3e331e, #7e6430, #be9137, #dbaf57, #f2ce88',
    plane: '#c3dd88, #88ddcc, #a288dd, #dd8899',
    type: {
      // Constantia replaces Georgia here — Georgia is also Depesche's display
      // face, and two of seven themes sharing one serif is the same
      // monoculture bug as falling through to Segoe UI. Constantia is a
      // cooler, more drafted transitional serif — closer to a printed star
      // atlas's plate captions.
      display: 'Constantia, Cambria, Georgia, serif',
      // Bahnschrift is a real installed engineering/drafting grotesk —
      // instrument-cold in the most literal sense, apt for cartographic data.
      body: 'Bahnschrift, "Segoe UI", system-ui, -apple-system, "Helvetica Neue", sans-serif',
      mono: 'Consolas, "Cascadia Mono", "Courier New", monospace',
      voice: '"Sitka Text", "Palatino Linotype", Georgia, serif',
      voiceWeight: 400,
      labelWeight: 600,
      labelTracking: 0.04,
      datumWeight: 500,
      datumTracking: 0,
      size: 13.5,
      scale: 1.25,
      displayWeight: 400,
      displayTracking: 0,
      displaySerif: true
    },
    form: {
      radius: 3, border: 1, unit: 8, elevation: 1, elevationPane: 1, elevationDrawer: 2, elevationModal: 3,
      material: 'flat', blur: 0, alpha: 0.94
    },
    stage: {
      layout: 'stars', glyph: 'star', backboneOnly: true, curve: 0.28, sizeByFanIn: 1, glow: 0.5,
      parallax: 0.4, depthFog: 0.5, depthBlur: 2.5
    },
    composition: { chrome: 'bar', chat: 'column' }
  },

  {
    id: 'depesche',
    name: 'Depesche',
    note: 'Das Gespräch als Titelseite: die Frage ist die Schlagzeile, der Graph ist Abbildung 1.',
    base: 'light',
    origin: 'gallery-2026-08-24',
    colors: {
      room: '#FAF8F4',
      room2: '#F3F0EA',
      surface: '#FAF8F4',
      surface2: '#F1EEE7',
      ink: '#151210',
      ink2: '#5C554E',
      ink3: '#6E675F',
      line: 'rgba(21,18,16,.6)',
      line2: 'rgba(21,18,16,.22)',
      accent: '#A3161F',
      accentInk: '#FAF8F4',
      live: '#A3161F',
      bad: '#A3161F',
      ok: '#2F5D3A',
      node: '#151210',
      node2: '#8A8279',
      edge: 'rgba(21,18,16,.35)',
      edgeHot: '#A3161F'
    },
    warn: '#8b660e',
    warnInk: '#fef8ec',
    // heat: masthead red (same family as the accent/bad hue, ~357) — a
    // broadsheet only has one ink colour to spend, and this is it.
    heat: '#e8d9da, #d49ea0, #cb585e, #b0242b, #770d13',
    plane: '#8e4829, #3e8e29, #29708e, #7a298e',
    type: {
      display: 'Georgia, Cambria, "Times New Roman", Times, serif',
      // Body drops to Cambria — a text-optimized serif, not the display face
      // repeated — so headline and column carry visibly different weight,
      // the way a real masthead and its body copy do.
      body: 'Cambria, Georgia, "Times New Roman", Times, serif',
      mono: 'Consolas, "Cascadia Mono", ui-monospace, Menlo, monospace',
      // Depesche IS the warm-voice page — the whole theme is Ikarus's words
      // as the front page, so voice matches body rather than introducing a
      // fourth serif; the "cold instrument" role here belongs to mono only.
      voice: 'Georgia, Cambria, "Times New Roman", Times, serif',
      voiceWeight: 400,
      labelWeight: 600,
      labelTracking: 0.08,
      datumWeight: 600,
      datumTracking: 0,
      size: 15,
      scale: 1.34,
      displayWeight: 400,
      displayTracking: -0.005,
      displaySerif: true
    },
    form: {
      radius: 0, border: 1, unit: 8, elevation: 0, elevationPane: 0, elevationDrawer: 1, elevationModal: 2,
      material: 'paper', blur: 0, alpha: 1
    },
    stage: {
      layout: 'arcs', glyph: 'disc', backboneOnly: false, curve: 1, sizeByFanIn: 0.4, glow: 0,
      parallax: 0, depthFog: 0, depthBlur: 0
    },
    composition: { chrome: 'masthead', chat: 'flow' }
  },

  {
    id: 'nachtfenster',
    name: 'Nachtfenster',
    note: 'Vier Scheiben bei Nacht: Tabelle und Karte sind dasselbe Objekt, zweimal gesehen.',
    base: 'dark',
    origin: 'gallery-2026-08-24',
    colors: {
      room: '#0a0a0f',
      room2: '#020203',
      surface: '#0d0d11',
      surface2: '#141419',
      ink: '#e9e9ef',
      ink2: '#a6a6b4',
      ink3: '#82828f',
      line: 'rgba(255,255,255,.08)',
      line2: 'rgba(255,255,255,.05)',
      accent: '#7C87E8',
      accentInk: '#0b0b12',
      live: '#9aa3ec',
      bad: '#d4665c',
      ok: '#5fae86',
      node: '#e9e9ef',
      node2: '#4a4a58',
      edge: 'rgba(233,233,239,.16)',
      edgeHot: '#9aa3ec'
    },
    warn: '#eac653',
    warnInk: '#302503',
    // heat: the signature move for this theme. A single hue would put the
    // hottest module in the SAME blue-violet family as the selection
    // accent — indistinguishable at a glance. Instead this sweeps the long
    // way round the wheel (blue -> indigo -> magenta -> ember -> cream),
    // never crossing green, so the ramp reads as a thermal-camera scan
    // through the theme's own night window: cold glass, hot module.
    heat: '#1e2e3e, #402d79, #bd33bd, #e0597b, #f3c291',
    plane: '#c3dd88, #88ddcc, #a288dd, #dd8899',
    type: {
      // Bahnschrift: an installed engineering/surveillance-panel grotesk,
      // narrower than Segoe UI — the cold instrument face for a theme about
      // watching four panes at night.
      display: 'Bahnschrift, "Segoe UI Variable Display", "Segoe UI", system-ui, sans-serif',
      body: 'Bahnschrift, "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif',
      mono: 'ui-monospace, "Cascadia Code", "SF Mono", Consolas, monospace',
      // The most dramatic cold/warm contrast of the seven: Sitka's humanist
      // serif breaking through an otherwise all-instrument, all-Bahnschrift
      // night panel.
      voice: '"Sitka Text", Georgia, serif',
      voiceWeight: 400,
      labelWeight: 600,
      labelTracking: 0.03,
      datumWeight: 600,
      datumTracking: -0.005,
      size: 13.5,
      scale: 1.2,
      displayWeight: 600,
      displayTracking: -0.01,
      displaySerif: false
    },
    form: {
      radius: 16, border: 1, unit: 8, elevation: 1, elevationPane: 2, elevationDrawer: 3, elevationModal: 4,
      material: 'flat', blur: 0, alpha: 1
    },
    stage: {
      // "Vier Scheiben bei Nacht" — four panes at night — is already a depth
      // idea by name; this theme gets the deepest parallax/fog/blur spread.
      layout: 'forest', glyph: 'disc', backboneOnly: true, curve: 0.12, sizeByFanIn: 0.6, glow: 0.2,
      parallax: 0.45, depthFog: 0.55, depthBlur: 3.5
    },
    composition: { chrome: 'rail', chat: 'column' }
  },

  {
    id: 'leitstand',
    name: 'Leitstand',
    note: 'Braun 1965: warme matte Hardware, ein Signalorange, der Graph als Schaltplan.',
    base: 'light',
    origin: 'gallery-2026-08-24',
    colors: {
      room: '#E4E2DD',
      room2: '#CDCAC4',
      surface: '#E4E2DD',
      surface2: '#F5F3EC',
      ink: '#2B2823',
      ink2: '#514E48',
      ink3: '#4A473F',
      line: '#4A463F',
      line2: '#8B877E',
      accent: '#93330A',
      accentInk: '#F5F3EC',
      live: '#8A2E05',
      bad: '#8A2E05',
      ok: '#2E5233',
      node: '#F5F3EC',
      node2: '#CDCAC4',
      edge: '#8B877E',
      edgeHot: '#D64A0C'
    },
    warn: '#795f0c',
    warnInk: '#fefaec',
    // heat: amber gauge-band (hue ~45), 27deg from the accent's rust (~18) —
    // banded amber-not-rust is the more authentic gauge idiom anyway (a real
    // VU meter bands green/amber/red rather than one hue at climbing
    // saturation) and it keeps a hot node from reading as the selected one:
    // Kartograph draws the stage's one focus node in --accent and every
    // other node from this ramp. A first pass reused the accent's own rust
    // hue outright.
    heat: '#e8e4d9, #d1c49f, #c7ab57, #b18e25, #81640e',
    plane: '#758e29, #298e75, #43298e, #8e2943',
    type: {
      // Franklin Gothic: an installed American industrial-panel grotesk —
      // the "Braun 1965 hardware nameplate" face this theme's note asks for,
      // in place of default Segoe UI Bold. Deliberately sans, not a serif —
      // a serif display here would drift into the cream/serif/terracotta
      // cluster this theme otherwise avoids (warm GREY, not cream; sans, not
      // serif).
      display: '"Franklin Gothic Medium", "Segoe UI", system-ui, -apple-system, Helvetica, sans-serif',
      body: '"Franklin Gothic Book", Corbel, "Segoe UI", system-ui, -apple-system, Helvetica, sans-serif',
      mono: 'Consolas, "Cascadia Mono", ui-monospace, monospace',
      voice: '"Sitka Text", Constantia, Georgia, serif',
      voiceWeight: 400,
      labelWeight: 700,
      labelTracking: 0.04,
      datumWeight: 600,
      datumTracking: 0,
      size: 13,
      scale: 1.18,
      displayWeight: 700,
      displayTracking: 0,
      displaySerif: false
    },
    form: {
      radius: 2, border: 1, unit: 7, elevation: 1, elevationPane: 1, elevationDrawer: 2, elevationModal: 3,
      material: 'flat', blur: 0, alpha: 1
    },
    stage: {
      // "Schaltplan" — a circuit diagram — is a flat technical drawing, so
      // depth stays the most restrained of the six gallery themes.
      layout: 'cards', glyph: 'card', backboneOnly: false, curve: 0, sizeByFanIn: 0, glow: 0,
      parallax: 0.1, depthFog: 0.2, depthBlur: 1
    },
    composition: { chrome: 'bar', chat: 'column' }
  }
];

export const BUILT_IN_IDS = new Set(BUILT_INS.map((t) => t.id));

export const DEFAULT_THEME_ID = 'referenz';

export function builtIn(id: string): ThemeSpec | undefined {
  return BUILT_INS.find((t) => t.id === id);
}
