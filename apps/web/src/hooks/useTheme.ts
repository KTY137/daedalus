import { useCallback, useEffect, useState } from 'react';

export type Theme = 'light' | 'dark';

function currentTheme(): Theme {
  const attr = document.documentElement.dataset.theme;
  return attr === 'light' ? 'light' : 'dark';
}

/**
 * Reads/writes the `data-theme` attribute on <html> that index.html seeds
 * before first paint. The choice is persisted so it survives reloads and is
 * shared with the no-FOUC bootstrap script.
 */
export function useTheme(): { theme: Theme; toggle: () => void; set: (t: Theme) => void } {
  const [theme, setThemeState] = useState<Theme>(currentTheme);

  const set = useCallback((next: Theme) => {
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem('daedalus-theme', next);
    } catch {
      /* private mode / storage disabled — attribute still applies for the session */
    }
    setThemeState(next);
  }, []);

  const toggle = useCallback(() => set(currentTheme() === 'dark' ? 'light' : 'dark'), [set]);

  // Keep in sync if the attribute is changed elsewhere (e.g. another tab).
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === 'daedalus-theme' && (e.newValue === 'light' || e.newValue === 'dark')) {
        document.documentElement.dataset.theme = e.newValue;
        setThemeState(e.newValue);
      }
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  return { theme, toggle, set };
}
