import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { applyTheme } from './apply';
import { BUILT_IN_IDS, DEFAULT_THEME_ID, builtIn } from './presets';
import {
  exportThemes,
  fork,
  importThemes,
  loadCatalogue,
  loadCurrentId,
  saveCurrentId,
  saveCustom,
  type CatalogueProblem
} from './store';
import type { StoredTheme, ThemeSpec } from './types';

/**
 * One active theme, a catalogue of the rest, and the operations the Studio
 * needs. Editing a BUILT-IN theme forks it first, automatically and visibly —
 * a design that shipped as a reference must stay recoverable, and "you cannot
 * edit this one" is a worse answer than "here is your copy of it".
 */

export interface ThemeApi {
  theme: ThemeSpec;
  builtIns: ThemeSpec[];
  custom: StoredTheme[];
  problems: CatalogueProblem[];
  /** true while the active theme is a read-only built-in */
  isBuiltIn: boolean;
  select: (id: string) => void;
  /** patch the active theme; forks a built-in on first edit and returns the id in use */
  update: (patch: DeepPartial<ThemeSpec>) => string;
  rename: (id: string, name: string) => void;
  remove: (id: string) => void;
  duplicate: (id: string, name?: string) => string;
  /** throw away a fork's edits and return to the built-in it came from */
  revert: (id: string) => void;
  exportAll: () => string;
  exportOne: (id: string) => string;
  importText: (text: string) => { added: number; problems: CatalogueProblem[] };
  /** last write error, e.g. storage full or blocked */
  saveError: string;
}

export type DeepPartial<T> = { [K in keyof T]?: T[K] extends object ? Partial<T[K]> : T[K] };

const ThemeContext = createContext<ThemeApi | null>(null);

function mergeSpec(base: ThemeSpec, patch: DeepPartial<ThemeSpec>): ThemeSpec {
  return {
    ...base,
    ...(patch as Partial<ThemeSpec>),
    colors: { ...base.colors, ...(patch.colors || {}) },
    type: { ...base.type, ...(patch.type || {}) },
    form: { ...base.form, ...(patch.form || {}) },
    stage: { ...base.stage, ...(patch.stage || {}) },
    composition: { ...base.composition, ...(patch.composition || {}) }
  };
}

/**
 * The catalogue write coalesces the same way the old glass editor's did: a
 * colour picker fires on every frame of a drag, and localStorage is
 * synchronous. Application is per-frame (that IS the live preview); the write
 * lands once the knob stops, and is flushed on pagehide.
 */
const PERSIST_IDLE_MS = 250;

export function ThemeProvider({ children }: { children: ReactNode }) {
  const initial = useMemo(() => loadCatalogue(), []);
  const [custom, setCustom] = useState<StoredTheme[]>(initial.custom);
  const [problems, setProblems] = useState<CatalogueProblem[]>(initial.problems);
  const [currentId, setCurrentId] = useState<string>(() => loadCurrentId());
  const [saveError, setSaveError] = useState('');

  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pending = useRef<StoredTheme[] | null>(null);

  const flush = useCallback(() => {
    if (timer.current !== null) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    if (pending.current) {
      const result = saveCustom(pending.current);
      setSaveError(result.ok ? '' : result.error || 'Speichern nicht möglich.');
      pending.current = null;
    }
  }, []);

  const persist = useCallback(
    (next: StoredTheme[]) => {
      pending.current = next;
      if (timer.current !== null) clearTimeout(timer.current);
      timer.current = setTimeout(flush, PERSIST_IDLE_MS);
    },
    [flush]
  );

  useEffect(() => {
    window.addEventListener('pagehide', flush);
    return () => {
      window.removeEventListener('pagehide', flush);
      flush();
    };
  }, [flush]);

  const commit = useCallback(
    (next: StoredTheme[]) => {
      setCustom(next);
      persist(next);
    },
    [persist]
  );

  const theme = useMemo<ThemeSpec>(() => {
    const found = custom.find((t) => t.id === currentId) || builtIn(currentId);
    return found || builtIn(DEFAULT_THEME_ID)!;
  }, [custom, currentId]);

  // Application is unconditional: every variable is rewritten on every change,
  // so a theme that omits what the previous one set cannot inherit it.
  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const takenIds = useCallback(
    () => new Set<string>([...BUILT_IN_IDS, ...custom.map((t) => t.id)]),
    [custom]
  );

  const select = useCallback((id: string) => {
    setCurrentId(id);
    saveCurrentId(id);
  }, []);

  const update = useCallback(
    (patch: DeepPartial<ThemeSpec>): string => {
      const active = custom.find((t) => t.id === currentId);
      if (active) {
        const next = custom.map((t) => (t.id === currentId ? { ...mergeSpec(t, patch), forkedFrom: t.forkedFrom, editedAt: Date.now() } : t));
        commit(next);
        return currentId;
      }
      // Editing a built-in forks it, and the fork becomes the selection.
      const source = builtIn(currentId) || builtIn(DEFAULT_THEME_ID)!;
      const copy = fork(source, takenIds(), `${source.name} — meins`);
      const edited: StoredTheme = { ...mergeSpec(copy, patch), id: copy.id, forkedFrom: source.id, editedAt: Date.now() };
      commit([...custom, edited]);
      setCurrentId(edited.id);
      saveCurrentId(edited.id);
      return edited.id;
    },
    [commit, currentId, custom, takenIds]
  );

  const rename = useCallback(
    (id: string, name: string) => {
      commit(custom.map((t) => (t.id === id ? { ...t, name: name.trim() || t.name, editedAt: Date.now() } : t)));
    },
    [commit, custom]
  );

  const remove = useCallback(
    (id: string) => {
      const gone = custom.find((t) => t.id === id);
      const next = custom.filter((t) => t.id !== id);
      commit(next);
      if (currentId === id) select(gone?.forkedFrom && (BUILT_IN_IDS.has(gone.forkedFrom) || next.some((t) => t.id === gone.forkedFrom)) ? gone.forkedFrom : DEFAULT_THEME_ID);
    },
    [commit, currentId, custom, select]
  );

  const duplicate = useCallback(
    (id: string, name?: string): string => {
      const source = custom.find((t) => t.id === id) || builtIn(id);
      if (!source) return currentId;
      const copy = fork(source, takenIds(), name);
      commit([...custom, copy]);
      select(copy.id);
      return copy.id;
    },
    [commit, currentId, custom, select, takenIds]
  );

  const revert = useCallback(
    (id: string) => {
      const target = custom.find((t) => t.id === id);
      if (!target?.forkedFrom) return;
      const source = builtIn(target.forkedFrom);
      if (!source) return;
      commit(
        custom.map((t) =>
          t.id === id
            ? { ...structuredClone(source), id: t.id, name: t.name, origin: 'custom', forkedFrom: t.forkedFrom, editedAt: Date.now() }
            : t
        )
      );
    },
    [commit, custom]
  );

  const importText = useCallback(
    (text: string) => {
      const result = importThemes(text);
      if (!result.themes.length) {
        setProblems(result.problems);
        return { added: 0, problems: result.problems };
      }
      const taken = takenIds();
      const added: StoredTheme[] = [];
      result.themes.forEach((spec) => {
        const copy = fork(spec, taken, spec.name);
        taken.add(copy.id);
        added.push(copy);
      });
      commit([...custom, ...added]);
      setProblems(result.problems);
      if (added.length) select(added[0].id);
      return { added: added.length, problems: result.problems };
    },
    [commit, custom, select, takenIds]
  );

  const api = useMemo<ThemeApi>(
    () => ({
      theme,
      builtIns: initial.builtIns,
      custom,
      problems,
      isBuiltIn: BUILT_IN_IDS.has(theme.id),
      select,
      update,
      rename,
      remove,
      duplicate,
      revert,
      exportAll: () => exportThemes([...custom]),
      exportOne: (id: string) => {
        const one = custom.find((t) => t.id === id) || builtIn(id);
        return one ? exportThemes([one]) : '';
      },
      importText,
      saveError
    }),
    [theme, initial.builtIns, custom, problems, select, update, rename, remove, duplicate, revert, importText, saveError]
  );

  return <ThemeContext.Provider value={api}>{children}</ThemeContext.Provider>;
}

export function useThemes(): ThemeApi {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useThemes must be used inside <ThemeProvider>');
  return ctx;
}
