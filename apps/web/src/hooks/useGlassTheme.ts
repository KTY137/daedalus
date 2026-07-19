import { useCallback, useEffect, useState } from 'react';
import type { Theme } from './useTheme';

/**
 * Live liquid-glass material settings. These write CSS custom properties onto
 * <html> so the whole OS re-skins in real time, and persist to localStorage
 * (key `daedalus-glass`). Ported from the Daedalus glass preview mock.
 */
export interface GlassSettings {
  blur: number;
  sat: number;
  diff: number;
  alpha: number;
  rad: number;
  accent: string;
  scene: string;
}

export const GLASS_DEFAULTS: GlassSettings = {
  blur: 22,
  sat: 180,
  diff: 14,
  alpha: 55,
  rad: 20,
  accent: '',
  scene: ''
};

export const GLASS_ACCENTS = ['', '#0a84ff', '#6aa8ff', '#5fd6a0', '#c15fff', '#ff6b8b', '#ffb020', '#22d3ee'];

interface SceneTone {
  a: string;
  b: string;
  c: string;
  s1: string;
  s2: string;
}
export interface SceneDef {
  d: SceneTone;
  l: SceneTone;
}

export const GLASS_SCENES: Record<string, SceneDef> = {
  aurora: {
    d: { a: 'rgba(88,166,255,.22)', b: 'rgba(180,120,255,.18)', c: 'rgba(60,200,180,.15)', s1: '#0b1220', s2: '#131a2e' },
    l: { a: 'rgba(120,160,255,.34)', b: 'rgba(200,150,255,.26)', c: 'rgba(120,220,200,.22)', s1: '#eef1f7', s2: '#e6ebff' }
  },
  dusk: {
    d: { a: 'rgba(255,120,150,.20)', b: 'rgba(255,170,90,.16)', c: 'rgba(150,90,255,.18)', s1: '#160f1e', s2: '#241522' },
    l: { a: 'rgba(255,150,170,.32)', b: 'rgba(255,190,120,.26)', c: 'rgba(180,130,255,.22)', s1: '#faf1ee', s2: '#ffe9ea' }
  },
  abyss: {
    d: { a: 'rgba(60,220,200,.18)', b: 'rgba(80,140,255,.16)', c: 'rgba(40,90,140,.16)', s1: '#05090f', s2: '#0a1420' },
    l: { a: 'rgba(80,210,200,.30)', b: 'rgba(120,170,255,.24)', c: 'rgba(150,220,230,.22)', s1: '#eef4f6', s2: '#e2eef2' }
  },
  mono: {
    d: { a: 'rgba(255,255,255,.06)', b: 'rgba(255,255,255,.05)', c: 'rgba(255,255,255,.04)', s1: '#0e0f12', s2: '#16181d' },
    l: { a: 'rgba(0,0,0,.05)', b: 'rgba(0,0,0,.04)', c: 'rgba(0,0,0,.03)', s1: '#f4f5f7', s2: '#e9eaee' }
  }
};

export const GLASS_SCENE_LIST: Array<[string, string]> = [
  ['', 'Default'],
  ['aurora', 'Aurora'],
  ['dusk', 'Dusk'],
  ['abyss', 'Abyss'],
  ['mono', 'Mono']
];

const LS_KEY = 'daedalus-glass';
const SCENE_VARS = ['--mesh-a', '--mesh-b', '--mesh-c', '--scene-1', '--scene-2'];

function loadSettings(): GlassSettings {
  try {
    const raw = localStorage.getItem(LS_KEY);
    const parsed = raw ? (JSON.parse(raw) as Partial<GlassSettings>) : null;
    return { ...GLASS_DEFAULTS, ...(parsed || {}) };
  } catch {
    return { ...GLASS_DEFAULTS };
  }
}

function persistSettings(settings: GlassSettings) {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(settings));
  } catch {
    /* private mode / storage disabled — settings still apply for the session */
  }
}

function applyScene(settings: GlassSettings, theme: Theme) {
  const root = document.documentElement;
  if (!settings.scene) {
    SCENE_VARS.forEach((key) => root.style.removeProperty(key));
    return;
  }
  const scene = GLASS_SCENES[settings.scene];
  if (!scene) return;
  const tone = theme === 'dark' ? scene.d : scene.l;
  root.style.setProperty('--mesh-a', tone.a);
  root.style.setProperty('--mesh-b', tone.b);
  root.style.setProperty('--mesh-c', tone.c);
  root.style.setProperty('--scene-1', tone.s1);
  root.style.setProperty('--scene-2', tone.s2);
}

function applyGlass(settings: GlassSettings, theme: Theme) {
  const root = document.documentElement;
  root.style.setProperty('--blur', `${settings.blur}px`);
  root.style.setProperty('--sat', `${settings.sat}%`);
  root.style.setProperty('--diffraction', (settings.diff / 100).toFixed(3));
  root.style.setProperty('--glass-alpha', (settings.alpha / 100).toFixed(3));
  root.style.setProperty('--r-lg', `${settings.rad}px`);
  root.style.setProperty('--r-xl', `${settings.rad + 6}px`);
  if (settings.accent) {
    root.style.setProperty('--accent', settings.accent);
  } else {
    root.style.removeProperty('--accent');
  }
  applyScene(settings, theme);
}

export function useGlassTheme(theme: Theme) {
  const [settings, setSettings] = useState<GlassSettings>(loadSettings);

  // Apply + persist whenever the settings change, and re-apply the scene when
  // the light/dark theme flips (scenes carry per-theme tones).
  useEffect(() => {
    applyGlass(settings, theme);
    persistSettings(settings);
  }, [settings, theme]);

  const update = useCallback((patch: Partial<GlassSettings>) => {
    setSettings((prev) => ({ ...prev, ...patch }));
  }, []);

  const reset = useCallback(() => setSettings({ ...GLASS_DEFAULTS }), []);

  return { settings, update, reset };
}
