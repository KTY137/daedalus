/* What the room knows.
 *
 * Per-project state is kept per project, never shared: switching projects must
 * not carry Daedalus's selection, thread, slice or spend into a project that
 * has no compiled index. fakedata.cjs drives the built app and refuses the
 * build if any of that leaks. */

import {
  createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode,
} from 'react';
import {
  allEdges, answerFor, loadFixture, urlState,
  type ChatMsg, type Depth, type Fixture, type Lens, type ViewMode,
} from './data';
import type { CamView } from './room/Scene';

export type MotionPref = 'Full' | 'Calm' | 'Off';
export type Overlay = 'palette' | 'library' | 'settings' | null;

export interface Prefs {
  route: string;
  localMayLeave: boolean;
  ceiling: number;
  rememberAcross: boolean;
  doNotRemember: boolean;
  retention: string;
  motion: MotionPref;
  killArmed: boolean;
}

const STORE_KEY = 'aurora.prefs.v1';
const sentence = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

function defaults(fx: Fixture): Prefs {
  return {
    route: fx.settings.route,
    localMayLeave: fx.settings.local_may_leave_machine,
    ceiling: fx.settings.spending_ceiling_usd,
    rememberAcross: fx.settings.memory.remember_across_sessions,
    doNotRemember: fx.settings.memory.do_not_remember_this_project,
    retention: sentence(fx.settings.memory.retention),
    motion: fx.settings.appearance.motion as MotionPref,
    killArmed: fx.rim.kill_switch === 'armed',
  };
}

function readStored(): Partial<Prefs> | null {
  try {
    const raw = window.localStorage.getItem(STORE_KEY);
    return raw ? (JSON.parse(raw) as Partial<Prefs>) : null;
  } catch { return null; }
}

export interface PState {
  selected: string | null;
  hovered: string | null;
  lens: Lens;
  chat: ChatMsg[];
  view: ViewMode;
  camView: CamView;
  depth: Depth;
  decision: 'approved' | 'rejected' | null;
  asking: boolean;      // the decision paragraph is on screen
  resetReq: number;
}

export interface Reason { text: string }

export interface Api {
  fx: Fixture;
  prefs: Prefs;
  setPrefs: (p: Partial<Prefs>) => void;
  motionOn: boolean;
  projectId: string;
  setProjectId: (id: string) => void;
  ps: PState;
  patch: (p: Partial<PState>) => void;
  overlay: Overlay;
  setOverlay: (o: Overlay) => void;
  screen: 'cockpit' | 'library';
  setScreen: (s: 'cockpit' | 'library') => void;
  streaming: boolean;
  reason: Reason | null;
  setReason: (r: Reason | null) => void;
  libPage: string;
  setLibPage: (p: string) => void;
  say: (m: ChatMsg) => void;
  ask: (text: string) => void;
  seed: string;
  setSeed: (s: string) => void;
}

const Ctx = createContext<Api | null>(null);
export const useApp = () => {
  const v = useContext(Ctx);
  if (!v) throw new Error('no app context');
  return v;
};

export function AppProvider({ children }: { children: (api: Api) => ReactNode }) {
  const url = useRef(urlState()).current;
  const [fx, setFx] = useState<Fixture | null>(null);
  const [prefs, setPrefsState] = useState<Prefs | null>(null);
  const [overlay, setOverlay] = useState<Overlay>(url.overlay);
  const [screen, setScreen] = useState<'cockpit' | 'library'>('cockpit');
  const [reason, setReason] = useState<Reason | null>(null);
  const [projectId, setProjectId] = useState('');
  const [pmap, setPmap] = useState<Record<string, PState>>({});
  const [libPage, setLibPage] = useState('');
  const [seed, setSeed] = useState('');
  const [stream, setStream] = useState<{ pid: string; full: string; shown: number } | null>(null);
  const [systemReduced, setSystemReduced] = useState(false);

  useEffect(() => {
    loadFixture().then(f => {
      setFx(f);
      setPrefsState({ ...defaults(f), ...(readStored() || {}) });
      const active = f.projects.find(p => p.active) || f.projects[0];
      setProjectId(active.id);
      setPmap(Object.fromEntries(f.projects.map(p => [p.id, {
        selected: p.id === f.project && url.state === 'selected' ? 'c5' : null,
        hovered: null,
        lens: 'structure' as Lens,
        chat: p.id === f.project ? f.chat : [],
        view: (url.state === 'ordered' ? 'ordered' : 'spatial') as ViewMode,
        camView: (url.state === 'ordered' ? 'flat' : 'room') as CamView,
        depth: 1 as Depth,
        decision: null,
        asking: p.id === f.project && url.state === 'decision',
        resetReq: 0,
      }])));
      setLibPage(f.library.project_wiki[0]?.path || '');
    });
  }, [url]);

  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    const on = () => setSystemReduced(mq.matches);
    on(); mq.addEventListener('change', on);
    return () => mq.removeEventListener('change', on);
  }, []);

  const setPrefs = useCallback((p: Partial<Prefs>) => {
    setPrefsState(prev => {
      if (!prev) return prev;
      const next = { ...prev, ...p };
      try { window.localStorage.setItem(STORE_KEY, JSON.stringify(next)); } catch { /* private mode */ }
      return next;
    });
  }, []);

  const patch = useCallback((p: Partial<PState>) => {
    setPmap(prev => (projectId && prev[projectId] ? { ...prev, [projectId]: { ...prev[projectId], ...p } } : prev));
  }, [projectId]);

  const say = useCallback((m: ChatMsg) => {
    setPmap(prev => (projectId && prev[projectId]
      ? { ...prev, [projectId]: { ...prev[projectId], chat: [...prev[projectId].chat, m] } }
      : prev));
  }, [projectId]);

  const timer = useRef<number | null>(null);
  /* The answer comes out of the compiled index, or it is the honest sentence
     saying that nothing is connected. It arrives word by word, because that is
     what a thing that is thinking looks like — not because streaming is
     decorative. An unindexed project can answer nothing at all, and says so. */
  const ask = useCallback((text: string) => {
    const pid = projectId;
    const reply: ChatMsg = fx && pid === fx.project
      ? answerFor(fx, allEdges(fx), text)
      : { role: 'system', text: 'This project has no compiled index, so there is nothing here to answer from.' };
    setPmap(prev => ({
      ...prev,
      [pid]: {
        ...prev[pid],
        chat: [...prev[pid].chat, { role: 'owner', text } as ChatMsg, { ...reply, text: '' } as ChatMsg],
      },
    }));
    setStream({ pid, full: reply.text, shown: 0 });
  }, [projectId, fx]);

  const motionLevel: MotionPref = systemReduced ? 'Off' : (prefs?.motion ?? 'Calm');
  const motionOn = motionLevel !== 'Off';

  useEffect(() => {
    if (!stream) return;
    const words = stream.full.split(' ');
    if (stream.shown >= words.length) { setStream(null); return; }
    const step = motionLevel === 'Off' ? 0 : 26;
    const advance = () => {
      const shown = motionLevel === 'Off' ? words.length : stream.shown + 1;
      setPmap(prev => {
        const p = prev[stream.pid];
        if (!p) return prev;
        const chat = [...p.chat];
        chat[chat.length - 1] = { ...chat[chat.length - 1], text: words.slice(0, shown).join(' ') };
        return { ...prev, [stream.pid]: { ...p, chat } };
      });
      setStream(s => (s ? { ...s, shown } : null));
    };
    if (step === 0) { advance(); return; }
    timer.current = window.setTimeout(advance, step);
    return () => { if (timer.current) window.clearTimeout(timer.current); };
  }, [stream, motionLevel]);

  useEffect(() => {
    if (!prefs) return;
    document.documentElement.dataset.motion = motionLevel.toLowerCase();
  }, [prefs, motionLevel]);

  if (!fx || !prefs || !projectId || !pmap[projectId]) return null;

  const api: Api = {
    fx, prefs, setPrefs, motionOn,
    screen, setScreen,
    /* the caret belongs to a sentence still arriving, not to the tick in which
       the last word landed */
    streaming: !!stream && stream.shown < stream.full.split(' ').length,
    projectId,
    setProjectId: id => { setProjectId(id); setOverlay(null); },
    ps: pmap[projectId], patch,
    overlay, setOverlay, reason, setReason,
    libPage, setLibPage,
    say, ask, seed, setSeed,
  };
  return <Ctx.Provider value={api}>{children(api)}</Ctx.Provider>;
}
