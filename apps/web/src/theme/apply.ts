// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-License-Identifier: Apache-2.0

import type { ThemeSpec } from './types';

/**
 * A theme becomes CSS custom properties on <html>, plus a handful of data
 * attributes for the choices CSS cannot express as a value (which layout the
 * stage draws, where the chat sits, what the panels are made of).
 *
 * Applying is synchronous and total: every variable this module can write is
 * written on every call, so switching from a theme that sets a variable to one
 * that does not can never leave the old value behind. That was the failure
 * mode of the previous glass editor, which only ever added.
 */

/** Every custom property this module owns. Kept for the reset path and tests. */
export const THEME_VARS = [
  '--room', '--room2',
  '--surface', '--surface2',
  '--ink', '--ink2', '--ink3',
  '--line', '--line2',
  '--accent', '--accent-ink',
  '--live', '--bad', '--ok', '--warn', '--warn-ink',
  '--node', '--node2', '--edge', '--edge-hot',
  '--heat-1', '--heat-2', '--heat-3', '--heat-4', '--heat-5',
  '--plane-1', '--plane-2', '--plane-3', '--plane-4',
  '--font-display', '--font-body', '--font-mono', '--font-voice',
  '--fs', '--fs-scale',
  '--fs-xs', '--fs-sm', '--fs-md', '--fs-lg', '--fs-xl', '--fs-2xl',
  '--display-weight', '--display-tracking',
  '--voice-weight', '--label-weight', '--label-tracking', '--datum-weight', '--datum-tracking',
  '--radius', '--radius-sm', '--border', '--unit',
  '--u1', '--u2', '--u3', '--u4', '--u6', '--u8',
  '--shadow', '--shadow-pane', '--shadow-drawer', '--shadow-modal', '--blur', '--panel-alpha',
  '--stage-curve', '--stage-glow', '--stage-size-fanin',
  '--stage-parallax', '--stage-depth-fog', '--stage-depth-blur'
] as const;

/**
 * The smallest text this interface will render, in px.
 *
 * A scale of 1.22 on a 14px base puts the second step down at 9.4px, and a
 * `code` element inside it at 8.7px — measured, on the shipped build. Below
 * this floor a font stack stops being typography and becomes texture, so the
 * scale is clamped rather than trusted. Themes may make text bigger; nothing
 * can make it smaller than this.
 */
const MIN_TEXT_PX = 11;

function step(base: number, scale: number, n: number): string {
  const raw = base * Math.pow(scale, n);
  return `${Math.max(MIN_TEXT_PX, raw).toFixed(2)}px`;
}

/**
 * `ThemeColors.heat` and `.plane` are comma-separated hex strings, not
 * arrays — see the comment on `heat` in types.ts for why. Splits one into
 * exactly `count` colours, repeating the last one if a hand-edited theme
 * came up short rather than writing `undefined` into a custom property.
 */
function splitRamp(csv: string, count: number): string[] {
  const parts = csv.split(',').map((s) => s.trim()).filter(Boolean);
  const out: string[] = [];
  for (let i = 0; i < count; i++) out.push(parts[i] ?? parts[parts.length - 1] ?? '#888888');
  return out;
}

/**
 * Elevation, read off shipped interfaces rather than invented.
 *
 * MEASURED 2026-08-25 with tools/reference.mjs: Linear's panels carry
 * `rgba(0,0,0,.2) 0 0 0 1px` — a RING, not a drop shadow — plus a stack of
 * near-zero-alpha layers. Raycast layers a 1.5px dark edge with a white inset
 * highlight. Graphite uses `rgba(0,0,0,.25) 0 4px 4px`. None of them use the
 * big soft blur that says "card floating over nothing", which is what this
 * function used to emit at both levels.
 */
/**
 * Extended 2026-08-26 to a four-step scale (card/pane/drawer/modal — see
 * ThemeForm.elevationPane/Drawer/Modal). Levels 0, 1 and 2 are the exact
 * strings this function already emitted; `--shadow` (level 1 or 2 depending
 * on the theme) is unchanged so nothing already reading it moves. Levels 3
 * and 4 extrapolate the same measured idiom — a hairline ring plus a near
 * shadow plus, from level 2 up, a soft far shadow — scaled deeper per level,
 * never the single big blur the comment above warns against.
 */
function shadowFor(elevation: number, base: 'light' | 'dark'): string {
  const lvl = Math.max(0, Math.min(4, Math.round(elevation)));
  if (lvl <= 0) return 'none';
  const dark = base === 'dark';
  if (lvl === 1) {
    return dark
      ? '0 0 0 1px rgba(0,0,0,.45), 0 1px 2px rgba(0,0,0,.4), inset 0 1px 0 rgba(255,255,255,.04)'
      : '0 0 0 1px rgba(0,0,0,.06), 0 1px 2px rgba(0,0,0,.05)';
  }
  if (lvl === 2) {
    return dark
      ? '0 0 0 1px rgba(0,0,0,.5), 0 2px 4px rgba(0,0,0,.4), 0 12px 32px rgba(0,0,0,.35), inset 0 1px 0 rgba(255,255,255,.05)'
      : '0 0 0 1px rgba(0,0,0,.07), 0 2px 6px rgba(0,0,0,.06), 0 10px 28px rgba(0,0,0,.07)';
  }
  if (lvl === 3) {
    return dark
      ? '0 0 0 1px rgba(0,0,0,.55), 0 4px 8px rgba(0,0,0,.45), 0 24px 56px rgba(0,0,0,.4), inset 0 1px 0 rgba(255,255,255,.06)'
      : '0 0 0 1px rgba(0,0,0,.08), 0 4px 10px rgba(0,0,0,.07), 0 20px 44px rgba(0,0,0,.09)';
  }
  return dark
    ? '0 0 0 1px rgba(0,0,0,.6), 0 8px 16px rgba(0,0,0,.5), 0 36px 80px rgba(0,0,0,.45), inset 0 1px 0 rgba(255,255,255,.07)'
    : '0 0 0 1px rgba(0,0,0,.09), 0 6px 14px rgba(0,0,0,.08), 0 30px 64px rgba(0,0,0,.11)';
}

export function applyTheme(theme: ThemeSpec, root: HTMLElement = document.documentElement): void {
  const s = root.style;
  const c = theme.colors;
  const t = theme.type;
  const f = theme.form;

  s.setProperty('--room', c.room);
  s.setProperty('--room2', c.room2);
  s.setProperty('--surface', c.surface);
  s.setProperty('--surface2', c.surface2);
  s.setProperty('--ink', c.ink);
  s.setProperty('--ink2', c.ink2);
  s.setProperty('--ink3', c.ink3);
  s.setProperty('--line', c.line);
  s.setProperty('--line2', c.line2);
  s.setProperty('--accent', c.accent);
  s.setProperty('--accent-ink', c.accentInk);
  s.setProperty('--live', c.live);
  s.setProperty('--bad', c.bad);
  s.setProperty('--ok', c.ok);
  // warn/heat/plane live on ThemeSpec, not ThemeColors — see the comment on
  // ThemeSpec.warn in types.ts. Optional: a theme saved before this field
  // existed falls back to something already guaranteed present, not blank.
  s.setProperty('--warn', theme.warn ?? c.bad);
  s.setProperty('--warn-ink', theme.warnInk ?? c.accentInk);
  s.setProperty('--node', c.node);
  s.setProperty('--node2', c.node2);
  s.setProperty('--edge', c.edge);
  s.setProperty('--edge-hot', c.edgeHot);
  const heat = splitRamp(theme.heat ?? `${c.node2},${c.node2},${c.node2},${c.accent},${c.accent}`, 5);
  s.setProperty('--heat-1', heat[0]);
  s.setProperty('--heat-2', heat[1]);
  s.setProperty('--heat-3', heat[2]);
  s.setProperty('--heat-4', heat[3]);
  s.setProperty('--heat-5', heat[4]);
  const plane = splitRamp(theme.plane ?? `${c.accent},${c.ok},${c.bad},${c.node2}`, 4);
  s.setProperty('--plane-1', plane[0]);
  s.setProperty('--plane-2', plane[1]);
  s.setProperty('--plane-3', plane[2]);
  s.setProperty('--plane-4', plane[3]);

  s.setProperty('--font-display', t.display);
  s.setProperty('--font-body', t.body);
  s.setProperty('--font-mono', t.mono);
  s.setProperty('--font-voice', t.voice ?? t.body);
  s.setProperty('--fs', `${t.size}px`);
  s.setProperty('--fs-scale', String(t.scale));
  s.setProperty('--fs-xs', step(t.size, t.scale, -2));
  s.setProperty('--fs-sm', step(t.size, t.scale, -1));
  s.setProperty('--fs-md', `${Math.max(MIN_TEXT_PX, t.size).toFixed(2)}px`);
  s.setProperty('--fs-lg', step(t.size, t.scale, 1));
  s.setProperty('--fs-xl', step(t.size, t.scale, 2));
  s.setProperty('--fs-2xl', step(t.size, t.scale, 3));
  s.setProperty('--display-weight', String(t.displayWeight));
  s.setProperty('--display-tracking', `${t.displayTracking}em`);
  // The six fields below are optional on ThemeType — see the comment on
  // ThemeType.voice — so a theme saved before they existed still applies.
  s.setProperty('--voice-weight', String(t.voiceWeight ?? 400));
  s.setProperty('--label-weight', String(t.labelWeight ?? t.displayWeight));
  s.setProperty('--label-tracking', `${t.labelTracking ?? 0}em`);
  s.setProperty('--datum-weight', String(t.datumWeight ?? t.displayWeight));
  s.setProperty('--datum-tracking', `${t.datumTracking ?? 0}em`);

  s.setProperty('--radius', `${f.radius}px`);
  s.setProperty('--radius-sm', `${Math.max(0, Math.round(f.radius * 0.5))}px`);
  s.setProperty('--border', `${f.border}px`);
  s.setProperty('--unit', `${f.unit}px`);
  s.setProperty('--u1', `${f.unit * 0.5}px`);
  s.setProperty('--u2', `${f.unit}px`);
  s.setProperty('--u3', `${f.unit * 1.5}px`);
  s.setProperty('--u4', `${f.unit * 2}px`);
  s.setProperty('--u6', `${f.unit * 3}px`);
  s.setProperty('--u8', `${f.unit * 4}px`);
  s.setProperty('--shadow', shadowFor(f.elevation, theme.base));
  // elevationPane/Drawer/Modal are optional on ThemeForm (see the comment on
  // ThemeForm.elevationPane) — fall back to the base `elevation` so a theme
  // saved before the four-step scale existed renders identically at every
  // height rather than losing its shadow.
  s.setProperty('--shadow-pane', shadowFor(f.elevationPane ?? f.elevation, theme.base));
  s.setProperty('--shadow-drawer', shadowFor(f.elevationDrawer ?? f.elevation, theme.base));
  s.setProperty('--shadow-modal', shadowFor(f.elevationModal ?? f.elevation, theme.base));
  s.setProperty('--blur', f.material === 'glass' ? `${f.blur}px` : '0px');
  s.setProperty('--panel-alpha', String(f.alpha));

  s.setProperty('--stage-curve', String(theme.stage.curve));
  s.setProperty('--stage-glow', String(theme.stage.glow));
  s.setProperty('--stage-size-fanin', String(theme.stage.sizeByFanIn));
  // parallax/depthFog/depthBlur are optional on ThemeStage — fall back to
  // "off" so a theme saved before spatial depth existed stays flat rather
  // than erroring.
  s.setProperty('--stage-parallax', String(theme.stage.parallax ?? 0));
  s.setProperty('--stage-depth-fog', String(theme.stage.depthFog ?? 0));
  s.setProperty('--stage-depth-blur', `${theme.stage.depthBlur ?? 0}px`);

  root.dataset.theme = theme.base;
  root.dataset.themeId = theme.id;
  root.dataset.material = f.material;
  root.dataset.chrome = theme.composition.chrome;
  root.dataset.chat = theme.composition.chat;
  root.dataset.stage = theme.stage.layout;
  root.dataset.glyph = theme.stage.glyph;
  root.dataset.serif = t.displaySerif ? 'yes' : 'no';
  root.style.colorScheme = theme.base;
}

/** Remove every variable this module owns — used by tests and the hard reset. */
export function clearTheme(root: HTMLElement = document.documentElement): void {
  THEME_VARS.forEach((v) => root.style.removeProperty(v));
}
