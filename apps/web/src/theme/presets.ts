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
    type: {
      display: '"Segoe UI", system-ui, -apple-system, sans-serif',
      body: '"Segoe UI", system-ui, -apple-system, sans-serif',
      mono: 'ui-monospace, "Cascadia Mono", Consolas, "SF Mono", monospace',
      size: 14,
      scale: 1.22,
      displayWeight: 600,
      displayTracking: -0.01,
      displaySerif: false
    },
    form: { radius: 24, border: 1, unit: 8, elevation: 2, material: 'glass', blur: 26, alpha: 0.11 },
    stage: { layout: 'forest', glyph: 'pearl', backboneOnly: true, curve: 0, sizeByFanIn: 0.75, glow: 0.85 },
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
    type: {
      display: 'Seravek, "Segoe UI", Frutiger, "Trebuchet MS", Verdana, sans-serif',
      body: 'Seravek, "Segoe UI", Frutiger, "Trebuchet MS", Verdana, sans-serif',
      mono: '"Cascadia Code", Consolas, "SF Mono", ui-monospace, Menlo, monospace',
      size: 14,
      scale: 1.2,
      displayWeight: 600,
      displayTracking: -0.005,
      displaySerif: false
    },
    form: { radius: 6, border: 1, unit: 8, elevation: 1, material: 'flat', blur: 0, alpha: 1 },
    stage: { layout: 'cards', glyph: 'card', backboneOnly: false, curve: 0, sizeByFanIn: 0, glow: 0 },
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
    type: {
      display: 'Georgia, "Times New Roman", serif',
      body: '"Segoe UI", system-ui, -apple-system, "Helvetica Neue", sans-serif',
      mono: 'Consolas, "Cascadia Mono", "Courier New", monospace',
      size: 13.5,
      scale: 1.25,
      displayWeight: 400,
      displayTracking: 0,
      displaySerif: true
    },
    form: { radius: 3, border: 1, unit: 8, elevation: 1, material: 'flat', blur: 0, alpha: 0.94 },
    stage: { layout: 'stars', glyph: 'star', backboneOnly: true, curve: 0.28, sizeByFanIn: 1, glow: 0.5 },
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
    type: {
      display: 'Georgia, Cambria, "Times New Roman", Times, serif',
      body: 'Georgia, Cambria, "Times New Roman", Times, serif',
      mono: 'Consolas, "Cascadia Mono", ui-monospace, Menlo, monospace',
      size: 15,
      scale: 1.34,
      displayWeight: 400,
      displayTracking: -0.005,
      displaySerif: true
    },
    form: { radius: 0, border: 1, unit: 8, elevation: 0, material: 'paper', blur: 0, alpha: 1 },
    stage: { layout: 'arcs', glyph: 'disc', backboneOnly: false, curve: 1, sizeByFanIn: 0.4, glow: 0 },
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
    type: {
      display: '"Segoe UI", system-ui, -apple-system, sans-serif',
      body: '"Segoe UI", system-ui, -apple-system, sans-serif',
      mono: 'ui-monospace, "Cascadia Code", "SF Mono", Consolas, monospace',
      size: 13.5,
      scale: 1.2,
      displayWeight: 600,
      displayTracking: -0.01,
      displaySerif: false
    },
    form: { radius: 16, border: 1, unit: 8, elevation: 1, material: 'flat', blur: 0, alpha: 1 },
    stage: { layout: 'forest', glyph: 'disc', backboneOnly: true, curve: 0.12, sizeByFanIn: 0.6, glow: 0.2 },
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
    type: {
      display: '"Segoe UI", system-ui, -apple-system, Helvetica, sans-serif',
      body: '"Segoe UI", system-ui, -apple-system, Helvetica, sans-serif',
      mono: 'Consolas, "Cascadia Mono", ui-monospace, monospace',
      size: 13,
      scale: 1.18,
      displayWeight: 700,
      displayTracking: 0,
      displaySerif: false
    },
    form: { radius: 2, border: 1, unit: 7, elevation: 1, material: 'flat', blur: 0, alpha: 1 },
    stage: { layout: 'cards', glyph: 'card', backboneOnly: false, curve: 0, sizeByFanIn: 0, glow: 0 },
    composition: { chrome: 'bar', chat: 'column' }
  }
];

export const BUILT_IN_IDS = new Set(BUILT_INS.map((t) => t.id));

export const DEFAULT_THEME_ID = 'kammer';

export function builtIn(id: string): ThemeSpec | undefined {
  return BUILT_INS.find((t) => t.id === id);
}
