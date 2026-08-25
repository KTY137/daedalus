import { BUILT_INS, BUILT_IN_IDS, DEFAULT_THEME_ID, builtIn } from './presets';
import type { StoredTheme, ThemeSpec } from './types';

/**
 * Where themes live.
 *
 * Built-ins are code. Everything the owner makes is one JSON object under
 * `daedalus-themes`, and the current selection is a separate key so switching
 * themes never rewrites the whole catalogue.
 *
 * Reads are defensive but never silent. A stored theme that no longer matches
 * the shape (an older export, a hand-edited file) is repaired by filling the
 * missing fields from its origin built-in, and the repair is REPORTED through
 * `loadCatalogue().problems` so the Studio can say "three fields were missing
 * and came from Kammer" instead of quietly showing a different design than the
 * one that was saved.
 */

const THEMES_KEY = 'daedalus-themes';
const CURRENT_KEY = 'daedalus-theme-id';

export interface CatalogueProblem {
  id: string;
  message: string;
}

export interface Catalogue {
  builtIns: ThemeSpec[];
  custom: StoredTheme[];
  problems: CatalogueProblem[];
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

/**
 * Fill a partial theme from a base, recording every field that had to be
 * borrowed. One level of nesting is all a ThemeSpec has, so this is written
 * out rather than made generic — a generic deep-merge would happily accept a
 * string where a number belongs.
 */
function repair(
  raw: Record<string, unknown>,
  base: ThemeSpec,
  missing: string[]
): ThemeSpec {
  const pick = <T,>(group: string, key: string, fallback: T, kind: 'string' | 'number' | 'boolean'): T => {
    const g = raw[group];
    if (isRecord(g) && typeof g[key] === kind) return g[key] as T;
    missing.push(`${group}.${key}`);
    return fallback;
  };
  const top = <T,>(key: string, fallback: T, kind: 'string' | 'number'): T => {
    if (typeof raw[key] === kind) return raw[key] as T;
    missing.push(key);
    return fallback;
  };
  /**
   * An enum field is not "a string". `material: "banana"` passes a typeof
   * check and then reaches CSS as a data attribute no stylesheet answers, so
   * the panel silently loses its material. Unknown values fall back to the
   * base and are reported like a missing field.
   */
  const one = <T extends string>(group: string, key: string, allowed: readonly T[], fallback: T): T => {
    const g = raw[group];
    const v = isRecord(g) ? g[key] : undefined;
    if (typeof v === 'string' && (allowed as readonly string[]).includes(v)) return v as T;
    missing.push(`${group}.${key}`);
    return fallback;
  };

  const colorKeys = Object.keys(base.colors) as Array<keyof ThemeSpec['colors']>;
  const colors = {} as ThemeSpec['colors'];
  colorKeys.forEach((k) => {
    colors[k] = pick('colors', k, base.colors[k], 'string');
  });

  return {
    id: top('id', base.id, 'string'),
    name: top('name', base.name, 'string'),
    note: top('note', base.note, 'string'),
    base: raw.base === 'light' || raw.base === 'dark' ? raw.base : base.base,
    origin: top('origin', base.origin, 'string'),
    colors,
    type: {
      display: pick('type', 'display', base.type.display, 'string'),
      body: pick('type', 'body', base.type.body, 'string'),
      mono: pick('type', 'mono', base.type.mono, 'string'),
      size: pick('type', 'size', base.type.size, 'number'),
      scale: pick('type', 'scale', base.type.scale, 'number'),
      displayWeight: pick('type', 'displayWeight', base.type.displayWeight, 'number'),
      displayTracking: pick('type', 'displayTracking', base.type.displayTracking, 'number'),
      displaySerif: pick('type', 'displaySerif', base.type.displaySerif, 'boolean')
    },
    form: {
      radius: pick('form', 'radius', base.form.radius, 'number'),
      border: pick('form', 'border', base.form.border, 'number'),
      unit: pick('form', 'unit', base.form.unit, 'number'),
      elevation: pick('form', 'elevation', base.form.elevation, 'number'),
      material: one('form', 'material', ['flat', 'glass', 'paper'] as const, base.form.material),
      blur: pick('form', 'blur', base.form.blur, 'number'),
      alpha: pick('form', 'alpha', base.form.alpha, 'number')
    },
    stage: {
      layout: one('stage', 'layout', ['forest', 'stars', 'cards', 'arcs'] as const, base.stage.layout),
      glyph: one('stage', 'glyph', ['pearl', 'disc', 'star', 'card'] as const, base.stage.glyph),
      backboneOnly: pick('stage', 'backboneOnly', base.stage.backboneOnly, 'boolean'),
      curve: pick('stage', 'curve', base.stage.curve, 'number'),
      sizeByFanIn: pick('stage', 'sizeByFanIn', base.stage.sizeByFanIn, 'number'),
      glow: pick('stage', 'glow', base.stage.glow, 'number')
    },
    composition: {
      chrome: one('composition', 'chrome', ['bar', 'rail', 'masthead'] as const, base.composition.chrome),
      chat: one('composition', 'chat', ['card', 'drawer', 'column', 'flow'] as const, base.composition.chat),
      decision: one('composition', 'decision', ['float', 'bar', 'inline'] as const, base.composition.decision)
    }
  };
}

export function loadCatalogue(): Catalogue {
  const problems: CatalogueProblem[] = [];
  let custom: StoredTheme[] = [];

  let raw: string | null = null;
  try {
    raw = localStorage.getItem(THEMES_KEY);
  } catch {
    problems.push({ id: '*', message: 'Browserspeicher ist gesperrt — eigene Themes gelten nur für diese Sitzung.' });
  }

  if (raw) {
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      problems.push({ id: '*', message: 'Die gespeicherten Themes sind kein gültiges JSON. Sie wurden nicht geladen und nicht gelöscht.' });
      parsed = null;
    }
    if (Array.isArray(parsed)) {
      parsed.forEach((entry, i) => {
        if (!isRecord(entry)) {
          problems.push({ id: `#${i}`, message: 'Eintrag ist kein Objekt und wurde übersprungen.' });
          return;
        }
        const from = typeof entry.forkedFrom === 'string' ? entry.forkedFrom : DEFAULT_THEME_ID;
        const base = builtIn(from) || builtIn(DEFAULT_THEME_ID)!;
        const missing: string[] = [];
        const spec = repair(entry, base, missing);
        if (missing.length) {
          problems.push({
            id: spec.id,
            message: `${missing.length} Feld(er) fehlten und kamen aus ${base.name}: ${missing.slice(0, 6).join(', ')}${missing.length > 6 ? ' …' : ''}`
          });
        }
        custom.push({
          ...spec,
          forkedFrom: from,
          editedAt: typeof entry.editedAt === 'number' ? entry.editedAt : 0
        });
      });
    } else if (parsed !== null) {
      problems.push({ id: '*', message: 'Die gespeicherten Themes sind keine Liste. Sie wurden nicht geladen.' });
    }
  }

  // A custom theme may not shadow a built-in id: the built-in must always stay
  // reachable as the reference the fork came from.
  custom = custom.filter((t) => {
    if (BUILT_IN_IDS.has(t.id)) {
      problems.push({ id: t.id, message: `Gespeichertes Theme trägt die id eines eingebauten Themes und wurde nicht geladen.` });
      return false;
    }
    return true;
  });

  return { builtIns: BUILT_INS, custom, problems };
}

export function saveCustom(themes: StoredTheme[]): { ok: boolean; error?: string } {
  try {
    localStorage.setItem(THEMES_KEY, JSON.stringify(themes));
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : 'Speichern nicht möglich.' };
  }
}

export function loadCurrentId(): string {
  try {
    return localStorage.getItem(CURRENT_KEY) || DEFAULT_THEME_ID;
  } catch {
    return DEFAULT_THEME_ID;
  }
}

export function saveCurrentId(id: string): void {
  try {
    localStorage.setItem(CURRENT_KEY, id);
  } catch {
    /* storage blocked — the choice still applies for this session */
  }
}

/** A url-safe, unique id derived from a name. */
export function makeId(name: string, taken: Set<string>): string {
  const stem =
    name
      .toLowerCase()
      .normalize('NFD')
      .replace(/[̀-ͯ]/g, '')
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 32) || 'theme';
  if (!taken.has(stem)) return stem;
  for (let n = 2; n < 999; n += 1) {
    const candidate = `${stem}-${n}`;
    if (!taken.has(candidate)) return candidate;
  }
  return `${stem}-${Date.now()}`;
}

/** Fork a theme into an editable copy. */
export function fork(source: ThemeSpec, taken: Set<string>, name?: string): StoredTheme {
  const nextName = name || `${source.name} (Kopie)`;
  return {
    ...structuredClone(source),
    id: makeId(nextName, taken),
    name: nextName,
    origin: 'custom',
    forkedFrom: source.id,
    editedAt: Date.now()
  };
}

export function exportThemes(themes: ThemeSpec[]): string {
  return JSON.stringify({ kind: 'daedalus-themes', version: 1, themes }, null, 2);
}

export interface ImportResult {
  themes: ThemeSpec[];
  problems: CatalogueProblem[];
}

/** Parse an export back. Never throws; problems are returned, not swallowed. */
export function importThemes(text: string): ImportResult {
  const problems: CatalogueProblem[] = [];
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch (e) {
    return { themes: [], problems: [{ id: '*', message: `Kein gültiges JSON: ${e instanceof Error ? e.message : 'unbekannt'}` }] };
  }
  const list = isRecord(parsed) && Array.isArray(parsed.themes)
    ? parsed.themes
    : Array.isArray(parsed)
      ? parsed
      : null;
  if (!list) {
    return { themes: [], problems: [{ id: '*', message: 'Erwartet wurde eine Liste von Themes oder ein Export mit dem Feld "themes".' }] };
  }
  const themes: ThemeSpec[] = [];
  list.forEach((entry, i) => {
    if (!isRecord(entry)) {
      problems.push({ id: `#${i}`, message: 'Eintrag ist kein Objekt.' });
      return;
    }
    const from = typeof entry.forkedFrom === 'string' ? entry.forkedFrom : DEFAULT_THEME_ID;
    const base = builtIn(from) || builtIn(DEFAULT_THEME_ID)!;
    const missing: string[] = [];
    const spec = repair(entry, base, missing);
    if (missing.length) {
      problems.push({ id: spec.id, message: `${missing.length} Feld(er) fehlten und kamen aus ${base.name}.` });
    }
    themes.push(spec);
  });
  return { themes, problems };
}
