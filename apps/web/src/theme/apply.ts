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
  '--live', '--bad', '--ok',
  '--node', '--node2', '--edge', '--edge-hot',
  '--font-display', '--font-body', '--font-mono',
  '--fs', '--fs-scale',
  '--fs-xs', '--fs-sm', '--fs-md', '--fs-lg', '--fs-xl', '--fs-2xl',
  '--display-weight', '--display-tracking',
  '--radius', '--radius-sm', '--border', '--unit',
  '--u1', '--u2', '--u3', '--u4', '--u6', '--u8',
  '--shadow', '--blur', '--panel-alpha',
  '--stage-curve', '--stage-glow', '--stage-size-fanin'
] as const;

function step(base: number, scale: number, n: number): string {
  return `${(base * Math.pow(scale, n)).toFixed(2)}px`;
}

function shadowFor(elevation: number, base: 'light' | 'dark'): string {
  if (elevation <= 0) return 'none';
  const dark = base === 'dark';
  if (elevation === 1) {
    return dark
      ? '0 1px 2px rgba(0,0,0,.5), 0 6px 18px rgba(0,0,0,.35)'
      : '0 1px 2px rgba(0,0,0,.06), 0 4px 14px rgba(0,0,0,.07)';
  }
  return dark
    ? '0 2px 6px rgba(0,0,0,.55), 0 20px 60px rgba(0,0,0,.5)'
    : '0 2px 6px rgba(0,0,0,.08), 0 18px 48px rgba(0,0,0,.12)';
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
  s.setProperty('--node', c.node);
  s.setProperty('--node2', c.node2);
  s.setProperty('--edge', c.edge);
  s.setProperty('--edge-hot', c.edgeHot);

  s.setProperty('--font-display', t.display);
  s.setProperty('--font-body', t.body);
  s.setProperty('--font-mono', t.mono);
  s.setProperty('--fs', `${t.size}px`);
  s.setProperty('--fs-scale', String(t.scale));
  s.setProperty('--fs-xs', step(t.size, t.scale, -2));
  s.setProperty('--fs-sm', step(t.size, t.scale, -1));
  s.setProperty('--fs-md', `${t.size}px`);
  s.setProperty('--fs-lg', step(t.size, t.scale, 1));
  s.setProperty('--fs-xl', step(t.size, t.scale, 2));
  s.setProperty('--fs-2xl', step(t.size, t.scale, 3));
  s.setProperty('--display-weight', String(t.displayWeight));
  s.setProperty('--display-tracking', `${t.displayTracking}em`);

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
  s.setProperty('--blur', f.material === 'glass' ? `${f.blur}px` : '0px');
  s.setProperty('--panel-alpha', String(f.alpha));

  s.setProperty('--stage-curve', String(theme.stage.curve));
  s.setProperty('--stage-glow', String(theme.stage.glow));
  s.setProperty('--stage-size-fanin', String(theme.stage.sizeByFanIn));

  root.dataset.theme = theme.base;
  root.dataset.themeId = theme.id;
  root.dataset.material = f.material;
  root.dataset.chrome = theme.composition.chrome;
  root.dataset.chat = theme.composition.chat;
  root.dataset.decision = theme.composition.decision;
  root.dataset.stage = theme.stage.layout;
  root.dataset.glyph = theme.stage.glyph;
  root.dataset.serif = t.displaySerif ? 'yes' : 'no';
  root.style.colorScheme = theme.base;
}

/** Remove every variable this module owns — used by tests and the hard reset. */
export function clearTheme(root: HTMLElement = document.documentElement): void {
  THEME_VARS.forEach((v) => root.style.removeProperty(v));
}
