import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  getGovernance,
  getHealth,
  getProjects,
  getStructure,
  isBackendDown,
  openEventStream,
  type HealthPayload
} from '../api';
import { useThemes } from '../theme/ThemeProvider';
import { ThemeStudio } from '../theme/ThemeStudio';
import type { GovernancePayload, ProjectRow, StructurePayload } from '../types';
import { Conversation } from './Conversation';
import { Decision } from './Decision';
import { buildIndex, defaultFocus, neighbourhood, rankModules, searchModules, shortLabel } from './graph';
import { Stage } from './Stage';
import { StatusLine } from './StatusLine';
import './cockpit.css';

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

export function Cockpit() {
  const { theme } = useThemes();

  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [project, setProject] = useState('');
  const [structure, setStructure] = useState<StructurePayload | undefined>();
  const [structureFor, setStructureFor] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [offline, setOffline] = useState(false);
  const [health, setHealth] = useState<HealthPayload | undefined>();
  const [healthError, setHealthError] = useState('');
  const [governance, setGovernance] = useState<GovernancePayload | undefined>();
  const [focus, setFocus] = useState('');
  const [direction] = useState<'both'>('both');
  const [studioOpen, setStudioOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [live, setLive] = useState<{ inFlight?: number; queued?: number }>({});
  const [streamLive, setStreamLive] = useState(false);
  const [budget, setBudget] = useState<{ hidden1: number; hidden2: number; ids: string[] }>({ hidden1: 0, hidden2: 0, ids: [] });
  const [paletteScope, setPaletteScope] = useState<'all' | 'hidden'>('all');
  const [draftSignal, setDraftSignal] = useState(0);
  const serial = useRef(0);
  /** the project the map on screen belongs to, read outside render */
  const loadedFor = useRef('');

  /* ---- projects ---- */
  useEffect(() => {
    let alive = true;
    getProjects()
      .then((payload) => {
        if (!alive) return;
        setOffline(false);
        setProjects(payload.projects);
        const fromUrl = new URLSearchParams(location.search).get('project') || '';
        const chosen = fromUrl || payload.projects[0]?.name || '';
        setProject(chosen);
      })
      .catch((e) => {
        if (!alive) return;
        setOffline(isBackendDown(e));
        setError(e instanceof Error ? e.message : 'Projekte konnten nicht gelesen werden.');
      });
    return () => {
      alive = false;
    };
  }, []);

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
    const es = openEventStream(project, (name, data) => {
      const d = (data || {}) as Record<string, number>;
      if (name === 'hello') {
        setStreamLive(true);
        setLive({ inFlight: d.in_flight, queued: d.queue_depth });
      } else if (name === 'heartbeat') {
        setStreamLive(true);
        setLive((prev) => ({ ...prev, inFlight: d.in_flight ?? prev.inFlight }));
      } else if (name === 'queue') {
        setLive((prev) => ({ ...prev, queued: d.depth ?? prev.queued }));
      } else if (name === 'report') {
        setDraftSignal((n) => n + 1);
      }
    });
    es.addEventListener('error', () => setStreamLive(false));
    return () => {
      es.close();
      setStreamLive(false);
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

  /* ---- keyboard: the palette ---- */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPaletteScope('all');
        setPaletteOpen((v) => !v);
      } else if (e.key === 'Escape') {
        setPaletteOpen(false);
        setStudioOpen(false);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const onBudget = useCallback(
    (hidden1: number, hidden2: number, ids: string[]) => setBudget({ hidden1, hidden2, ids }),
    []
  );

  const showHidden = useCallback(() => {
    setPaletteScope('hidden');
    setQuery('');
    setPaletteOpen(true);
  }, []);

  const contextLine = nh
    ? `Auf der Bühne steht ${nh.focus} (${nh.direct} direkte Nachbarn, ${nh.reach} über zwei Ebenen) im Projekt ${project}.`
    : undefined;

  const conversation = (
    <Conversation
      project={project}
      resolveModule={resolveModule}
      onFocusModule={chooseFocus}
      contextLine={contextLine}
      compact={theme.composition.chat === 'card'}
    />
  );
  const decision = <Decision signal={draftSignal} onChanged={() => setDraftSignal((n) => n + 1)} />;

  const stageHeader = nh ? (
    <>
      <div className="stage-eyebrow">
        Nachbarschaft · {project}
        {structure?.structure?.repo_root ? '' : ''}
      </div>
      <h1 className="stage-focus" title={nh.focus}>
        {shortLabel(nh.focus)}
      </h1>
      <div className="stage-path">{nh.focus}</div>
      <div className="stage-counts">
        <b>{nh.direct}</b> direkt · <b>{nh.reach}</b> über zwei Ebenen
        {nh.focusNode ? (
          <span className="muted">
            {' '}
            · {nh.focusNode.fan_in} Importeure · {nh.focusNode.loc} Zeilen · Hitze {nh.focusNode.score.toFixed(1)}
          </span>
        ) : null}
      </div>
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

  const emptyStage = (
    <div className="stage-empty">
      {offline ? (
        <>
          <h2>Die Daedalus-API antwortet nicht.</h2>
          <p>
            Nichts auf diesem Bildschirm wurde von ihr gelesen — das ist nicht dasselbe wie „es gibt nichts zu zeigen“.
            Starte sie mit <code>python -m daedalus.cli web</code> und lade neu.
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

  return (
    <div className="cockpit">
      {theme.composition.chrome === 'masthead' ? (
        <header className="chrome masthead">
          <div className="masthead-rule" />
          <h1 className="masthead-title">Daedalus</h1>
          <div className="masthead-meta">
            <ProjectPicker projects={projects} project={project} onPick={setProject} />
            <span>{structure?.structure?.repo_root || ''}</span>
            <ChromeTools onStudio={() => setStudioOpen(true)} onPalette={() => { setPaletteScope('all'); setPaletteOpen(true); }} onRefresh={() => void loadStructure(project, true)} loading={loading} />
          </div>
          <div className="masthead-rule" />
        </header>
      ) : (
        <header className="chrome bar">
          <ProjectPicker projects={projects} project={project} onPick={setProject} />
          <div className="chrome-spacer" />
          <ChromeTools onStudio={() => setStudioOpen(true)} onPalette={() => { setPaletteScope('all'); setPaletteOpen(true); }} onRefresh={() => void loadStructure(project, true)} loading={loading} />
        </header>
      )}

      <main className="cockpit-body">
        <div className="cockpit-stage">
          {nh ? (
            <Stage
              neighbourhood={nh}
              theme={theme}
              onFocus={chooseFocus}
              onBudget={onBudget}
              onShowHidden={showHidden}
              header={stageHeader}
              overlay={theme.composition.decision === 'float' ? decision : undefined}
              panel={theme.composition.chat === 'card' ? conversation : undefined}
            />
          ) : (
            emptyStage
          )}
        </div>

        {theme.composition.chat === 'column' && (
          <aside className="cockpit-column">
            {theme.composition.decision === 'inline' && decision}
            {conversation}
            <HotList nodes={hottest} focus={focus} onPick={chooseFocus} />
          </aside>
        )}

        {theme.composition.chat === 'drawer' && (
          <section className="cockpit-drawer">
            {theme.composition.decision === 'inline' && decision}
            {conversation}
          </section>
        )}

        {theme.composition.chat === 'flow' && (
          <section className="cockpit-flow">
            {conversation}
            {theme.composition.decision === 'inline' && decision}
          </section>
        )}
      </main>

      {theme.composition.decision === 'bar' && <div className="cockpit-decisionbar">{decision}</div>}

      <footer className="cockpit-foot">
        <StatusLine
          project={project}
          health={health}
          healthError={healthError}
          governance={governance}
          structure={structure}
          inFlight={live.inFlight}
          queued={live.queued}
          streamLive={streamLive}
          onOpenHealth={() => setStudioOpen(false)}
        />
      </footer>

      {paletteOpen && (
        <div className="palette-scrim" onClick={() => setPaletteOpen(false)}>
          <div className="palette" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Modul suchen">
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={`Modul in ${project} suchen …`}
              aria-label="Modulsuche"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && hits[0]) chooseFocus(hits[0].module);
              }}
            />
            <ul>
              {paletteList.map((n) => (
                <li key={n.module}>
                  <button type="button" onClick={() => chooseFocus(n.module)}>
                    <span className="palette-name">{shortLabel(n.module)}</span>
                    <span className="palette-path">{n.module}</span>
                    <span className="palette-meta">
                      {n.fan_in} Importeure · {n.loc} Zeilen
                    </span>
                  </button>
                </li>
              ))}
              {query && hits.length === 0 && <li className="palette-none">Kein Modul in der Karte passt zu „{query}“.</li>}
            </ul>
            <p className="palette-foot">
              {paletteScope === 'hidden' && !query
                ? `${budget.ids.length} direkte Nachbarn, die auf der Bühne nicht gezeichnet sind. Tippen sucht wieder in allen ${index.nodes.size} Modulen.`
                : `Die Suche läuft über die ${index.nodes.size} Module der Karte — nicht über das ganze Repository.`}
            </p>
          </div>
        </div>
      )}

      <ThemeStudio open={studioOpen} onClose={() => setStudioOpen(false)} />
    </div>
  );
}

function ProjectPicker({
  projects,
  project,
  onPick
}: {
  projects: ProjectRow[];
  project: string;
  onPick: (name: string) => void;
}) {
  if (!projects.length) return <span className="muted">Keine Projekte gemeldet</span>;
  return (
    <nav className="projects" aria-label="Projekte">
      {projects.map((p) => (
        <button key={p.name} type="button" className={p.name === project ? 'on' : ''} onClick={() => onPick(p.name)}>
          {p.name}
        </button>
      ))}
    </nav>
  );
}

function ChromeTools({
  onStudio,
  onPalette,
  onRefresh,
  loading
}: {
  onStudio: () => void;
  onPalette: () => void;
  onRefresh: () => void;
  loading: boolean;
}) {
  return (
    <div className="chrome-tools">
      <button type="button" onClick={onPalette} title="Modul suchen (Strg+K)">
        Suchen
      </button>
      <button type="button" onClick={onRefresh} disabled={loading} title="Index neu bauen">
        {loading ? 'Liest …' : 'Neu lesen'}
      </button>
      <button type="button" onClick={onStudio} title="Themes">
        Themes
      </button>
      <a className="chrome-link" href="?surface=classic" title="Die vorherige Oberfläche — Runtimes, Control Plane, Inbox">
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
      <span className="hotlist-title">Heißeste Module</span>
      <ul>
        {nodes.map((n) => (
          <li key={n.module}>
            <button type="button" className={n.module === focus ? 'on' : ''} onClick={() => onPick(n.module)}>
              <span>{shortLabel(n.module)}</span>
              <span className="muted">{n.score.toFixed(0)}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
