import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  Crosshair,
  Flame,
  Map as MapIcon,
  RefreshCw,
  Scissors,
  Unplug,
  Waypoints,
  X
} from 'lucide-react';
import Graph from 'graphology';
import Sigma from 'sigma';
import forceAtlas2 from 'graphology-layout-forceatlas2';
import FA2Layout from 'graphology-layout-forceatlas2/worker';
import { GlassButton, GlassCard, cx } from './glass';
import { DistillResult } from './StructureSheet';
import { distill, getStructure } from '../api';
import type {
  DistillPayload,
  StructureGraph,
  StructureGraphNode,
  StructurePayload
} from '../types';
import type { Theme } from '../hooks/useTheme';

/**
 * The structural findings the architecture map produces, joined onto the graph.
 *
 * ISLANDS and SHIMS are named ONLY when the generated snapshot was trusted and
 * the picker actually ranked them — the counts endpoint deliberately serves no
 * module lists. So `namesWithheld` carries the reason the names are missing,
 * and the UI must print it: "no islands drawn" and "the island list was
 * withheld" are the same empty set and completely different facts.
 */
export interface MapFindings {
  islands: string[];
  shims: string[];
  /** Non-empty when island/shim NAMES could not be obtained. */
  namesWithheld: string;
  /** Snapshot counts, for the ribbon. Untrusted counts are struck through. */
  counts?: Record<string, number>;
  trusted?: boolean;
}

/** Only two of these are FINDINGS. `no-inbound` is a property of the drawn
 * edges and is labelled as one — see the note where it is computed. */
export type FindingClass = 'island' | 'shim' | 'no-inbound';

interface CodeMapProps {
  project: string;
  data?: StructurePayload;
  loading: boolean;
  error: string;
  onRefresh: () => void;
  theme: Theme;
  findings?: MapFindings;
}

function num(value: number): string {
  return Number.isFinite(value) ? value.toLocaleString() : '0';
}

/**
 * Heat scores span wildly different ranges — a five-file repo tops out around
 * 3.5, a large one runs into the hundreds. Rounding unconditionally printed
 * "hot 4" as the ceiling of a graph whose real maximum was 3.5, i.e. a number
 * no module in the repo actually had. Keep a decimal while the range is small.
 */
function fmtScore(value: number, max: number): string {
  if (!Number.isFinite(value)) return '0';
  return max < 10 ? value.toFixed(1) : Math.round(value).toLocaleString();
}

/* ------------------------------------------------------------------ *
 * Heat ramp — the product insight made visible.
 *
 * `score` is churn x complexity: rot lives where code is complex AND
 * changing. Cold code must RECEDE (low-contrast slate that sinks into the
 * scene) and hot code must POP (amber -> red). Stops are hand-picked per
 * theme so the cold end sits close to the backdrop in both.
 * ------------------------------------------------------------------ */
type Stop = [number, [number, number, number]];

const RAMP_DARK: Stop[] = [
  [0.0, [56, 68, 90]],
  [0.3, [74, 118, 168]],
  [0.55, [106, 168, 255]],
  [0.78, [240, 195, 74]],
  [1.0, [255, 92, 96]]
];

const RAMP_LIGHT: Stop[] = [
  [0.0, [188, 198, 214]],
  [0.3, [124, 158, 202]],
  [0.55, [56, 122, 220]],
  [0.78, [226, 158, 30]],
  [1.0, [214, 45, 60]]
];

function rampColor(t: number, theme: Theme): string {
  const stops = theme === 'light' ? RAMP_LIGHT : RAMP_DARK;
  const x = Math.max(0, Math.min(1, t));
  let lo = stops[0];
  let hi = stops[stops.length - 1];
  for (let i = 0; i < stops.length - 1; i += 1) {
    if (x >= stops[i][0] && x <= stops[i + 1][0]) {
      lo = stops[i];
      hi = stops[i + 1];
      break;
    }
  }
  const span = hi[0] - lo[0] || 1;
  const k = (x - lo[0]) / span;
  const ch = (i: number) => Math.round(lo[1][i] + (hi[1][i] - lo[1][i]) * k);
  return `rgb(${ch(0)}, ${ch(1)}, ${ch(2)})`;
}

/**
 * Heat scores are long-tailed (a couple of monsters, a long cold tail), so a
 * linear normalisation would flatten everything below the top file into one
 * indistinguishable cold blob. log1p spreads the mass where the modules
 * actually are while keeping the ordering exact and the ends anchored to the
 * real min/max, which the legend prints.
 */
function heatT(score: number, maxScore: number): number {
  if (!(maxScore > 0) || !Number.isFinite(score) || score <= 0) return 0;
  return Math.log1p(score) / Math.log1p(maxScore);
}

/**
 * The floor is a *hit-target* constraint, not an aesthetic one: a leaf module
 * with fan-in 0 still has to be clickable to be distillable, and anything
 * under ~4px is a coin-flip with a real mouse (measured — a 2.4px node ate
 * repeated genuine clicks while only synthetic pixel-exact events landed).
 * Cold code is made to recede with colour instead, which costs no hit area.
 */
const MIN_SIZE = 4.5;
const MAX_SIZE = 15;

/**
 * Size encodes `fan_in` (how many modules import this one), NOT `loc`.
 * `score` already folds complexity in, and complexity tracks loc closely — so
 * sizing by loc would just re-draw the colour axis. fan_in is orthogonal: it
 * is blast radius. Big AND hot therefore reads as "lots depends on this and it
 * is rotting", which is exactly the triage target. sqrt because perceived
 * magnitude follows disc area, not radius.
 */
function nodeSize(fanIn: number, maxFanIn: number): number {
  if (!(maxFanIn > 0)) return 5;
  const k = Math.sqrt(Math.max(0, fanIn) / maxFanIn);
  return MIN_SIZE + (MAX_SIZE - MIN_SIZE) * k;
}

/**
 * Findings colours — deliberately OUTSIDE the heat ramp's blue→amber→red axis.
 *
 * The heat ramp already owns warm hues, so a finding painted amber would read
 * as "hot" rather than "structurally disconnected". Islands and shims get the
 * violet/teal end of the wheel, and `unreached` gets a plain bright cyan
 * because it is the weakest claim of the three (see the note in the panel).
 */
const FINDING_COLOR: Record<FindingClass, string> = {
  island: '#c07dff',
  shim: '#ff9de0',
  'no-inbound': '#4fd7d1'
};

const FINDING_LABEL: Record<FindingClass, string> = {
  island: 'island — the map says nothing reaches it',
  shim: 'shim — a re-export nothing reaches',
  'no-inbound': 'no inbound edge in THIS graph (not a verdict)'
};

interface Palette {
  edge: string;
  edgeHi: string;
  dim: string;
  /** Findings mode's un-flagged nodes. Deliberately MUCH stronger than `dim`:
   * `dim` exists to push a neighbourhood's context away for a second while you
   * hover, but findings mode is a mode you sit in, and on a repo with zero
   * flagged modules `dim` turned the entire graph invisible — a blank canvas
   * reads as "nothing here" when the truth is "nothing flagged". */
  backdrop: string;
  label: string;
  ring: string;
}

function palette(theme: Theme): Palette {
  return theme === 'light'
    ? {
        // Light theme needs a notably darker edge than the dark theme needs a
        // lighter one: near-white scene + low-alpha strokes washed the import
        // lines out almost completely at 14%.
        edge: 'rgba(52, 72, 104, .30)',
        edgeHi: 'rgba(40, 90, 180, .70)',
        dim: 'rgba(150, 162, 180, .13)',
        backdrop: 'rgba(96, 112, 142, .60)',
        label: 'rgba(23, 30, 44, .92)',
        ring: '#1b2436'
      }
    : {
        edge: 'rgba(150, 180, 230, .11)',
        edgeHi: 'rgba(140, 190, 255, .5)',
        dim: 'rgba(120, 140, 175, .09)',
        backdrop: 'rgba(138, 158, 194, .55)',
        label: 'rgba(236, 240, 247, .92)',
        ring: '#0b1220'
      };
}

/**
 * Movement II — the living code map.
 *
 * A WebGL (Sigma.js) module dependency graph over `structure.graph`, with the
 * churn x complexity heat painted straight onto the nodes and "Distill this"
 * wired to the same `/api/distill` path the Structure sheet uses.
 */
export function CodeMap({ project, data, loading, error, onRefresh, theme, findings }: CodeMapProps) {
  const [graphLimit, setGraphLimit] = useState<number | 'all'>(2000);
  const [projection, setProjection] = useState<StructurePayload | undefined>(data);
  const [projectionLoading, setProjectionLoading] = useState(false);
  const [projectionError, setProjectionError] = useState('');
  const requestSerial = useRef(0);
  const graph = projection?.structure?.graph;

  useEffect(() => setProjection(data), [data]);

  const changeGraphLimit = useCallback(async (next: number | 'all') => {
    const serial = ++requestSerial.current;
    setGraphLimit(next);
    setProjectionLoading(true);
    setProjectionError('');
    try {
      const payload = await getStructure(project, false, next);
      if (serial === requestSerial.current) setProjection(payload);
    } catch (err) {
      if (serial === requestSerial.current) {
        setProjectionError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      if (serial === requestSerial.current) setProjectionLoading(false);
    }
  }, [project]);

  const busy = loading || projectionLoading;
  const visibleError = error || projectionError;

  return (
    <section className="panel feature-panel codemap-panel">
      <div className="panel-head">
        <Waypoints size={18} />
        <div>
          <h2>Code Map</h2>
          <p>Every module, every import edge — coloured by churn x complexity. Hot means rotting.</p>
        </div>
        <label className="graph-limit" title="Server-side projection of the canonical indexed graph">
          <span>Show</span>
          <select
            value={String(graphLimit)}
            disabled={busy}
            onChange={(event) => {
              const value = event.target.value;
              void changeGraphLimit(value === 'all' ? 'all' : Number(value));
            }}
            aria-label="Maximum graph nodes"
          >
            <option value="250">250 nodes</option>
            <option value="500">500 nodes</option>
            <option value="1000">1,000 nodes</option>
            <option value="2000">2,000 nodes</option>
            <option value="all">whole network</option>
          </select>
        </label>
        <button
          type="button"
          className="iconbtn struct-refresh"
          onClick={onRefresh}
          disabled={busy}
          title="Re-index repository"
          aria-label="Re-index repository"
        >
          <RefreshCw size={15} className={busy ? 'spin' : undefined} />
        </button>
      </div>

      {busy && !graph && (
        <div className="struct-state">
          <RefreshCw size={22} className="spin" />
          <strong>Indexing {project || 'repository'}…</strong>
          <span>The first scan of a big repo can take minutes. The map draws as soon as it lands.</span>
        </div>
      )}

      {!busy && visibleError && (
        <div className="struct-state struct-state-error">
          <AlertTriangle size={22} />
          <strong>Couldn't load the map</strong>
          <span>{visibleError}</span>
          <GlassButton onClick={onRefresh}><RefreshCw size={14} /> Retry</GlassButton>
        </div>
      )}

      {!busy && !visibleError && projection && !graph && (
        <div className="struct-state">
          <MapIcon size={22} />
          <strong>No dependency graph</strong>
          <span>This backend didn't return <code>structure.graph</code> for the project.</span>
        </div>
      )}

      {!busy && !visibleError && !projection && (
        <div className="struct-state">
          <MapIcon size={22} />
          <strong>No map yet</strong>
          <span>Open this sheet to index the project and draw its dependency graph.</span>
        </div>
      )}

      {!visibleError && graph && (
        graph.nodes.length === 0 ? (
          <div className="struct-state">
            <MapIcon size={22} />
            <strong>Nothing to draw</strong>
            <span>The index found no modules with dependency data in this repository.</span>
          </div>
        ) : (
          <CodeMapCanvas
            key={`${project}:${theme}:${graphLimit}:${graph.nodes.length}:${graph.edges.length}`}
            project={project}
            graph={graph}
            theme={theme}
            findings={findings}
          />
        )
      )}
    </section>
  );
}

/**
 * One class of finding, listed and clickable.
 *
 * `withheld` is the honest empty state: an empty island list because the
 * snapshot was suppressed and an empty island list because there are no
 * islands are the same zero, and only this prop keeps them apart.
 */
function FindingGroup({
  cls,
  modules,
  blocked,
  onPick
}: {
  cls: FindingClass;
  modules: string[];
  /** True when the NAMES could not be obtained. The count then reads
   * "withheld" instead of 0 — a zero here would be a straight lie. */
  blocked: boolean;
  onPick: (module: string) => void;
}) {
  const [open, setOpen] = useState(true);

  return (
    <div className={`mf-group mf-${cls}`}>
      <button
        type="button"
        className="mf-head"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        disabled={blocked}
      >
        <i style={{ background: FINDING_COLOR[cls] }} />
        <b>{cls}</b>
        <span className={cx('mf-count', blocked && 'mf-blocked')}>{blocked ? 'withheld' : modules.length}</span>
      </button>
      {open && !blocked && (
        modules.length === 0 ? (
          <p className="mf-none">none in this view</p>
        ) : (
          <ul className="mf-list">
            {modules.slice(0, 40).map((m) => (
              <li key={m}>
                <button type="button" onClick={() => onPick(m)} title={m}>{m}</button>
              </li>
            ))}
            {modules.length > 40 && <li className="mf-more">+{modules.length - 40} more</li>}
          </ul>
        )
      )}
    </div>
  );
}

function CodeMapCanvas({
  project,
  graph,
  theme,
  findings
}: {
  project: string;
  graph: StructureGraph;
  theme: Theme;
  findings?: MapFindings;
}) {
  const holder = useRef<HTMLDivElement | null>(null);
  const sigmaRef = useRef<Sigma | null>(null);
  const layoutRef = useRef<FA2Layout | null>(null);
  const stopTimer = useRef<number | undefined>(undefined);

  // Hover/selection live in refs so the Sigma reducers always read fresh
  // values without tearing the renderer down and rebuilding it.
  const hoverRef = useRef<string | null>(null);
  const neighborRef = useRef<Set<string> | null>(null);
  const selectedRef = useRef<string | null>(null);
  /** Re-derives the focus/neighbour highlight; owned by the renderer effect. */
  const refocusRef = useRef<(() => void) | null>(null);

  const [selected, setSelected] = useState<StructureGraphNode | null>(null);
  const [laying, setLaying] = useState(false);

  const [distilling, setDistilling] = useState('');
  const [distillResult, setDistillResult] = useState<DistillPayload | undefined>();
  const [distillError, setDistillError] = useState('');
  const [distillTarget, setDistillTarget] = useState('');
  const [showSlice, setShowSlice] = useState(false);

  const byId = useMemo(() => {
    const m = new Map<string, StructureGraphNode>();
    graph.nodes.forEach((n) => m.set(n.module, n));
    return m;
  }, [graph]);

  const stats = useMemo(() => {
    let maxScore = 0;
    let maxFanIn = 0;
    let minScore = Number.POSITIVE_INFINITY;
    graph.nodes.forEach((n) => {
      if (n.score > maxScore) maxScore = n.score;
      if (n.score < minScore) minScore = n.score;
      if (n.fan_in > maxFanIn) maxFanIn = n.fan_in;
    });
    if (!Number.isFinite(minScore)) minScore = 0;
    return { maxScore, minScore, maxFanIn };
  }, [graph]);

  /* ---------------- structural findings, joined onto the graph ----------------
   *
   * TWO of these are findings and ONE is not, and conflating them would be the
   * same defect in miniature:
   *
   *   island      the generated snapshot says nothing reaches it. A real
   *               finding: it comes from a digest-covered reachability pass
   *               over the whole tree, and it is refused outright when that
   *               snapshot does not describe this HEAD.
   *   shim        a re-export nothing reaches. Same evidence, OPPOSITE remedy
   *               (remove it; do not "wire it in") — which is why the backend
   *               keeps them as separate sources and this keeps them as
   *               separate colours.
   *   no-inbound  NOT a finding. Measured here, from the drawn edges only:
   *               nothing in THIS graph imports it. On this repo that is 79 of
   *               164 modules while the snapshot's whole-tree pass counts 10
   *               unreached — the extracted import edges are demonstrably
   *               incomplete, so painting these as islands would manufacture
   *               ~70 false ones. It is off by default, it is never coloured
   *               like a finding, and the disagreement is reported instead.
   */
  const findingOf = useMemo(() => {
    const norm = (m: string) => m.replace(/\\/g, '/').replace(/^\.\//, '');
    // Keyed by the RAW node id, so the Sigma reducer is a single Map hit per
    // node per frame rather than a string rewrite.
    const rawByNorm = new Map<string, string>();
    graph.nodes.forEach((n) => rawByNorm.set(norm(n.module), n.module));

    const byModule = new Map<string, FindingClass>();
    const missing: string[] = [];
    const islands: string[] = [];
    const shims: string[] = [];

    (findings?.shims || []).forEach((m) => {
      const raw = rawByNorm.get(norm(m));
      if (raw) { byModule.set(raw, 'shim'); shims.push(raw); } else missing.push(m);
    });
    // Islands last so an entry claimed by both wins as the stronger finding.
    (findings?.islands || []).forEach((m) => {
      const raw = rawByNorm.get(norm(m));
      if (raw) { byModule.set(raw, 'island'); islands.push(raw); } else missing.push(m);
    });

    const inbound = new Set<string>();
    graph.edges.forEach((e) => inbound.add(e.target));
    const noInbound = graph.nodes
      .filter((n) => !inbound.has(n.module) && !byModule.has(n.module))
      .map((n) => n.module)
      .sort();

    // The snapshot's whole-tree answer to the same question. When the two
    // disagree by a wide margin, the drawn edges are the thing at fault and
    // saying so is more useful than either number.
    const snapshotUnreached = findings?.counts?.unreached;
    const disagreement = typeof snapshotUnreached === 'number' && graph.nodes.length > 0
      && noInbound.length > snapshotUnreached * 2
      ? `${noInbound.length} of ${graph.nodes.length} modules drawn here have no inbound edge, while the whole-tree reachability pass counts ${snapshotUnreached} unreached. The import edges in this graph are incomplete — trust the snapshot's verdict, not this one.`
      : '';

    return {
      byModule,
      islands: islands.sort(),
      shims: shims.sort(),
      noInbound,
      noInboundSet: new Set(noInbound),
      disagreement,
      /** Findings the map named that this view does not contain — a bounded
       * graph or a different scope. Silence here would look like "clean". */
      missing: Array.from(new Set(missing)).sort()
    };
  }, [graph, findings]);

  const findingRef = useRef(findingOf);
  findingRef.current = findingOf;

  const [mode, setMode] = useState<'heat' | 'findings'>('heat');
  const modeRef = useRef(mode);
  const [showNoInbound, setShowNoInbound] = useState(false);
  const noInboundRef = useRef(showNoInbound);

  /** Stop the layout worker but keep the renderer alive. */
  const stopLayout = useCallback(() => {
    if (stopTimer.current !== undefined) {
      window.clearTimeout(stopTimer.current);
      stopTimer.current = undefined;
    }
    if (layoutRef.current?.isRunning()) layoutRef.current.stop();
    setLaying(false);
  }, []);

  /**
   * Kick ForceAtlas2 for a bounded burst. It runs in a **web worker**, so the
   * main thread stays free to pan/zoom/scroll while the graph settles — the
   * cockpit is supposed to feel snappy, and a 2k-node layout on the UI thread
   * would freeze it solid. We auto-stop so we never pin a core forever.
   */
  const runLayout = useCallback((ms: number) => {
    if (!layoutRef.current) return;
    if (stopTimer.current !== undefined) window.clearTimeout(stopTimer.current);
    if (!layoutRef.current.isRunning()) layoutRef.current.start();
    setLaying(true);
    stopTimer.current = window.setTimeout(() => {
      if (layoutRef.current?.isRunning()) layoutRef.current.stop();
      setLaying(false);
      stopTimer.current = undefined;
    }, ms);
  }, []);

  useEffect(() => {
    const container = holder.current;
    if (!container) return undefined;

    const pal = palette(theme);
    const { maxScore, maxFanIn } = stats;
    const g = new Graph({ type: 'directed', multi: false, allowSelfLoops: false });

    // Seed positions on a jittered circle — FA2 cannot escape a degenerate
    // all-zero start, and a ring unfolds far more evenly than pure random.
    const n = graph.nodes.length;
    graph.nodes.forEach((node, i) => {
      const a = (2 * Math.PI * i) / Math.max(1, n);
      const r = 100 + Math.random() * 40;
      const t = heatT(node.score, maxScore);
      g.addNode(node.module, {
        x: Math.cos(a) * r + (Math.random() - 0.5) * 12,
        y: Math.sin(a) * r + (Math.random() - 0.5) * 12,
        size: nodeSize(node.fan_in, maxFanIn),
        color: rampColor(t, theme),
        label: node.module.split(/[\\/]/).pop() || node.module,
        heat: t,
        zIndex: Math.round(t * 100)
      });
    });

    // The backend guarantees no dangling endpoints, but a self-loop or a
    // repeated pair would still throw — guard rather than trust.
    graph.edges.forEach((e) => {
      if (e.source === e.target) return;
      if (!g.hasNode(e.source) || !g.hasNode(e.target)) return;
      if (g.hasEdge(e.source, e.target)) return;
      g.addEdge(e.source, e.target, { color: pal.edge, size: 0.6 });
    });

    const big = n > 400;
    const renderer = new Sigma(g, container, {
      allowInvalidContainer: true,
      defaultEdgeColor: pal.edge,
      labelColor: { color: pal.label },
      labelSize: 11,
      labelWeight: '600',
      labelDensity: 0.6,
      labelGridCellSize: 90,
      // Only the structurally-important nodes earn a label; otherwise a big
      // repo turns into unreadable text soup and costs a fortune to draw. The
      // threshold is on rendered size, so it tightens automatically as you
      // zoom out and relaxes as you zoom into a neighbourhood.
      labelRenderedSizeThreshold: n > 1200 ? 9 : big ? 7.5 : 3,
      renderEdgeLabels: false,
      enableEdgeEvents: false,
      // Dropping edges/labels during a drag is what keeps a 2k-node graph at
      // 60fps while panning.
      hideEdgesOnMove: big,
      hideLabelsOnMove: big,
      zIndex: true,
      minCameraRatio: 0.05,
      maxCameraRatio: 14,
      nodeReducer: (key, attrs) => {
        const hovered = hoverRef.current;
        const sel = selectedRef.current;
        const focus = hovered || sel;
        const res: Record<string, unknown> = { ...attrs };
        // Findings mode repaints the whole scene on the structural axis: the
        // three finding classes light up and everything else recedes, so the
        // findings are the picture instead of an entry in a legend.
        if (modeRef.current === 'findings') {
          const cls = findingRef.current.byModule.get(key);
          if (cls) {
            res.color = FINDING_COLOR[cls];
            res.zIndex = cls === 'island' ? 400 : 380;
            res.forceLabel = true;
            res.size = Math.max(Number(attrs.size) || 5, 8);
          } else if (noInboundRef.current && findingRef.current.noInboundSet.has(key)) {
            // Deliberately unlabelled and left at its own size: this is a
            // property of the drawn edges, not a verdict, and it must not read
            // as one of the two findings above.
            res.color = FINDING_COLOR['no-inbound'];
            res.zIndex = 120;
          } else {
            res.color = pal.backdrop;
            res.label = '';
            res.zIndex = 0;
          }
        }
        if (focus) {
          const near = key === focus || neighborRef.current?.has(key);
          if (!near) {
            // Push the unrelated repo into the background rather than hiding
            // it — you keep the sense of scale, you lose the noise.
            res.color = pal.dim;
            res.label = '';
            res.zIndex = 0;
          } else {
            res.forceLabel = true;
            res.zIndex = 200;
          }
        }
        if (key === sel) {
          res.highlighted = true;
          res.forceLabel = true;
          res.zIndex = 300;
        }
        return res;
      },
      edgeReducer: (key, attrs) => {
        const focus = hoverRef.current || selectedRef.current;
        const res: Record<string, unknown> = { ...attrs };
        if (focus) {
          const [s, t] = g.extremities(key);
          if (s === focus || t === focus) {
            res.color = pal.edgeHi;
            res.size = 1.2;
            res.zIndex = 250;
          } else {
            res.hidden = true;
          }
        }
        return res;
      }
    });

    sigmaRef.current = renderer;

    /**
     * Hover and selection are two independent sources of focus, so the
     * neighbour set is always DERIVED from whichever is active rather than
     * written by each handler. Doing it the other way round meant that simply
     * moving the pointer off the canvas (say, to reach "Distill this") fired
     * `leaveNode`, cleared the neighbours out from under the still-active
     * selection, and greyed out the very dependencies you selected the node
     * to look at.
     */
    const applyFocus = () => {
      const focus = hoverRef.current || selectedRef.current;
      neighborRef.current = focus && g.hasNode(focus)
        ? new Set<string>(g.neighbors(focus))
        : null;
      renderer.refresh({ skipIndexation: true });
    };
    refocusRef.current = applyFocus;

    renderer.on('enterNode', ({ node }) => {
      hoverRef.current = node;
      applyFocus();
      container.style.cursor = 'pointer';
    });
    renderer.on('leaveNode', () => {
      hoverRef.current = null;
      applyFocus();
      container.style.cursor = 'default';
    });
    renderer.on('clickNode', ({ node }) => {
      selectedRef.current = node;
      setSelected(byId.get(node) || null);
      applyFocus();
    });
    renderer.on('clickStage', () => {
      selectedRef.current = null;
      setSelected(null);
      applyFocus();
    });

    const supervisor = new FA2Layout(g, {
      settings: {
        // inferSettings picks barnesHutOptimize etc. from the graph order.
        ...forceAtlas2.inferSettings(g),
        slowDown: 8,
        // Spread has to scale with the graph or a big repo collapses into one
        // unreadable disc where the heat signal is invisible: weaken gravity
        // and push repulsion up so packages separate. Small graphs need the
        // opposite — without gravity a handful of nodes just drift apart.
        gravity: big ? 0.35 : 1.2,
        scalingRatio: big ? 18 : 6,
        // Anti-collision makes nodes readable but is O(expensive); only worth
        // it while the graph is small enough to converge quickly.
        adjustSizes: n <= 800
      }
    });
    layoutRef.current = supervisor;
    supervisor.start();
    setLaying(true);
    // Scale the burst with the graph: small repos settle almost instantly,
    // big ones need longer, but nothing runs unbounded.
    const budget = Math.min(9000, 2200 + n * 3);
    stopTimer.current = window.setTimeout(() => {
      if (supervisor.isRunning()) supervisor.stop();
      setLaying(false);
      stopTimer.current = undefined;
    }, budget);

    return () => {
      if (stopTimer.current !== undefined) window.clearTimeout(stopTimer.current);
      stopTimer.current = undefined;
      supervisor.kill();
      layoutRef.current = null;
      renderer.kill();
      sigmaRef.current = null;
      refocusRef.current = null;
      hoverRef.current = null;
      neighborRef.current = null;
      selectedRef.current = null;
    };
  }, [graph, theme, stats, byId]);

  // Mode and findings live in refs the reducers read, so switching either
  // repaints without tearing down the WebGL renderer or restarting the layout.
  useEffect(() => {
    modeRef.current = mode;
    noInboundRef.current = showNoInbound;
    refocusRef.current?.();
  }, [mode, showNoInbound, findingOf]);

  /** Select a module and fly the camera to it — the findings list is a
   * navigation control, not a read-only report. */
  const focusModule = useCallback((module: string) => {
    const renderer = sigmaRef.current;
    if (!renderer || !renderer.getGraph().hasNode(module)) return;
    stopLayout();
    selectedRef.current = module;
    setSelected(byId.get(module) || null);
    refocusRef.current?.();
    const pos = renderer.getNodeDisplayData(module);
    if (pos) renderer.getCamera().animate({ x: pos.x, y: pos.y, ratio: 0.3 }, { duration: 420 });
  }, [byId, stopLayout]);

  async function runDistill(target: string) {
    if (!target || distilling) return;
    setDistilling(target);
    setDistillTarget(target);
    setDistillError('');
    setShowSlice(false);
    try {
      const res = await distill(project, target);
      setDistillResult(res);
    } catch (err) {
      setDistillResult(undefined);
      setDistillError(err instanceof Error ? err.message : String(err));
    } finally {
      setDistilling('');
    }
  }

  function clearSelection() {
    selectedRef.current = null;
    setSelected(null);
    refocusRef.current?.();
  }

  const shownNodes = graph.nodes.length;
  const shownEdges = graph.edges.length;
  /** "Withheld" is only true when NO name arrived. When some did, the notice
   * is about the list being partial — a panel that lists six modules while
   * calling the list withheld is worse than either message alone. */
  const namesBlocked = !!findings?.namesWithheld
    && findingOf.islands.length === 0 && findingOf.shims.length === 0;

  return (
    <>
      {/* ---- no silent caps: say exactly what is on screen ---- */}
      {graph.truncated ? (
        <div className="map-truncated" role="status">
          <AlertTriangle size={15} />
          <span>
            Bounded view — showing the <b>{num(shownNodes)} hottest</b> of{' '}
            <b>{num(graph.n_nodes_total)}</b> modules and {num(shownEdges)} of{' '}
            {num(graph.n_edges_total)} edges. This is not the whole repository.
          </span>
        </div>
      ) : (
        <div className="map-complete" role="status">
          Complete graph — {num(shownNodes)} modules, {num(shownEdges)} edges.
        </div>
      )}

      <div className="map-stage">
        <div className="map-canvas" ref={holder} />

        {/* ---- legend: anchors whichever axis is painted to real numbers ---- */}
        <div className="map-legend">
          {mode === 'heat' ? (
            <>
              <div className="ml-title"><Flame size={12} /> churn × complexity</div>
              <div
                className="ml-ramp"
                style={{
                  background: `linear-gradient(90deg, ${[0, 0.25, 0.5, 0.75, 1]
                    .map((t) => rampColor(t, theme))
                    .join(', ')})`
                }}
              />
              <div className="ml-scale">
                <span>cold {fmtScore(stats.minScore, stats.maxScore)}</span>
                <span>hot {fmtScore(stats.maxScore, stats.maxScore)}</span>
              </div>
              <div className="ml-note">size = fan-in (blast radius), max {num(stats.maxFanIn)}</div>
            </>
          ) : (
            <>
              <div className="ml-title"><Unplug size={12} /> structural findings</div>
              <div className="ml-keys">
                {(['island', 'shim', 'no-inbound'] as FindingClass[]).map((cls) => (
                  <span className="ml-key" key={cls}>
                    <i style={{ background: FINDING_COLOR[cls] }} />
                    {FINDING_LABEL[cls]}
                  </span>
                ))}
              </div>
              <div className="ml-note">everything else is dimmed, not hidden — the scale stays readable</div>
            </>
          )}
        </div>

        <div className="map-tools">
          {laying && <span className="map-chip laying"><RefreshCw size={11} className="spin" /> settling</span>}
          <div className="map-modes" role="group" aria-label="Colour the map by">
            <button
              type="button"
              className={mode === 'heat' ? 'active' : ''}
              aria-pressed={mode === 'heat'}
              onClick={() => setMode('heat')}
            >
              <Flame size={11} /> Heat
            </button>
            <button
              type="button"
              className={mode === 'findings' ? 'active' : ''}
              aria-pressed={mode === 'findings'}
              onClick={() => setMode('findings')}
            >
              <Unplug size={11} /> Findings
            </button>
          </div>
          <button type="button" className="map-chip btn" onClick={() => runLayout(4000)} disabled={laying}>
            <Waypoints size={11} /> Re-run layout
          </button>
          <button
            type="button"
            className="map-chip btn"
            onClick={() => {
              stopLayout();
              sigmaRef.current?.getCamera().animatedReset({ duration: 260 });
            }}
          >
            <Crosshair size={11} /> Fit
          </button>
        </div>

        {/* ---- the findings, as a navigable list ----
            A count in a ribbon is a fact nobody can act on. These are the
            actual modules, and clicking one flies the camera to it. */}
        {mode === 'findings' && (
          <div className="map-findings">
            {/* The reason lives here ONCE. Repeating it per group buried the
                two counts it is explaining. */}
            {findings?.namesWithheld ? (
              <p className="mf-withheld" title={findings.namesWithheld}>
                <AlertTriangle size={11} />
                <span>
                  <b>{namesBlocked ? 'Withheld, not zero.' : 'Partial list.'}</b> The reason is above
                  the map.
                </span>
              </p>
            ) : findingOf.islands.length === 0 && findingOf.shims.length === 0 ? (
              <p className="mf-caveat">
                The snapshot was read and trusted, and it flags <b>no</b> island or shim in this
                view. That is a finding: nothing is withheld here.
              </p>
            ) : null}
            <FindingGroup cls="island" modules={findingOf.islands} blocked={namesBlocked} onPick={focusModule} />
            <FindingGroup cls="shim" modules={findingOf.shims} blocked={namesBlocked} onPick={focusModule} />

            {findingOf.missing.length > 0 && (
              <p className="mf-missing">
                {findingOf.missing.length} named finding(s) are not in this view at all
                ({findingOf.missing.slice(0, 3).join(', ')}
                {findingOf.missing.length > 3 ? '…' : ''}) — the graph is scoped or bounded differently
                from the snapshot.
              </p>
            )}

            {/* NOT a finding, and it does not get to look like one. */}
            <div className="mf-group mf-derived">
              <label className="mf-toggle">
                <input
                  type="checkbox"
                  checked={showNoInbound}
                  onChange={(e) => setShowNoInbound(e.target.checked)}
                />
                <i style={{ background: FINDING_COLOR['no-inbound'] }} />
                <span>no inbound edge here</span>
                <span className="mf-count">{findingOf.noInbound.length}</span>
              </label>
              <p className="mf-caveat">
                Measured from the edges drawn above, not from a reachability pass. An entrypoint — a
                CLI, a server, a worker — is <b>supposed</b> to have no importer, so this is a
                property of the graph, never a work item.
              </p>
              {findingOf.disagreement && (
                <p className="mf-missing">{findingOf.disagreement}</p>
              )}
              {graph.truncated && (
                <p className="mf-caveat">
                  This view is bounded, so edges outside the cap are missing entirely and inflate this
                  number further.
                </p>
              )}
            </div>
          </div>
        )}

        {selected && (
          <div className="map-inspector">
            <div className="mi-head">
              <strong title={selected.module}>{selected.module}</strong>
              <button type="button" className="iconbtn" onClick={clearSelection} aria-label="Close inspector">
                <X size={14} />
              </button>
            </div>

            <div className="mi-metrics">
              <span className="struct-chip"><b>{selected.language || 'unknown'}</b></span>
              <span className="struct-chip">{num(selected.loc)} loc</span>
              <span className="struct-chip">churn {num(selected.churn)}</span>
              <span className="struct-chip">fan-in {num(selected.fan_in)}</span>
            </div>

            <div className="mi-heat">
              <div className="mi-heat-label">
                <span>heat</span>
                <b style={{ color: rampColor(heatT(selected.score, stats.maxScore), theme) }}>
                  {fmtScore(selected.score, stats.maxScore)}
                </b>
              </div>
              <div className="mi-heat-track">
                <div
                  className="mi-heat-fill"
                  style={{
                    width: `${Math.round(heatT(selected.score, stats.maxScore) * 100)}%`,
                    background: rampColor(heatT(selected.score, stats.maxScore), theme)
                  }}
                />
              </div>
            </div>

            <GlassButton
              className="distill-btn mi-distill"
              onClick={() => runDistill(selected.module)}
              disabled={distilling === selected.module}
            >
              <Scissors size={13} />{' '}
              {distilling === selected.module ? 'Distilling…' : 'Distill this'}
            </GlassButton>

            {(distilling || distillResult || distillError) && (
              <DistillResult
                distilling={distilling}
                result={distillResult}
                error={distillError}
                target={distillTarget}
                showSlice={showSlice}
                onToggleSlice={() => setShowSlice((v) => !v)}
              />
            )}
          </div>
        )}

        {/* Follows the `.railcard` precedent: keep the glass edge treatment,
            drop the per-element blur (see the rule in styles.css). */}
        {!selected && (
          <GlassCard className="map-hint">
            Click a node to inspect it and distill it.
          </GlassCard>
        )}
      </div>
    </>
  );
}
