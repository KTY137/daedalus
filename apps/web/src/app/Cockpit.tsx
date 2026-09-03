import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import {
  getGovernance,
  getHealth,
  getProjects,
  getStructure,
  getTopology,
  isBackendDown,
  openEventStream,
  type HealthPayload
} from '@/shared/api';
import { useThemes } from '@/shared/ui/theme/ThemeProvider';
import { ThemeStudio } from '@/shared/ui/theme/ThemeStudio';
import type { GovernancePayload, ProjectRow, StructurePayload, TopologyPayload } from '@/shared/contracts';
import type { DraftRow } from '@/shared/api';
import GlassSurface from '@/shared/ui/glass/GlassSurface';
import {
  listItemVariants,
  listVariants,
  revealVariants,
  scrimVariants,
  surfaceVariants,
  transitionFor,
  useReducedMotionPref
} from '@/shared/ui/motion';
import { loadAutonomy, saveAutonomy, type AutonomyLevel } from '@/features/settings/autonomy';
import { Conversation } from '@/features/conversation/Conversation';
import { ThreadList } from '@/features/conversation/ThreadList';
import { WorkRail } from '@/features/mission/WorkRail';
import { HealthPanel } from '@/features/system/HealthPanel';
import { EMPTY_LIVE, markDisconnected, markSeen, reduceLiveEvent } from '@/features/mission/live';
import type { OpenDispatch } from '@/features/conversation/model';
import { Settings } from '@/features/settings/Settings';
import { Decision } from '@/features/mission/Decision';
import { IdeWorkspace } from '@/features/ide/IdeWorkspace';
import { ProjectDialog } from '@/features/projects/ProjectDialog';
import { buildIndex, defaultFocus, neighbourhood, rankModules, searchModules, shortLabel } from '@/features/twin/graph';
import { Stage } from '@/features/twin/Stage';
import { StatusLine } from './StatusLine';
import './styles/cockpit.css';

/**
 * True while the keyboard event's target is somewhere a person is typing —
 * any text field, including the palette's own search input. The bare-letter
 * shortcuts (`1`, `2`, `r`) must never fire there; a module name containing
 * "r" is not a request to refresh the index. Chorded shortcuts (Strg+K,
 * Strg+,) are exempt — nobody produces those by accident while composing text.
 */
function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable;
}

/**
 * The cockpit: one project, one module in the middle of it, one conversation
 * about it, and whatever is waiting for a decision.
 *
 * The composition — where the chat sits, what the chrome is, how the stage
 * draws — comes from the active theme, so the six designs of the gallery round
 * are six arrangements of THIS surface rather than six pictures of it.
 * Everything on screen is read from the local API; there is no fixture path.
 */

const LAST_FOCUS_KEY = 'daedalus-cockpit-focus';
type CockpitView = 'map' | 'chat' | 'ide';

export function Cockpit() {
  const { theme } = useThemes();
  const reducedMotion = useReducedMotionPref();

  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [project, setProject] = useState('');
  const [structure, setStructure] = useState<StructurePayload | undefined>();
  const [structureFor, setStructureFor] = useState('');
  const [topology, setTopology] = useState<TopologyPayload | undefined>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [offline, setOffline] = useState(false);
  const [health, setHealth] = useState<HealthPayload | undefined>();
  const [healthError, setHealthError] = useState('');
  const [governance, setGovernance] = useState<GovernancePayload | undefined>();
  const [focus, setFocus] = useState('');
  const [direction] = useState<'both'>('both');
  /**
   * THE MAP IS A PAGE.
   *
   * Everything used to share one screen: the graph, the conversation, the
   * decision and the state line, with two of them floating ON TOP of the
   * graph. The owner's verdict on 2026-08-25 was that it read badly and that
   * the graph needs a page of its own where it is legible. The map therefore
   * gets the whole canvas, the conversation is its own page, and the IDE owns
   * a third full body slot. The theme still decides the shared shell.
   */
  const [view, setView] = useState<CockpitView>(() => {
    const fromUrl = new URLSearchParams(location.search).get('view');
    if (fromUrl === 'chat' || fromUrl === 'map' || fromUrl === 'ide') return fromUrl;
    try {
      const saved = localStorage.getItem('daedalus-cockpit-view');
      return saved === 'chat' || saved === 'ide' ? saved : 'map';
    } catch {
      return 'map';
    }
  });
  const [studioOpen, setStudioOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  /** The health surface. Its chip in the status line used to be a button that
   *  closed the theme studio — an affordance that did nothing. */
  const [healthOpen, setHealthOpen] = useState(false);
  /** which runtime answers; '' means "let the backend route" */
  const [brain, setBrain] = useState<string>(() => {
    try {
      return localStorage.getItem('daedalus-brain') || '';
    } catch {
      return '';
    }
  });
  const [autonomy, setAutonomy] = useState<AutonomyLevel>(loadAutonomy);
  const [autoLog, setAutoLog] = useState(0);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [paletteActive, setPaletteActive] = useState(0);
  const [query, setQuery] = useState('');
  /**
   * The live counters, all of them, folded by a reducer that can be tested.
   *
   * `stream_state` (interfaces/bridge/projection.py) has always sent the
   * watcher state, the unread and quarantined counts and the last report
   * brief; this held two of the seven and discarded the rest, including the
   * whole `report` payload. The fold now lives in `features/mission/live.ts`
   * so a frame can be fed to it and asserted.
   */
  const [live, setLive] = useState(EMPTY_LIVE);
  const [streamLive, setStreamLive] = useState(false);
  const [budget, setBudget] = useState<{ hidden1: number; hidden2: number; ids: string[] }>({ hidden1: 0, hidden2: 0, ids: [] });
  const [paletteScope, setPaletteScope] = useState<'all' | 'hidden'>('all');
  const [draftSignal, setDraftSignal] = useState(0);
  const [pendingCount, setPendingCount] = useState(0);
  /** The rail beside the conversation: threads, the work overview, or the map. */
  const [railTab, setRailTab] = useState<'verlauf' | 'arbeit' | 'karte'>('verlauf');
  /**
   * True only while the reader is actually looking at the rail that shows
   * reports. The rail lives inside the conversation view, so leaving that
   * view makes an arriving report news again — otherwise a reader who parked
   * on Arbeit and switched to the map never saw the badge fire.
   */
  const railSeenRef = useRef(false);
  /** Every pending draft, handed up by the decision card that already read them. */
  const [pendingDrafts, setPendingDrafts] = useState<{ rows: DraftRow[]; scoped: boolean }>({ rows: [], scoped: false });
  const onPendingDrafts = useCallback(
    (rows: DraftRow[], scoped: boolean) => setPendingDrafts({ rows, scoped }),
    []
  );
  /**
   * The draft queue belongs to the project it was read for.
   *
   * `Decision` only overwrites this on a SUCCESSFUL load, and that load has
   * been measured at 17-31s on this machine. Without this reset the rail drew
   * the previous project's drafts, clickable, under the new project's name
   * for the whole of that window — the wrong-project form of the defect the
   * decision card itself was rebuilt for in August.
   */
  useEffect(() => {
    setPendingDrafts({ rows: [], scoped: false });
  }, [project]);
  /** A thread chosen in the rail; the serial makes re-picking the same id a fresh request. */
  const [threadPick, setThreadPick] = useState<{ id: string; serial: number } | undefined>();
  /** What the conversation holds, so the rail can mark it and re-read after a turn. */
  const [threadState, setThreadState] = useState<{
    id: string;
    settled: number;
    labels: Record<string, string>;
    openDispatches: OpenDispatch[];
  }>({ id: '', settled: 0, labels: {}, openDispatches: [] });
  /**
   * The rail is on screen only when the conversation view is open AND the
   * Arbeit tab is the one showing. A ref, because the SSE callback is created
   * once and would otherwise close over a stale value.
   */
  useEffect(() => {
    railSeenRef.current = view === 'chat' && railTab === 'arbeit';
    if (railSeenRef.current) setLive(markSeen);
  }, [railTab, view]);

  const onThreadState = useCallback(
    (state: { id: string; settled: number; labels: Record<string, string>; openDispatches: OpenDispatch[] }) =>
      setThreadState(state),
    []
  );
  const projectsSerial = useRef(0);
  const serial = useRef(0);
  /** the project the map on screen belongs to, read outside render */
  const loadedFor = useRef('');

  /* ---- projects ---- */
  const loadProjects = useCallback(async (preferredName = '', preferredRoot = '') => {
    const mine = ++projectsSerial.current;
    try {
      const payload = await getProjects();
      if (mine !== projectsSerial.current) return;
      setOffline(false);
      setProjects(payload.projects);
      setProject((current) => {
        const fromUrl = new URLSearchParams(location.search).get('project') || '';
        // Registration and URL parameters are explicit user choices and keep
        // their exact identity even if reachability later changes. The
        // fallback below is a default, so it never chooses a known-false row.
        const chosen = (preferredName ? payload.projects.find((row) => row.name === preferredName) : undefined)
          || (preferredRoot ? payload.projects.find((row) => row.repo_root === preferredRoot) : undefined)
          || (fromUrl ? payload.projects.find((row) => row.name === fromUrl) : undefined)
          || (current ? payload.projects.find((row) => row.name === current && row.reachable === true) : undefined)
          || payload.projects.find((row) => row.reachable === true)
          || (current ? payload.projects.find((row) => row.name === current && row.reachable === undefined) : undefined)
          || payload.projects.find((row) => row.reachable === undefined);
        return chosen?.name || '';
      });
    } catch (reason) {
      if (mine !== projectsSerial.current) return;
      setOffline(isBackendDown(reason));
      setError(reason instanceof Error ? reason.message : 'Projekte konnten nicht gelesen werden.');
      throw reason;
    }
  }, []);

  useEffect(() => {
    void loadProjects().catch(() => undefined);
  }, [loadProjects]);

  /* ---- structure (the map) ---- */
  const loadStructure = useCallback(
    async (name: string, refresh = false) => {
      if (!name) return;
      const mine = ++serial.current;
      setLoading(true);
      setError('');
      // SWITCHING PROJECTS CLEARS THE MAP FIRST.
      //
      // Keeping the previous payload on screen while the next scan runs left
      // the cockpit drawing one project's modules under another project's
      // name — the exact defect review round three found in the previous
      // surface, and the one tests/cockpit.spec.ts now fails on. A refresh of
      // the SAME project keeps its map, because there the old picture is still
      // a true picture of the thing being redrawn.
      if (loadedFor.current && loadedFor.current !== name) {
        setStructure(undefined);
        setFocus('');
      }
      loadedFor.current = name;
      try {
        const payload = await getStructure(name, refresh);
        if (mine !== serial.current) return;
        setStructure(payload);
        setStructureFor(name);
        setOffline(false);
      } catch (e) {
        if (mine !== serial.current) return;
        setStructure(undefined);
        setOffline(isBackendDown(e));
        setError(e instanceof Error ? e.message : 'Die Karte konnte nicht gebaut werden.');
      } finally {
        if (mine === serial.current) setLoading(false);
      }
    },
    []
  );

  useEffect(() => {
    if (project) void loadStructure(project);
  }, [project, loadStructure]);

  /**
   * The spectral read of the import graph, fetched AFTER the map so it can
   * never delay the picture. It answers a question the map cannot: whether the
   * graph is one thing or many. On this repository it is 46 things, which is
   * also why 1840 edges lead off the drawn map.
   */
  useEffect(() => {
    if (!structureFor) return;
    let alive = true;
    setTopology(undefined);
    getTopology(structureFor)
      .then((p) => alive && setTopology(p))
      .catch(() => alive && setTopology(undefined));
    return () => {
      alive = false;
    };
  }, [structureFor]);

  /* ---- health + governance ---- */
  useEffect(() => {
    let alive = true;
    getHealth()
      .then((p) => alive && setHealth(p))
      .catch((e) => alive && setHealthError(e instanceof Error ? e.message : 'Zustand nicht lesbar.'));
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!project) return;
    let alive = true;
    getGovernance(project)
      .then((p) => alive && setGovernance(p))
      .catch(() => alive && setGovernance(undefined));
    return () => {
      alive = false;
    };
  }, [project]);

  /* ---- live counters ---- */
  useEffect(() => {
    if (!project) return;
    // Nothing the previous project's bus said is true of this one. The counts,
    // the watcher, the report list and the announcement all start empty, and
    // the surface says "not reported yet" until this project's stream speaks.
    setLive(EMPTY_LIVE);
    const es = openEventStream(project, (name, data) => {
      if (name === 'hello' || name === 'heartbeat') setStreamLive(true);
      // A report the reader is already looking at is not news to announce.
      setLive((prev) => reduceLiveEvent(prev, name, data, railSeenRef.current));
      if (name === 'report') setDraftSignal((n) => n + 1);
    });
    es.addEventListener('error', () => {
      setStreamLive(false);
      setLive(markDisconnected);
    });
    return () => {
      es.close();
      setStreamLive(false);
      setLive(markDisconnected);
    };
  }, [project]);

  /* ---- the graph model ---- */
  const index = useMemo(() => buildIndex(structure?.structure?.graph), [structure]);

  useEffect(() => {
    if (!index.nodes.size) return;
    const remembered = (() => {
      try {
        return localStorage.getItem(`${LAST_FOCUS_KEY}:${structureFor}`) || '';
      } catch {
        return '';
      }
    })();
    setFocus((current) => {
      if (current && index.nodes.has(current)) return current;
      if (remembered && index.nodes.has(remembered)) return remembered;
      return defaultFocus(index);
    });
  }, [index, structureFor]);

  const chooseBrain = useCallback((id: string) => {
    setBrain(id);
    try {
      localStorage.setItem('daedalus-brain', id);
    } catch {
      /* storage blocked — the choice still holds for this session */
    }
  }, []);

  const chooseAutonomy = useCallback((level: AutonomyLevel) => {
    setAutonomy(level);
    saveAutonomy(level);
  }, []);

  const goto = useCallback((next: CockpitView) => {
    setView(next);
    try {
      localStorage.setItem('daedalus-cockpit-view', next);
    } catch {
      /* storage blocked — the choice still holds for this session */
    }
  }, []);

  const chooseFocus = useCallback(
    (module: string) => {
      setFocus(module);
      setPaletteOpen(false);
      setQuery('');
      try {
        localStorage.setItem(`${LAST_FOCUS_KEY}:${structureFor}`, module);
      } catch {
        /* storage blocked — the choice still holds for this session */
      }
    },
    [structureFor]
  );

  const nh = useMemo(
    () => (focus && index.nodes.has(focus) ? neighbourhood(index, focus, direction) : undefined),
    [index, focus, direction]
  );

  const resolveModule = useCallback(
    (needle: string) => {
      if (index.nodes.has(needle)) return needle;
      const normalized = needle.replace(/\\/g, '/');
      for (const id of index.nodes.keys()) {
        if (id.replace(/\\/g, '/').endsWith(normalized)) return id;
      }
      return undefined;
    },
    [index]
  );

  const hits = useMemo(() => (paletteOpen ? searchModules(index, query, 12) : []), [index, paletteOpen, query]);
  const hottest = useMemo(() => rankModules(index, 8), [index]);

  /**
   * What the palette lists. Typing always searches the whole map; with nothing
   * typed it lists either the hottest modules or exactly the direct neighbours
   * the stage could not draw, depending on how it was opened.
   */
  const paletteList = useMemo(() => {
    if (query) return hits;
    if (paletteScope === 'hidden') {
      return budget.ids.map((id) => index.nodes.get(id)).filter((n): n is NonNullable<typeof n> => Boolean(n));
    }
    return hottest;
  }, [budget.ids, hits, hottest, index, paletteScope, query]);

  // The highlighted row always starts at the top of whatever the list
  // currently is — reopening, typing, or switching scope all count as a new
  // list, and a highlight left over from the last one points at the wrong row.
  useEffect(() => {
    setPaletteActive(0);
  }, [paletteList]);

  /**
   * The shell's whole keyboard surface, in one place so the tier is legible:
   * chords (Strg+K, Strg+,) work anywhere; Escape always closes whatever is
   * open; the bare letters (1, 2, r) are accelerators for the mouse-driven
   * controls next to them and stand down the moment a text field — including
   * the palette's own search box — has focus, or an overlay already owns the
   * keyboard.
   */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const chord = e.ctrlKey || e.metaKey;
      if (chord && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPaletteScope('all');
        setPaletteOpen((v) => !v);
        return;
      }
      if (chord && e.key === ',') {
        e.preventDefault();
        setSettingsOpen((v) => !v);
        return;
      }
      if (e.key === 'Escape') {
        setPaletteOpen(false);
        setStudioOpen(false);
        setSettingsOpen(false);
        setHealthOpen(false);
        return;
      }
      if (chord || e.altKey || paletteOpen || settingsOpen || studioOpen || healthOpen || isTypingTarget(e.target)) return;
      if (e.key === '1') goto('map');
      else if (e.key === '2') goto('chat');
      else if (e.key === '3') goto('ide');
      else if (e.key.toLowerCase() === 'r') void loadStructure(project, true);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [goto, healthOpen, loadStructure, paletteOpen, project, settingsOpen, studioOpen]);

  const onBudget = useCallback(
    (hidden1: number, hidden2: number, ids: string[]) => setBudget({ hidden1, hidden2, ids }),
    []
  );

  const showHidden = useCallback(() => {
    setPaletteScope('hidden');
    setQuery('');
    setPaletteOpen(true);
  }, []);

  /**
   * How many things genuinely wait on a person, for the rail's badge. Same
   * arithmetic as the rail itself: an unscoped draft pile is never counted
   * under this project's name.
   */
  const workWaiting =
    (pendingDrafts.scoped ? pendingDrafts.rows.length : 0) + (live.quarantined || 0) + (live.unread || 0);
  /** What the rail's tab has to announce: things waiting, plus reports that
   *  arrived while the reader was looking somewhere else. */
  const railBadge = workWaiting + live.unseen;

  const contextModule = nh?.focus;
  const selectedProject = projects.find((row) => row.name === project);

  const conversation = (
    <Conversation
      key={project || '__no_project__'}
      project={project}
      resolveModule={resolveModule}
      onFocusModule={chooseFocus}
      onGoMap={() => goto('map')}
      contextModule={contextModule}
      provider={brain || undefined}
      onProvider={chooseBrain}
      autonomy={autonomy}
      onDispatched={() => {
        setDraftSignal((n) => n + 1);
        setAutoLog((n) => n + 1);
      }}
      pickThread={threadPick}
      onThreadState={onThreadState}
    />
  );
  const decision = (
    <Decision
      project={project}
      signal={draftSignal}
      onChanged={() => setDraftSignal((n) => n + 1)}
      onCount={setPendingCount}
      onPending={onPendingDrafts}
    />
  );

  /**
   * The one pane of glass on the map.
   *
   * `@react-bits/GlassSurface` is the real thing — an SVG displacement filter
   * with a chromatic edge, the Apple/visionOS material rather than a
   * backdrop-filter pretending to be one, and it falls back cleanly where the
   * filter is unsupported. ONE pane: the owner's earlier ruling was glass as a
   * material for at most two surfaces, and this is the surface that sits over
   * the graph.
   */
  const stageHeaderInner = nh ? (
    <>
      <h1 className="stage-focus" title={nh.focus}>
        {shortLabel(nh.focus)}
      </h1>
      <div className="stage-path">{nh.focus}</div>
      <div className="stage-counts">
        <b>{nh.direct}</b> direkt · <b>{nh.reach}</b> über zwei Ebenen
      </div>
      {/* Labelled figures, not a run-on sentence — a number stranded from its
          unit at the reading rail's width ("2807 / Zeilen") reads as a
          broken figure. Kartograph styles `.stage-figures` in stage.css. */}
      {nh.focusNode && (
        <dl className="stage-figures">
          <div>
            <dt>Importeure</dt>
            <dd>{nh.focusNode.fan_in}</dd>
          </div>
          <div>
            <dt>Zeilen</dt>
            <dd>{nh.focusNode.loc}</dd>
          </div>
          <div>
            <dt>Hitze</dt>
            <dd>{nh.focusNode.score.toFixed(1)}</dd>
          </div>
        </dl>
      )}
      {(budget.hidden1 > 0 || budget.hidden2 > 0) && (
        <div className="stage-elision">
          Nicht gezeichnet: {budget.hidden1 > 0 ? `${budget.hidden1} direkte` : ''}
          {budget.hidden1 > 0 && budget.hidden2 > 0 ? ' und ' : ''}
          {budget.hidden2 > 0 ? `${budget.hidden2} entfernte` : ''} Nachbarn — die Bühne zeigt die schwersten zuerst.
          {budget.hidden1 > 0 && (
            <button type="button" onClick={showHidden}>
              Alle auflisten
            </button>
          )}
        </div>
      )}
    </>
  ) : null;

  const stageHeader =
    stageHeaderInner && theme.form.material === 'glass' ? (
      <GlassSurface
        width="100%"
        height="auto"
        borderRadius={theme.form.radius}
        blur={theme.form.blur}
        backgroundOpacity={theme.form.alpha}
        saturation={1.4}
        brightness={60}
        opacity={0.9}
        className="stage-header-glass"
      >
        {stageHeaderInner}
      </GlassSurface>
    ) : (
      stageHeaderInner
    );

  const emptyStage = (
    <div className="stage-empty">
      {offline ? (
        <>
          <h2>Die Daedalus-API antwortet nicht.</h2>
          <p>
            Nichts auf diesem Bildschirm wurde von ihr gelesen — das ist nicht dasselbe wie „es gibt nichts zu zeigen“.
            Starte sie mit <code>python -m daedalus.interfaces.cli.entry web</code> und lade neu.
          </p>
        </>
      ) : !project ? (
        <>
          <h2>Kein erreichbarer Checkout ausgewählt.</h2>
          <p>
            Öffne oben „Projekt hinzufügen“ und registriere den vollständigen lokalen Pfad eines bestehenden
            Checkouts. Der Ordner bleibt an seinem Platz.
          </p>
        </>
      ) : loading ? (
        <>
          <h2>Die Karte wird gebaut.</h2>
          <p>
            Der Index liest {project} einmal vollständig. Beim ersten Mal dauert das etwa eine Minute; danach kommt er
            aus dem Cache.
          </p>
        </>
      ) : error ? (
        <>
          <h2>Die Karte konnte nicht gebaut werden.</h2>
          <p>{error}</p>
          <button type="button" onClick={() => void loadStructure(project, true)}>
            Noch einmal versuchen
          </button>
        </>
      ) : (
        <>
          <h2>Kein Modul ausgewählt.</h2>
          <p>Drück Strg+K und such ein Modul, oder wähl eines aus der Liste der heißesten.</p>
        </>
      )}
    </div>
  );

  const chrome =
    theme.composition.chrome === 'masthead' ? (
      <header className="chrome masthead">
        <div className="masthead-rule" />
        <h1 className="masthead-title">Daedalus</h1>
        <div className="masthead-meta">
          <ProjectPicker projects={projects} project={project} onPick={setProject} onRegistered={loadProjects} reduced={reducedMotion} />
          <span className="chrome-divider" aria-hidden="true" />
          <ViewSwitch view={view} onGo={goto} pending={pendingCount} reduced={reducedMotion} />
          <ChromeTools
            onStudio={() => setStudioOpen(true)}
            onSettings={() => setSettingsOpen(true)}
            onPalette={() => {
              setPaletteScope('all');
              setPaletteOpen(true);
            }}
            onRefresh={() => void loadStructure(project, true)}
            loading={loading}
          />
        </div>
        <div className="masthead-rule" />
      </header>
    ) : (
      <header className="chrome bar">
        <ProjectPicker projects={projects} project={project} onPick={setProject} onRegistered={loadProjects} reduced={reducedMotion} />
        <span className="chrome-divider" aria-hidden="true" />
        <ViewSwitch view={view} onGo={goto} pending={pendingCount} reduced={reducedMotion} />
        <div className="chrome-spacer" />
        <ChromeTools
          onStudio={() => setStudioOpen(true)}
          onSettings={() => setSettingsOpen(true)}
          onPalette={() => {
            setPaletteScope('all');
            setPaletteOpen(true);
          }}
          onRefresh={() => void loadStructure(project, true)}
          loading={loading}
        />
      </header>
    );

  return (
    <div className="cockpit" data-view={view}>
      {chrome}

      {view === 'map' ? (
        <main className="cockpit-body map">
          <div className="cockpit-stage">
            {nh ? (
              <Stage
                neighbourhood={nh}
                theme={theme}
                onFocus={chooseFocus}
                onBudget={onBudget}
                onShowHidden={showHidden}
                header={stageHeader}
              />
            ) : (
              emptyStage
            )}
          </div>
        </main>
      ) : view === 'chat' ? (
        <main className="cockpit-body talk">
          <section className="talk-main">
            {decision}
            {conversation}
          </section>
          <aside className="talk-side">
            {/* Two things belong beside a conversation: the other conversations,
                and the map it is about. Tabs, because both want the full rail
                and neither is a standing panel (owner ruling: Knowledge is an
                inspector). Verlauf opens first: the first question on this page
                is "where was I". */}
            <div className="rail-tabs" role="tablist" aria-label="Neben dem Gespräch">
              <button type="button" role="tab" aria-selected={railTab === 'verlauf'} className={railTab === 'verlauf' ? 'on' : ''} onClick={() => setRailTab('verlauf')}>
                Verlauf
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={railTab === 'arbeit'}
                className={railTab === 'arbeit' ? 'on' : ''}
                onClick={() => {
                  setRailTab('arbeit');
                  setLive(markSeen);
                }}
              >
                Arbeit
                {railBadge > 0 && (
                  <span className={live.unseen > 0 ? 'rail-badge new' : 'rail-badge'}>{railBadge}</span>
                )}
              </button>
              <button type="button" role="tab" aria-selected={railTab === 'karte'} className={railTab === 'karte' ? 'on' : ''} onClick={() => setRailTab('karte')}>
                Karte
              </button>
            </div>
            {railTab === 'arbeit' && (
              <WorkRail
                project={project}
                drafts={pendingDrafts.rows}
                draftsScoped={pendingDrafts.scoped}
                live={{ ...live, connected: streamLive }}
                openDispatches={threadState.openDispatches}
                onGoDecision={() => setRailTab('verlauf')}
              />
            )}
            {railTab === 'verlauf' && (
              <ThreadList
                key={project}
                project={project}
                current={threadState.id}
                refreshKey={threadState.settled}
                onPick={(id) => setThreadPick((prev) => ({ id, serial: (prev?.serial || 0) + 1 }))}
                onNew={() => setThreadPick((prev) => ({ id: '', serial: (prev?.serial || 0) + 1 }))}
                labelOf={(id) => threadState.labels[id]}
              />
            )}
            {railTab === 'karte' && nh && (
              <div className="focuscard">
                <span className="focuscard-eyebrow">Auf der Karte</span>
                <b className="focuscard-name">{shortLabel(nh.focus)}</b>
                <span className="focuscard-path">{nh.focus}</span>
                <span className="focuscard-counts">
                  {nh.direct} direkt · {nh.reach} über zwei Ebenen
                  {nh.focusNode ? ` · ${nh.focusNode.fan_in} Importeure` : ''}
                </span>
                <button type="button" onClick={() => goto('map')}>
                  Auf der Karte ansehen
                </button>
              </div>
            )}
            {railTab === 'karte' && <HotList nodes={hottest} focus={focus} onPick={chooseFocus} />}
          </aside>
        </main>
      ) : (
        <IdeWorkspace project={selectedProject} />
      )}

      <footer className="cockpit-foot">
        <StatusLine
          project={project}
          health={health}
          healthError={healthError}
          governance={governance}
          structure={structure}
          topology={topology}
          inFlight={live.inFlight}
          queued={live.queued}
          streamLive={streamLive}
          onOpenHealth={() => setHealthOpen(true)}
        />
      </footer>

      <AnimatePresence>
        {paletteOpen && (
          <motion.div
            className="palette-scrim"
            onClick={() => setPaletteOpen(false)}
            initial="closed"
            animate="open"
            exit="closed"
            variants={scrimVariants(reducedMotion)}
          >
            <motion.div
              className="palette"
              onClick={(e) => e.stopPropagation()}
              role="dialog"
              aria-label="Modul suchen"
              initial="closed"
              animate="open"
              exit="closed"
              variants={surfaceVariants(reducedMotion)}
            >
              <input
                autoFocus
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={`Modul in ${project} suchen …`}
                aria-label="Modulsuche"
                role="combobox"
                aria-expanded
                aria-controls="palette-results"
                aria-activedescendant={paletteList[paletteActive] ? `palette-opt-${paletteList[paletteActive].module}` : undefined}
                onKeyDown={(e) => {
                  if (e.key === 'ArrowDown') {
                    e.preventDefault();
                    setPaletteActive((i) => Math.min(i + 1, paletteList.length - 1));
                  } else if (e.key === 'ArrowUp') {
                    e.preventDefault();
                    setPaletteActive((i) => Math.max(i - 1, 0));
                  } else if (e.key === 'Enter') {
                    const chosen = paletteList[paletteActive];
                    if (chosen) chooseFocus(chosen.module);
                  }
                }}
              />
              <KeyList
                id="palette-results"
                items={paletteList}
                activeIndex={paletteActive}
                onActiveChange={setPaletteActive}
                onCommit={(n) => chooseFocus(n.module)}
                getKey={(n) => n.module}
                optionId={(n) => `palette-opt-${n.module}`}
                ariaLabel="Suchergebnisse"
                reduced={reducedMotion}
                emptyLabel={query ? `Kein Modul in der Karte passt zu „${query}“.` : undefined}
                renderItem={(n) => (
                  <>
                    <span className="palette-name">{shortLabel(n.module)}</span>
                    <span className="palette-path">{n.module}</span>
                    <span className="palette-meta">
                      {n.fan_in} Importeure · {n.loc} Zeilen
                    </span>
                  </>
                )}
              />
              <p className="palette-foot">
                {paletteScope === 'hidden' && !query
                  ? `${budget.ids.length} direkte Nachbarn, die auf der Bühne nicht gezeichnet sind. Tippen sucht wieder in allen ${index.nodes.size} Modulen.`
                  : `Die Suche läuft über die ${index.nodes.size} Module der Karte — nicht über das ganze Repository.`}{' '}
                ↑↓ wählt · Enter öffnet · Esc schließt.
              </p>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      <Settings
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        project={project}
        brain={brain}
        onBrain={chooseBrain}
        autonomy={autonomy}
        onAutonomy={chooseAutonomy}
        logSignal={autoLog}
      />

      <AnimatePresence>
        <HealthPanel open={healthOpen} onClose={() => setHealthOpen(false)} health={health} error={healthError} />
      </AnimatePresence>

      <ThemeStudio open={studioOpen} onClose={() => setStudioOpen(false)} />
    </div>
  );
}

/**
 * A keyboard-navigable, single-select list: arrow keys move a highlighted
 * row, Enter (wired by the caller) commits it, hover syncs the highlight to
 * the pointer so the two input methods never disagree about which row is
 * "on". The pattern — arrow traversal plus a highlighted active row over a
 * staggered reveal — is `@react-bits/AnimatedList`'s; it is rebuilt here on
 * this app's own motion tiers (`listVariants` / `listItemVariants`) instead
 * of the component's bundled ad-hoc transition, because a second place a
 * duration can live is how this design system starts to rot (see
 * src/shared/ui/motion/tokens.ts). File ownership keeps every part of
 * the shell in Cockpit.tsx, so it lives here rather than as its own
 * component file — used by both the project switcher and the module palette,
 * the two places the chrome asks someone to pick one thing out of a list
 * that can grow.
 */
function KeyList<T>({
  id,
  items,
  activeIndex,
  onActiveChange,
  onCommit,
  getKey,
  optionId,
  extraClass,
  renderItem,
  emptyLabel,
  ariaLabel,
  reduced,
  animate = true
}: {
  id?: string;
  items: T[];
  activeIndex: number;
  onActiveChange: (i: number) => void;
  onCommit: (item: T) => void;
  getKey: (item: T) => string;
  optionId?: (item: T) => string;
  /** an additional class for the row button — e.g. marking the current project */
  extraClass?: (item: T) => string;
  renderItem: (item: T, active: boolean) => ReactNode;
  emptyLabel?: string;
  ariaLabel: string;
  reduced: boolean;
  animate?: boolean;
}) {
  const List = animate ? motion.ul : 'ul';
  const Item = animate ? motion.li : 'li';
  const listProps = animate
    ? { initial: 'hidden', animate: 'visible', variants: listVariants(reduced, items.length) }
    : {};
  const itemVariants = animate ? listItemVariants(reduced) : undefined;
  return (
    <List id={id} role="listbox" aria-label={ariaLabel} {...listProps}>
      {items.map((item, i) => (
        <Item key={getKey(item)} variants={itemVariants} role="option" id={optionId?.(item)} aria-selected={i === activeIndex}>
          <button
            type="button"
            className={[i === activeIndex ? 'active' : '', extraClass?.(item) || ''].filter(Boolean).join(' ')}
            onMouseEnter={() => onActiveChange(i)}
            onClick={() => onCommit(item)}
          >
            {renderItem(item, i === activeIndex)}
          </button>
        </Item>
      ))}
      {items.length === 0 && emptyLabel && <li className="list-empty">{emptyLabel}</li>}
    </List>
  );
}

/**
 * Three pages, named for what they are. The active tab rides one shared pill
 * (`layoutId`) instead of each button drawing its own underline, so choosing
 * a page reads as the SAME control moving rather than as two independent
 * buttons toggling — a state change (`src/shared/ui/motion/variants.ts`'s `move`
 * tier), not two acknowledgements. The badge is the count of decisions
 * actually pending — it is absent when there are none, because a zero on a
 * navigation control is a thing to look at that means nothing.
 */
function ViewSwitch({
  view,
  onGo,
  pending,
  reduced
}: {
  view: CockpitView;
  onGo: (v: CockpitView) => void;
  pending: number;
  reduced: boolean;
}) {
  const thumbTransition = transitionFor('move', reduced);
  // The pill has to be an ANCESTOR of the label it colours, not a sibling
  // laid on top of it: tools/audit.mjs (and every real contrast checker)
  // reads a text node's background by walking up `parentElement`, so a
  // same-level decorative layer is invisible to it even though it is what a
  // person actually sees painted behind the word. Wrapping the label in the
  // motion pill on the active tab, instead of floating the pill beside it,
  // makes the measured contrast match the rendered one.
  const gespraech = (
    <>
      Gespräch
      {pending > 0 && (
        <span className="viewswitch-badge" title={`${pending} Entscheidung(en) warten`}>
          {pending}
        </span>
      )}
    </>
  );
  return (
    <nav className="viewswitch" aria-label="Ansicht">
      <button type="button" className={view === 'map' ? 'on' : ''} aria-current={view === 'map'} title="Karte (1)" onClick={() => onGo('map')}>
        {view === 'map' ? (
          <motion.span layoutId="viewswitch-thumb" className="viewswitch-thumb" transition={thumbTransition}>
            Karte
          </motion.span>
        ) : (
          'Karte'
        )}
      </button>
      <button
        type="button"
        className={view === 'chat' ? 'on' : ''}
        aria-current={view === 'chat'}
        title="Gespräch (2)"
        onClick={() => onGo('chat')}
      >
        {view === 'chat' ? (
          <motion.span layoutId="viewswitch-thumb" className="viewswitch-thumb" transition={thumbTransition}>
            {gespraech}
          </motion.span>
        ) : (
          gespraech
        )}
      </button>
      <button
        type="button"
        className={view === 'ide' ? 'on' : ''}
        aria-current={view === 'ide'}
        title="IDE (3)"
        onClick={() => onGo('ide')}
      >
        {view === 'ide' ? (
          <motion.span layoutId="viewswitch-thumb" className="viewswitch-thumb" transition={thumbTransition}>
            IDE
          </motion.span>
        ) : (
          'IDE'
        )}
      </button>
    </nav>
  );
}

/**
 * The scope of the whole screen — both pages read only what this picks — so
 * it is built as an actual control rather than a row of links: one trigger
 * that names the current project, a listbox underneath it with type-ahead
 * and arrow-key selection. Four projects today do not need the search field,
 * so it only mounts past a threshold; twenty projects get exactly the same
 * control, not a wider row of buttons.
 */
function ProjectPicker({
  projects,
  project,
  onPick,
  onRegistered,
  reduced
}: {
  projects: ProjectRow[];
  project: string;
  onPick: (name: string) => void;
  onRegistered: (preferredName?: string, preferredRoot?: string) => Promise<void>;
  reduced: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const wrapRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const filtered = useMemo(() => {
    if (!query) return projects;
    const q = query.toLowerCase();
    return projects.filter((p) => p.name.toLowerCase().includes(q));
  }, [projects, query]);
  const selected = projects.find((row) => row.name === project);

  useEffect(() => setActive(0), [filtered]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  useEffect(() => {
    if (!open) {
      setQuery('');
      return;
    }
    if (projects.length <= 6) menuRef.current?.focus();
  }, [open, projects.length]);

  const commit = (name: string) => {
    onPick(name);
    setOpen(false);
  };

  return (
    <div className="scope" ref={wrapRef}>
      <button
        type="button"
        className="scope-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="scope-eyebrow">Projekt</span>
        <span className="scope-name">
          {project
            ? (selected?.reachable === false ? `${project} · Pfad fehlt` : project)
            : 'Projekt hinzufügen'}
        </span>
        <svg className="scope-chevron" width="10" height="6" viewBox="0 0 10 6" aria-hidden="true">
          <path d="M1 1l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            ref={menuRef}
            className="scope-menu"
            tabIndex={-1}
            initial="hidden"
            animate="visible"
            exit="hidden"
            variants={revealVariants(reduced)}
            onKeyDown={(e) => {
              if (e.key === 'ArrowDown') {
                e.preventDefault();
                setActive((i) => Math.min(i + 1, filtered.length - 1));
              } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                setActive((i) => Math.max(i - 1, 0));
              } else if (e.key === 'Enter') {
                e.preventDefault();
                if (filtered[active]) commit(filtered[active].name);
              } else if (e.key === 'Escape') {
                e.preventDefault();
                setOpen(false);
              }
            }}
          >
            {projects.length > 6 && (
              <input
                autoFocus
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={`${projects.length} Projekte durchsuchen …`}
                aria-label="Projekt suchen"
              />
            )}
            <KeyList
              items={filtered}
              activeIndex={active}
              onActiveChange={setActive}
              onCommit={(p) => commit(p.name)}
              getKey={(p) => p.name}
              extraClass={(p) => (p.name === project ? 'on' : '')}
              ariaLabel="Projekt wählen"
              reduced={reduced}
              animate={false}
              emptyLabel={projects.length ? `Kein Projekt passt zu „${query}“.` : 'Noch kein Projekt registriert.'}
              renderItem={(p) => (
                <span
                  data-project-name={p.name}
                  data-project-reachable={
                    p.reachable === true ? 'true' : p.reachable === false ? 'false' : 'unknown'
                  }
                >
                  {p.reachable === false ? `${p.name} · Pfad fehlt` : p.name}
                </span>
              )}
            />
            <button
              type="button"
              className="scope-add"
              onClick={() => {
                setOpen(false);
                setAddOpen(true);
              }}
            >
              + Projekt hinzufügen / Ordner öffnen
            </button>
          </motion.div>
        )}
      </AnimatePresence>
      <ProjectDialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        onRegistered={(name, repoRoot) => onRegistered(name, repoRoot)}
      />
    </div>
  );
}

function ChromeTools({
  onStudio,
  onSettings,
  onPalette,
  onRefresh,
  loading
}: {
  onStudio: () => void;
  onSettings: () => void;
  onPalette: () => void;
  onRefresh: () => void;
  loading: boolean;
}) {
  return (
    <div className="chrome-tools">
      <button type="button" onClick={onPalette} title="Modul suchen (Strg+K)">
        Suchen
        <kbd className="chrome-kbd">Strg K</kbd>
      </button>
      <button type="button" onClick={onRefresh} disabled={loading} title="Index neu bauen (R)">
        {loading ? 'Liest …' : 'Neu lesen'}
        {!loading && <kbd className="chrome-kbd">R</kbd>}
      </button>
      <button type="button" onClick={onSettings} title="Brain, Autonomie, Erreichbarkeit (Strg+,)">
        Einstellungen
        <kbd className="chrome-kbd">Strg ,</kbd>
      </button>
      <button type="button" onClick={onStudio} title="Themes">
        Themes
      </button>
      <span className="chrome-divider" aria-hidden="true" />
      <a className="chrome-link" href="?surface=classic" title="Kompatibilitätsalias — öffnet dieselbe Cockpit-App">
        Alte Oberfläche
      </a>
    </div>
  );
}

function HotList({
  nodes,
  focus,
  onPick
}: {
  nodes: Array<{ module: string; fan_in: number; score: number }>;
  focus: string;
  onPick: (m: string) => void;
}) {
  if (!nodes.length) return null;
  return (
    <div className="hotlist">
      <div className="hotlist-head">
        <span className="hotlist-title">Heißeste Module</span>
        <span className="hotlist-col" title="Hitze: Importeure gewichtet gegen Codegröße">
          Hitze
        </span>
      </div>
      <ul>
        {nodes.map((n) => (
          <li key={n.module}>
            <button type="button" className={n.module === focus ? 'on' : ''} onClick={() => onPick(n.module)}>
              <span>{shortLabel(n.module)}</span>
              <span className="muted" title={`Hitze ${n.score.toFixed(1)}`}>
                {n.score.toFixed(0)}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
